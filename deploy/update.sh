#!/usr/bin/env bash
set -Eeuo pipefail
# The update service uses a private umask; Git source must remain readable by unm.
umask 022
[[ $EUID -eq 0 ]] || { echo 'Run with sudo bash /opt/unm/deploy/update.sh'; exit 1; }
cd /opt/unm
[[ -z $(git status --porcelain) ]] || { echo 'Checkout has local changes; resolve them before updating.'; exit 1; }
make_code_readable() {
  python3 - <<'PY'
import os
from pathlib import Path
import subprocess
root = Path.cwd()
root.chmod(root.stat().st_mode | 0o555)
for raw in subprocess.check_output(['git', 'ls-files', '-z']).split(b'\0'):
    if not raw:
        continue
    path = root / os.fsdecode(raw)
    if path.is_symlink() or not path.is_file():
        continue
    path.chmod(path.stat().st_mode | 0o444)
    for parent in path.parents:
        if parent == root:
            break
        parent.chmod(parent.stat().st_mode | 0o555)
PY
}
make_code_readable
old=$(git rev-parse HEAD)
git fetch origin main
next=$(git rev-parse origin/main)
[[ $old != "$next" ]] || { echo 'Already up to date.'; exit 0; }
git merge-base --is-ancestor "$old" "$next" || { echo 'Update is not a fast-forward; stop and review.'; exit 1; }
echo "Updating $old -> $next"
trap 'systemctl start unm || true' ERR
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
if [[ -f /usr/local/sbin/unm-services ]]; then
  cp -a /usr/local/sbin/unm-services "$backup/services-helper"
  cp -a /usr/local/lib/unm/service_schema.py "$backup/services-schema"
fi
rollback() {
  echo 'Update failed. Restoring the previous commit and configuration.'
  git checkout --detach "$old"
  make_code_readable
  cp -a "$backup/data/." /var/lib/unm/
  cp -a "$backup/config/." /etc/unm/
  cp -a "$backup/helper" /usr/local/sbin/unm-firewall
  if [[ -f "$backup/wireguard-helper" ]]; then
    cp -a "$backup/wireguard-helper" /usr/local/sbin/unm-wireguard
  fi
  cp -a "$backup/service" /etc/systemd/system/unm.service
  cp -a "$backup/sudoers" /etc/sudoers.d/unm
  if [[ -f "$backup/services-helper" ]]; then
    cp -a "$backup/services-helper" /usr/local/sbin/unm-services
    cp -a "$backup/services-schema" /usr/local/lib/unm/service_schema.py
  fi
  systemctl daemon-reload
  systemctl start unm || true
  echo "Backup: $backup. Inspect journalctl -u unm."
  exit 1
}
trap rollback ERR
git merge --ff-only origin/main
make_code_readable
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
