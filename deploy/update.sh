#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo bash /opt/unm/deploy/update.sh'; exit 1; }
cd /opt/unm
[[ -z $(git status --porcelain) ]] || { echo 'Checkout has local changes; resolve them before updating.'; exit 1; }
old=$(git rev-parse HEAD)
git fetch origin main
next=$(git rev-parse origin/main)
[[ $old != "$next" ]] || { echo 'Already up to date.'; exit 0; }
git merge-base --is-ancestor "$old" "$next" || { echo 'Update is not a fast-forward; stop and review.'; exit 1; }
echo "Updating $old -> $next"
systemctl stop unm
install -d -m 700 /var/backups/unm
backup="/var/backups/unm/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 700 "$backup"
cp -a /var/lib/unm "$backup/data"
cp -a /etc/unm "$backup/config"
cp -a /usr/local/sbin/unm-firewall "$backup/helper"
if [[ -f /usr/local/sbin/unm-wireguard ]]; then
  cp -a /usr/local/sbin/unm-wireguard "$backup/wireguard-helper"
fi
cp -a /etc/systemd/system/unm.service "$backup/service"
cp -a /etc/sudoers.d/unm "$backup/sudoers"
rollback() {
  echo 'Update failed. Restoring the previous commit and configuration.'
  git checkout --detach "$old"
  cp -a "$backup/data/." /var/lib/unm/
  cp -a "$backup/config/." /etc/unm/
  cp -a "$backup/helper" /usr/local/sbin/unm-firewall
  if [[ -f "$backup/wireguard-helper" ]]; then
    cp -a "$backup/wireguard-helper" /usr/local/sbin/unm-wireguard
  fi
  cp -a "$backup/service" /etc/systemd/system/unm.service
  cp -a "$backup/sudoers" /etc/sudoers.d/unm
  systemctl daemon-reload
  systemctl start unm || true
  echo "Backup: $backup. Inspect journalctl -u unm."
  exit 1
}
trap rollback ERR
git merge --ff-only origin/main
python3 -m unittest discover -s tests -v
sudo -u unm python3 /opt/unm/unm.py --config /etc/unm/config.json check
bash deploy/install.sh
systemctl start unm
sleep 3
systemctl is-active --quiet unm
health_url=$(python3 - <<'PY'
import json
from pathlib import Path
c=json.loads(Path('/etc/unm/config.json').read_text())
host='127.0.0.1' if c['bind']=='0.0.0.0' else c['bind']
print('http://'+host+':'+str(c['port'])+'/healthz')
PY
)
curl --fail --silent --noproxy '*' "$health_url"
echo
echo "Updated. Backup: $backup"
