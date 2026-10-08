import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service_schema import record,proxy,validate_records


class SchemaTests(unittest.TestCase):
    def test_dns_scoping_srv_and_injection(self):
        base=dict(zone='minecraft.mrhaydenn.us',name='trigun',type='A',content='203.0.113.5',ttl=300,enabled=True)
        self.assertEqual(record(base,[base['zone']])['name'],'trigun.minecraft.mrhaydenn.us')
        srv=record(dict(base,name='_minecraft._tcp.trigun',type='SRV',content='0 5 20080 trigun.minecraft.mrhaydenn.us'),[base['zone']])
        self.assertEqual(srv['content'],'0 5 20080 trigun.minecraft.mrhaydenn.us.')
        for changed in (dict(zone='other.example.com'),dict(content='1.2.3.4\nIN NS attacker.example'),dict(type='NS'),dict(ttl=1)):
            with self.assertRaises(ValueError): record(dict(base,**changed),[base['zone']])
        cname=record(dict(base,type='CNAME',content='target.example.com'),[base['zone']])
        with self.assertRaises(ValueError):validate_records([record(base,[base['zone']]),cname])

    def test_web_scope_and_config_injection(self):
        base=dict(domains=['site.example.com'],address='10.7.0.2',port=8080,scheme='http',ssl=True,enabled=True)
        self.assertEqual(proxy(base,'10.7.0.0/24')['port'],8080)
        local = proxy(dict(base,address='127.0.0.1',hostId='@vps'),'10.7.0.0/24')
        self.assertEqual(local['hostId'], '@vps')
        with self.assertRaises(ValueError): proxy(dict(base,address='192.168.0.1',hostId='@vps'),'10.7.0.0/24')
        for changed in (dict(address='127.0.0.1'),dict(domains=['*.example.com']),dict(domains=['example.com { respond secret }']),dict(port=True),dict(scheme='file')):
            with self.assertRaises(ValueError):proxy(dict(base,**changed),'10.7.0.0/24')


@unittest.skipIf(os.name=='nt','Privileged helper targets Ubuntu')
class HelperTests(unittest.TestCase):
    def setUp(self):
        source=Path(__file__).resolve().parents[1]/'deploy'/'unm-services'
        loader=importlib.machinery.SourceFileLoader('services_helper',str(source))
        spec=importlib.util.spec_from_loader(loader.name,loader)
        self.helper=importlib.util.module_from_spec(spec);loader.exec_module(self.helper)
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.helper.BASE=root
        self.helper.WEB=root/'Caddyfile'
        self.helper.DNS=root/'dns';self.helper.DNS.mkdir()
        self.helper.WIREGUARD=root/'wireguard.json';self.helper.WIREGUARD.write_text('{"subnet":"10.7.0.0/24"}')
        self.cfg=dict(web_enabled=True,dns_enabled=True,staging=True,email='admin@example.com',public_ip='203.0.113.5',dns_zones=['minecraft.mrhaydenn.us'],nameservers=['ns1.mrhaydenn.us'])

    def tearDown(self):self.tmp.cleanup()

    def test_public_panel_https_and_reserved_domain(self):
        cfg = dict(self.cfg, public_panel={'domain': 'unm.mrhaydenn.us', 'port': 8787, 'backend_port': 8786})
        text = self.helper.web_text(cfg, [])
        self.assertIn('https://unm.mrhaydenn.us:8787 {', text)
        self.assertIn('reverse_proxy 127.0.0.1:8786', text)
        with self.assertRaises(ValueError):
            self.helper.web_text(dict(cfg, public_panel=dict(cfg['public_panel'], backend_port=22)), [])
        website = dict(domains=['unm.mrhaydenn.us'],address='10.7.0.2',port=8080,scheme='http',ssl=True,enabled=True)
        with self.assertRaises(ValueError):
            self.helper.web_text(cfg, [website])
        if shutil.which('caddy'):
            self.helper.WEB.write_text(text)
            subprocess.run(['caddy', 'validate', '--config', str(self.helper.WEB), '--adapter', 'caddyfile'], check=True, capture_output=True)

    def test_disabled_gate_and_transactional_rollback(self):
        with self.assertRaises(ValueError):self.helper.execute(dict(self.cfg,web_enabled=False),dict(action='web',items=[]))
        path=self.helper.WEB;path.write_text('previous')
        with patch.object(self.helper,'command',return_value=''):
            with self.assertRaises(ValueError):
                self.helper.apply_files({path:'changed'},lambda:(_ for _ in ()).throw(ValueError('invalid')),'unm-caddy')
        self.assertEqual(path.read_text(),'previous')

    def test_native_caddy_and_bind_configuration_validation(self):
        if not all(shutil.which(p) for p in ('caddy','named-checkzone','named-checkconf')):
            self.skipTest('Native config validators are required in Ubuntu CI')
        website=dict(domains=['site.example.com'],address='10.7.0.2',port=8080,scheme='http',ssl=True,enabled=True)
        self.helper.WEB.write_text(self.helper.web_text(self.cfg,[website]))
        result=subprocess.run(['caddy','validate','--config',str(self.helper.WEB),'--adapter','caddyfile'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        zone=self.cfg['dns_zones'][0]
        items=[record(dict(zone=zone,name='trigun',type='A',content='203.0.113.5',enabled=True),[zone]),record(dict(zone=zone,name='_minecraft._tcp.trigun',type='SRV',content='0 5 20080 trigun.minecraft.mrhaydenn.us',enabled=True),[zone]),record(dict(zone=zone,name='test',type='TXT',content='quoted "text" and \\ slash',enabled=True),[zone])]
        path=self.helper.DNS/(zone+'.zone');path.write_text(self.helper.zone_text(zone,self.cfg['nameservers'],self.cfg['public_ip'],items,123))
        conf=self.helper.DNS/'named.conf';conf.write_text(self.helper.dns_text(self.cfg))
        for args in (['named-checkzone',zone,str(path)],['named-checkconf','-z',str(conf)]):
            result=subprocess.run(args,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('recursion no',conf.read_text())

