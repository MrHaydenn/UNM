# Connect a Windows PC

Install WireGuard from the [official installation page](https://www.wireguard.com/install/).

UNM must be running on the VPS in live mode with WireGuard provisioning configured. The local preview does not configure the VPS or create a working connection. Check the readiness message on the WireGuard hosts page first.

## Use Add Empty Tunnel

1. Open WireGuard, choose **Add Tunnel → Add Empty Tunnel**, and give it a name such as **UNM-PC**.
2. Keep the generated **[Interface]** and **PrivateKey** lines in that editor. Copy only the **Public key** displayed above the editor.
3. In UNM, choose **WireGuard hosts → Add host → Create a new WireGuard peer**.
4. Enter a host name, leave the tunnel address blank for allocation, and paste the public key into **Host public key**.
5. Click **Add host**. UNM checks address/key conflicts and configures the peer on the VPS.
6. Click **Copy settings for empty tunnel**. Paste them on a new line after the PrivateKey line in WireGuard. Do not add another [Interface] header.
7. Click **Save**, select the tunnel and click **Activate**.
8. Refresh the UNM host page and check for a recent handshake.

The completed editor looks like this. These are placeholders, not working connection details:

```ini
[Interface]
PrivateKey = YOUR_EXISTING_WINDOWS_PRIVATE_KEY
Address = ADDRESS_ALLOCATED_BY_UNM/32

[Peer]
PublicKey = VPS_PUBLIC_KEY_FROM_UNM
Endpoint = VPS_PUBLIC_ADDRESS:WIREGUARD_UDP_PORT
AllowedIPs = YOUR_TUNNEL_SUBNET
PersistentKeepalive = 25
```

The PC private key stays on your PC. UNM provides the allocated address, VPS public key, public endpoint, allowed routes and keepalive. Do not paste your private key into the public-key field.

## Import a complete generated configuration instead

Leave **Host public key** blank when creating the new peer. UNM generates a key pair and returns a complete configuration. Download it immediately; UNM does not retain the private key.

In WireGuard use **Add Tunnel → Import tunnel(s) from file**, select the downloaded .conf file, and activate it. Alternatively, copy the complete configuration into an empty tunnel, replacing all of its existing editor text. For this method use the generated key, not the empty tunnel's original key.

If you supplied an existing public key, **Download template .conf** contains a private-key placeholder. Insert your private key locally before importing that template. The copy-settings flow above avoids this extra step.

## Check the connection

A recent handshake shows that the tunnel is exchanging authenticated traffic. If none appears, check the public endpoint, existing WireGuard UDP firewall rules on the VPS and DigitalOcean, and that the VPS peer matches the Windows public key. Test connectivity before configuring forwarding.

Allow the destination application/port through Windows Firewall from the VPS tunnel address. Being connected to WireGuard does not automatically open the application's Windows firewall rule. UNM's TCP forwarding rule uses the destination port where that application actually listens.

Do not share a private key, a configuration containing one, or screenshots of the editor with the key visible. If a private key was exposed, discard that newly created tunnel and generate a fresh one before registering its public key. For an already registered peer, remove/recreate that managed peer and update its host configuration.
