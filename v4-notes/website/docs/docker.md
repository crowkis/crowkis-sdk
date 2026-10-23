---
title: Docker deployment
path: /docs/docker
server_version: 0.5.2
---

# Docker deployment

*Server 0.5.2 · `crowkis/crowkis:0.5.2` (also `:0.5` and `:latest`) · linux/amd64 and linux/arm64*

## Pull and run

**Reachable from other machines.** Set the one secret, `CROWKIS_AUTH_TOKEN`:

```bash
docker run -d --name crowkis \
  -p 6383:6383 -p 127.0.0.1:6384:6384 \
  -e CROWKIS_AUTH_TOKEN=<a long random secret> \
  -e CROWKIS_MANAGEMENT_BIND_HOST=0.0.0.0 \
  -v crowkis-data:/data \
  --memory 2g \
  crowkis/crowkis:0.5.2
```

**This machine only (development):**

```bash
docker run -d --name crowkis \
  -p 127.0.0.1:6383:6383 -p 127.0.0.1:6384:6384 \
  -e CROWKIS_PROTECTED_MODE=off -e CROWKIS_MANAGEMENT_BIND_HOST=0.0.0.0 \
  -v crowkis-data:/data \
  crowkis/crowkis:0.5.2
```

| Port | Surface | Reachable from outside the container |
|---|---|---|
| `6383` | Cache (RESP2/RESP3): SDKs, `crowkis cli`, any Redis client | When you publish it (`-p`). |
| `6384` | Dashboard and management REST API, `/health`, `/metrics` | Only with `CROWKIS_MANAGEMENT_BIND_HOST=0.0.0.0` and `-p`. Without that setting it listens inside the container only. Publish it on `127.0.0.1` or behind your proxy. |
| `6385` | gRPC (h2c) | When you publish it. **gRPC always needs the token:** with no `CROWKIS_AUTH_TOKEN` set, every gRPC call is refused. |
| `6386` | Health probes `/livez`, `/readyz` | Used by the image's own health check; publish it for an outside load balancer. |

- **Memory:** at least **1 GB**, **2 GB recommended**. The bundled models use about 530 MB, and the server refuses writes once it reaches 90% of its memory limit.
- **Data:** everything lives in the `/data` volume. Keep it on a persistent volume.
- **Security:** the server runs as user `999`.

## Docker Compose

```yaml
services:
  crowkis:
    image: crowkis/crowkis:0.5.2
    restart: unless-stopped
    ports:
      - "6383:6383"
      - "127.0.0.1:6384:6384"
    environment:
      CROWKIS_AUTH_TOKEN: ${CROWKIS_AUTH_TOKEN:?set it in .env}
      CROWKIS_MANAGEMENT_BIND_HOST: 0.0.0.0
    volumes:
      - crowkis-data:/data
    mem_limit: 2g
    init: true
    ulimits:
      nofile: 65536            # the server allows 10,000 connections
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    stop_grace_period: 30s
volumes:
  crowkis-data:
```

## Health and auth checks

```bash
curl -s http://127.0.0.1:6384/health                  # {"status":"ok","uptime_secs":12,"version":"0.5.2"}
docker inspect --format '{{.State.Health.Status}}' crowkis   # "healthy" once it answers its probe
```

There is **one secret**, `CROWKIS_AUTH_TOKEN`. There are no users and no per-tenant keys.

| What | Needs the token? | How a client sends it |
|---|---|---|
| Cache commands (RESP) | Yes, when set | `AUTH <token>`. The SDKs do it for you from `CROWKIS_AUTH_TOKEN`. |
| gRPC | Yes, always: with no token set, gRPC is refused | `authorization: Bearer <token>` |
| The LLM gateway (`/v1/chat/completions`, when enabled) | Yes, always | `Authorization: Bearer <token>` |
| Management writes (any non-GET) and content exports | Yes | `Authorization: Bearer <token>` (or `x-crowkis-auth-token`) |
| Dashboard and read-only GETs (`/api/metrics`, `/metrics`) | No | — |

```bash
# A management write without the token is refused (401):
curl -s -o /dev/null -w "%{http_code}
" -X POST -H "Content-Type: application/json" -d '{}'   http://127.0.0.1:6384/api/v1/invalidate
# With it, add:  -H "Authorization: Bearer $CROWKIS_AUTH_TOKEN"
```

**Protected mode** is on by default. With no token set, the server refuses every connection that doesn't come from inside the container (`-DENIED`). So either set `CROWKIS_AUTH_TOKEN`, or, on your own machine only, `CROWKIS_PROTECTED_MODE=off`. Use a token of at least 32 characters; the server warns about shorter ones.

`CROWKIS_ADMIN_KEY` and `CROWKIS_ALLOW_UNAUTHENTICATED_ADMIN` are **retired in 0.5.2**. The server ignores them and logs a warning. Use `CROWKIS_AUTH_TOKEN`.

## Mounting a license

The image runs as the Community edition without one. With a license file:

```bash
docker run -d --name crowkis \
  -p 6383:6383 -p 127.0.0.1:6384:6384 \
  -e CROWKIS_AUTH_TOKEN=<a long random secret> -e CROWKIS_MANAGEMENT_BIND_HOST=0.0.0.0 \
  -v crowkis-data:/data \
  -v /path/to/license.json:/etc/crowkis/license.json:ro \
  crowkis/crowkis:0.5.2
```

You can also pass it as `CROWKIS_LICENSE_KEY` (base64 or one-line JSON), which wins over the file.

## Upgrades

```bash
docker pull crowkis/crowkis:0.5.2
docker compose up -d
```

**Upgrading to 0.5.2:** the embedding model changed, so cached entries re-warm once. Answers are re-embedded as they are used.

## Day-2 operations

```bash
docker logs -f crowkis                 # structured JSON, one line per event
docker exec -it crowkis crowkis cli    # REPL into the running server (type AUTH <token> first if one is set)
docker compose down                    # stop, keep data
docker compose down -v                 # stop and remove the data volume
```

Kubernetes probes: `/readyz` on port 6386 for readiness, and `/livez` for liveness. Loading a large index can take a long time after a restart, so give the startup probe room: for example `/livez` every 10 s with `failureThreshold: 360` (an hour). A pod killed while its index loads starts the load again.
