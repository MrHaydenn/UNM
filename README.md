# UNM — Ubuntu Network Manager

A focused web panel for an Ubuntu VPS: WireGuard hosts, TCP/UDP port forwarding, firewall allowances, traffic history and optional DNS records. Python 3.10+ with no third-party Python dependencies.

## Features

- Admin login, optional authenticator-based two-factor authentication, secure sessions and an audit history.
- Register existing WireGuard hosts without changing their tunnels.
- Create new WireGuard peers: check address/key conflicts, allocate a free IPv4 address, generate keys or accept a host public key, and persist the peer on the VPS without restarting the interface.
- Show/download the host's WireGuard configuration. Generated host private keys are shown once and are not saved in the database.
- Named forwarding and firewall rules with single ports or ranges, TCP, UDP or both, and individual switches.
- A master switch starts/stops all of firewalld when explicitly enabled in the root settings.
- Tunnel status indicators use recent handshakes: green within 180 seconds, red otherwise, gray when unavailable.
- Dashboard with daily traffic charts and per-tunnel usage bars; persistent traffic totals for today, the last seven days and the last 30 days, with daily UTC totals and average receive/send rates per peer and overall.
- Optional DNS-only A records through your existing Cloudflare account.
- Website proxy hosts through tunnel addresses or the VPS itself, automatic Let's Encrypt SSL/renewal with Caddy, and stored certificate expiry.
- Authoritative BIND9 DNS zones with A/AAAA/CNAME/TXT/SRV records and Cloudflare subdomain delegation instructions.
- Rule identifiers are generated internally; forwarding/firewall forms only require friendly names. Website domains and DNS records have their own pages.
- Preview mode and a backed-up GitHub update workflow.

## Install on Ubuntu 24.04 LTS

UNM 0.2.1 runs as a systemd service. Start in preview mode, then enable live operations after configuring your network. No default admin password or personal domain/IP is included. Examples use `example.com`, `203.0.113.10` and `10.8.0.0/24`; replace these with your own values.

### 1. Install and create an account

Keep SSH and your provider's recovery console available. On an existing VPS, inspect its firewall and WireGuard configuration before making changes. UNM uses firewalld; avoid running it alongside another firewall manager. Installing UNM does not enable the firewall or replace existing tunnels.

```bash
sudo apt-get update
sudo apt-get install -y git python3 sudo curl wireguard-tools firewalld
sudo git clone https://github.com/MrHaydenn/UNM.git /opt/unm
sudo bash /opt/unm/deploy/install.sh
sudo -u unm python3 /opt/unm/unm.py --config /etc/unm/config.json create-admin
sudo systemctl enable --now unm
curl --fail http://127.0.0.1:8787/healthz
```

Use a lowercase admin username and a password of at least 14 characters. Password entry is hidden. Optional authenticator setup:

```bash
sudo -u unm python3 /opt/unm/unm.py --config /etc/unm/config.json enable-totp
sudo systemctl restart unm
```

### 2. Open the panel

On your own computer, run the following, replacing the SSH username and VPS address:

```bash
ssh -N -L 8788:127.0.0.1:8787 YOUR_SSH_USER@YOUR_VPS_IP
```

Open **http://localhost:8788**, sign in with the account you created, and keep the SSH terminal open. Dashboard opens first. Preview saves entries without applying network changes.

### 3. Configure WireGuard and live operation

