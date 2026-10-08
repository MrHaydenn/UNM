import base64
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def public(n):
    return base64.b64encode(bytes([n]) * 32).decode()


@unittest.skipIf(os.name == 'nt', 'Linux helper uses fcntl')
class WireGuardHelperTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'deploy' / 'unm-wireguard'
        loader = importlib.machinery.SourceFileLoader('wireguard_helper', str(source))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.helper = importlib.util.module_from_spec(spec)
        loader.exec_module(self.helper)
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.helper.BASE = base
        self.helper.WG_DIR = base
        self.path = base / 'wg0.conf'
        self.original = '[Interface]\nPrivateKey = DO_NOT_EXPOSE\nAddress = 10.8.0.1/24\nSaveConfig = false\n\n[Peer]\nPublicKey = ' + public(1) + '\nAllowedIPs = 10.8.0.2/32\n'
        self.path.write_text(self.original)
        self.cfg = dict(enabled=True, interface='wg0', subnet='10.8.0.0/24', server_address='10.8.0.1/24', endpoint='vps.example.com:51820')
        self.runtime = {public(1): '10.8.0.2/32'}
        self.commands = []
        self.fail_next_set = False

    def tearDown(self):
        self.tmp.cleanup()

    def fake_command(self, args):
        self.commands.append(args)
        if args[0] == '/usr/sbin/ip':
            if 'address' in args:
                return json.dumps([{'addr_info': [{'local': '10.8.0.1', 'prefixlen': 24}]}])
            return json.dumps([{'dev': 'wg0'}])
        if args[1] == 'show':
            if args[-1] == 'public-key':
                return public(9)
            if args[-1] == 'listen-port':
                return '51820'
            if args[-1] == 'allowed-ips':
                return '\n'.join(k + '\t' + v for k, v in self.runtime.items())
            if args[-1] == 'transfer':
                return '\n'.join(k + '\t100\t200' for k in self.runtime)
            if args[-1] == 'latest-handshakes':
                return '\n'.join(k + '\t1234' for k in self.runtime)
        if args[1] == 'set':
            if self.fail_next_set:
                self.fail_next_set = False
                raise ValueError('UNM: simulated wg set failure')
            if args[-1] == 'remove':
                self.runtime.pop(args[4], None)
            else:
                self.runtime[args[4]] = args[-1]
            return ''
        raise AssertionError(args)

    def execute(self, body):
        with patch.object(self.helper, 'command', side_effect=self.fake_command):
            return self.helper.execute(self.cfg, body)

    def test_add_remove_preserves_unmanaged_peers_and_secrets(self):
        result = self.execute({'action': 'status'})
        self.assertNotIn('DO_NOT_EXPOSE', json.dumps(result))
        self.execute(dict(action='add', id='new-host', address='10.8.0.3', publicKey=public(2)))
        self.assertIn(self.original.rstrip(), self.path.read_text())
        self.assertEqual(self.runtime[public(1)], '10.8.0.2/32')
        self.assertEqual(self.runtime[public(2)], '10.8.0.3/32')
        self.assertIn('# BEGIN UNM HOST new-host', self.path.read_text())
        self.execute(dict(action='remove', id='new-host'))
        self.assertEqual(self.runtime, {public(1): '10.8.0.2/32'})
        self.assertNotIn('# BEGIN UNM HOST', self.path.read_text())
        self.execute(dict(action='remove', id='unmanaged-host'))
        self.assertEqual(self.runtime, {public(1): '10.8.0.2/32'})

    def test_address_collision_key_collision_and_bounds(self):
        for address, pub in [('10.8.0.2', public(2)), ('10.8.0.3', public(1)), ('127.0.0.1', public(2)), ('10.8.0.1', public(2))]:
            with self.assertRaises(ValueError):
                self.execute(dict(action='add', id='new-host', address=address, publicKey=pub))
        self.assertEqual(self.path.read_text(), self.original)
        self.assertFalse(any(c[1] == 'set' for c in self.commands if c[0] == '/usr/bin/wg'))

    def test_runtime_failure_restores_persistent_file(self):
        self.fail_next_set = True
        with self.assertRaises(ValueError):
            self.execute(dict(action='add', id='new-host', address='10.8.0.3', publicKey=public(2)))
        self.assertEqual(self.path.read_text(), self.original)
        self.assertEqual(self.runtime, {public(1): '10.8.0.2/32'})
        self.assertTrue(list(Path(self.tmp.name).glob('wg0-*.conf')))

    def test_disabled_and_saveconfig_true_are_rejected(self):
        self.cfg['enabled'] = False
        with self.assertRaises(ValueError):
            self.execute({'action': 'status'})
        self.cfg['enabled'] = True
        self.path.write_text(self.original.replace('SaveConfig = false', 'SaveConfig = true'))
        with self.assertRaises(ValueError):
            self.execute({'action': 'status'})
        self.assertEqual(self.commands, [])


if __name__ == '__main__':
    unittest.main()
