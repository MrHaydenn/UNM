#!/usr/bin/env bash
# Explicitly enable public HTTPS. Keeps the application HTTP listener on loopback.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo bash /opt/unm/deploy/setup-public-panel.sh'; exit 1; }
[[ -f /etc/caddy/unm/Caddyfile && -f /etc/unm/services.json ]] || { echo 'Set up Caddy services first.'; exit 1; }
systemctl is-active --quiet unm-caddy || { echo 'Start unm-caddy first.'; exit 1; }
backup="/var/backups/unm/public-panel-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 700 "$backup"
cp -a /etc/unm/config.json "$backup/config.json"
cp -a /etc/unm/services.json "$backup/services.json"
cp -a /etc/caddy/unm/Caddyfile "$backup/Caddyfile"
rollback() {
  systemctl stop unm-caddy || true
  cp -a "$backup/config.json" /etc/unm/config.json
  cp -a "$backup/services.json" /etc/unm/services.json
  cp -a "$backup/Caddyfile" /etc/caddy/unm/Caddyfile
  systemctl restart unm || true
  systemctl start unm-caddy || true
  echo "Setup failed; restored previous configuration. Backup: $backup"
}
trap rollback ERR
systemctl stop unm
python3 - <<'PY'
import importlib.machinery
import importlib.util
import json
import sqlite3
import subprocess
from pathlib import Path
loader=importlib.machinery.SourceFileLoader('unm_services','/usr/local/sbin/unm-services')
spec=importlib.util.spec_from_loader(loader.name,loader)
helper=importlib.util.module_from_spec(spec);loader.exec_module(helper)
config_path=Path('/etc/unm/config.json')
config=json.loads(config_path.read_text())
services=json.loads(helper.CONFIG.read_text())
services['public_panel']={'domain':'unm.mrhaydenn.us','port':8787,'backend_port':8786}
services['web_enabled']=True
services['staging']=False
with sqlite3.connect(str(Path(config['data_dir'])/'unm.sqlite')) as db:
    hosts={**dict(db.execute('SELECT id,address FROM hosts')), '@vps':'127.0.0.1'}
    items=[json.loads(row[0]) for row in db.execute('SELECT body FROM proxy_hosts')]
items=[dict(item,address=hosts[item['hostId']]) for item in items]
text=helper.web_text(services,items)
candidate=helper.WEB.with_name('public-panel.candidate')
try:
    helper.write(candidate,text)
    subprocess.run(['caddy','validate','--config',str(candidate),'--adapter','caddyfile'],check=True)
finally:
    candidate.unlink(missing_ok=True)
config.update(bind='127.0.0.1',port=8786,origin='https://unm.mrhaydenn.us:8787',secure_cookie=True,mode='live')
config_path.write_text(json.dumps(config,indent=2)+'\n')
helper.CONFIG.write_text(json.dumps(services,indent=2)+'\n')
helper.write(helper.WEB,text)
PY
sudo -u unm python3 /opt/unm/unm.py --config /etc/unm/config.json check
systemctl restart unm
systemctl reload unm-caddy
if firewall-cmd --state >/dev/null 2>&1; then
  zone=$(python3 -c "import json;print(json.load(open('/etc/unm/firewall.json')).get('firewall_zone','public'))")
  firewall-cmd --zone="$zone" --add-port=8787/tcp
  firewall-cmd --permanent --zone="$zone" --add-port=8787/tcp
fi
systemctl enable unm unm-caddy
curl --fail --silent --noproxy '*' http://127.0.0.1:8786/healthz
trap - ERR
echo
echo "Public panel: https://unm.mrhaydenn.us:8787"
echo "Allow TCP 8787 in the DigitalOcean firewall if attached. Ports 80/443 must remain reachable for automatic certificates."
echo "Backup: $backup"
