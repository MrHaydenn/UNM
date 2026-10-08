# Monitoring and firewall service control

Update using `sudo bash /opt/unm/deploy/update.sh`. Keep preview mode for the first checks; updating never enables firewalld or peer provisioning.

## Existing WireGuard monitoring

Set the root-owned `/etc/unm/wireguard.json` to match the existing VPS interface. Monitoring works with `enabled: false`; that flag controls peer changes only. For the existing PacketMover9000 setup:

```json
{
  "enabled": false,
  "interface": "wg0",
  "subnet": "10.7.0.0/24",
  "server_address": "10.7.0.1/24",
  "endpoint": "157.230.239.126:51820"
}
```

Keep `/etc/unm/config.json` wireguard_subnet set to the same subnet. Keep the root file mode 600. Restart UNM after changing these settings. The WireGuard hosts page should then show recent handshakes for registered hosts, and the Traffic page will collect totals every minute. The first sample establishes a baseline; send traffic through a tunnel and wait for the next sample to see usage. Daily totals use UTC. There is no earlier history to import from cumulative WireGuard counters.

## Master firewalld switch

The switch controls the whole running firewalld service. It requires live mode and `"allow_service_control": true` added to `/etc/unm/firewall.json`, preserving port_min, port_max and firewall_zone. Missing/false keeps service control disabled. This setting is intentionally not enabled by the installer or updater.

Before enabling it, preserve SSH, WireGuard UDP 51820 and every existing service's required access in firewalld. Keep an SSH session and the DigitalOcean recovery console available. Starting firewalld applies its existing permanent configuration and can interrupt services. Stopping it removes firewalld protection for all services. Individual rule switches only control UNM allowances; other system rules can still permit the same traffic. The master switch does not change service boot enablement or DigitalOcean Cloud Firewall settings.

Do not enable live mode just to test the monitor. Review the existing firewall and NGINX ports before taking over forwarding. The app never imports NGINX or arbitrary firewall rules automatically.
