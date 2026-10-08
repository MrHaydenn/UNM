# UNM — Ubuntu Network Manager

A small web panel and launcher API for Minecraft Java servers behind an Ubuntu VPS and existing WireGuard tunnels. Python 3.10+; no third-party Python dependencies.

## Included in this first version

- Admin accounts created through the VPS command line; optional authenticator-based two-factor login.
- Secure browser sessions, CSRF protection, bounded login attempts and an audit history.
- Register WireGuard IPv4 destinations and assign each Minecraft server a separate public TCP port.
- Enable/disable listeners and their firewalld port rules within a reserved range.
- Expiring, revocable launcher tokens restricted by server ID, PC and public port range.
- Explicit Cloudflare A-record synchronization using DNS-only records; refusal to adopt existing records.
- Preview mode, systemd installation, GitHub updates, configuration backups and failed-update rollback.

**Scope:** Existing WireGuard tunnels and NGINX Proxy Manager remain in place. UNM does not yet import NPM routes, create WireGuard peers, manage arbitrary firewall rules, manage DigitalOcean Cloud Firewalls, or host authoritative DNS. Use `hostname:port` for Minecraft connections; SRV automation is not included. Disabling a route prevents new connections; established game sessions may continue until they disconnect. Proxying means the Minecraft server sees the VPS's tunnel IP rather than each player's original IP. There is no PROXY protocol support in this release.

## VPS deployment

Follow [DEPLOY.md](DEPLOY.md), starting with the read-only inventory. Do not turn on live mode until you have checked the WireGuard subnet, active firewall zone and reserved port range.

Install path: `/opt/unm`. Private settings: `/etc/unm`. Database: `/var/lib/unm`. Firewall helper state: `/var/lib/unm-firewall`. Do not put secrets in GitHub.

## Updates

Once changes are pushed to this repository, run:

```bash
sudo bash /opt/unm/deploy/update.sh
```

This follows `origin/main` and preserves settings. Updates briefly disconnect active forwarded sessions because the service restarts. Backups are in `/var/backups/unm`. Updates require explicit execution; there is no automatic remote code deployment or unattended update timer. Only give repository write access to people you trust to run software on this VPS.

## Local preview

```bash
cp config.example.json config.json
python3 unm.py create-admin
python3 unm.py serve
```

Open `http://localhost:8787`. Preview mode persists your entries but applies no forwarding, firewall or DNS changes.

## Launcher API

See [API.md](API.md). The Cloudflare token stays on the VPS. Authenticate the launcher with its own restricted token.

## Verification

```bash
python3 -m unittest discover -s tests -v
bash -n deploy/install.sh deploy/update.sh
node --check web/app.js
```

The tests exercise HTTP authentication, CSRF rejection, TOTP, token scope and revocation, idempotency, port conflicts, failed-apply rollback, DNS ownership, and real TCP forwarding. Live firewalld, Cloudflare credentials and your actual WireGuard routes still require validation on the VPS. This is an initial implementation, not a production security audit.

## Implementation notes

UNM runs unprivileged on the host. Its web listener binds to `127.0.0.1:8787`; publish it through your existing HTTPS reverse proxy. A Python asyncio TCP proxy listens on enabled IPv4 game ports and connects directly to the registered WireGuard address. Only the narrowly scoped firewall helper runs as root through a fixed sudo command. No Docker socket is mounted and no arbitrary commands are accepted by the API.

DNS synchronization is a separate explicit operation. A route can be active even if DNS synchronization fails. Retrying a Cloudflare request after an ambiguous timeout may encounter a record that was created successfully; inspect it in Cloudflare before retrying. UNM deliberately refuses to overwrite records it does not own. API response success for saving a route means the listener and firewall operation completed, not that the remote Minecraft server is running.

Documentation used: [Cockpit/firewalld](https://cockpit-project.org/guide/latest/feature-firewall.html), [firewall-cmd](https://firewalld.org/documentation/man-pages/firewall-cmd.html), [Docker firewall behavior](https://docs.docker.com/engine/network/packet-filtering-firewalls/), [Cloudflare DNS API](https://developers.cloudflare.com/api/resources/dns/subresources/records/).
