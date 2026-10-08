#!/usr/bin/env bash
# Stage separate UNM backend configurations. Does not start services or change DNS delegation.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo bash /opt/unm/deploy/setup-services.sh'; exit 1; }
[[ -f /etc/unm/services.json && -f /usr/local/sbin/unm-services ]] || { echo 'Update/install UNM first.'; exit 1; }
for program in caddy named named-checkzone named-checkconf; do
  command -v "$program" >/dev/null || { echo 'Install caddy, bind9 and bind9-utils first; see WEBSITE-DNS.md.'; exit 1; }
done
install -d -m 750 -o root -g caddy /etc/caddy/unm
install -d -m 750 -o root -g bind /etc/bind/unm
install -d -m 750 -o caddy -g caddy /var/lib/caddy/data /var/lib/caddy/config
python3 - <<'PY'
import importlib.machinery
import importlib.util
import json
from pathlib import Path
loader=importlib.machinery.SourceFileLoader('unm_services','/usr/local/sbin/unm-services')
spec=importlib.util.spec_from_loader(loader.name,loader)
helper=importlib.util.module_from_spec(spec)
loader.exec_module(helper)
cfg=json.loads(helper.CONFIG.read_text())
zones,names,public,email=helper.settings(cfg)
files={helper.WEB:helper.web_text(cfg,[]),helper.DNS/'named.conf':helper.dns_text(cfg)}
for zone in zones:
    files[helper.DNS/(zone+'.zone')]=helper.zone_text(zone,names,public,[],1)
for path,text in files.items():
    if path.exists():
        if path.is_symlink():
            raise SystemExit('Managed files must not be symlinks')
        print('Keeping existing:',path)
    else:
        helper.write(path,text)
PY
caddy validate --config /etc/caddy/unm/Caddyfile --adapter caddyfile
named-checkconf -z /etc/bind/unm/named.conf
install -m 644 -o root -g root /opt/unm/deploy/unm-caddy.service /etc/systemd/system/unm-caddy.service
install -m 644 -o root -g root /opt/unm/deploy/unm-dns.service /etc/systemd/system/unm-dns.service
systemctl daemon-reload
echo 'Backend files staged. Services have NOT been started or enabled. Follow WEBSITE-DNS.md for migration.'
