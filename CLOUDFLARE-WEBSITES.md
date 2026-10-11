# Automatic website DNS through Cloudflare

UNM can create the A records needed for website proxy hosts while Cloudflare continues hosting DNS. This does not change nameservers or your existing delegated DNS setup.

## One-time VPS setup

1. In Cloudflare, create an API token using the Edit zone DNS template. Restrict Zone / DNS / Edit permission to the one domain you want UNM to manage. Copy that domain's Zone ID from its overview page. Do not use a Global API key.
2. Edit `/etc/unm/config.json` on the VPS:

```bash
sudo nano /etc/unm/config.json
```

Set these fields, retaining all other settings:

```json
"cloudflare_zone_id": "YOUR_32_CHARACTER_ZONE_ID",
"cloudflare_zone_name": "example.com",
"public_ip": "203.0.113.10"
```

Replace all three values with your real zone ID, root domain and public VPS IPv4 address. The root domain is the Cloudflare zone, not the panel hostname. Only one Cloudflare zone is configured per UNM installation for this feature.

3. Create or edit the service's environment file. Preserve any existing entries:

```bash
sudo touch /etc/unm/secrets.env
sudo chown root:root /etc/unm/secrets.env
sudo chmod 600 /etc/unm/secrets.env
sudo nano /etc/unm/secrets.env
```

Add or replace the existing token line without duplicating it:

```text
CLOUDFLARE_API_TOKEN=YOUR_SCOPED_API_TOKEN
```

4. Restart UNM to load the token and configuration:

```bash
sudo systemctl restart unm
```

## Add a website

Under Websites / SSL, add the desired domain, destination host and application port. **Automatically publish website DNS through Cloudflare** is checked by default once the above configuration is present. Save the website in live mode.

UNM creates a DNS-only A record for every domain, pointing to the configured public VPS IPv4. Caddy handles HTTP/HTTPS on ports 80/443 and forwards to the destination port. DNS does not contain the backend application port. Allow public 80/443 in your firewalls and give DNS/certificate issuance time to complete.

Existing matching A records are reused without changing their proxy setting. Conflicting A/AAAA/CNAME/NS records are never overwritten. Domains outside the configured zone or below an NS delegation are rejected for publishing. A delegated subdomain must be managed on its authoritative DNS server instead.

DNS publishing has its own visible status per website. A DNS error leaves the website saved. Resolve the token, connectivity or record conflict, then click **Apply saved websites** to retry. Partial creates are safe to retry; matching records are reused. In preview, no Cloudflare changes are made.

Disabling, deleting or renaming a website retains previously created DNS records. Remove obsolete records through Cloudflare deliberately. UNM does not automatically delete records that may still be used elsewhere. The API token is stored only in the root-owned environment file and is never returned to the browser.

Existing websites do not opt in automatically. Edit each website and select the checkbox if you want DNS publishing enabled. Existing settings and delegated Minecraft DNS continue to work.
