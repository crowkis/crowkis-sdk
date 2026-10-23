---
title: Quickstart
path: /docs/quickstart
sdk_version: 0.5.2
server_version: 0.5.2
---

# Quickstart

*Crowkis 0.5.2 · server image `crowkis/crowkis:0.5.2` · SDKs 0.5.2*

From nothing to a cache hit in about five minutes.

## 1. Run the server

```bash
docker run -d --name crowkis \
  -p 127.0.0.1:6383:6383 -p 127.0.0.1:6384:6384 \
  -e CROWKIS_PROTECTED_MODE=off -e CROWKIS_MANAGEMENT_BIND_HOST=0.0.0.0 \
  -v crowkis-data:/data \
  crowkis/crowkis:0.5.2
```

This server is reachable from this machine only. To serve other machines, see [Docker deployment](/docs/docker): you set `CROWKIS_AUTH_TOKEN` there instead of turning protected mode off. Give the container at least 1 GB of memory; its models use about 530 MB.

| Port | What it is |
|---|---|
| `6383` | The cache: Redis protocol (RESP2/RESP3). The SDKs, `crowkis cli` and any Redis client connect here. |
| `6384` | The dashboard and management API (`/health`, `/metrics`). |
| `6385` | gRPC (h2c). It needs `CROWKIS_AUTH_TOKEN`, so it is off in this no-token setup. |
| `6386` | Health probes (`/livez`, `/readyz`), inside the container. |

The first start loads the embedding model, which takes a moment. The server is ready when this returns `"status":"ok"`:

```bash
curl -s http://127.0.0.1:6384/health
```

## 2. Talk to it

```bash
docker exec -it crowkis crowkis cli
```

```text
PING
CSET "Explain vector caches" "Vector caches store embeddings of past queries so similar questions can reuse answers." EX 86400 TENANT demo
CGET "Explain vector caches" TENANT demo
CGET "what are vector caches?" TENANT demo
```

The last `CGET` is worded differently but still returns the answer. That's a semantic hit.

## 3. Watch it decide

Open **http://127.0.0.1:6384**. The dashboard shows every lookup, whether it hit, and why.

## 4. Use it from your app

```bash
pip install crowkis            # or: npm install @crowkis/client
```

```python
from crowkis import Crowkis

cache = Crowkis(tenant="demo")                 # 127.0.0.1:6383 by default

@cache.cached(ttl=3600)
def answer(prompt: str) -> str:
    return my_model(prompt)                    # runs only on a miss

answer("Explain vector caches")                # served from the cache
```

```js
const { Crowkis } = require("@crowkis/client");

const cache = new Crowkis({ tenant: "demo" });
const answer = cache.cached(async (prompt) => myModel(prompt), { ttl: 3600 });
answer("Explain vector caches").then(console.log);   // served from the cache
```

To point the SDK at another server, set `CROWKIS_HOST`, `CROWKIS_PORT`, `CROWKIS_AUTH_TOKEN` and `CROWKIS_TENANT` in the environment. Every client reads them (see [Configuration](/docs/configuration#sdk-settings)).

**Next:** [Docker deployment](/docs/docker) · [Python SDK](/docs/sdk-python) · [Node.js SDK](/docs/sdk-node) · [Voice agents](/docs/voice)
