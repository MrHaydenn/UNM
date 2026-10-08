# VPS setup and update guide

Keep your current SSH session open throughout setup. Have the DigitalOcean console available. UNM never edits SSH rules, but an existing firewall or routing issue can still interrupt access.

## 1. Inspect the VPS first

Run these read-only commands on the VPS. Share the output if you want step-by-step help. Do not post WireGuard private keys, login passwords or Cloudflare credentials.

```bash
lsb_release -ds
sudo wg show
ip -4 address show
ip -4 route show
sudo firewall-cmd --state
sudo firewall-cmd --get-active-zones
sudo firewall-cmd --list-all-zones
sudo docker ps --format 'table {{.Names}}\t{{.Ports}}'
sudo ss -lntup
```

If `firewall-cmd` is absent or inactive, stop here and review the existing firewall. Do not install a second firewall manager blindly. `wg show` hides private keys, but it exposes peer public keys and endpoints; you can redact them.

Choose an unused range, for example **20000–20099**. It must not overlap NPM Stream rules, Docker published ports, other listeners, or existing firewall port rules. Do not modify an existing rule to make the installer proceed. Select another range. The helper refuses to adopt pre-existing direct port rules, but broader zone/service/rich rules must be checked manually. The active external interface should be in a filtering zone such as `public`, not a blanket-accept zone.

If you use a DigitalOcean Cloud Firewall, separately allow inbound TCP for the chosen forwarded-port range. UNM cannot modify that firewall in this version. Retain SSH and WireGuard access.

## 2. Clone and install in preview mode

For a public GitHub repository:

```bash
sudo apt-get update
sudo apt-get install -y git python3 sudo curl wireguard-tools
sudo git clone https://github.com/MrHaydenn/UNM.git /opt/unm
sudo bash /opt/unm/deploy/install.sh
```

If the repository is private, configure a read-only GitHub deploy key for root first, then clone using `git@github.com:MrHaydenn/UNM.git`. Do not paste a personal access token into the clone URL or shell history. Root must also be able to fetch the repository for updates.

Create the admin account. Passwords are prompted, not included in a command:

```bash
cd /opt/unm
sudo -u unm python3 unm.py --config /etc/unm/config.json create-admin
sudo -u unm python3 unm.py --config /etc/unm/config.json enable-totp
sudo systemctl enable --now unm
sudo systemctl status unm --no-pager
curl http://127.0.0.1:8787/healthz
```

Additional accounts can be created with `create-admin`. All accounts are administrators in this version. There is no public signup. `create-admin` can reset a password without disabling an existing TOTP secret. Restart the service after changing credentials.

From your PC, use an SSH tunnel to preview the panel:

```bash
ssh -L 8787:127.0.0.1:8787 YOUR_SSH_USER@YOUR_VPS_IP
```

Then open `http://localhost:8787`. Keep the terminal open. Use the admin credentials you created. Forwarding and DNS actions are still disabled.

## 3. Configure your network and DNS

```bash
sudo nano /etc/unm/config.json
```

Set:

- `wireguard_subnet`: the subnet containing your PCs' tunnel IPv4 addresses.
- `public_ip`: your VPS's public IPv4 address.
- `dns_suffix`: for example `hosts.yourdomain.com`. UNM will only manage names below this suffix.
- `cloudflare_zone_id`: the Zone ID for your existing Cloudflare domain.
- `port_min` and `port_max`: the exclusive range you selected.
- `firewall_zone`: the zone assigned to the external interface.
- Keep `mode` as `preview` until testing is ready.

The root helper has its own restricted configuration. Match the range and zone here:

```bash
sudo nano /etc/unm/firewall.json
```

Never shrink or change that range while it owns active rules. Disable/delete the managed routes first. Do not manually delete `/var/lib/unm-firewall/ports.json` while rules are active.

In Cloudflare, create a DNS edit token with **Zone / DNS / Edit** permission scoped to your domain. Then save it privately on the VPS:

```bash
sudo install -m 600 /dev/null /etc/unm/secrets.env
sudo nano /etc/unm/secrets.env
```

Put this one line in the file, replacing the placeholder:

```text
CLOUDFLARE_API_TOKEN=YOUR_TOKEN
```

No NS change is required. Keep Cloudflare authoritative for the domain.

## Configure WireGuard peer provisioning

This uses your existing VPS WireGuard interface. Determine its name and IPv4 prefix from the inventory. Do not post its private key. The installer creates the helper settings with provisioning disabled.

```bash
sudo nano /etc/unm/wireguard.json
```

Example only — replace these values with your existing configuration:

```json
{
  "enabled": true,
  "interface": "wg0",
  "subnet": "10.8.0.0/24",
  "server_address": "10.8.0.1/24",
  "endpoint": "YOUR_VPS_IP:51820"
}
```

The panel's `wireguard_subnet` must match this subnet. The helper verifies the live interface address and listen port. The endpoint must be your public IPv4 address or hostname plus the existing WireGuard UDP port. Keep that UDP port allowed in both your existing firewall and any DigitalOcean Cloud Firewall; UNM does not change this gateway rule.

Peer persistence requires a root-owned /etc/wireguard/INTERFACE.conf managed with wg-quick. If your interface is created by a container or another manager, stop and adapt the deployment first. Do not run two tools that independently rewrite the same peer list.

Inspect SaveConfig without exposing the rest of the file:

```bash
sudo grep -i '^[[:space:]]*SaveConfig' /etc/wireguard/wg0.conf
```

