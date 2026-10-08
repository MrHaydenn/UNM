# Minecraft launcher API

Base URL: `https://panel.yourdomain.com`. Use `Authorization: Bearer TOKEN` with a token created in the panel. Tokens can access only specified server IDs, registered host IDs and public ports. Tokens expire and can be revoked immediately. Never distribute a shared token in a public launcher binary. Store private per-user/per-installation credentials in the OS credential store.

## Save or update a server route

`PUT /api/v1/minecraft/servers/{serverId}` is idempotent. Required fields are `hostId`, `targetPort`, `publicPort`, and `enabled`. `hostname` is optional and must be below the configured DNS suffix. Ports are JSON integers; enabled is a JSON boolean.

```bash
read -rs -p 'Launcher API token: ' UNM_TOKEN; echo
curl --fail-with-body 'https://panel.yourdomain.com/api/v1/minecraft/servers/survival' \
  -X PUT \
  -H "Authorization: Bearer $UNM_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"hostId":"gaming-pc","targetPort":25565,"publicPort":25570,"hostname":"survival.games.yourdomain.com","enabled":true}'
unset UNM_TOKEN
```

The example token is entered privately, but the expanded header can still be visible to processes owned by the same OS user while curl runs. Application clients should set the header directly.

Response includes:

```json
{
  "id": "survival",
  "hostId": "gaming-pc",
  "targetPort": 25565,
  "publicPort": 25570,
  "hostname": "survival.games.yourdomain.com",
  "enabled": true,
  "dnsRecordId": null,
  "dnsStatus": "Not synced"
}
```

Saving a route does not automatically change DNS. This separates DNS failures from networking updates. In preview mode the route is saved without changing the system. Call `/healthz` to read the current mode.

## Other operations

| Method | Path | Action |
|---|---|---|
| GET | `/api/v1/minecraft/servers/{id}` | Read the route |
| PUT | `/api/v1/minecraft/servers/{id}` | Create/update; set `enabled:false` to disable |
| DELETE | `/api/v1/minecraft/servers/{id}` | Disable and delete; remove managed DNS first |
| POST | `/api/v1/minecraft/servers/{id}/dns` | Create/update a DNS-only A record pointing at the VPS |
| DELETE | `/api/v1/minecraft/servers/{id}/dns` | Remove the DNS record owned by this route |
| GET | `/healthz` | Read service health and preview/live mode |

DNS is available only in live mode with Cloudflare configured. DNS actions do not imply reachability of the game server. Changing a managed hostname requires removing its DNS record first. DNS remains when a route is disabled so temporary shutdowns do not churn records; explicitly remove it when retiring a server.

Failures return JSON `{"error":"..."}`: 400 for invalid/conflicting configuration, 403 for authentication/scope/CSRF rejection, 404 for a missing route, 429 for excessive browser login attempts, and 503 for an external/internal operation failure. Do not interpret a timeout as success. GET the route after an ambiguous network response and retry idempotent PUT as needed.

The administrative endpoints under `/api/hosts`, `/api/tokens`, and `/api/state` require a browser admin session. Launcher tokens cannot create hosts, mint tokens, or change other servers. There is no CORS allowance for websites to use the API directly; call it from your launcher/backend.
