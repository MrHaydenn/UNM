# Websites, automatic SSL and delegated DNS

UNM manages two optional host services: Caddy for websites/SSL, and BIND9 for authoritative DNS. The normal UNM update only installs their restricted helper and disabled settings. It does not install/start the backends, stop NGINX Proxy Manager, issue certificates or change Cloudflare delegation. All current rules and tunnels remain stored.

## 1. Update and prepare in preview

```bash
sudo bash /opt/unm/deploy/update.sh
```

Refresh the panel. Under **Websites / SSL**, copy each NPM Proxy Host into a website: a friendly name, domain(s), WireGuard host, destination scheme/port, automatic SSL and enabled state. Multiple domains can use the same website. Keep UNM in preview. Under **DNS server**, prepare records for the delegated zone. Neither page changes the VPS while in preview.

This is a first website implementation, not full NPM feature parity: HTTP/HTTPS reverse proxying, WebSockets, automatic Let's Encrypt SSL, renewal, HTTP-to-HTTPS redirects and certificate expiry display. Custom certificate uploads, wildcard certificates, access lists, custom locations and arbitrary NGINX snippets are not included. Caddy validates upstream HTTPS certificates; a service with an untrusted certificate needs an HTTP destination or a properly trusted certificate. Migrated sites receive new certificates; UNM does not import NPM's certificate private keys. Renewals are handled by Caddy while it is running.

Website creation does not create Cloudflare DNS records automatically. Keep existing website DNS records pointing to the VPS. The DNS page manages records on the new authoritative server, not the parent Cloudflare zone. Legacy Cloudflare records associated with old forwards are retained and can be removed from the DNS page.

## 2. Root backend settings

Edit `/etc/unm/services.json`, replacing YOUR_EMAIL with your contact email:

```json
{
  "web_enabled": false,
  "dns_enabled": false,
  "staging": true,
  "email": "YOUR_EMAIL",
  "public_ip": "157.230.239.126",
  "dns_zones": ["minecraft.mrhaydenn.us"],
  "nameservers": ["ns1.mrhaydenn.us"]
}
```

Keep this root-owned and mode 600. Configure `/etc/unm/wireguard.json` to match wg0 and 10.7.0.0/24 as described in MONITORING.md. The privileged website helper restricts destinations to that root-configured tunnel subnet. A website's destination must be a registered host in the panel. Root settings authorize exactly which DNS zones can be managed. Do not remove or rename an active zone until its delegation has been moved away and its records migrated.

One nameserver on one VPS is adequate for initial testing but has no redundancy. Use a second independent authoritative server before relying on DNS availability; this version does not configure replication or zone transfers automatically. Do not list a second nameserver unless it really serves the same zone. In-zone nameserver A records are generated automatically; nameservers such as ns1.mrhaydenn.us outside the delegated zone need their A record at Cloudflare.

## 3. Install and stage the optional backends

During the agreed maintenance window, first back up NPM's Docker volumes/compose configuration and take screenshots of Streams, Proxy Hosts and certificates. Keep SSH, wg0 and the DigitalOcean recovery console available. Identify the actual NPM container with `docker ps` and stop that container using its real name; do not remove it or its volumes.

Install Ubuntu packages:

```bash
sudo apt-get update
sudo apt-get install -y caddy bind9 bind9-utils dnsutils
```

Packages may start their standard services automatically. Stop/disable those standard instances before using the dedicated UNM instances; this assumes no existing Caddy/BIND service you need to preserve:

```bash
sudo systemctl disable --now caddy.service named.service
sudo bash /opt/unm/deploy/setup-services.sh
```

The staging script creates dedicated configs and systemd units without starting them. Existing UNM configs are kept. It validates Caddy and BIND files and never edits `/etc/caddy/Caddyfile` or `/etc/bind/named.conf`. Configuration lives in `/etc/caddy/unm` and `/etc/bind/unm`. Caddy certificate storage persists in `/var/lib/caddy/data`. Root-only apply backups live under `/var/lib/unm-services`.

