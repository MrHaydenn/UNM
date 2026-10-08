import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
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
        self.app.db.execute('INSERT INTO hosts VALUES(?,?)', ('pc', '10.8.0.2'))
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
        return dict(hostId='pc', targetPort=25565, publicPort=25570, enabled=True, hostname='survival.games.example.com', **kwargs)

    def test_auth_csrf_and_session_logout(self):
        self.assertEqual(self.req('/api/state')[0], 403)
        self.assertEqual(self.req('/api/login', 'POST', {'username': 'admin', 'password': 'wrong'})[0], 401)
        self.login()
        self.assertEqual(self.req('/api/hosts', 'POST', {'id': 'other', 'address': '10.8.0.3'}, csrf=False)[0], 403)
        self.assertEqual(self.req('/api/hosts', 'POST', {'id': 'other', 'address': '10.8.0.3'}, origin=False)[0], 403)
        self.assertEqual(self.req('/api/hosts', 'POST', {'id': 'other', 'address': '127.0.0.1'})[0], 400)
        self.assertEqual(self.req('/api/logout', 'POST', {})[0], 200)
        self.assertEqual(self.req('/api/state')[0], 403)

    def test_scoped_api_idempotency_conflicts_expiry_revocation(self):
        self.login()
        code, token = self.req('/api/tokens', 'POST', dict(id='launcher', hosts=['pc'], servers=['survival'], portMin=25570, portMax=25571, days=1))
        self.assertEqual(code, 201)
        key = token['token']
        route = '/api/v1/minecraft/servers/survival'
        for _ in range(2):
            self.assertEqual(self.req(route, 'PUT', self.body(), bearer=key)[0], 200)
        self.assertEqual(len(self.app.servers()), 1)
        self.assertEqual(self.req('/api/v1/minecraft/servers/other', 'PUT', self.body(), bearer=key)[0], 403)
        outside = self.body(); outside['publicPort'] = 25572
        self.assertEqual(self.req(route, 'PUT', outside, bearer=key)[0], 403)
        self.assertEqual(self.req('/api/hosts', 'POST', {'id': 'hack', 'address': '10.8.0.4'}, bearer=key)[0], 403)
        self.assertEqual(self.req('/api/v1/minecraft/servers/conflict', 'PUT', self.body())[0], 400)
        self.assertEqual(self.req(route + '/dns', 'POST', {}, bearer=key)[0], 400)
        self.assertEqual(self.req('/api/tokens/launcher', 'DELETE')[0], 200)
        self.assertEqual(self.req(route, bearer=key)[0], 403)

    def test_totp_known_vector_and_replay(self):
        secret = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
        self.assertEqual(unm.totp(secret, 59), '287082')
        self.app.db.execute('UPDATE users SET totp=?', (secret,))
        self.app.db.commit()
        payload = {'username': 'admin', 'password': 'strong-test-password', 'code': unm.totp(secret)}
        self.assertEqual(self.req('/api/login', 'POST', payload)[0], 200)
        self.assertEqual(self.req('/api/login', 'POST', payload)[0], 401)

    def test_network_failure_does_not_save(self):
        self.app.save_server('survival', self.body(), 'admin')
        new = self.body(); new['targetPort'] = 25566
        with patch.object(self.app, 'apply', side_effect=[OSError('bind failure'), None]) as apply:
            with self.assertRaises(ValueError):
                self.app.save_server('survival', new, 'admin')
        self.assertEqual(apply.call_count, 2)
        self.assertEqual(self.app.servers()[0]['targetPort'], 25565)

    def test_dns_ownership_and_dns_only(self):
        self.app.save_server('survival', self.body(), 'admin')
        self.app.cfg['mode'] = 'live'
        self.app.cfg['public_ip'] = '203.0.113.5'
        with patch.object(self.app, 'cf', return_value=[{'id': 'foreign'}]):
            with self.assertRaises(ValueError):
                self.app.dns('survival', False, 'admin', None)
        with patch.object(self.app, 'cf', side_effect=[[], {'id': 'owned'}]) as cf:
            item = self.app.dns('survival', False, 'admin', None)
            self.assertFalse(cf.call_args.args[2]['proxied'])
            self.assertEqual(item['dnsRecordId'], 'owned')
        renamed = self.body(); renamed['hostname'] = 'new.games.example.com'
        with self.assertRaises(ValueError):
            self.app.validate_server('survival', renamed)
        with patch.object(self.app, 'cf', return_value={}):
            self.assertIsNone(self.app.dns('survival', True, 'admin', None)['dnsRecordId'])


class ProxyTests(unittest.TestCase):
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
            payload = b'minecraft-data' * 10000
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
