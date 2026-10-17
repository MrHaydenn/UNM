import importlib.machinery
import importlib.util
import json
from pathlib import Path
import unittest

loader = importlib.machinery.SourceFileLoader('recovery', str(Path(__file__).resolve().parents[1] / 'deploy' / 'unm-cert-recovery'))
spec = importlib.util.spec_from_loader(loader.name, loader)
recovery = importlib.util.module_from_spec(spec)
loader.exec_module(recovery)


def event(ts, **values):
    return {'MESSAGE': json.dumps(dict(ts=ts, **values))}


class RecoveryTests(unittest.TestCase):
    def failure(self, ts=100):
        return event(ts, logger='tls', msg='job failed', error='site.example.com: obtaining certificate: downloading certificate chain: HTTP 404 Certificate not found')

    def test_terminal_download_only_after_delay_and_once(self):
        logs = [self.failure(), {'MESSAGE': 'not JSON'}]
        self.assertEqual(recovery.failed_download(logs, 0, 219), 0)
        self.assertEqual(recovery.failed_download(logs, 0, 220), 100)
        self.assertEqual(recovery.failed_download(logs, 100, 500), 0)
        dns = event(100, logger='tls', msg='job failed', error='DNS problem: NXDOMAIN')
        retry = event(100, logger='tls.obtain', msg='will retry', error='downloading certificate chain: HTTP 404 Certificate not found')
        self.assertEqual(recovery.failed_download([dns, retry], 0, 500), 0)

    def test_success_cancels_failure_only_for_same_domain(self):
        success = event(110, msg='certificate obtained successfully', identifier='site.example.com')
        self.assertEqual(recovery.failed_download([self.failure(), success], 0, 500), 0)
        other = event(110, msg='certificate obtained successfully', identifier='other.example.com')
        self.assertEqual(recovery.failed_download([self.failure(), other], 0, 500), 100)

    def test_bounded_retries(self):
        self.assertTrue(recovery.retry_allowed([], 1000))
        self.assertFalse(recovery.retry_allowed([100], 999))
        self.assertTrue(recovery.retry_allowed([100], 1000))
        self.assertFalse(recovery.retry_allowed([100, 1000, 1900], 10000))
