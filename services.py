"""Website and authoritative DNS management with preview and transactional apply."""
import ipaddress
import os
from urllib.parse import urlencode
import json
import secrets
import subprocess
from service_schema import domain, proxy, record, validate_records
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
            return dict(available=False,webEnabled=False,dnsEnabled=False,zones=self.cfg.get('dns_zones',['minecraft.example.com']),
                        nameservers=self.cfg.get('dns_nameservers',['ns1.example.com']),publicIP=self.cfg.get('public_ip',''),
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
        if type(body.get('cloudflareDNS', False)) is not bool:
            raise ValueError('Cloudflare DNS must be true or false')
        item['cloudflareDNS'] = body.get('cloudflareDNS', False)
        self.save_service_item('proxy_hosts','web',old,item,actor)
        return self.publish_website_dns(item)

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

    def cloudflare_website_status(self):
        return dict(configured=bool(self.cfg.get('cloudflare_zone_id') and
                    self.cfg.get('cloudflare_zone_name') and self.cfg.get('public_ip') and
                    os.environ.get('CLOUDFLARE_API_TOKEN')),
                    zone=self.cfg.get('cloudflare_zone_name', ''))

    def publish_website_dns(self, item):
        if not item.get('cloudflareDNS'):
            return item
        if self.cfg['mode'] != 'live':
            status = 'Preview: DNS was not changed'
        elif not item['enabled']:
            status = 'Website disabled; DNS records retained'
        else:
            try:
                if not self.cloudflare_website_status()['configured']:
                    raise ValueError('Configure Cloudflare zone name, zone ID, public IP and API token first')
                zone = domain(self.cfg['cloudflare_zone_name'])
                address = str(ipaddress.IPv4Address(self.cfg['public_ip']))
                names = item['domains']
                if any(n != zone and not n.endswith('.'+zone) for n in names):
                    raise ValueError('Website domain is outside the configured Cloudflare zone')
                # Inspect all names before creating any record. Never replace existing DNS.
                pending = []
                checked = set()
                for name in names:
                    ancestor = name
                    while ancestor != zone:
                        if ancestor not in checked:
                            ns = self.cf('GET', '?'+urlencode(dict(name=ancestor, type='NS')))
                            if ns:
                                raise ValueError('Domain is delegated to another DNS server; manage its records there')
                            checked.add(ancestor)
                        ancestor = ancestor.split('.', 1)[1]
                    existing = self.cf('GET', '?'+urlencode(dict(name=name, per_page=100)))
                    blockers = [r for r in existing if r['type'] in ('A','AAAA','CNAME','NS')]
                    if blockers:
                        if all(r['type']=='A' and r['content']==address for r in blockers):
                            continue
                        raise ValueError('Conflicting DNS record for '+name+'; existing records were left unchanged')
                    pending.append(name)
                for name in pending:
                    self.cf('POST', '', dict(type='A', name=name, content=address, ttl=300,
                            proxied=False, comment='UNM website: '+item['id']))
                status = 'Synced to Cloudflare (A records; existing matching records preserved)'
            except (ValueError, OSError, TimeoutError) as error:
                # Website remains saved; retry through Apply saved websites after resolving DNS.
                status = 'DNS publishing failed: '+(str(error) if isinstance(error, ValueError) else
                         'Cannot contact Cloudflare; check the API token, permissions and connection')
        item = dict(item, cloudflareStatus=status)
        self.db.execute('UPDATE proxy_hosts SET body=? WHERE id=?', (json.dumps(item),item['id']))
        self.db.commit()
        return item
