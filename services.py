"""Website and authoritative DNS management with preview and transactional apply."""
import json
import secrets
import subprocess
from service_schema import proxy, record, validate_records
from networking import valid_id
from ports import label


class Services:
    def init_services(self):
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS proxy_hosts(id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dns_records(id TEXT PRIMARY KEY, body TEXT NOT NULL);
        ''')
        self.db.commit()

    def service_call(self, payload):
        if payload['action']!='status' and self.cfg['mode']!='live':
            raise ValueError('Service changes require live mode')
        result=subprocess.run(['sudo','-n','/usr/local/sbin/unm-services'],input=json.dumps(payload),text=True,capture_output=True,timeout=50)
        if result.returncode:
            message=result.stderr.strip()
            raise ValueError(message if message.startswith('UNM: ') else 'Website/DNS apply failed; inspect service setup and logs')
        return json.loads(result.stdout)

    def services_status(self):
        try:
            return dict(self.service_call(dict(action='status')),available=True)
        except (ValueError,OSError,subprocess.TimeoutExpired):
            return dict(available=False,webEnabled=False,dnsEnabled=False,zones=self.cfg.get('dns_zones',['minecraft.mrhaydenn.us']),
                        nameservers=self.cfg.get('dns_nameservers',['ns1.mrhaydenn.us']),publicIP=self.cfg.get('public_ip',''),
                        certificates=[],message='Backends not configured. Preview entries are saved only; follow the website/DNS setup guide.')

    def proxy_hosts(self):
        return [json.loads(r['body']) for r in self.db.execute('SELECT * FROM proxy_hosts ORDER BY id')]

    def dns_records(self):
        return [json.loads(r['body']) for r in self.db.execute('SELECT * FROM dns_records ORDER BY id')]

    def apply_services(self, kind, items):
        if self.cfg['mode']!='live':
            return
        if kind=='web':
            hosts={**{h['id']:h['address'] for h in self.hosts()}, '@vps':'127.0.0.1'}
            items=[dict(r,address=hosts[r['hostId']]) for r in items]
        self.service_call(dict(action=kind,items=items))

    def save_proxy(self, body, actor):
        rid=valid_id(body.get('id') or 'site-'+secrets.token_hex(8))
        hosts={**{h['id']:h['address'] for h in self.hosts()}, '@vps':'127.0.0.1'}
        if body.get('hostId') not in hosts:
            raise ValueError('Select a registered WireGuard host')
        item=proxy(dict(body,address=hosts[body['hostId']]),self.cfg['wireguard_subnet'])
        item.pop('address')
        item.update(id=rid,hostId=body['hostId'],name=label(dict(body,id=rid)))
        old=self.proxy_hosts()
        if any(set(r['domains']) & set(item['domains']) for r in old if r['id']!=rid):
            raise ValueError('A domain already belongs to another website')
        self.save_service_item('proxy_hosts','web',old,item,actor)
        return item

    def save_dns(self, body, actor):
        rid=valid_id(body.get('id') or 'dns-'+secrets.token_hex(8))
        self.assert_dns_unmanaged(rid)
        zones=self.services_status()['zones']
        item=record(body,zones)
        item['id']=rid
        old=self.dns_records()
        validate_records([r for r in old if r['id']!=rid]+[item])
        self.save_service_item('dns_records','dns',old,item,actor)
        return item

    def save_service_item(self, table, kind, old, item, actor):
        desired=[r for r in old if r['id']!=item['id']]+[item]
        self.apply_services(kind,desired)
        try:
            self.db.execute('INSERT OR REPLACE INTO '+table+' VALUES(?,?)',(item['id'],json.dumps(item)))
            self.audit(actor,kind+'.save',item['id']);self.db.commit()
        except Exception:
            self.db.rollback();self.apply_services(kind,old);raise

    def delete_service_item(self, kind, rid, actor):
        if kind=='dns': self.assert_dns_unmanaged(rid)
        table='proxy_hosts' if kind=='web' else 'dns_records'
        old=self.proxy_hosts() if kind=='web' else self.dns_records()
        self.apply_services(kind,[r for r in old if r['id']!=rid])
        try:
            self.db.execute('DELETE FROM '+table+' WHERE id=?',(rid,))
            self.audit(actor,kind+'.delete',rid);self.db.commit()
        except Exception:
            self.db.rollback();self.apply_services(kind,old);raise
