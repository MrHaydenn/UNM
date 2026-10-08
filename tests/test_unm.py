import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import subprocess
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unm


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = json.loads((unm.ROOT / 'config.example.json').read_text())
        cfg['data_dir'] = self.tmp.name
        self.config = Path(self.tmp.name) / 'config.json'
        self.config.write_text(json.dumps(cfg))
        self.app = unm.App(self.config)
        self.app.db.execute('INSERT INTO users(name,password) VALUES(?,?)', ('admin', unm.password_hash('strong-test-password')))
        self.app.db.execute('INSERT INTO hosts(id,address) VALUES(?,?)', ('pc', '10.8.0.2'))
        self.app.db.commit()
        self.http = unm.ThreadingHTTPServer(('127.0.0.1', 0), unm.Handler)
        self.http.app = self.app
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.cookie, self.csrf = '', ''

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.app.db.close()
        self.tmp.cleanup()

    def req(self, path, method='GET', body=None, bearer=None, csrf=True, origin=True):
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = 'http://localhost:8787'
        if self.cookie:
            headers['Cookie'] = self.cookie
        if csrf:
            headers['X-CSRF-Token'] = self.csrf
        if bearer:
            headers['Authorization'] = 'Bearer ' + bearer
            headers.pop('Cookie', None)
        req = Request('http://127.0.0.1:' + str(self.http.server_port) + path,
                      method=method, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            cookie = response.headers.get('Set-Cookie')
            if cookie:
                self.cookie = cookie.split(';')[0]
            return response.status, json.load(response)

    def login(self):
        self.assertEqual(self.req('/api/login', 'POST', {'username': 'admin', 'password': 'strong-test-password'})[0], 200)
        code, state = self.req('/api/state')
        self.assertEqual(code, 200)
        self.csrf = state['csrf']

    def body(self, **kwargs):
        return dict(hostId='pc', targetPort=8080, publicPort=20080, enabled=True, hostname='media.hosts.example.com', **kwargs)

    def test_integration_key_management_security_and_rotation(self):
        route = '/api/integration-keys'
        body = {'name': 'MMSM Home Server', 'zone': 'minecraft.example.com'}
        self.assertEqual(self.req(route, 'POST', body)[0], 403)
        self.login()
        self.assertEqual(self.req(route, 'POST', body, csrf=False)[0], 403)
        self.assertEqual(self.req(route, 'POST', body, origin=False)[0], 403)
        with patch.object(self.app, 'services_status', return_value={'zones': ['minecraft.example.com']}):
            self.assertEqual(self.req(route, 'POST', {**body, 'zone': 'other.example.com'})[0], 400)
            self.assertEqual(self.req(route, 'POST', {**body, 'name': ''})[0], 400)
            code, created = self.req(route, 'POST', body)
        self.assertEqual(code, 201)
        token = created['token']
        key_id = created['id']
        self.assertEqual(self.app.dns_client('Bearer ' + token)['id'], key_id)
        self.assertEqual(self.req(route, bearer=token)[0], 403)
        code, listing = self.req(route)
        self.assertEqual(listing, [{'id': key_id, 'name': body['name'], 'zone': body['zone']}])
        self.assertNotIn(token, json.dumps(self.req('/api/state')[1]))
        self.assertNotIn(token, self.app.db.execute('SELECT hash FROM dns_clients WHERE id=?', (key_id,)).fetchone()['hash'])
        self.app.db.execute('INSERT INTO dns_publications VALUES(?,?,?)', (key_id, 'server1', '{"recordIds": ["retained"]}'))
        self.app.db.commit()
        path = route + '/' + key_id
        self.assertEqual(self.req(path, 'PUT', {'name': 'Renamed'})[0], 200)
        self.assertEqual(self.req(route)[1][0]['name'], 'Renamed')
        code, rotated = self.req(path + '/rotate', 'POST', {})
        self.assertEqual(code, 200)
        with self.assertRaises(PermissionError):
            self.app.dns_client('Bearer ' + token)
        self.assertEqual(self.app.dns_client('Bearer ' + rotated['token'])['id'], key_id)
        self.assertEqual(self.req(path, 'DELETE')[0], 200)
        with self.assertRaises(PermissionError):
            self.app.dns_client('Bearer ' + rotated['token'])
        self.assertEqual(self.req(route)[1], [])
        self.assertIsNotNone(self.app.db.execute('SELECT body FROM dns_publications WHERE client=?', (key_id,)).fetchone())

    def test_auth_csrf_and_session_logout(self):
        self.assertEqual(self.req('/api/state')[0], 403)
        self.assertEqual(self.req('/api/login', 'POST', {'username': 'admin', 'password': 'wrong'})[0], 401)
        self.login()
        self.assertEqual(self.req('/api/hosts', 'POST', {'id': 'other', 'address': '10.8.0.3'}, csrf=False)[0], 403)
        self.assertEqual(self.req('/api/hosts', 'POST', {'id': 'other', 'address': '10.8.0.3'}, origin=False)[0], 403)
        self.assertEqual(self.req('/api/hosts', 'POST', {'id': 'other', 'address': '127.0.0.1'})[0], 400)
        self.assertEqual(self.req('/api/logout', 'POST', {})[0], 200)
        self.assertEqual(self.req('/api/state')[0], 403)

    def test_forward_idempotency_conflicts_and_external_access_disabled(self):
        self.login()
        route = '/api/forwards/media'
        for _ in range(2):
            self.assertEqual(self.req(route, 'PUT', self.body())[0], 200)
        self.assertEqual(len(self.app.servers()), 1)
        self.assertEqual(self.req('/api/forwards/conflict', 'PUT', self.body())[0], 400)
        self.assertEqual(self.req(route, bearer='retired-token')[0], 403)
        self.assertEqual(self.req('/api/tokens', 'POST', {})[0], 404)
        self.assertEqual(self.req(route + '/dns', 'POST', {})[0], 400)

    def test_registered_host_and_firewall_lifecycle(self):
        self.login()
        status, body = self.req('/api/hosts', 'POST', dict(id='new-pc', address='10.8.0.3', enroll=False))
        self.assertEqual(status, 201)
        self.assertFalse(body['host']['managed'])
        self.assertIsNone(body['configuration'])
        self.assertEqual(self.req('/api/firewall', 'POST', dict(id='web', port=20090, enabled=True))[0], 200)
        self.assertEqual(self.req('/api/firewall', 'POST', dict(id='ssh', port=22, enabled=True))[0], 400)
        self.assertEqual(self.req('/api/state')[1]['firewallRules'][0]['port'], 20090)
        self.assertEqual(self.req('/api/firewall/web', 'DELETE')[0], 200)
        self.assertEqual(self.req('/api/hosts/new-pc', 'DELETE')[0], 200)
        self.app.save_server('media', self.body(), 'admin')
        self.assertEqual(self.req('/api/hosts/pc', 'DELETE')[0], 400)
        self.assertEqual(self.req('/api/hosts', 'POST', dict(id='new-peer', address='', enroll=True))[0], 400)

    def test_enrollment_allocation_and_private_key_is_not_persisted(self):
        self.login()
        self.app.cfg['mode'] = 'live'
        private = base64.b64encode(bytes([4]) * 32).decode()
        public = base64.b64encode(bytes([5]) * 32).decode()
        status = dict(available=True, serverAddress='10.8.0.1/24', publicKey=base64.b64encode(bytes([9]) * 32).decode(),
                      endpoint='vps.example.com:51820', peers=[])
        with patch.object(self.app, 'wg_status', return_value=status), patch.object(self.app, 'wg_call', return_value={'ok': True}) as call, patch('networking.subprocess.run', side_effect=[subprocess.CompletedProcess([], 0, private), subprocess.CompletedProcess([], 0, public)]):
            code, response = self.req('/api/hosts', 'POST', dict(id='new-peer', address='', enroll=True))
            self.assertEqual(code, 201)
            self.assertEqual(response['host']['address'], '10.8.0.3')
            self.assertTrue(response['privateKeyIncluded'])
            self.assertIn('PrivateKey = ' + private, response['configuration'])
            self.assertIn('AllowedIPs = 10.8.0.0/24', response['configuration'])
            self.assertNotIn('0.0.0.0/0', response['configuration'])
            self.assertNotIn(private, repr([dict(r) for r in self.app.db.execute('SELECT * FROM hosts')]))
            self.assertEqual(call.call_args.args[0]['action'], 'add')
            code, config = self.req('/api/hosts/new-peer/configuration')
            self.assertEqual(code, 200)
            self.assertIn('<HOST_PRIVATE_KEY>', config['configuration'])
            self.assertNotIn(private, config['configuration'])
            self.assertEqual(self.req('/api/hosts/new-peer', 'DELETE')[0], 200)
            self.assertEqual(call.call_args.args[0]['action'], 'remove')

    def test_ranges_protocols_names_and_master_preview(self):
        self.login()
        rule = dict(self.body(), publicPort='20080-20082', targetPort='8080-8082', protocol='both', name='Home media')
        self.assertEqual(self.req('/api/forwards/media', 'PUT', rule)[0], 200)
        self.assertEqual(self.req('/api/forwards/other', 'PUT', dict(rule, protocol='udp'))[0], 400)
        self.assertEqual(self.req('/api/forwards/media', 'PUT', dict(rule, targetPort=8080))[0], 400)
        self.assertEqual(self.req('/api/firewall', 'POST', dict(id='status', name='Status services', port='20090-20095', protocol='both', enabled=True))[0], 200)
        self.assertEqual(self.req('/api/firewall/service', 'POST', dict(enabled=False))[0], 200)
        self.assertFalse(self.req('/api/state')[1]['firewall']['enabled'])
        self.assertEqual(self.req('/api/traffic?days=7')[0], 200)

    def test_website_dns_and_generated_rule_ids(self):
        self.login()
        code,item=self.req('/api/forwards','POST',dict(self.body(),name='Named forward'))
        self.assertEqual(code,201);self.assertTrue(item['id'].startswith('forward-'))
        self.assertEqual(self.req('/api/firewall','POST',dict(name='Named rule',port=20090,enabled=True))[0],200)
        website=dict(name='My site',domains=['site.example.com'],hostId='pc',port=8080,scheme='http',ssl=True,enabled=True)
        code,site=self.req('/api/websites','POST',website)
        self.assertEqual(code,200)
        self.assertEqual(self.req('/api/websites','POST',website)[0],400)
        self.assertEqual(self.req('/api/hosts/pc','DELETE')[0],400)
        with patch.object(self.app,'services_status',return_value=dict(zones=['minecraft.mrhaydenn.us'])):
            body=dict(zone='minecraft.mrhaydenn.us',name='trigun',type='A',content='203.0.113.5',ttl=300,enabled=True)
            code,dns=self.req('/api/dns-records','POST',body)
            self.assertEqual(code,200)
            self.assertEqual(self.req('/api/dns-records','POST',body)[0],400)
            self.assertEqual(self.req('/api/dns-records/'+dns['id'],'DELETE')[0],200)
        self.assertEqual(self.req('/api/websites/'+site['id'],'DELETE')[0],200)

    def test_creating_websites_after_edit_preserves_existing_sites(self):
        self.login()
        body=dict(name='First site',domains=['first.example.com'],hostId='pc',port=8080,scheme='http',ssl=True,enabled=True)
        code,first=self.req('/api/websites','POST',dict(body,id=''))
        self.assertEqual(code,200)
        code,edited=self.req('/api/websites','POST',dict(first,port=8090))
        self.assertEqual(code,200)
        code,second=self.req('/api/websites','POST',dict(body,id='',name='Second site',domains=['second.example.com']))
        self.assertEqual(code,200)
        self.assertNotEqual(first['id'],second['id'])
        sites={site['id']:site for site in self.req('/api/state')[1]['websites']}
        self.assertEqual(len(sites),2)
        self.assertEqual(sites[first['id']],edited)
        self.assertEqual(sites[second['id']],second)

    def test_broad_public_port_range(self):
        self.login()
        self.app.cfg.update(port_min=1024,port_max=65535)
        for port in (2456,8211,25565,32400,65535):
            code,item=self.req('/api/forwards','POST',dict(self.body(),publicPort=port,hostname=''))
            self.assertEqual(code,201)
            self.assertEqual(item['publicPort'],port)
        self.assertEqual(self.req('/api/forwards','POST',dict(self.body(),publicPort=99999))[0],400)
        self.assertEqual(self.req('/api/forwards','POST',dict(self.body(),publicPort=80))[0],400)
        self.assertEqual(self.req('/api/firewall','POST',dict(name='Valheim',port='2456-2458',protocol='both',enabled=True))[0],200)

    def test_failed_service_apply_keeps_saved_configuration(self):
        item=self.app.save_proxy(dict(name='My site',domains=['site.example.com'],hostId='pc',port=8080,scheme='http',ssl=True,enabled=True),'admin')
        with patch.object(self.app,'apply_services',side_effect=ValueError('reload failed')):
            with self.assertRaises(ValueError):self.app.save_proxy(dict(item,port=8090),'admin')
        self.assertEqual(self.app.proxy_hosts()[0]['port'],8080)

    def test_dns_integration_scope_ownership_rename_revoke_and_rollback(self):
        status=dict(zones=['minecraft.example.com'],dnsEnabled=True,dnsRunning=True,publicIP='203.0.113.9')
        with patch.object(self.app,'services_status',return_value=status), patch.object(self.app,'apply_services') as apply:
            token=self.app.create_dns_client('mmsm','minecraft.example.com')
            other=self.app.create_dns_client('other','minecraft.example.com')
            self.app.cfg['mode']='live'
            body=dict(zone='minecraft.example.com',label='test',port=25565)
            path='/api/integrations/servers/server1'
            self.assertEqual(self.req('/api/state',bearer=token)[0],403)
            self.assertEqual(self.req(path,'PUT',body,bearer='invalid')[0],403)
            self.assertEqual(self.req(path,'PUT',dict(body,zone='elsewhere.example.com'),bearer=token)[0],400)
            code,result=self.req(path,'PUT',body,bearer=token)
            self.assertEqual(code,200);self.assertEqual(result['hostname'],'test.minecraft.example.com')
            self.assertEqual(len(self.app.dns_records()),2)
            apply.reset_mock()
            self.assertEqual(self.req(path,'PUT',body,bearer=token)[0],200)
            apply.assert_not_called()
            self.assertEqual(self.req(path,'PUT',body,bearer=other)[0],400)
            before=self.app.dns_records()
            with patch.object(self.app,'apply_services',side_effect=ValueError('reload failed')):
                self.assertEqual(self.req(path,'PUT',dict(body,label='renamed'),bearer=token)[0],400)
            self.assertEqual(self.app.dns_records(),before)
            self.assertEqual(self.req(path,'PUT',dict(body,label='renamed',port=25566),bearer=token)[0],200)
            self.assertTrue(all('renamed' in r['name'] for r in self.app.dns_records()))
            self.assertEqual(self.req(path,'DELETE',bearer=other)[0],200)
            self.assertEqual(len(self.app.dns_records()),2)
            self.assertEqual(self.req(path,'DELETE',bearer=token)[0],200)
            self.assertEqual(self.app.dns_records(),[])
            self.app.db.execute('DELETE FROM dns_clients WHERE id=?',('mmsm',));self.app.db.commit()
            self.assertEqual(self.req(path,'PUT',body,bearer=token)[0],403)

    def test_traffic_deltas_reset_and_retained_baseline(self):
        now=time.time()
        def sample(rx, tx, boot='first'):
            return dict(bootId=boot, peers=[dict(publicKey='peer', rxBytes=rx, txBytes=tx)])
        self.app.record_traffic(sample(1000,2000),now-120)
        self.app.record_traffic(sample(1100,2200),now-60)
        self.app.record_traffic(sample(50,70,'second'),now)
        totals=self.app.traffic_summary(1)
        self.assertEqual((totals['rx'],totals['tx']),(150,270))
        self.app.record_traffic(sample(50,70,'second'),now+1)
        self.assertEqual(self.app.traffic_summary(30)['rx'],150)

    def test_enrollment_failure_does_not_register_host(self):
        status = dict(available=True, serverAddress='10.8.0.1/24', publicKey=base64.b64encode(bytes([9]) * 32).decode(), endpoint='vps.example.com:51820', peers=[])
        with patch.object(self.app, 'wg_status', return_value=status), patch.object(self.app, 'wg_call', side_effect=ValueError('duplicate peer')):
            with self.assertRaises(ValueError):
                self.app.add_host(dict(id='new-peer', address='', enroll=True, publicKey=base64.b64encode(bytes([2]) * 32).decode()), 'admin')
        self.assertNotIn('new-peer', [h['id'] for h in self.app.hosts()])

    def test_totp_known_vector_and_replay(self):
        secret = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
        self.assertEqual(unm.totp(secret, 59), '287082')
        self.app.db.execute('UPDATE users SET totp=?', (secret,))
        self.app.db.commit()
        payload = {'username': 'admin', 'password': 'strong-test-password', 'code': unm.totp(secret)}
        self.assertEqual(self.req('/api/login', 'POST', payload)[0], 200)
        self.assertEqual(self.req('/api/login', 'POST', payload)[0], 401)

    def test_network_failure_does_not_save(self):
        self.app.save_server('media', self.body(), 'admin')
        new = self.body(); new['targetPort'] = 25566
        with patch.object(self.app, 'apply', side_effect=[OSError('bind failure'), None]) as apply:
            with self.assertRaises(ValueError):
                self.app.save_server('media', new, 'admin')
        self.assertEqual(apply.call_count, 2)
        self.assertEqual(self.app.servers()[0]['targetPort'], 8080)

    def test_dns_ownership_and_dns_only(self):
        self.app.save_server('media', self.body(), 'admin')
        self.app.cfg['mode'] = 'live'
        self.app.cfg['public_ip'] = '203.0.113.5'
        with patch.object(self.app, 'cf', return_value=[{'id': 'foreign'}]):
            with self.assertRaises(ValueError):
                self.app.dns('media', False, 'admin', None)
        with patch.object(self.app, 'cf', side_effect=[[], {'id': 'owned'}]) as cf:
            item = self.app.dns('media', False, 'admin', None)
            self.assertFalse(cf.call_args.args[2]['proxied'])
            self.assertEqual(item['dnsRecordId'], 'owned')
        without_hostname=self.body()
        without_hostname.pop('hostname')
        retained=self.app.validate_server('media',without_hostname)
        self.assertEqual(retained['hostname'],item['hostname'])
        self.assertEqual(retained['dnsRecordId'],'owned')
        renamed = self.body(); renamed['hostname'] = 'new.hosts.example.com'
        with self.assertRaises(ValueError):
            self.app.validate_server('media', renamed)
        with patch.object(self.app, 'cf', return_value={}):
            self.assertIsNone(self.app.dns('media', True, 'admin', None)['dnsRecordId'])


class ProxyTests(unittest.TestCase):
    def test_udp_reply_client_isolation_and_disable(self):
        proxy = unm.Proxy({'max_connections': 16})
        async def exercise():
            class Echo(asyncio.DatagramProtocol):
                def connection_made(self, transport): self.transport=transport
                def datagram_received(self, data, client): self.transport.sendto(data,client)
            class Client(asyncio.DatagramProtocol):
                def __init__(self): self.reply=asyncio.get_running_loop().create_future()
                def datagram_received(self, data, address):
                    if not self.reply.done(): self.reply.set_result(data)
            upstream,_=await proxy.loop.create_datagram_endpoint(Echo,local_addr=('127.0.0.1',0))
            reserved,_=await proxy.loop.create_datagram_endpoint(Echo,local_addr=('127.0.0.1',0))
            port=reserved.get_extra_info('sockname')[1]
            reserved.close();await asyncio.sleep(.02)
            await proxy.reconcile([dict(address='127.0.0.1',targetPort=upstream.get_extra_info('sockname')[1],publicPort=port,protocol='udp',enabled=True)])
            clients=[]
            try:
                for payload in (b'first-client',b'second-client'):
                    transport,client=await proxy.loop.create_datagram_endpoint(Client,remote_addr=('127.0.0.1',port))
                    clients.append(transport);transport.sendto(payload)
                    self.assertEqual(await asyncio.wait_for(client.reply,3),payload)
                await proxy.reconcile([])
                self.assertEqual(proxy.listeners,{})
            finally:
                for transport in clients: transport.close()
                upstream.close()
                await proxy.reconcile([])
                await asyncio.sleep(.05)
        try:
            asyncio.run_coroutine_threadsafe(exercise(),proxy.loop).result(10)
        finally:
            proxy.loop.call_soon_threadsafe(proxy.loop.stop);proxy.thread.join();proxy.loop.close()
    def test_real_tcp_forwarding_conflict_and_disable(self):
        proxy = unm.Proxy({'max_connections': 16})

        async def exercise():
            async def echo(reader, writer):
                try:
                    while chunk := await reader.read(4096):
                        writer.write(chunk); await writer.drain()
                finally:
                    writer.close()
            upstream = await asyncio.start_server(echo, '127.0.0.1', 0)
            reserved = await asyncio.start_server(echo, '0.0.0.0', 0, reuse_address=False)
            target = upstream.sockets[0].getsockname()[1]
            port = reserved.sockets[0].getsockname()[1]
            entry = dict(address='127.0.0.1', targetPort=target, publicPort=port, enabled=True)
            with self.assertRaises(OSError):
                await proxy.reconcile([entry])
            reserved.close(); await reserved.wait_closed()
            await proxy.reconcile([entry])
            reader, writer = await asyncio.open_connection('127.0.0.1', port)
            payload = b'network-data' * 10000
            writer.write(payload); await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(len(payload)), 5), payload)
            writer.close(); await writer.wait_closed()
            await proxy.reconcile([])
            with self.assertRaises(OSError):
                await asyncio.open_connection('127.0.0.1', port)
            await asyncio.sleep(.1)
            upstream.close(); await upstream.wait_closed()
        try:
            asyncio.run_coroutine_threadsafe(exercise(), proxy.loop).result(10)
        finally:
            proxy.loop.call_soon_threadsafe(proxy.loop.stop)
            proxy.thread.join()
            proxy.loop.close()


if __name__ == '__main__':
    unittest.main()