## 4. Start and test without changing delegation

Preserve existing access when preparing firewalld. Outside UNM's forwarding pool, allow SSH, WireGuard UDP 51820, website TCP 80/443 and DNS TCP/UDP 53 in the external zone and DigitalOcean Cloud Firewall. BIND listens only on the root-configured public IPv4 address; it does not replace systemd-resolved or your PC's resolver. UNM never changes your system resolver settings.

Check ports with `sudo ss -lntup`. NPM must release TCP 80/443. No other server may bind DNS port 53 on the VPS public IP. Then:

```bash
sudo systemctl enable --now unm-caddy unm-dns
sudo systemctl status unm-caddy unm-dns --no-pager
sudo journalctl -u unm-caddy -u unm-dns -n 50 --no-pager
```

Set web_enabled/dns_enabled true for the backend(s) you intend to use. These flags authorize live changes; leave the unused backend false. Review firewalld and all saved forwarding rules before changing UNM's mode to live. Live mode will also activate saved forwarding routes; do not use it until their public ports are available.

After restarting UNM in live mode, use **Apply saved websites** and **Apply saved DNS records**. Subsequent saves/toggles/removals apply automatically and retain the saved entry if backend validation/reload fails. A running backend is required; the panel does not start it implicitly.

Test DNS before delegation:

```bash
dig @157.230.239.126 minecraft.mrhaydenn.us SOA +norecurse
dig @157.230.239.126 trigun.minecraft.mrhaydenn.us A +norecurse
dig @157.230.239.126 _minecraft._tcp.trigun.minecraft.mrhaydenn.us SRV +norecurse
dig +tcp @157.230.239.126 trigun.minecraft.mrhaydenn.us A +norecurse
```

Run these from outside the VPS too. Responses should have the authoritative `aa` flag. BIND has recursion/cache queries and zone transfers disabled, plus response rate limiting. An unrelated domain should not receive a recursive answer.

For websites, point DNS A records to the public VPS IP and remove stale AAAA records unless IPv6 also routes to Caddy. Both 80/443 must be accessible for Let's Encrypt validation. Initially staging=true uses test certificates, which browsers will not trust. After testing routing/issuance, set staging=false and click **Apply saved websites** to request publicly trusted production certificates. Do not repeatedly delete certificates or resave many domains during tests; ACME rate limits apply. The panel reports stored certificate expiry, not a live external HTTPS health check. HTTP-only websites can be tested before SSL issuance.

## 5. Cloudflare subdomain delegation

After the DNS server answers correctly, create these records in the existing Cloudflare zone for mrhaydenn.us:

| Type | Name | Content |
|---|---|---|
| A, DNS only | ns1 | 157.230.239.126 |
| NS | minecraft | ns1.mrhaydenn.us |

Do not change mrhaydenn.us's registrar nameservers. Only minecraft.mrhaydenn.us is delegated. Recreate existing records under minecraft on BIND before delegation and resolve conflicts with Cloudflare records at that delegation name. Existing DS records must match a DNSSEC-signed child zone; this initial backend is unsigned, so do not add a DS record. If one already exists, review it before migration.

For Trigun, create in UNM:

| Type | Name | Content |
|---|---|---|
| A | trigun | 157.230.239.126 |
| SRV | _minecraft._tcp.trigun | 0 5 20080 trigun.minecraft.mrhaydenn.us |

Create the matching TCP forwarding rule separately: public 20080 → the tunnel host's Java server port (often 25565). The client uses trigun.minecraft.mrhaydenn.us, and the SRV record selects the forwarded port. Records do not start a game server, allocate a port or change firewall rules. The planned external Minecraft-manager integration is not exposed yet; it will need scoped authentication and ownership controls.

Verify public resolution after cached delegation expires:

```bash
dig +trace trigun.minecraft.mrhaydenn.us
dig _minecraft._tcp.trigun.minecraft.mrhaydenn.us SRV
```

