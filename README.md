# UNM — Ubuntu Network Manager

A focused web panel for an Ubuntu VPS: WireGuard hosts, TCP port forwarding, firewall allowances and optional DNS records. Python 3.10+ with no third-party Python dependencies.

## Features

- Admin login, optional authenticator-based two-factor authentication, secure sessions and an audit history.
- Register existing WireGuard hosts without changing their tunnels.
- Create new WireGuard peers: check address/key conflicts, allocate a free IPv4 address, generate keys or accept a host public key, and persist the peer on the VPS without restarting the interface.
- Show/download the host's WireGuard configuration. Generated host private keys are shown once and are not saved in the database.
- Forward a public VPS TCP port to any service on a registered tunnel host.
- Automatically manage forwarding firewall ports, plus independent TCP port allowances within a reserved range.
- Optional DNS-only A records through your existing Cloudflare account.
- Preview mode and a backed-up GitHub update workflow.

## Setup

Follow [DEPLOY.md](DEPLOY.md). Begin with the read-only VPS inventory. New peer provisioning is disabled until the root-owned WireGuard configuration is set to match your actual interface, subnet and endpoint.

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

This version supports TCP forwarding and TCP firewall allowances within a reserved range. UDP forwarding, arbitrary system firewall editing and automatic DigitalOcean Cloud Firewall management are not implemented. Existing NGINX Proxy Manager website routes remain in place. UNM uses existing WireGuard interfaces; it does not create a new VPS interface or change its private key.

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
