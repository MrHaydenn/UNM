import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipIf(os.name == 'nt', 'Linux firewalld helper uses fcntl')
class FirewallTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'deploy' / 'unm-firewall'
        loader = importlib.machinery.SourceFileLoader('firewall_helper', str(source))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.helper = importlib.util.module_from_spec(spec)
        loader.exec_module(self.helper)
        self.tmp = tempfile.TemporaryDirectory()
        self.helper.BASE = Path(self.tmp.name)
        self.helper.CONFIG = self.helper.BASE / 'config.json'
        self.helper.CONFIG.write_text(json.dumps(dict(port_min=25565, port_max=25600, firewall_zone='public')))
        self.rules = set()
        self.failed = False

    def tearDown(self):
        self.tmp.cleanup()

    def fake_run(self, zone, action, port, permanent=False):
        key = (port, permanent)
        if action == 'query':
            return subprocess.CompletedProcess([], 0 if key in self.rules else 1)
        if self.failed and action == 'add' and port == 25571 and permanent:
            self.failed = False
            return subprocess.CompletedProcess([], 2)
        if action == 'add':
            self.rules.add(key)
        else:
            self.rules.discard(key)
        return subprocess.CompletedProcess([], 0)

    def apply(self, ports):
        with patch.object(self.helper.os, 'geteuid', return_value=0), patch.object(self.helper, 'run', side_effect=self.fake_run), patch.object(self.helper.sys, 'stdin', io.StringIO(json.dumps(ports))):
            self.helper.main()

    def test_reserved_range_and_unmanaged_rule_rejection(self):
        with self.assertRaises(SystemExit):
            self.apply([22])
        self.rules.add((25570, True))
        with self.assertRaises(SystemExit):
            self.apply([25570])
        self.assertEqual(self.rules, {(25570, True)})

    def test_runtime_permanent_rules_and_rollback(self):
        self.apply([25570])
        before = self.rules.copy()
        self.failed = True
        with self.assertRaises(SystemExit):
            self.apply([25571])
        self.assertEqual(self.rules, before)
        self.assertEqual(json.loads((self.helper.BASE / 'ports.json').read_text()), [25570])
        self.apply([])
        self.assertEqual(self.rules, set())


if __name__ == '__main__':
    unittest.main()
