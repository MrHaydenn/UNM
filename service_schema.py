"""Strict structured inputs shared with the root-owned website/DNS helper."""
import ipaddress
import re


def domain(value, service=False):
    if not isinstance(value, str):
        raise ValueError('A domain name is required')
    value = value.lower().rstrip('.')
    labels = value.split('.')
    pattern = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
    if service:
        pattern = r'_?[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?'
    if len(value) > 253 or not labels or any(not re.fullmatch(pattern, p) for p in labels):
        raise ValueError('Use a valid domain name without wildcards')
    return value


def proxy(body, subnet):
    names = body.get('domains')
    if not isinstance(names, list) or not 1 <= len(names) <= 20:
        raise ValueError('Enter 1–20 domain names')
    names = sorted(set(domain(n) for n in names))
    if any('.' not in n or n.endswith(('.localhost','.local','.internal','.home.arpa')) for n in names):
        raise ValueError('Use public domain names for websites')
    address = ipaddress.ip_address(body.get('address', ''))
    if address.version != 4 or address not in ipaddress.ip_network(subnet):
        raise ValueError('Website destination must be in the WireGuard subnet')
    port = body.get('port')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Destination port must be between 1 and 65535')
    if body.get('scheme') not in ('http','https'):
        raise ValueError('Choose HTTP or HTTPS for the destination')
    if type(body.get('ssl')) is not bool or type(body.get('enabled')) is not bool:
        raise ValueError('SSL and enabled must be true or false')
    return dict(domains=names,address=str(address),port=port,scheme=body['scheme'],ssl=body['ssl'],enabled=body['enabled'])


def record(body, zones):
    zone = domain(body.get('zone'))
    if zone not in zones:
        raise ValueError('Zone is not configured for this DNS server')
    raw_name=body.get('name','')
    if not isinstance(raw_name,str):
        raise ValueError('A DNS record name is required')
    name = raw_name.strip().lower().rstrip('.')
    if raw_name.strip().endswith('.') and name!=zone and not name.endswith('.'+zone):
        raise ValueError('An absolute record name must be inside the configured zone')
    if name == '@':
        name = zone
    elif name != zone and not name.endswith('.'+zone):
        name += '.'+zone
    kind = body.get('type')
    if kind not in ('A','AAAA','CNAME','TXT','SRV'):
        raise ValueError('Choose A, AAAA, CNAME, TXT or SRV')
    name = domain(name, service=kind in ('TXT','SRV'))
    if name != zone and not name.endswith('.'+zone):
        raise ValueError('Record must be within the configured zone')
    ttl = body.get('ttl',300)
    if type(ttl) is not int or not 60 <= ttl <= 86400:
        raise ValueError('TTL must be between 60 and 86400 seconds')
    content = body.get('content')
    if not isinstance(content,str) or not content or len(content)>1000 or any(ord(c)<32 or ord(c)>126 for c in content):
        raise ValueError('Enter printable DNS record content')
    if kind in ('A','AAAA'):
        address=ipaddress.ip_address(content)
        if address.version != (4 if kind=='A' else 6):
            raise ValueError('Address does not match record type')
        content=str(address)
    elif kind == 'CNAME':
        if name == zone:
            raise ValueError('A zone root cannot be a CNAME')
        content=domain(content)+'.'
        if content == name+'.':
            raise ValueError('A CNAME cannot point to itself')
    elif kind == 'SRV':
        parts=content.split()
        if len(parts)!=4 or any(not p.isdecimal() or not 0<=int(p)<=65535 for p in parts[:3]):
            raise ValueError('SRV format: priority weight port target.example.com')
        content=' '.join(str(int(p)) for p in parts[:3])+' '+domain(parts[3])+'.'
    elif len(content.encode())>255:
        raise ValueError('TXT content must fit within 255 bytes')
    if type(body.get('enabled')) is not bool:
        raise ValueError('enabled must be true or false')
    return dict(zone=zone,name=name,type=kind,ttl=ttl,content=content,enabled=body['enabled'])


def validate_records(items):
    enabled=[r for r in items if r['enabled']]
    for r in enabled:
        same=[p for p in enabled if (p['zone'],p['name'])==(r['zone'],r['name'])]
        if r['type']=='CNAME' and len(same)>1:
            raise ValueError('A CNAME must be the only record at that name')
        if any(p['type']==r['type'] and p['ttl']!=r['ttl'] for p in same):
            raise ValueError('Records with the same name and type must use the same TTL')
    keys=[(r['zone'],r['name'],r['type'],r['content']) for r in enabled]
    if len(keys)!=len(set(keys)):
        raise ValueError('This DNS record already exists')
