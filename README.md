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
- Persistent traffic totals for today, the last seven days and the last 30 days, with daily UTC totals and average receive/send rates per peer and overall.
- Optional DNS-only A records through your existing Cloudflare account.
- Website proxy hosts through tunnel addresses, automatic Let's Encrypt SSL/renewal with Caddy, and stored certificate expiry.
- Authoritative BIND9 DNS zones with A/AAAA/CNAME/TXT/SRV records and Cloudflare subdomain delegation instructions.
- Rule identifiers are generated internally; forwarding/firewall forms only require friendly names. Website domains and DNS records have their own pages.
- Preview mode and a backed-up GitHub update workflow.

## Setup

Follow [DEPLOY.md](DEPLOY.md). Begin with the read-only VPS inventory. New peer provisioning is disabled until the root-owned WireGuard configuration is set to match your actual interface, subnet and endpoint.

See [MONITORING.md](MONITORING.md) for monitoring existing tunnels in preview and enabling the master firewalld switch.

See [WEBSITE-DNS.md](WEBSITE-DNS.md) for the optional website/SSL and authoritative DNS backends. Updating leaves both disabled, and does not stop NPM or change Cloudflare records. This first version does not include custom/wildcard certificates or every advanced NPM feature.

For a Windows PC, follow [WINDOWS.md](WINDOWS.md) or expand **Windows setup · start here** on the WireGuard hosts page. The panel includes the official download link and a copy-settings flow for **Add Empty Tunnel**.

For each new host, UNM prepares the VPS peer and returns a standard WireGuard configuration containing the host tunnel address, host private key, VPS public key, endpoint, tunnel routes and keepalive. Import it in WireGuard on Windows, or install it with wg-quick on Linux. Only the tunnel subnet is routed through the VPS. Your normal internet route remains unchanged.

You can supply a public key generated on the host instead. The returned configuration then contains a private-key placeholder to replace on that host; its existing private key never needs to leave the host.

## Updates

After changes are pushed here, run:

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

Public ports remain restricted to the configured pool of at most 200 ports. A forwarding range such as 20000-20005 must map to an equal-sized destination range such as 8080-8085. TCP and UDP may use the same port independently. Arbitrary system firewall editing and automatic DigitalOcean Cloud Firewall management are not implemented. Existing NGINX Proxy Manager website routes remain in place. UNM uses existing WireGuard interfaces; it does not create a new VPS interface or change its private key.

Traffic is sampled every 60 seconds and retained for 35 days. Collection begins at the first successful sample and persists across UNM restarts. It cannot reconstruct earlier daily history or traffic lost before a counter reset. Collection gaps are assigned to the day of the next sample. Overall means all WireGuard peers, including unregistered peers, not total VPS internet traffic. A recent handshake indicates tunnel activity, not application reachability. Idle tunnels may show red until they send traffic; PersistentKeepalive=25 helps maintain visibility.

UDP sessions expire after 60 idle seconds and are bounded by max_connections per public port. Disabling a UDP rule closes its sessions. Firewalld stop/start changes the running service only, not its boot enablement. With the master switch off, forwarded listeners remain active and the VPS loses firewalld protection. Other firewalls, Docker rules and cloud firewall rules still apply.

Disabling a forwarding rule stops new connections; existing sessions can continue until disconnect. Destination services see the VPS tunnel address rather than the original client address. Host firewalls must allow their destination service from the VPS.

New peers are saved as individually marked blocks in the existing WireGuard file. Unmanaged peers are preserved. SaveConfig=true is rejected because it can rewrite the file and remove ownership markers. Peer configuration backups are stored root-only under /var/lib/unm-wireguard; these include the VPS private key and must stay private.

External token access is disabled. The previous token page and integration guide are removed. Existing hosts and forwarding entries migrate without deletion; existing DNS records remain managed.

## Validation

```bash
python3 -m unittest discover -s tests -v
bash -n deploy/install.sh deploy/update.sh
node --check web/app.js
```

Tests cover login/CSRF/TOTP, forwarding conflicts and rollback, real TCP forwarding, firewall rule ownership, peer allocation and key handling, preservation of unmanaged peers, persistent peer changes, and WireGuard rollback. Linux helper tests run on Ubuntu in GitHub Actions. Your live WireGuard routes, firewall rules and DNS credentials still need validation on the VPS.

Implementation uses an unprivileged host service with narrow root-owned helpers for firewalld and WireGuard. It does not mount the Docker socket. No host private keys appear in activity logs or later configuration retrieval.

References: [WireGuard quick start](https://www.wireguard.com/quickstart/), [Ubuntu wg-quick documentation](https://manpages.ubuntu.com/manpages/noble/man8/wg-quick.8.html), [firewalld commands](https://firewalld.org/documentation/man-pages/firewall-cmd.html), [Docker firewall behavior](https://docs.docker.com/engine/network/packet-filtering-firewalls/).
