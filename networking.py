"""WireGuard enrollment and explicitly scoped firewall operations."""
import base64
import ipaddress
import json
import re
import subprocess


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', value):
        raise ValueError('Use 1–48 lowercase letters, numbers or hyphens for the name')
    return value


def valid_key(value):
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception:
        raise ValueError('WireGuard public key must be a base64-encoded 32-byte key') from None
    if len(raw) != 32 or raw == bytes(32) or base64.b64encode(raw).decode() != value:
        raise ValueError('Invalid WireGuard public key')
    return value


class Networking:
    def wg_call(self, payload):
        if self.cfg['mode'] != 'live':
            raise ValueError('Peer changes are disabled in preview mode')
        response = subprocess.run(['sudo', '-n', '/usr/local/sbin/unm-wireguard'], input=json.dumps(payload),
                                  text=True, capture_output=True, timeout=30)
        if response.returncode:
            # Helper failures contain only deliberately written public diagnostics.
            message = response.stderr.strip()
            raise ValueError(message if message.startswith('UNM: ') else 'WireGuard operation failed; inspect VPS setup')
        return json.loads(response.stdout)

    def wg_status(self):
        if self.cfg['mode'] == 'preview':
            return dict(available=False, message='Preview: peer provisioning requires a configured VPS.', peers=[])
        try:
            status = self.wg_call({'action': 'status'})
            if ipaddress.ip_interface(status['serverAddress']).network != ipaddress.ip_network(self.cfg['wireguard_subnet']):
                raise ValueError('WireGuard helper and panel subnets do not match')
            return dict(status, available=True)
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            return dict(available=False, message=str(exc), peers=[])

    def allocate_address(self, status):
        subnet = ipaddress.ip_network(self.cfg['wireguard_subnet'])
        if subnet.version != 4 or subnet.num_addresses > 65536:
            raise ValueError('Automatic allocation requires an IPv4 subnet of /16 or smaller')
        occupied = [ipaddress.ip_network(h['address'] + '/32') for h in self.hosts()]
        gateway = str(ipaddress.ip_interface(status['serverAddress']).ip)
        occupied.append(ipaddress.ip_network(gateway + '/32'))
        for peer in status['peers']:
            for cidr in peer['allowedIPs']:
                occupied.append(ipaddress.ip_network(cidr, strict=False))
        for address in subnet.hosts():
            if not any(address in net for net in occupied if net.version == 4):
                return str(address)
        raise ValueError('No unused tunnel addresses remain')

    def host_config(self, host, status, private='<HOST_PRIVATE_KEY>'):
        if not status.get('available'):
            raise ValueError(status.get('message', 'Configure WireGuard provisioning first'))
        return ('[Interface]\nPrivateKey = ' + private + '\nAddress = ' + host['address'] + '/32\n\n'
                '[Peer]\nPublicKey = ' + status['publicKey'] + '\nEndpoint = ' + status['endpoint'] + '\n'
                'AllowedIPs = ' + self.cfg['wireguard_subnet'] + '\nPersistentKeepalive = 25\n')

    def add_host(self, body, actor):
        hid = valid_id(body.get('id'))
        enroll = body.get('enroll', False)
        if type(enroll) is not bool:
            raise ValueError('enroll must be true or false')
        if self.db.execute('SELECT 1 FROM hosts WHERE id=?', (hid,)).fetchone():
            raise ValueError('Host ID already exists; remove the old host before replacing it')
        private, public, status = None, None, None
        if enroll:
            status = self.wg_status()
            if not status['available']:
                raise ValueError(status['message'])
            public = body.get('publicKey', '').strip()
            if public:
                valid_key(public)
            else:
                private = subprocess.run(['/usr/bin/wg', 'genkey'], text=True, capture_output=True, check=True, timeout=5).stdout.strip()
                public = subprocess.run(['/usr/bin/wg', 'pubkey'], input=private + '\n', text=True, capture_output=True, check=True, timeout=5).stdout.strip()
                valid_key(public)
        address = body.get('address', '').strip()
        if enroll and not address:
            address = self.allocate_address(status)
        address = ipaddress.ip_address(address)
        subnet = ipaddress.ip_network(self.cfg['wireguard_subnet'])
        if address.version != 4 or address not in subnet or address in (subnet.network_address, subnet.broadcast_address):
            raise ValueError('Host must use an IPv4 host address inside the WireGuard subnet')
        if str(address) in {h['address'] for h in self.hosts()}:
            raise ValueError('Tunnel address already belongs to a registered host')
        host = dict(id=hid, address=str(address), publicKey=public, managed=enroll)
        config = self.host_config(host, status, private or '<HOST_PRIVATE_KEY>') if enroll else None
        if enroll:
            # Persistence and live peer changes are confined to the privileged helper.
            self.wg_call(dict(action='add', id=hid, address=str(address), publicKey=public))
        try:
            self.db.execute('INSERT INTO hosts(id,address,public_key,managed) VALUES(?,?,?,?)', (hid, str(address), public, int(enroll)))
            self.audit(actor, 'host.enroll' if enroll else 'host.register', hid)
            self.db.commit()
        except Exception:
            self.db.rollback()
            if enroll:
                self.wg_call(dict(action='remove', id=hid))
            raise
        return dict(host=host, configuration=config, privateKeyIncluded=bool(private))

    def remove_host(self, hid, actor):
        if any(f['hostId'] == hid for f in self.servers()):
            raise ValueError('Delete this host’s forwarding routes first')
        host = next((h for h in self.hosts() if h['id'] == hid), None)
        if not host:
            return
        if host['managed']:
            self.wg_call(dict(action='remove', id=hid))
        self.db.execute('DELETE FROM hosts WHERE id=?', (hid,))
        self.audit(actor, 'host.remove', hid)
        self.db.commit()

    def firewall_rules(self):
        return [dict(id=r['id'], port=r['port'], enabled=bool(r['enabled'])) for r in
                self.db.execute('SELECT * FROM firewall_rules ORDER BY port')]

    def save_firewall_rule(self, body, actor):
        rid = valid_id(body.get('id'))
        port, enabled = body.get('port'), body.get('enabled')
        if type(port) is not int or not self.cfg['port_min'] <= port <= self.cfg['port_max']:
            raise ValueError('Choose a TCP port inside the reserved range')
        if type(enabled) is not bool:
            raise ValueError('enabled must be true or false')
        old = self.firewall_rules()
        new = [r for r in old if r['id'] != rid] + [dict(id=rid, port=port, enabled=enabled)]
        if any(r['port'] == port and r['id'] != rid for r in old):
            raise ValueError('A firewall entry already uses this port')
        try:
            self.firewall(self.servers(), new)
            self.db.execute('INSERT OR REPLACE INTO firewall_rules VALUES(?,?,?)', (rid, port, int(enabled)))
            self.audit(actor, 'firewall.save', rid)
            self.db.commit()
        except Exception:
            self.db.rollback()
            self.firewall(self.servers(), old)
            raise ValueError('Firewall apply failed; entry was not saved') from None

    def delete_firewall_rule(self, rid, actor):
        old = self.firewall_rules()
        try:
            self.firewall(self.servers(), [r for r in old if r['id'] != rid])
            self.db.execute('DELETE FROM firewall_rules WHERE id=?', (rid,))
            self.audit(actor, 'firewall.remove', rid)
            self.db.commit()
        except Exception:
            self.db.rollback()
            self.firewall(self.servers(), old)
            raise ValueError('Firewall removal failed') from None
