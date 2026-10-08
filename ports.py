"""Validated port ranges and protocol expansion shared by network controls."""
def port_range(value):
    if type(value) is int:
        start = end = value
    elif isinstance(value, str):
        parts = value.strip().split('-')
        if len(parts) not in (1, 2) or any(not p.isdecimal() for p in parts):
            raise ValueError('Use a port or range such as 8080 or 8080-8085')
        start, end = int(parts[0]), int(parts[-1])
    else:
        raise ValueError('A port or port range is required')
    if not 1 <= start <= end <= 65535 or end - start >= 200:
        raise ValueError('Port ranges must contain 1–200 ports between 1 and 65535')
    return start, end


def protocols(value):
    if value not in ('tcp', 'udp', 'both'):
        raise ValueError('Protocol must be tcp, udp or both')
    return ('tcp', 'udp') if value == 'both' else (value,)


def sockets(entry, field='publicPort'):
    start, end = port_range(entry[field])
    return {(p, protocol) for p in range(start, end + 1) for protocol in protocols(entry.get('protocol', 'tcp'))}


def label(body):
    value = body.get('name') or body['id']
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80:
        raise ValueError('Display name must contain 1–80 characters')
    return value.strip()
