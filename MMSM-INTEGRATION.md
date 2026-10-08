# MMSM and UNM delegated DNS

UNM hosts the delegated DNS zone; MMSM publishes one A and one Java SRV record per server. This integration does not allocate ports, create forwarding rules or start game servers. Use the external TCP port already forwarded in UNM to the MMSM host port. Normal stop/sleep preserves the address. Archiving preserves DNS; clear the public address before archiving if it should be removed. Existing manually managed DNS records are never taken over.

## Prepare UNM on the VPS

Update UNM with `sudo bash /opt/unm/deploy/update.sh`. Keep existing website and forwarding settings. The DNS backend was staged previously; confirm `/etc/unm/services.json` has `public_ip` set to the VPS IPv4, `dns_zones` containing `minecraft.mrhaydenn.us`, and `nameservers` containing `ns1.mrhaydenn.us`.

Allow DNS while firewalld is running:

```bash
sudo firewall-cmd --zone=public --add-service=dns
sudo firewall-cmd --permanent --zone=public --add-service=dns
sudo systemctl enable --now unm-dns
```

Allow incoming TCP and UDP 53 in any attached DigitalOcean Cloud Firewall too. Enable only `dns_enabled` in `/etc/unm/services.json`; preserve the other values. In UNM click Apply saved DNS records. Test before changing delegation:

```bash
dig @157.230.239.126 minecraft.mrhaydenn.us SOA +norecurse
dig +tcp @157.230.239.126 minecraft.mrhaydenn.us SOA +norecurse
```

Repeat from outside the VPS. Responses must have the `aa` authoritative flag. Keep systemd-resolved running. This BIND instance binds only the configured public IPv4 and disables recursion.

## Delegate the child zone at Cloudflare

Keep the main domain's registrar nameservers unchanged. Add a DNS-only A record `ns1` → `157.230.239.126`, then an NS record `minecraft` → `ns1.mrhaydenn.us`. Copy any records that must remain under minecraft into UNM before delegation. Review conflicting records or DS records first. One VPS/nameserver has no redundancy; a second independent authoritative server can be added later.

## Create the restricted credential

```bash
sudo -u unm python3 /opt/unm/unm.py --config /etc/unm/config.json create-dns-client
```

Enter client name `mmsm` and zone `minecraft.mrhaydenn.us`. Save the displayed token privately; only its hash is stored by UNM. Do not paste it into chat. This token can only publish/delete its own server A/SRV pairs in that zone, using UNM's configured public IP. It cannot access the panel, websites, WireGuard or firewall. Integration records appear in UNM's DNS list; edit/clear them through MMSM.

Revoke later with:

```bash
sudo -u unm python3 /opt/unm/unm.py --config /etc/unm/config.json revoke-dns-client
```

Revocation retains published records. Recreating the same client name rotates credentials and preserves ownership. A second MMSM installation must use a different client name.

## Connect MMSM

Install the verified Experimental update (no new stable release). Run this on the computer that runs the MMSM backend, keeping the terminal open for this initial test:

```powershell
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:8790:127.0.0.1:8787 root@157.230.239.126
```

The initial connection uses a localhost SSH tunnel. Reconnect it after reboot; it is not a persistent service. A production HTTPS endpoint with a trusted certificate is also supported. HTTP to a remote hostname/IP is rejected to protect the token, and redirects are not followed.

MMSM Settings → Minecraft domains:

- Provider: UNM delegated DNS
- UNM URL: `http://127.0.0.1:8790` (on the MMSM backend computer)
- UNM integration token: the one-time token
- DNS zone and base domain: both `minecraft.mrhaydenn.us`
- Public entry-point IP: `157.230.239.126`
- Enable automatic DNS publishing; save Settings

Tokens are never returned by MMSM's settings API; a blank token field preserves the saved value. The MMSM host stores its credential, so protect its data directory. Before switching providers/endpoints/zones, clear previous owned addresses through the old connection. Previously published Cloudflare records must be removed through the Cloudflare provider before switching.

Set a server's Public address label to `test`, with the forwarded external port, e.g. 25565. Saving (or creating a server with a label) publishes immediately. Failures are displayed and retried every five minutes while automation is enabled. Disabling automation leaves records in place. Renaming replaces the pair; clearing the label deletes only that server's pair. Repeated publication with unchanged records does not reload BIND. Different names using the same IP/port still reach the same server.

Verify:

```bash
dig @157.230.239.126 test.minecraft.mrhaydenn.us A +norecurse
dig @157.230.239.126 _minecraft._tcp.test.minecraft.mrhaydenn.us SRV +norecurse
dig test.minecraft.mrhaydenn.us A
```

Connect Minecraft Java using `test.minecraft.mrhaydenn.us`. DNS caches may retain the old address/port until TTL expires (300 seconds); a running server and a working forwarding rule are still required.
