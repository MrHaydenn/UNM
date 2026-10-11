import json
import os
import sqlite3
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs
from services import Services


class WebsiteCloudflareTests(unittest.TestCase):
    def setUp(self):
        self.app = Services()
        self.app.cfg = dict(mode='live', cloudflare_zone_id='a'*32,
                            cloudflare_zone_name='example.com', public_ip='203.0.113.10')
        self.app.db = sqlite3.connect(':memory:')
        self.app.init_services()
        self.item = dict(id='website', domains=['site.example.com'], cloudflareDNS=True, enabled=True)
        self.app.db.execute('INSERT INTO proxy_hosts VALUES(?,?)', ('website',json.dumps(self.item)))
        self.app.db.commit()
        self.records = []
        self.posts = []
        def api(method, path, body=None):
            if method == 'GET':
                query = parse_qs(path[1:])
                return [r for r in self.records if r['name'] == query['name'][0] and
                        ('type' not in query or r['type'] == query['type'][0])]
            self.posts.append(body)
            self.records.append(dict(body, id='record'))
            return dict(body, id='record')
        self.app.cf = Mock(side_effect=api)
        self.environment = patch.dict(os.environ, CLOUDFLARE_API_TOKEN='test-only-token')
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.app.db.close()

    def test_create_and_repeat_without_duplicate_or_backend_ip(self):
        for _ in range(2):
            result = self.app.publish_website_dns(self.item)
            self.assertTrue(result['cloudflareStatus'].startswith('Synced'))
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.posts[0]['content'], '203.0.113.10')
        self.assertFalse(self.posts[0]['proxied'])

    def test_existing_matching_records_are_not_modified(self):
        self.records.append(dict(type='A',name='site.example.com',content='203.0.113.10',proxied=True))
        self.assertTrue(self.app.publish_website_dns(self.item)['cloudflareStatus'].startswith('Synced'))
        self.assertEqual(self.posts, [])

    def test_conflict_does_not_overwrite_or_create_other_domains(self):
        self.records.append(dict(type='AAAA',name='site.example.com',content='2001:db8::1'))
        result=self.app.publish_website_dns(dict(self.item, domains=['new.example.com','site.example.com']))
        self.assertIn('Conflicting',result['cloudflareStatus'])
        self.assertEqual(self.posts, [])

    def test_delegation_and_outside_zone_are_rejected(self):
        self.records.append(dict(type='NS',name='minecraft.example.com',content='ns1.example.com'))
        self.assertIn('delegated',self.app.publish_website_dns(dict(self.item,domains=['web.minecraft.example.com']))['cloudflareStatus'])
        self.assertIn('outside',self.app.publish_website_dns(dict(self.item,domains=['example.com.attacker.net']))['cloudflareStatus'])
        self.assertEqual(self.posts, [])

    def test_preview_disabled_and_opt_out_never_call_cloudflare(self):
        self.app.publish_website_dns(dict(self.item,cloudflareDNS=False))
        self.app.publish_website_dns(dict(self.item,enabled=False))
        self.app.cfg['mode']='preview'
        self.app.publish_website_dns(self.item)
        self.app.cf.assert_not_called()

    def test_api_failure_is_saved_and_can_be_retried(self):
        api=self.app.cf.side_effect
        self.app.cf.side_effect=OSError('unavailable')
        result=self.app.publish_website_dns(self.item)
        self.assertIn('DNS publishing failed',result['cloudflareStatus'])
        self.assertIn('DNS publishing failed',self.app.db.execute('SELECT body FROM proxy_hosts').fetchone()[0])
        self.app.cf.side_effect=api
        self.assertTrue(self.app.publish_website_dns(result)['cloudflareStatus'].startswith('Synced'))