## Recovery

Stop unm-caddy before restarting NPM to release 80/443. NPM volumes and old settings remain intact. Disabling a website does not delete its certificates. To roll back DNS, restore the previous Cloudflare records/delegation; cached NS records can continue sending clients to BIND, so keep it serving the old zone until caches expire. Stopping UNM itself leaves Caddy/BIND running from their last applied configs.

References: [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https), [Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), [Cloudflare delegation](https://developers.cloudflare.com/dns/manage-dns-records/how-to/subdomains-outside-cloudflare/), [BIND authoritative configuration](https://bind9.readthedocs.io/en/v9.18.41/reference.html).


### Named integration keys in the panel

Open **Integration keys** to generate a named, zone-scoped DNS publishing token.
Copy the token into MMSM and save its settings; the token is displayed only once.
Existing command-line clients appear using their original names. Use **Rotate** on
that existing client when replacing a lost token: its DNS record ownership remains
unchanged. **Rename** changes only its display name. **Revoke** immediately rejects
future authentication and leaves published DNS records in place. Creating a different
client does not transfer ownership of an existing client's records.

The integration token is separate from the SSH private key. On the Windows MMSM
host, find the previously generated SSH key without displaying its contents:

```powershell
Get-Item "$env:USERPROFILE\.ssh\unm_mmsm" | Select-Object -ExpandProperty FullName
```

Use the private file without `.pub`, and the VPS account whose authorized_keys
contains its public key (in the documented setup, `root`).


### Public UNM panel with HTTPS on port 8787

Create a Cloudflare **DNS-only** A record `unm` pointing to the VPS IPv4 address.
Keep it DNS-only: the standard Cloudflare proxy does not support HTTPS port 8787.
After updating UNM, explicitly enable the public panel:

```bash
sudo bash /opt/unm/deploy/setup-public-panel.sh
```

This backs up the existing configuration, validates the generated Caddy configuration,
preserves saved websites, enables live mode, and sets the browser origin and secure
cookies for **https://unm.mrhaydenn.us:8787**. Caddy handles automatic production
certificates and listens publicly on TCP 8787; UNM itself moves to loopback port 8786.
The configured panel is retained whenever UNM regenerates website configuration.
Ensure any DigitalOcean cloud firewall allows inbound TCP 8787. Ports 80 and 443
must remain reachable for Let's Encrypt validation. Login credentials stay unchanged.
A previously configured browser SSH tunnel to backend port 8787 must be closed;
use the public HTTPS address instead.

In MMSM, disable automatic SSH, set UNM URL to `https://unm.mrhaydenn.us:8787`,
keep the integration token, and save settings before testing the connection.
The private SSH key field is no longer needed for this connection.


### Settings and services on the VPS

After a one-time `sudo bash /opt/unm/deploy/update.sh`, Settings includes **Update
from GitHub**. It pulls the latest main push, backs up data and configuration, runs
tests and restarts UNM with rollback on failure. Reload and sign in after restart.
The update runs as a separate systemd service; diagnostics are available with
`sudo journalctl -u unm-update --no-pager`.

For websites hosted on the VPS, select **This VPS** under Websites / SSL and enter
the local app port. Caddy connects to 127.0.0.1 and handles automatic certificates.
You only need public 80/443 for this website; the backend port can remain private.
For direct TCP/UDP access to a service listening on the VPS public interface, add a
firewall allowance instead of a WireGuard forwarding rule.

Live mode does not automatically enable peer provisioning. In Settings, enter the
public WireGuard endpoint (IP or hostname plus its actual UDP listen port), then
click **Enable peer provisioning**. UNM checks the existing interface against the
panel subnet and updates only its provisioning settings. Existing peers and their
configuration are preserved. SaveConfig=true must first be changed to false in the
WireGuard interface configuration. Keep its UDP listen port allowed through both
firewalld and any DigitalOcean cloud firewall.
