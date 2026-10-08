#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo bash deploy/install.sh'; exit 1; }
[[ -f /opt/unm/unm.py && -f /opt/unm/deploy/unm.service ]] || { echo 'Clone this repository to /opt/unm first'; exit 1; }
command -v python3 >/dev/null
command -v firewall-cmd >/dev/null || { echo 'firewalld is missing. Stop and inspect the existing firewall before installing it.'; exit 1; }
firewall-cmd --state
id unm >/dev/null 2>&1 || useradd --system --home-dir /var/lib/unm --shell /usr/sbin/nologin unm
install -d -m 750 -o root -g unm /etc/unm
install -d -m 700 -o unm -g unm /var/lib/unm
install -d -m 700 -o root -g root /var/lib/unm-firewall
install -d -m 700 -o root -g root /var/lib/unm-wireguard
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
Path('/etc/unm/firewall.json').write_text(json.dumps({k:c[k] for k in ('port_min','port_max','firewall_zone')},indent=2)+'\n')
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
install -m 755 -o root -g root /opt/unm/deploy/unm-firewall /usr/local/sbin/unm-firewall
install -m 755 -o root -g root /opt/unm/deploy/unm-wireguard /usr/local/sbin/unm-wireguard
printf 'unm ALL=(root) NOPASSWD: /usr/local/sbin/unm-firewall "", /usr/local/sbin/unm-wireguard ""\n' >/etc/sudoers.d/unm
chmod 440 /etc/sudoers.d/unm
visudo -cf /etc/sudoers.d/unm
install -m 644 /opt/unm/deploy/unm.service /etc/systemd/system/unm.service
systemctl daemon-reload
echo 'Installed in preview mode. Edit /etc/unm/config.json, create your admin, then start unm.'
