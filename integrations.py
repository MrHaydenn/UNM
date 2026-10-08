"""Scoped, revocable DNS integration; never grants general panel access."""
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import threading
from service_schema import record, validate_records

class Integrations:
    def init_integrations(self):
        self.integration_lock = threading.RLock()
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS dns_clients(id TEXT PRIMARY KEY, hash TEXT NOT NULL, zone TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dns_publications(client TEXT, server TEXT, body TEXT NOT NULL, PRIMARY KEY(client,server));
        """)
        self.db.commit()

    def assert_dns_unmanaged(self, rid):
        for row in self.db.execute('SELECT body FROM dns_publications'):
            if rid in json.loads(row['body']).get('recordIds',[]):
                raise ValueError('This record is managed by an integration; change its address in MMSM')

    def create_dns_client(self, name, zone):
        if not re.fullmatch(r'[a-z0-9-]{1,48}', name):
            raise ValueError('Use lowercase letters, digits and hyphens for the client name')
        if zone not in self.services_status()['zones']:
            raise ValueError('Choose a configured DNS zone')
        token = secrets.token_urlsafe(32)
        self.db.execute('INSERT INTO dns_clients VALUES(?,?,?)', (name,hashlib.sha256(token.encode()).hexdigest(),zone))
        self.db.commit()
        return token

    def dns_client(self, authorization):
        if not authorization.startswith('Bearer '):
            raise PermissionError('DNS integration token required')
        hashed = hashlib.sha256(authorization[7:].encode()).hexdigest()
        for row in self.db.execute('SELECT * FROM dns_clients'):
            if hmac.compare_digest(row['hash'],hashed):
                return dict(row)
        raise PermissionError('Invalid or revoked DNS integration token')

    def publish_server_dns(self, client, sid, body=None):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',sid):
            raise ValueError('Invalid server ID')
        if self.cfg['mode'] != 'live':
            raise ValueError('DNS integration requires live mode')
        status = self.services_status()
        if not status.get('dnsEnabled') or not status.get('dnsRunning'):
            raise ValueError('Start and enable the UNM DNS backend first')
        with self.integration_lock:
            row=self.db.execute('SELECT body FROM dns_publications WHERE client=? AND server=?',(client['id'],sid)).fetchone()
            previous=json.loads(row['body']) if row else {}
            old=self.dns_records()
            owned=set(previous.get('recordIds',[]))
            desired=[r for r in old if r['id'] not in owned]
            result={'hostname':'','recordIds':[],'published':False}
            if body is not None:
                if body.get('zone') != client['zone']:
                    raise ValueError('Token is restricted to a different DNS zone')
                name=body.get('label','')
                if not isinstance(name,str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',name):
                    raise ValueError('Choose a single lowercase DNS label')
                port=body.get('port')
                if type(port) is not int or not 1<=port<=65535:
                    raise ValueError('Public port must be between 1 and 65535')
                address=str(ipaddress.IPv4Address(status.get('publicIP','')))
                fqdn=name+'.'+client['zone']
                srv='_minecraft._tcp.'+fqdn
                if any(r['name'] in (fqdn,srv) for r in desired):
                    raise ValueError('That DNS name is owned by another entry; existing records will not be replaced')
                prefix='integration-'+hashlib.sha256((client['id']+':'+sid).encode()).hexdigest()[:24]
                records=[]
                for kind,owner,content in [('A',fqdn,address),('SRV',srv,f'0 5 {port} {fqdn}')]:
                    item=record(dict(zone=client['zone'],name=owner,type=kind,content=content,ttl=300,enabled=True),[client['zone']])
                    item['id']=prefix+'-'+kind.lower()
                    records.append(item)
                desired+=records
                result=dict(hostname=fqdn,port=port,recordIds=[r['id'] for r in records],published=True)
            validate_records(desired)
            if sorted(old,key=lambda r:r['id']) != sorted(desired,key=lambda r:r['id']):
                self.apply_services('dns',desired)
            try:
                for rid in owned:
                    self.db.execute('DELETE FROM dns_records WHERE id=?',(rid,))
                for item in desired:
                    if item['id'] in result['recordIds']:
                        self.db.execute('INSERT INTO dns_records VALUES(?,?)',(item['id'],json.dumps(item)))
                if body is None:
                    self.db.execute('DELETE FROM dns_publications WHERE client=? AND server=?',(client['id'],sid))
                else:
                    self.db.execute('INSERT OR REPLACE INTO dns_publications VALUES(?,?,?)',(client['id'],sid,json.dumps(result)))
                self.audit('integration:'+client['id'],'dns.publish' if body else 'dns.remove',sid)
                self.db.commit()
            except Exception:
                self.db.rollback()
                self.apply_services('dns',old)
                raise
            return result