If it says true, edit only that setting to false (or remove it). Do not restart the tunnel just to change this option. UNM makes root-only backups before peer edits. Other peer blocks and interface settings are preserved.

After switching UNM to live mode and restarting it, open **WireGuard hosts → Add host → Create a new WireGuard peer**. You can leave the tunnel address blank for automatic allocation. Leave the public-key field blank to generate a key pair, or paste a public key already generated on the host.

Save the downloaded configuration immediately. UNM does not store the generated private key. A later **Host setup** action returns a template with a private-key placeholder.

On Windows, use WireGuard's **Import tunnel(s) from file** and activate the tunnel.

On a Linux host, transfer the downloaded file privately and run:

```bash
sudo apt-get install -y wireguard-tools
sudo install -m 600 home-server.conf /etc/wireguard/unm.conf
sudo wg-quick up unm
sudo systemctl enable wg-quick@unm
sudo wg show unm
```

Use your downloaded filename instead of home-server.conf. Keep the configuration private. The host setup includes its /32 address, the VPS public key, public endpoint, the tunnel subnet as AllowedIPs and PersistentKeepalive=25. It does not route all internet traffic through the VPS. Refresh the host page to see the latest handshake.

Existing hosts can instead be added with **Register an existing tunnel host**. Removing a registered host leaves its peer untouched. Removing a managed host removes its peer from the VPS live interface and persistent file; delete its forwarding rules first.

If creation is interrupted after the file is saved but before the browser receives the configuration, inspect the marked peer block and helper backup via SSH before retrying. Generated private keys cannot be recovered from UNM. Do not delete unmanaged peer blocks.


## 4. Publish through NGINX Proxy Manager

Your NPM container cannot reach the host's loopback address. One practical option is binding the NPM-facing web listener to the host's Docker bridge gateway address. Inspect NPM's network first:

```bash
sudo docker inspect YOUR_NPM_CONTAINER --format '{{json .NetworkSettings.Networks}}'
```

Use the relevant `Gateway` address as `bind` in `/etc/unm/config.json`, and use that same address as NPM's **Forward Hostname / IP**. Set Forward Port to **8787**, scheme **http**, your panel hostname, and request an SSL certificate with **Force SSL** enabled. Keep this host port off the public interface. Do not publish port 8787 with Docker or allow it in DigitalOcean's public firewall.

Also set in `/etc/unm/config.json`:

```json
"origin": "https://panel.yourdomain.com",
"secure_cookie": true
```

Restart and test through HTTPS:

```bash
sudo systemctl restart unm
sudo journalctl -u unm -n 50 --no-pager
```

Only the configured origin is accepted for browser mutations/login. SSH-tunnel login stops working once you switch the origin to the public HTTPS domain. Binding to a Docker bridge address depends on that network existing after reboot; if NPM's network is recreated, update the address. This app does not change NPM's container configuration automatically.

In NPM's Advanced configuration, you can cap request size/time and reject oversized requests:

```nginx
client_max_body_size 16k;
client_body_timeout 15s;
```

Enable TOTP before publishing the admin panel. Keep Cockpit restricted to WireGuard or trusted source addresses separately.

## 5. Test one live route

Register one host in UNM using its existing WireGuard address, or create a new peer as described above. Create one forwarding rule using an unused public port. Verify the destination service is running and its local firewall permits TCP from the VPS through WireGuard.

From the VPS, check that the destination service is reachable through the tunnel (replace the address/port):

```bash
python3 -c "import socket; s=socket.create_connection(('10.8.0.2',8080),5); print('Destination port reachable'); s.close()"
```

Change `mode` to `live`, then:

```bash
sudo -u unm python3 /opt/unm/unm.py --config /etc/unm/config.json check
sudo systemctl restart unm
sudo systemctl status unm --no-pager
sudo journalctl -u unm -n 50 --no-pager
sudo firewall-cmd --zone=public --list-ports
```

Use your configured zone instead of `public` if different. Test from outside the tunnel with `YOUR_VPS_IP:PUBLIC_PORT`, then use **Sync DNS** and connect to `media.hosts.yourdomain.com:PUBLIC_PORT`.

Test disabling the route: new connections should fail, and its direct firewalld port rule should disappear. Existing sessions can remain alive until disconnect. If a broader existing firewall rule permits the port, the panel cannot override that rule, but its listener still closes.

## 6. Pull future changes

```bash
sudo bash /opt/unm/deploy/update.sh
```

The updater backs up the database and configuration, validates the new build, then restarts it. A failed health check restores the previous commit and files. It never resets a dirty checkout. Active forwarded connections disconnect during restart. Configuration lives outside Git and is preserved. No changes appear on the VPS until they have been pushed to GitHub and you run the update command.

If your web listener is no longer on loopback, the updater uses the configured bind address for its health check. Inspect logs on any failure.

## Recovery and removal

```bash
sudo journalctl -u unm -n 100 --no-pager
sudo systemctl stop unm
```

Stopping UNM closes its TCP listeners but retains saved firewall rules. To close all rules owned by UNM without changing other rules:

```bash
printf '[]' | sudo /usr/local/sbin/unm-firewall
```

Do not uninstall firewalld, flush the firewall, or remove existing WireGuard/NPM services as part of troubleshooting. Back up `/etc/unm`, `/var/lib/unm`, `/var/lib/unm-firewall`, `/var/lib/unm-wireguard`, and `/etc/wireguard` privately before moving this installation. Existing update backups contain secrets; retain them root-only and prune them periodically.
