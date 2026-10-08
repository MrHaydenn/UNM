"""UNM: dependency-free control panel and bounded TCP forwarding service."""
from integrations import Integrations
import argparse
import asyncio
import base64
import getpass
import hashlib
import hmac
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import struct
import subprocess
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, urlopen
from networking import Networking
from ports import port_range, protocols, sockets, label
from udp_proxy import UDPProxy
from traffic import Traffic
from services import Services

ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()
LOG = logging.getLogger('unm')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', value):
        raise ValueError('Use 1–48 lowercase letters, numbers or hyphens for the ID.')
    return value


def totp(secret, timestamp=None):
    counter = int((time.time() if timestamp is None else timestamp) // 30)
    raw = hmac.new(base64.b32decode(secret), struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = raw[-1] & 15
    return str((struct.unpack('>I', raw[offset:offset + 4])[0] & 0x7fffffff) % 1000000).zfill(6)


class Proxy:
    def __init__(self, cfg):
        self.cfg, self.listeners, self.active = cfg, {}, 0
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    async def connect(self, reader, writer, target):
        if self.active >= self.cfg['max_connections']:
            writer.close()
            return
        self.active += 1
        upstream = None
        try:
            remote, upstream = await asyncio.wait_for(asyncio.open_connection(*target), 10)

            async def pump(source, destination):
                while True:
                    chunk = await asyncio.wait_for(source.read(65536), 300)
                    if not chunk:
                        if destination.can_write_eof():
                            destination.write_eof()
                        return
                    destination.write(chunk)
                    await destination.drain()

            tasks = [asyncio.create_task(pump(reader, upstream)), asyncio.create_task(pump(remote, writer))]
            try:
                await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except (OSError, asyncio.TimeoutError):
            LOG.info('Upstream unavailable for %s:%s', *target)
        finally:
            self.active -= 1
            for stream in (writer, upstream):
                if stream:
                    stream.close()

    async def reconcile(self, entries):
        wanted = {}
        for r in entries:
            if not r['enabled']:
                continue
            public_start, public_end = port_range(r['publicPort'])
            target_start, _ = port_range(r['targetPort'])
            for port in range(public_start, public_end + 1):
                for protocol in protocols(r.get('protocol', 'tcp')):
                    wanted[port, protocol] = (r['address'], target_start + port - public_start)
        # Bind new sockets before removing existing listeners. Bind failure leaves old service intact.
        added = {}
        try:
            for key, target in wanted.items():
                if key not in self.listeners:
                    port, protocol = key
                    async def accept(reader, writer, p=key):
                        await self.connect(reader, writer, self.listeners[p][1])
                    if protocol == 'tcp':
                        server = await asyncio.start_server(accept, '0.0.0.0', port, start_serving=False, reuse_address=False)
                    else:
                        _, server = await self.loop.create_datagram_endpoint(lambda t=target: UDPProxy(t, self.cfg['max_connections']), local_addr=('0.0.0.0', port))
                    added[key] = (server, target)
        except Exception:
            for server, _ in added.values():
                server.close()
                if isinstance(server, asyncio.Server):
                    await server.wait_closed()
            raise
        self.listeners.update(added)
        for port in list(self.listeners):
            if port not in wanted:
                server, _ = self.listeners.pop(port)
                server.close()
                if isinstance(server, asyncio.Server):
                    await server.wait_closed()
            else:
                if isinstance(self.listeners[port][0], UDPProxy):
                    self.listeners[port][0].update_target(wanted[port])
                self.listeners[port] = (self.listeners[port][0], wanted[port])
        for server, _ in added.values():
            if isinstance(server, asyncio.Server):
                await server.start_serving()

    def apply(self, entries):
        asyncio.run_coroutine_threadsafe(self.reconcile(entries), self.loop).result(20)


class App(Networking, Traffic, Services, Integrations):
    def __init__(self, config):
        self.cfg = json.loads(Path(config).read_text())
        c = self.cfg
        if c['mode'] not in ('preview', 'live'):
            raise ValueError('mode must be preview or live')
        if not 1024 <= c['port_min'] <= c['port_max'] <= 65535:
            raise ValueError('Managed public ports must be between 1024 and 65535')
        ipaddress.ip_network(c['wireguard_subnet'])
        if c['secure_cookie'] and not c['origin'].startswith('https://'):
            raise ValueError('Secure cookies require an HTTPS origin')
        origin = urlsplit(c['origin'])
        if not c['secure_cookie'] and (origin.scheme != 'http' or origin.hostname not in ('localhost', '127.0.0.1')
                                       or origin.username or origin.password or origin.path or origin.query or origin.fragment):
            raise ValueError('Public access requires HTTPS and secure_cookie=true')
        data = Path(c['data_dir'])
        data.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(data / 'unm.sqlite', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY, password TEXT NOT NULL, totp TEXT);
        CREATE TABLE IF NOT EXISTS hosts(id TEXT PRIMARY KEY, address TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS servers(id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tokens(id TEXT PRIMARY KEY, hash TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS firewall_rules(id TEXT PRIMARY KEY, port INTEGER UNIQUE NOT NULL, enabled INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(at INTEGER, actor TEXT, action TEXT, resource TEXT);
        CREATE TABLE IF NOT EXISTS firewall_items(id TEXT PRIMARY KEY,body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        ''')
        columns = {r['name'] for r in self.db.execute('PRAGMA table_info(hosts)')}
        if 'public_key' not in columns:
            self.db.execute('ALTER TABLE hosts ADD COLUMN public_key TEXT')
        if 'managed' not in columns:
            self.db.execute('ALTER TABLE hosts ADD COLUMN managed INTEGER NOT NULL DEFAULT 0')
        # External tokens are retired; existing forwarding entries remain intact.
        self.db.execute('DELETE FROM tokens')
        for row in self.db.execute('SELECT * FROM firewall_rules').fetchall():
            item = dict(id=row['id'], name=row['id'], port=row['port'], protocol='tcp', enabled=bool(row['enabled']))
            self.db.execute('INSERT OR IGNORE INTO firewall_items VALUES(?,?)', (row['id'], json.dumps(item)))
        self.db.execute('DELETE FROM firewall_rules')
        self.db.commit()
        self.init_traffic()
        self.init_services()
        self.init_integrations()
        self.sessions, self.attempts, self.otp_used = {}, {}, {}
        self.proxy = Proxy(c) if c['mode'] == 'live' else None

    def audit(self, actor, action, resource):
        self.db.execute('INSERT INTO audit VALUES(?,?,?,?)', (int(time.time()), actor, action, resource))
        self.db.execute('DELETE FROM audit WHERE rowid NOT IN (SELECT rowid FROM audit ORDER BY rowid DESC LIMIT 2000)')

    def hosts(self):
        return [dict(id=r['id'], address=r['address'], publicKey=r['public_key'], managed=bool(r['managed']))
                for r in self.db.execute('SELECT * FROM hosts ORDER BY id')]

    def servers(self):
        return [json.loads(r['body']) for r in self.db.execute('SELECT body FROM servers ORDER BY id')]

    def resolved(self, entries):
        hosts = {h['id']: h['address'] for h in self.hosts()}
        return [dict(r, address=hosts[r['hostId']]) for r in entries]

    def firewall(self, entries, rules=None):
        if self.proxy:
            rules = self.firewall_rules() if rules is None else rules
            if not self.firewall_enabled():
                return
            desired = set()
            for r in entries:
                if r['enabled']:
                    desired |= sockets(r)
            for r in rules:
                if r['enabled']:
                    desired |= sockets(r, 'port')
            ports = sorted(str(p) + '/' + proto for p, proto in desired)
            subprocess.run(['sudo', '-n', '/usr/local/sbin/unm-firewall'], input=json.dumps(ports),
                           text=True, capture_output=True, check=True, timeout=120)

    def apply(self, entries):
        if self.proxy:
            self.proxy.apply(self.resolved(entries))
            self.firewall(entries)

    def validate_server(self, sid, body, scope=None):
        valid_id(sid)
        host = body.get('hostId')
        if host not in {h['id'] for h in self.hosts()}:
            raise ValueError('Unknown hostId; register this host first.')
        start, end = port_range(body.get('publicPort'))
        target_start, target_end = port_range(body.get('targetPort'))
        if end - start != target_end - target_start:
            raise ValueError('Public and destination ranges must contain the same number of ports')
        protocol = body.get('protocol', 'tcp')
        protocols(protocol)
        port = start if start == end else str(start) + '-' + str(end)
        if not self.cfg['port_min'] <= start <= end <= self.cfg['port_max']:
            raise ValueError('Public port is outside the reserved range')
        if type(body.get('enabled')) is not bool:
            raise ValueError('enabled must be true or false')
        old = next((r for r in self.servers() if r['id'] == sid), None)
        hostname = body.get('hostname', (old or {}).get('hostname','')).lower().rstrip('.')
        suffix = self.cfg['dns_suffix'].lower().rstrip('.')
        if hostname and (not hostname.endswith('.' + suffix) or len(hostname) > 253 or
                         any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', p) for p in hostname.split('.'))):
            raise ValueError('Hostname must be a valid name under ' + suffix)
        for r in self.servers():
            if r['id'] != sid and (sockets(r) & sockets(dict(publicPort=port,protocol=protocol)) or (hostname and r['hostname'] == hostname)):
                raise ValueError('Port or hostname already belongs to another forwarding route')
        old = next((r for r in self.servers() if r['id'] == sid), None)
        if old and old.get('dnsRecordId') and hostname != old['hostname']:
            raise ValueError('Remove the managed DNS record before changing its hostname')
        return dict(id=sid, name=label(dict(body,id=sid)), protocol=protocol, hostId=host, targetPort=target_start if target_start == target_end else str(target_start)+'-'+str(target_end), publicPort=port,
                    hostname=hostname, enabled=body['enabled'], dnsRecordId=(old or {}).get('dnsRecordId'),
                    dnsStatus=(old or {}).get('dnsStatus', 'Not synced'))

    def save_server(self, sid, body, actor, scope=None):
        item = self.validate_server(sid, body, scope)
        old = self.servers()
        desired = [r for r in old if r['id'] != sid] + [item]
        try:
            self.apply(desired)
        except Exception:
            try:
                self.apply(old)
            except Exception:
                LOG.exception('Rollback failed; administrator intervention required')
            raise ValueError('Network apply failed; check service logs. Configuration was not saved.')
        self.db.execute('INSERT OR REPLACE INTO servers VALUES(?,?)', (sid, json.dumps(item)))
        self.audit(actor, 'forward.save', sid)
        self.db.commit()
        return item

    def cf(self, method, path, body=None):
        token = os.environ.get('CLOUDFLARE_API_TOKEN', '')
        zone = self.cfg['cloudflare_zone_id']
        if not token or not re.fullmatch(r'[a-f0-9]{32}', zone):
            raise ValueError('Configure Cloudflare zone ID and CLOUDFLARE_API_TOKEN first')
        req = Request('https://api.cloudflare.com/client/v4/zones/' + zone + '/dns_records' + path,
                      data=json.dumps(body).encode() if body is not None else None, method=method,
                      headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        with urlopen(req, timeout=15) as response:
            result = json.load(response)
        if not result.get('success'):
            raise ValueError('Cloudflare rejected the DNS change')
        return result['result']

    def dns(self, sid, remove, actor, scope):
        item = next((r for r in self.servers() if r['id'] == sid), None)
        if not item:
            raise ValueError('Forwarding route not found')
        self.validate_server(sid, item, scope)
        if self.cfg['mode'] != 'live':
            raise ValueError('DNS changes are disabled in preview mode')
        if remove:
            if item['dnsRecordId']:
                self.cf('DELETE', '/' + item['dnsRecordId'])
            item['dnsRecordId'], item['dnsStatus'] = None, 'Removed'
        else:
            if not item['hostname']:
                raise ValueError('Set a hostname first')
            ip = str(ipaddress.IPv4Address(self.cfg['public_ip']))
            payload = dict(type='A', name=item['hostname'], content=ip, ttl=120, proxied=False,
                           comment='UNM managed server: ' + sid)
            if item['dnsRecordId']:
                result = self.cf('PUT', '/' + item['dnsRecordId'], payload)
            else:
                existing = self.cf('GET', '?' + urlencode({'name': item['hostname']}))
                if existing:
                    raise ValueError('DNS name already exists; UNM will not overwrite an unmanaged record')
                result = self.cf('POST', '', payload)
            item['dnsRecordId'], item['dnsStatus'] = result['id'], 'Synced'
        self.db.execute('UPDATE servers SET body=? WHERE id=?', (json.dumps(item), sid))
        self.audit(actor, 'dns.remove' if remove else 'dns.sync', sid)
        self.db.commit()
        return item


class Handler(BaseHTTPRequestHandler):
    server_version = 'UNM'
    def log_message(self, *args):
        pass  # No URLs, credentials or bearer tokens in logs.

    def send(self, status, value, cookie=None, html=False):
        raw = value.encode() if html else json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(raw)

    def cookie(self, token, age=28800):
        return 'unm_session=' + token + '; HttpOnly; SameSite=Strict; Path=/; Max-Age=' + str(age) + ('; Secure' if self.app.cfg['secure_cookie'] else '')

    @property
    def app(self):
        return self.server.app

    def read_body(self):
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 < size <= 16384 or self.headers.get_content_type() != 'application/json':
            raise ValueError('A JSON body of at most 16KB is required')
        body = json.loads(self.rfile.read(size))
        if not isinstance(body, dict):
            raise ValueError('JSON body must be an object')
        return body

    def authenticate(self):
        app = self.app
        if self.headers.get('Authorization'):
            raise PermissionError('External tokens are disabled; sign in through the panel')
        cookies = SimpleCookie()
        cookies.load(self.headers.get('Cookie', ''))
        raw = cookies.get('unm_session')
        key = digest(raw.value) if raw else ''
        session = app.sessions.get(key)
        if session and session['expires'] > time.time():
            if self.command != 'GET':
                if self.headers.get('Origin') != app.cfg['origin'] or not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), session['csrf']):
                    raise PermissionError('Invalid origin or CSRF token')
            return session['name'], None, session
        raise PermissionError('Authentication required')

    def route(self):
        path = urlsplit(self.path).path
        app = self.app
        if self.command == 'GET' and path in ('/', '/app.js', '/style.css'):
            filename = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[path]
            if path == '/':
                self.send(200, (ROOT / 'web' / filename).read_text(encoding='utf-8'), html=True)
            else:
                raw = (ROOT / 'web' / filename).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/javascript' if path.endswith('.js') else 'text/css')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(raw)
            return
        if path == '/healthz' and self.command == 'GET':
            return self.send(200, {'ok': True, 'mode': app.cfg['mode']})
        if path == '/api/login' and self.command == 'POST':
            if self.headers.get('Origin') != app.cfg['origin']:
                raise PermissionError('Invalid origin')
            now = time.time()
            app.attempts = {k: v for k, v in app.attempts.items() if v[1] > now}
            count, expiry = app.attempts.get('global', (0, now + 60))
            if count >= 15:
                return self.send(429, {'error': 'Too many login attempts. Try again in a minute.'})
            app.attempts['global'] = (count + 1, expiry)
            body = self.read_body()
            row = app.db.execute('SELECT * FROM users WHERE name=?', (body.get('username'),)).fetchone()
            stored = row['password'] if row else '00' * 16 + ':' + '00' * 32
            supplied = password_hash(str(body.get('password', '')), stored.split(':')[0])
            if not row or not hmac.compare_digest(stored, supplied):
                return self.send(401, {'error': 'Incorrect username or password'})
            if row['totp']:
                valid = next((step for step in (-1, 0, 1) if hmac.compare_digest(
                    totp(row['totp'], now + step * 30), str(body.get('code', '')))), None)
                counter = int(now // 30) + valid if valid is not None else -1
                if valid is None or counter <= app.otp_used.get(row['name'], -1):
                    return self.send(401, {'error': 'Invalid or already used authenticator code'})
                app.otp_used[row['name']] = counter
            app.sessions = {k: v for k, v in app.sessions.items() if v['expires'] > now}
            token = secrets.token_urlsafe(32)
            app.sessions[digest(token)] = dict(name=row['name'], expires=now + 28800, csrf=secrets.token_urlsafe(24))
            app.audit(row['name'], 'login', '')
            app.db.commit()
            return self.send(200, {'ok': True}, cookie=self.cookie(token))
        if path.startswith('/api/integrations/servers/'):
            client=app.dns_client(self.headers.get('Authorization',''))
            if self.command not in ('PUT','DELETE'):
                return self.send(405,{'error':'Use PUT or DELETE'})
            result=app.publish_server_dns(client,path[len('/api/integrations/servers/'):],self.read_body() if self.command=='PUT' else None)
            return self.send(200,result)
        actor, scope, session = self.authenticate()
        if path == '/api/integration-keys':
            if self.command == 'GET':
                return self.send(200, app.integration_keys())
            if self.command == 'POST':
                return self.send(201, app.manage_integration_key(actor, 'create', body=self.read_body()))
        key_parts = path.strip('/').split('/')
        if len(key_parts) in (3, 4) and key_parts[:2] == ['api', 'integration-keys']:
            key_id = valid_id(key_parts[2])
            if len(key_parts) == 4 and key_parts[3] == 'rotate' and self.command == 'POST':
                return self.send(200, app.manage_integration_key(actor, 'rotate', key_id))
            if len(key_parts) == 3 and self.command in ('PUT', 'DELETE'):
                action = 'rename' if self.command == 'PUT' else 'revoke'
                return self.send(200, app.manage_integration_key(actor, action, key_id, self.read_body() if action == 'rename' else None))
        if path == '/api/update' and self.command in ('GET','POST'):
            result = subprocess.run(['sudo','-n','/usr/local/sbin/unm-update'],input=json.dumps({'action':'start' if self.command=='POST' else 'status'}),capture_output=True,text=True,timeout=15)
            if result.returncode: raise ValueError('Update helper is not installed; run the VPS update script once first')
            return self.send(202 if self.command=='POST' else 200,json.loads(result.stdout))
        if path == '/api/wireguard/provisioning' and self.command == 'POST':
            body = self.read_body()
            return self.send(200, app.wg_call({'action':'configure','endpoint':body.get('endpoint','')}))
        if path == '/api/state'  and self.command == 'GET':
            return self.send(200, dict(user=actor, csrf=session['csrf'], hosts=app.hosts(), forwards=app.servers(),
                                      firewallRules=app.firewall_rules(), wireguard=app.wg_status(),
                                      firewall=app.firewall_state(),traffic=app.traffic_summary(30),
                                      websites=app.proxy_hosts(),dnsRecords=app.dns_records(),services=app.services_status(),integrationKeys=app.integration_keys(),
                                      mode=app.cfg['mode'], portMin=app.cfg['port_min'], portMax=app.cfg['port_max'],
                                      subnet=app.cfg['wireguard_subnet'], dnsSuffix=app.cfg['dns_suffix'],
                                      audit=[dict(r) for r in app.db.execute('SELECT * FROM audit ORDER BY rowid DESC LIMIT 40')]))
        if path == '/api/logout' and self.command == 'POST' and session:
            app.sessions = {k: v for k, v in app.sessions.items() if v is not session}
            return self.send(200, {'ok': True}, cookie=self.cookie('', 0))
        if path == '/api/hosts' and self.command == 'POST':
            return self.send(201, app.add_host(self.read_body(), actor))
        parts = path.strip('/').split('/')
        if len(parts) >= 3 and parts[:2] == ['api', 'hosts']:
            hid = valid_id(parts[2])
            if len(parts) == 3 and self.command == 'DELETE':
                app.remove_host(hid, actor)
                return self.send(200, {'ok': True})
            if len(parts) == 4 and parts[3] == 'configuration' and self.command == 'GET':
                host = next((h for h in app.hosts() if h['id'] == hid), None)
                if not host or not host['managed']:
                    raise ValueError('Configuration is available for managed hosts only')
                return self.send(200, dict(configuration=app.host_config(host, app.wg_status()), privateKeyIncluded=False))
        if path == '/api/firewall' and self.command == 'POST':
            body=self.read_body()
            body['id']=body.get('id') or 'rule-'+secrets.token_hex(8)
            app.save_firewall_rule(body, actor)
            return self.send(200, {'ok': True})
        if path == '/api/forwards' and self.command == 'POST':
            body=self.read_body()
            return self.send(201,app.save_server('forward-'+secrets.token_hex(8),body,actor))
        if path in ('/api/websites','/api/dns-records') and self.command=='POST':
            item=app.save_proxy(self.read_body(),actor) if path=='/api/websites' else app.save_dns(self.read_body(),actor)
            return self.send(200,item)
        if path in ('/api/websites/apply','/api/dns-records/apply') and self.command=='POST':
            app.apply_services('web' if path.startswith('/api/websites') else 'dns',app.proxy_hosts() if path.startswith('/api/websites') else app.dns_records())
            return self.send(200,dict(ok=True,preview=app.cfg['mode']=='preview'))
        if len(parts)==3 and parts[1] in ('websites','dns-records') and parts[0]=='api' and self.command=='DELETE':
            app.delete_service_item('web' if parts[1]=='websites' else 'dns',valid_id(parts[2]),actor)
            return self.send(200,dict(ok=True))
        if path == '/api/firewall/service' and self.command == 'POST':
            app.set_firewall_enabled(self.read_body().get('enabled'),actor)
            return self.send(200, {'ok':True})
        if path == '/api/traffic' and self.command == 'GET':
            from urllib.parse import parse_qs
            days=int(parse_qs(urlsplit(self.path).query).get('days',['30'])[0])
            if days not in (1,7,30):
                raise ValueError('Choose 1, 7 or 30 days')
            return self.send(200,app.traffic_summary(days))
        if len(parts) == 3 and parts[:2] == ['api', 'firewall'] and self.command == 'DELETE':
            app.delete_firewall_rule(valid_id(parts[2]), actor)
            return self.send(200, {'ok': True})
        prefix = '/api/forwards/'
        if path.startswith(prefix):
            rest = path[len(prefix):].split('/')
            sid = valid_id(rest[0])
            item = next((r for r in app.servers() if r['id'] == sid), None)
            if len(rest) == 2 and rest[1] == 'dns' and self.command in ('POST', 'DELETE'):
                return self.send(200, app.dns(sid, self.command == 'DELETE', actor, scope))
            if len(rest) != 1:
                return self.send(404, {'error': 'Route not found'})
            if self.command == 'GET':
                return self.send(200 if item else 404, item or {'error': 'Forwarding route not found'})
            if self.command == 'PUT':
                return self.send(200, app.save_server(sid, self.read_body(), actor, scope))
            if self.command == 'DELETE':
                if not item:
                    return self.send(200, {'ok': True})
                if item.get('dnsRecordId'):
                    raise ValueError('Remove this route’s managed DNS record first')
                app.save_server(sid, dict(item, enabled=False), actor, scope)
                app.db.execute('DELETE FROM servers WHERE id=?', (sid,))
                app.audit(actor, 'forward.delete', sid)
                app.db.commit()
                return self.send(200, {'ok': True})
        self.send(404, {'error': 'Route not found'})

    def handle_request(self):
        self.connection.settimeout(15)
        try:
            with LOCK:
                self.route()
        except PermissionError as exc:
            self.send(403, {'error': str(exc)})
        except (ValueError, KeyError, TypeError, sqlite3.IntegrityError) as exc:
            self.send(400, {'error': str(exc)})
        except Exception:
            LOG.exception('Request failed')
            self.send(503, {'error': 'Operation failed. Check UNM logs; no success is implied.'})

    do_GET = do_POST = do_PUT = do_DELETE = handle_request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.json')
    parser.add_argument('command', choices=['serve', 'create-admin', 'enable-totp', 'check', 'create-dns-client', 'revoke-dns-client'], nargs='?', default='serve')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    app = App(args.config)
    if args.command == 'create-dns-client':
        token=app.create_dns_client(input('Client name (e.g. mmsm): ').strip(),input('Delegated DNS zone: ').strip().lower())
        print('Save this token in MMSM; it is shown only once:')
        print(token)
        return
    if args.command == 'revoke-dns-client':
        app.db.execute('DELETE FROM dns_clients WHERE id=?',(input('Client name: ').strip(),))
        app.db.commit()
        print('Token revoked. Published DNS records are retained.')
        return
    if args.command == 'create-admin':
        name = valid_id(input('Admin username: ').strip())
        password = getpass.getpass('Password (at least 14 characters): ')
        if len(password) < 14 or password != getpass.getpass('Confirm password: '):
            raise SystemExit('Password too short or confirmation mismatch')
        app.db.execute('INSERT INTO users(name,password) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET password=excluded.password', (name, password_hash(password)))
        app.db.commit()
        print('Admin saved. Restart UNM to revoke existing browser sessions.')
        return
    if args.command == 'enable-totp':
        name = valid_id(input('Existing admin username: ').strip())
        if not app.db.execute('SELECT 1 FROM users WHERE name=?', (name,)).fetchone():
            raise SystemExit('Account not found')
        secret = base64.b32encode(secrets.token_bytes(20)).decode()
        print('Add this secret to your authenticator app:', secret)
        print('Type: TOTP, SHA1, 6 digits, 30 seconds. Keep a private backup of the secret.')
        code = input('Current 6-digit code: ').strip()
        if not any(hmac.compare_digest(totp(secret, time.time() + offset), code) for offset in (-30, 0, 30)):
            raise SystemExit('Code mismatch; no changes made')
        app.db.execute('UPDATE users SET totp=? WHERE name=?', (secret, name))
        app.db.commit()
        print('Two-factor authentication enabled. Restart UNM to revoke existing sessions.')
        return
    if args.command == 'check':
        for entry in app.servers():
            app.validate_server(entry['id'], entry)
        print('Configuration and stored forwarding routes validated; no rules applied.')
        return
    if not app.db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
        raise SystemExit('Create an admin before starting the service')
    app.apply(app.servers())
    server = ThreadingHTTPServer((app.cfg['bind'], app.cfg['port']), Handler)
    server.app = app
    def collect():
        while True:
            try:
                with LOCK:
                    status=app.wg_status()
                    if status.get('available'):
                        app.record_traffic(status)
            except Exception:
                LOG.warning('Traffic sample unavailable')
            time.sleep(60)
    threading.Thread(target=collect,daemon=True).start()
    LOG.info('UNM listening on %s:%s in %s mode', app.cfg['bind'], app.cfg['port'], app.cfg['mode'])
    server.serve_forever()


if __name__ == '__main__':
    main()
