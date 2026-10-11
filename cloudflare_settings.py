"""Private application settings for optional Cloudflare DNS publishing."""
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
from service_schema import domain


class CloudflareSettings:
    def cloudflare_config(self):
        path = Path(self.cfg['data_dir']) / 'cloudflare.json' if self.cfg.get('data_dir') else None
        if path and path.exists():
            if path.is_symlink():
                raise ValueError('Cloudflare settings must not be a symlink')
            return json.loads(path.read_text(encoding='utf-8'))
        return dict(enabled=True, zoneId=self.cfg.get('cloudflare_zone_id',''),
                    zoneName=self.cfg.get('cloudflare_zone_name',''),
                    publicIP=self.cfg.get('public_ip',''), token=os.environ.get('CLOUDFLARE_API_TOKEN',''))

    def cloudflare_website_status(self):
        c = self.cloudflare_config()
        return dict(enabled=c['enabled'], configured=bool(c['enabled'] and c['zoneId'] and
                    c['zoneName'] and c['publicIP'] and c['token']), tokenSaved=bool(c['token']),
                    zone=c['zoneName'], zoneId=c['zoneId'], publicIP=c['publicIP'])

    def save_cloudflare_settings(self, body, actor):
        if type(body.get('enabled')) is not bool:
            raise ValueError('Enabled must be true or false')
        old = self.cloudflare_config()
        c = dict(enabled=body['enabled'], zoneId=str(body.get('zoneId','')).strip().lower(),
                 zoneName=str(body.get('zoneName','')).strip().lower(),
                 publicIP=str(body.get('publicIP','')).strip(),
                 token=body.get('token') or old['token'])
        if c['enabled'] or c['zoneId'] or c['zoneName'] or c['publicIP']:
            if not re.fullmatch('[a-f0-9]{32}', c['zoneId']):
                raise ValueError('Enter the 32-character Cloudflare Zone ID')
            c['zoneName'] = domain(c['zoneName'])
            if '.' not in c['zoneName']:
                raise ValueError('Enter the root domain, for example example.com')
            try:
                c['publicIP'] = str(ipaddress.IPv4Address(c['publicIP']))
            except ValueError:
                raise ValueError('Enter the VPS public IPv4 address') from None
        if c['enabled'] and (not isinstance(c['token'],str) or
                            not re.fullmatch('[A-Za-z0-9_-]{20,256}', c['token'])):
            raise ValueError('Enter a valid Cloudflare API token')
        path = Path(self.cfg['data_dir']) / 'cloudflare.json'
        if path.is_symlink():
            raise ValueError('Cloudflare settings must not be a symlink')
        temporary = path.with_name('.cloudflare-'+secrets.token_hex(8))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(json.dumps(c))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        self.audit(actor, 'cloudflare.settings', 'website-dns')
        self.db.commit()
        return self.cloudflare_website_status()

    def test_cloudflare_settings(self):
        if not self.cloudflare_website_status()['configured']:
            raise ValueError('Enable and save Cloudflare settings first')
        try:
            self.cf('GET', '?per_page=1')
        except OSError:
            raise ValueError('Cannot access Cloudflare DNS; check the token, zone permission and network connection') from None
        return dict(ok=True, message='Cloudflare DNS access verified. Publishing still checks each domain for conflicts.')
