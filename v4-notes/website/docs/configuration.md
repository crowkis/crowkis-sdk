---
title: Configuration
path: /docs/configuration
server_version: 0.5.2
sdk_version: 0.5.2
---

# Configuration

*Server 0.5.2 · SDKs 0.5.2*

The server needs no settings to start. In production, set `CROWKIS_AUTH_TOKEN` and keep `/data` on a persistent volume.

For each setting the server uses, in order: a command-line flag, then the environment variable, then the config file (`/etc/crowkis/crowkis.toml` in the image, or `CROWKIS_CONFIG_PATH`), then the default. **The environment always wins over the file.**

## Networking

| Variable | Default | Notes |
|---|---|---|
| `CROWKIS_PORT` | `6383` | The cache (RESP) port. Also `--port`. |
| `CROWKIS_DASHBOARD_PORT` | port + 1 (`6384`) | Dashboard and management API. |
| `CROWKIS_GRPC_PORT` | port + 2 (`6385`) | gRPC (h2c). |
| `CROWKIS_PROBE_PORT` | port + 3 (`6386`) | `/livez`, `/readyz`, `/health`. |
| `CROWKIS_BIND_HOST` | `127.0.0.1` (image: `0.0.0.0`) | Address for the cache, gRPC and probe listeners. |
| `CROWKIS_MANAGEMENT_BIND_HOST` | `127.0.0.1` | Address for the dashboard. Set `0.0.0.0` in Docker to publish it. |
| `CROWKIS_MANAGEMENT_ALLOWED_HOSTS` | empty | Extra host names a browser may use for the dashboard. `localhost` and IP addresses are always allowed. |
| `CROWKIS_MAX_CONNECTIONS` | `10000` | |
| `CROWKIS_IDLE_TIMEOUT_MS` | `900000` (15 min) | Idle client connections are closed after this. |

## Authentication

| Variable | Default | Notes |
|---|---|---|
| `CROWKIS_AUTH_TOKEN` | not set | **The one secret.** It guards cache commands (RESP `AUTH`), every gRPC call, and every management write. Use at least 32 characters. |
| `CROWKIS_PROTECTED_MODE` | on | With no token set, refuses connections from other hosts. `off` is for a machine only you use. |
| `CROWKIS_SECURITY_MODE` | `strict` | `permissive` relaxes the answer-safety checks. |

`CROWKIS_ADMIN_KEY` and `CROWKIS_ALLOW_UNAUTHENTICATED_ADMIN` are **retired in 0.5.2** and ignored, with a warning.

## Storage and memory

| Variable | Default | Notes |
|---|---|---|
| `CROWKIS_DATA_DIR` | `./.crow` (image: `/data`) | Where everything is kept. |
| `CROWKIS_MAXMEMORY_MB` | 90% of the container's (or host's) memory | Writes are refused above it. `0` turns the guard off. |
| `CROWKIS_BLOCK_CACHE_BYTES` | `64m` | Read cache for the storage engine. |
| `CROWKIS_MAX_ENTRIES` | no ceiling | The Community edition caps at 50,000 entries. |
| `CROWKIS_SIMILARITY_THRESHOLD` | `0.88` | How close a question must be to match. |
| `CROWKIS_CONFIDENCE_THRESHOLD` | `0.80` | How sure the server must be to serve a match. |
| `CROWKIS_BACKUP_DIR` | not set | Where snapshots go. |

## Decision engine (optional)

With the decision engine on, the server's own model checks a new answer before anyone is served it, and judges how long it stays correct. The easiest way to turn it on is `crowkis curva setup`. You can also set the variables yourself:

| Variable | Notes |
|---|---|
| `CROWKIS_CURVA_URL` | An OpenAI-compatible (or Anthropic `messages`) endpoint. Setting it turns the engine on. |
| `CROWKIS_CURVA_KEY` | The endpoint's API key. |
| `CROWKIS_CURVA_MODEL` | The model name. |
| `CROWKIS_CURVA_WIRE` | `chat-completions` or `messages`. Worked out from the URL when not set. |
| `CROWKIS_DECIDE_MIN_CONFIDENCE` | Default `0.80`. |
| `CROWKIS_DECIDE_MAX_PER_DAY` | A daily cap on engine calls. |
| `CROWKIS_DECIDE_CONCURRENCY` | Default `8`. |

The older names `CROWKIS_DECIDE_UPSTREAM` / `_MODEL` / `_KEY_ENV` still work. Use either the old names or the new ones, not both.

## Voice add-on

| Variable | Default |
|---|---|
| `CROWKIS_AUDIO_MAX_CLIP_BYTES` | 2 MiB per cached clip |
| `CROWKIS_AUDIO_MAX_TENANT_BYTES` | 512 MiB of audio per tenant |

## Logging and privacy

| Variable | Default | Notes |
|---|---|---|
| `CROWKIS_STRUCTURED_LOGS` | off (image: on) | JSON logs, one line per event. |
| `CROWKIS_LOG_QUERY_PREVIEWS` | off | Never put question text in logs unless you turn this on. |
| `CROWKIS_QUERY_LOG_RETENTION_DAYS` | `30` | How long the dashboard's query log is kept. |

## License

| Variable | Notes |
|---|---|
| `CROWKIS_LICENSE_PATH` | Default `/etc/crowkis/license.json`. |
| `CROWKIS_LICENSE_KEY` | The license as base64 or one-line JSON. It wins over the file. |

The **Community edition** (no license) allows up to **3 tenants** and **50,000 entries**. A write for a fourth tenant is refused, and flushing a tenant doesn't free its slot.

## SDK settings

The Python and Node SDKs read the server's details from the environment, so code needs none of them:

| Variable | Default | Notes |
|---|---|---|
| `CROWKIS_HOST` | `127.0.0.1` | |
| `CROWKIS_PORT` | `6383` | |
| `CROWKIS_AUTH_TOKEN` | not set | The server's token, sent as `AUTH`. `CROWKIS_TOKEN` works too. |
| `CROWKIS_TENANT` | not set | |
| `CROWKIS_URL` | not set | All in one: `crowkis://:TOKEN@HOST:PORT/TENANT`. |

A value passed in code always wins: `Crowkis(port=7000)`, or `new Crowkis({ port: 7000 })`. Then come the variables above, then the matching part of `CROWKIS_URL`, then the default. The SDKs never load a `.env` file themselves; use `python-dotenv`, `dotenv` (Node), `node --env-file=.env` (Node 20.6+), or your platform. A bad value such as `CROWKIS_PORT=abc` fails at once with an error naming the variable, and the token is never printed.