UNM manages peers on an existing `wg-quick` interface; it does not create the VPS interface. For a new VPS, create that interface first using the [WireGuard quick start](https://www.wireguard.com/quickstart/). Match `/etc/unm/config.json` → `wireguard_subnet` and `/etc/unm/wireguard.json` to the actual interface, address and endpoint. See [the detailed setup guide](DEPLOY.md#configure-wireguard-peer-provisioning).

Set the allowed port bounds and firewall zone in both `/etc/unm/config.json` and `/etc/unm/firewall.json`. Before enabling firewalld, allow your actual SSH port and WireGuard UDP port in the correct zone, and preserve access in any provider firewall. [DEPLOY.md](DEPLOY.md) explains inspection and testing; [MONITORING.md](MONITORING.md) explains monitoring and firewall service control.

When ready, set `mode` to `live` in `/etc/unm/config.json` and restart:

```bash
sudo systemctl restart unm
```

Register existing hosts, or use **WireGuard hosts → Enable peer provisioning → Add host**. Ensure `SaveConfig` is false in the WireGuard interface file. [Windows host setup](WINDOWS.md) includes importing the generated configuration. Add a forwarding rule and test it from outside your tunnel.

### 4. Optional public HTTPS, websites and DNS

Follow [WEBSITE-DNS.md](WEBSITE-DNS.md) to install Caddy/BIND, configure your email, public IP, DNS zones and nameservers, and stage the backends. The guide also covers migrating another proxy and configuring firewall ports. Once Caddy is configured and running, create a **DNS-only** A record pointing your chosen panel domain to your VPS, then run with your real domain:

```bash
sudo bash /opt/unm/deploy/setup-public-panel.sh unm.example.com
```

This explicitly enables live mode and publishes **https://YOUR_PANEL_DOMAIN:8787**, with automatic HTTPS and a private backend on port 8786. Allow TCP 8787 in your server/provider firewall and TCP 80/443 for certificate validation. Cloudflare's standard proxy does not support port 8787; use DNS-only for this record. Existing installations keep their configured domains and addresses when updating.

Website destinations can be WireGuard hosts or **This VPS**. DNS hosting is optional; delegate only your chosen subdomain after testing the authoritative server. [MMSM integration](MMSM-INTEGRATION.md) uses named, revocable keys to publish server DNS records.

## Automatic Cloudflare website DNS

Configure a scoped Cloudflare token, Zone ID, root domain and public VPS IP once, then website creation can automatically publish the required A records. See [Cloudflare website DNS setup](CLOUDFLARE-WEBSITES.md). Existing DNS records are protected from replacement.

## Updates

Use **Settings gear → Update from GitHub**, or run the command below. Updates track the latest `main` push, including changes newer than a stable release:

```bash
sudo bash /opt/unm/deploy/update.sh
```

Configuration and data live outside the Git checkout. The updater backs them up, validates the build and restarts the service, with failed-update rollback. Service restarts briefly disconnect forwarded sessions. Updates are explicitly pulled; they are not deployed automatically.

## Preview

```bash
cp config.example.json config.json
python3 unm.py create-admin
python3 unm.py serve
```

Open http://localhost:8787. Preview mode saves entries but does not change forwarding, firewall, DNS or WireGuard peers. Real peer enrollment and usable host keys require the configured Ubuntu VPS.

## Scope

Public forwarding ports use the configured bounds, from 1024 through 65535. Each individual range may contain at most 200 ports. A forwarding range such as 20000-20005 must map to an equal-sized destination range such as 8080-8085. TCP and UDP may use the same port independently. Arbitrary system firewall editing and automatic DigitalOcean Cloud Firewall management are not implemented. UNM does not stop existing proxy services automatically; release their listening ports before migrating to Caddy. UNM uses existing WireGuard interfaces; it does not create a new VPS interface or change its private key.

Traffic is sampled every 60 seconds and retained for 35 days. Collection begins at the first successful sample and persists across UNM restarts. It cannot reconstruct earlier daily history or traffic lost before a counter reset. Collection gaps are assigned to the day of the next sample. Overall means all WireGuard peers, including unregistered peers, not total VPS internet traffic. A recent handshake indicates tunnel activity, not application reachability. Idle tunnels may show red until they send traffic; PersistentKeepalive=25 helps maintain visibility.

UDP sessions expire after 60 idle seconds and are bounded by max_connections per public port. Disabling a UDP rule closes its sessions. Firewalld stop/start changes the running service only, not its boot enablement. With the master switch off, forwarded listeners remain active and the VPS loses firewalld protection. Other firewalls, Docker rules and cloud firewall rules still apply.

Disabling a forwarding rule stops new connections; existing sessions can continue until disconnect. Destination services see the VPS tunnel address rather than the original client address. Host firewalls must allow their destination service from the VPS.

New peers are saved as individually marked blocks in the existing WireGuard file. Unmanaged peers are preserved. SaveConfig=true is rejected because it can rewrite the file and remove ownership markers. Peer configuration backups are stored root-only under /var/lib/unm-wireguard; these include the VPS private key and must stay private.

Named integration keys grant DNS publishing access only within an authorized zone. Existing hosts, forwarding entries and configured domains are preserved on upgrade.

## Validation

```bash
python3 -m unittest discover -s tests -v
bash -n deploy/install.sh deploy/update.sh
node --check web/app.js
```

Tests cover login/CSRF/TOTP, forwarding conflicts and rollback, real TCP forwarding, firewall rule ownership, peer allocation and key handling, preservation of unmanaged peers, persistent peer changes, and WireGuard rollback. Linux helper tests run on Ubuntu in GitHub Actions. Your live WireGuard routes, firewall rules and DNS credentials still need validation on the VPS.

Implementation uses an unprivileged host service with narrow root-owned helpers for firewalld, WireGuard and the optional Caddy/BIND backends. It does not mount the Docker socket. No host private keys appear in activity logs or later configuration retrieval.

References: [WireGuard quick start](https://www.wireguard.com/quickstart/), [Ubuntu wg-quick documentation](https://manpages.ubuntu.com/manpages/noble/man8/wg-quick.8.html), [firewalld commands](https://firewalld.org/documentation/man-pages/firewall-cmd.html), [Docker firewall behavior](https://docs.docker.com/engine/network/packet-filtering-firewalls/).
