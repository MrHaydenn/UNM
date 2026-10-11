import os
from pathlib import Path
import subprocess
import sys
import unittest


class PublicPanelSetupTests(unittest.TestCase):
    def test_requires_domain_without_accepting_urls_or_shell_input(self):
        script = (Path(__file__).resolve().parents[1] / 'deploy/setup-public-panel.sh').read_text()
        validation = script.split("python3 - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        for domain, valid in [('panel.example.net', True), ('unm.example.org', True),
                              ('https://panel.example.net', False), ('example.net:8787', False),
                              ('', False), ('$(id).example.net', False), ('-bad.example.net', False)]:
            with self.subTest(domain=domain):
                result = subprocess.run([sys.executable, '-c', validation],
                                        env=dict(os.environ, UNM_PANEL_DOMAIN=domain),
                                        capture_output=True)
                self.assertEqual(result.returncode == 0, valid)
