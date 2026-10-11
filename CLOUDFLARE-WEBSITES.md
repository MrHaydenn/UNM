# Automatic website DNS through Cloudflare

UNM can create the A records needed for website proxy hosts while Cloudflare continues hosting DNS. This does not change nameservers or your existing delegated DNS setup.

## One-time setup in UNM

1. Update UNM from **Settings gear → Update from GitHub**. Reload the panel after the update.
2. Open **Websites / SSL → Cloudflare DNS connection**.
3. In Cloudflare, create an API token using the Edit zone DNS template. Restrict **Zone / DNS / Edit** permission to the one domain you want UNM to manage. Do not use a Global API key. The form links directly to the token page.
4. Enable Cloudflare website DNS and enter:
   - **Root domain:** your Cloudflare zone, for example `example.com`.
   - **Cloudflare Zone ID:** the 32-character ID on that domain’s Cloudflare overview page.
   - **VPS public IPv4 address:** your public server IP, for example `203.0.113.10`.
   - **API token:** the scoped token you created.
5. Click **Save Cloudflare settings**, then **Test saved connection**. The test reads DNS records; it does not create a test record or prove DNS Edit permission. Publishing a website requires DNS Edit permission.

No terminal commands or service restart are needed. Settings apply immediately. Leave the token field blank to keep the saved token, or paste a new one to replace it. Disable the integration using the checkbox when needed; this retains saved credentials and existing DNS records. One Cloudflare zone is supported per UNM installation.

The GUI stores settings in a private `cloudflare.json` file in UNM’s data directory (normally `/var/lib/unm`), mode 600 and owned by the UNM service account. Treat it and update backups as secrets. The token is never returned to the browser. Existing terminal configuration continues to work until GUI settings are saved; afterward, GUI settings take precedence. Disabling in the GUI does not silently fall back to the old environment token.

## Add a website

Under Websites / SSL, add the desired domain, destination host and application port. **Automatically publish website DNS through Cloudflare** is checked by default once the above configuration is present. Save the website in live mode.

UNM creates a DNS-only A record for every domain, pointing to the configured public VPS IPv4. Caddy handles HTTP/HTTPS on ports 80/443 and forwards to the destination port. DNS does not contain the backend application port. Allow public 80/443 in your firewalls and give DNS/certificate issuance time to complete.

Existing matching A records are reused without changing their proxy setting. Conflicting A/AAAA/CNAME/NS records are never overwritten. Domains outside the configured zone or below an NS delegation are rejected for publishing. A delegated subdomain must be managed on its authoritative DNS server instead.

DNS publishing has its own visible status per website. A DNS error leaves the website saved. Resolve the token, connectivity or record conflict, then click **Apply saved websites** to retry. Partial creates are safe to retry; matching records are reused. In preview, no Cloudflare changes are made.

Disabling, deleting or renaming a website retains previously created DNS records. Remove obsolete records through Cloudflare deliberately. UNM does not automatically delete records that may still be used elsewhere. The saved API token is never returned to the browser.

Existing websites do not opt in automatically. Edit each website and select the checkbox if you want DNS publishing enabled. Existing settings and delegated Minecraft DNS continue to work.
