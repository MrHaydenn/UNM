# UNM 0.2.0

Public release for Ubuntu 24.04 LTS.

- Generic examples and defaults: no preconfigured personal IP addresses or domains.
- Public HTTPS setup accepts the administrator's chosen panel domain.
- GitHub README includes installation, first login, WireGuard setup, live mode and optional HTTPS/DNS guidance.
- Dashboard opens first, with daily traffic charts, tunnel usage and bandwidth rates.
- WireGuard host registration and provisioning, TCP/UDP forwarding ranges, named firewall rules, Caddy websites/SSL and delegated BIND DNS.
- Named DNS integration keys and GitHub updates from Settings.
- Includes updater permission recovery and the scoped provisioning permission fix.

Existing installations retain their configuration, domains, accounts and data. The public-panel setup command now requires a domain argument. It is not necessary to rerun that command on an already configured VPS.

See README.md and DEPLOY.md for installation. There are no default login credentials. Create an administrator during setup. Release archives contain Git-tracked source only; runtime data, credentials and Git history are excluded. Earlier Git history is unchanged.

Updates from the Settings page continue to track main, including pushes newer than this stable release.
