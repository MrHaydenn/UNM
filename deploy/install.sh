#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo bash deploy/install.sh'; exit 1; }
[[ -f /opt/unm/unm.py && -f /opt/unm/deploy/unm.service ]] || { echo 'Clone this repository to /opt/unm first'; exit 1; }
command -v python3 >/dev/null
command -v firewall-cmd >/dev/null || { echo 'firewalld is missing. Stop and inspect the existing firewall before installing it.'; exit 1; }
if ! firewall-cmd --state; then
  install_mode=$(python3 - <<'PY'
import json
from pathlib import Path
p=Path('/etc/unm/config.json')
print(json.loads(p.read_text())['mode'] if p.exists() else 'preview')
PY
)
  service_control=$(python3 - <<'PY'
import json
from pathlib import Path
p=Path('/etc/unm/firewall.json')
print('yes' if p.exists() and json.loads(p.read_text()).get('allow_service_control') is True else 'no')
PY
)
  [[ "$install_mode" == preview || "$service_control" == yes ]] || { echo 'Live mode requires a running firewalld. Review existing rules before enabling it.'; exit 1; }
  echo 'firewalld is inactive: installing preview only. No firewall will be enabled or changed.'
fi
id unm >/dev/null 2>&1 || useradd --system --home-dir /var/lib/unm --shell /usr/sbin/nologin unm
install -d -m 750 -o root -g unm /etc/unm
install -d -m 700 -o unm -g unm /var/lib/unm
install -d -m 700 -o root -g root /var/lib/unm-firewall
install -d -m 700 -o root -g root /var/lib/unm-wireguard
install -d -m 700 -o root -g root /var/lib/unm-services
install -d -m 755 -o root -g root /usr/local/lib/unm
install -d -m 700 -o root -g root /etc/wireguard
if [[ ! -f /etc/unm/config.json ]]; then
  python3 - <<'PY'
import json
from pathlib import Path
c=json.loads(Path('/opt/unm/config.example.json').read_text())
c['data_dir']='/var/lib/unm'
Path('/etc/unm/config.json').write_text(json.dumps(c,indent=2)+'\n')
PY
fi
chown root:unm /etc/unm/config.json
chmod 640 /etc/unm/config.json
if [[ ! -f /etc/unm/firewall.json ]]; then
  python3 - <<'PY'
import json
from pathlib import Path
c=json.loads(Path('/etc/unm/config.json').read_text())
settings={k:c[k] for k in ('port_min','port_max','firewall_zone')}
settings['allow_service_control']=False
Path('/etc/unm/firewall.json').write_text(json.dumps(settings,indent=2)+'\n')
PY
fi
chmod 600 /etc/unm/firewall.json
if [[ ! -f /etc/unm/wireguard.json ]]; then
  python3 - <<'PY'
import json
from pathlib import Path
c=json.loads(Path('/etc/unm/config.json').read_text())
settings=dict(enabled=False,interface='wg0',subnet=c['wireguard_subnet'],server_address='10.8.0.1/24',endpoint='YOUR_VPS_IP:51820')
Path('/etc/unm/wireguard.json').write_text(json.dumps(settings,indent=2)+'\n')
PY
fi
chmod 600 /etc/unm/wireguard.json
install -m 755 -o root -g root /opt/unm/deploy/unm-update /usr/local/sbin/unm-update
install -m 644 -o root -g root /opt/unm/deploy/unm-update.service /etc/systemd/system/unm-update.service
install -m 755 -o root -g root /opt/unm/deploy/unm-firewall /usr/local/sbin/unm-firewall
install -m 755 -o root -g root /opt/unm/deploy/unm-wireguard /usr/local/sbin/unm-wireguard
install -m 755 -o root -g root /opt/unm/deploy/unm-services /usr/local/sbin/unm-services
install -m 644 -o root -g root /opt/unm/service_schema.py /usr/local/lib/unm/service_schema.py
if [[ ! -f /etc/unm/services.json ]]; then
  python3 - <<'PY'
import json
from pathlib import Path
c=json.loads(Path('/etc/unm/config.json').read_text())
settings=dict(web_enabled=False,dns_enabled=False,staging=True,email='YOUR_EMAIL',public_ip=c.get('public_ip',''),dns_zones=['minecraft.mrhaydenn.us'],nameservers=['ns1.mrhaydenn.us'])
Path('/etc/unm/services.json').write_text(json.dumps(settings,indent=2)+'\n')
PY
fi
chmod 600 /etc/unm/services.json
printf 'unm ALL=(root) NOPASSWD: /usr/local/sbin/unm-firewall "", /usr/local/sbin/unm-wireguard "", /usr/local/sbin/unm-services "", /usr/local/sbin/unm-update ""\n' >/etc/sudoers.d/unm
chmod 440 /etc/sudoers.d/unm
visudo -cf /etc/sudoers.d/unm
install -m 644 /opt/unm/deploy/unm.service /etc/systemd/system/unm.service
systemctl daemon-reload
echo 'Installed in preview mode. Edit /etc/unm/config.json, create your admin, then start unm.'
