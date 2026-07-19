<div align="center">

<img src="https://raw.githubusercontent.com/crowkis/crowkis-sdk/main/assets/banner.png" alt="Crowkis — the intelligent cache & memory for LLM apps, built in Rust" width="100%" />

<p>
<a href="https://pypi.org/project/crowkis/"><img src="https://img.shields.io/pypi/v/crowkis?color=d62221&label=PyPI&logo=pypi&logoColor=white" alt="PyPI" /></a>
<a href="https://www.npmjs.com/package/@crowkis/client"><img src="https://img.shields.io/npm/v/%40crowkis%2Fclient?color=d62221&label=npm&logo=npm&logoColor=white" alt="npm" /></a>
<a href="https://hub.docker.com/r/crowkis/crowkis"><img src="https://img.shields.io/docker/pulls/crowkis/crowkis?color=d62221&label=Docker&logo=docker&logoColor=white" alt="Docker" /></a>
<img src="https://img.shields.io/badge/License-Apache_2.0-d62221" alt="Apache 2.0" />
</p>

<p>
<a href="https://www.crowkis.com"><b>Website</b></a> &nbsp;·&nbsp;
<a href="https://www.crowkis.com/docs"><b>Documentation</b></a> &nbsp;·&nbsp;
<a href="https://hub.docker.com/r/crowkis/crowkis"><b>Docker Hub</b></a>
</p>

</div>

## About Crowkis

Every LLM app quietly pays the same bill twice. Users ask the same questions worded a
hundred different ways, and each rewording is billed at full price. **Crowkis is an
intelligent, Redis-compatible cache and memory layer that sits between your app and your
model** — it recognises when a new question *means* the same as one already answered, and
serves that answer instantly, for free.

Crowkis is **model-agnostic** (wrap the call you already make to any provider) and gives
your agents **durable, semantic memory** that survives restarts and stays isolated per
tenant. The engine is written in Rust and ships as a single small container.

This repository holds the **official client SDKs**.

| SDK | Install | Source |
|-----|---------|--------|
| **Python** | `pip install crowkis` | [`python/`](./python) |
| **Node / TypeScript** | `npm install @crowkis/client` | [`node/`](./node) |

## Quick start

**Python** — cache any model with a decorator:

```python
from crowkis import Crowkis

cache = Crowkis(tenant="my-app")

@cache.cached(ttl=3600)
def answer(prompt: str) -> str:
    return my_model(prompt)          # OpenAI, Anthropic, a local model — anything

answer("How do refunds work?")       # miss → your model runs, result cached
answer("What's the refund process?") # semantic HIT → no model call
```

**Node**:

```js
const { Crowkis } = require("@crowkis/client");
const cache = new Crowkis({ tenant: "my-app" });

const answer = cache.cached(async (prompt) => myModel(prompt), { ttl: 3600 });
await answer("How do refunds work?");
await answer("What's the refund process?");   // semantic hit
```

Both SDKs also ship a LangChain semantic-cache adapter and durable agent memory. Full
docs: **[www.crowkis.com/docs](https://www.crowkis.com/docs)**.

## Run a server

```bash
docker run -d -p 6383:6383 -v "$(pwd)/.crow:/data/.crow" \
  crowkis/crowkis:latest server --data /data/.crow
```

## Releasing

Tag a GitHub Release and the workflows publish automatically — Python to PyPI (Trusted
Publishing) and Node to npm. See [RELEASING.md](./RELEASING.md) for the one-time setup.

## Contributing

Issues and pull requests are welcome. The client SDKs are Apache-2.0 licensed and safe to
fork, embed, and ship.

<br/>

<table>
<tr>
<td width="96"><img src="https://raw.githubusercontent.com/crowkis/crowkis-sdk/main/assets/founder.jpg" width="84" alt="Mohit Rohilla" /></td>
<td>
Built with care by <b><a href="https://github.com/itsmohitrohilla">Mohit Rohilla</a></b>, founder & creator of Crowkis — engineering the intelligent cache & memory layer for the agentic era, in Rust. 🦀
</td>
</tr>
</table>

<sub>© 2026 Crowkis · Licensed under Apache-2.0 · <a href="https://www.crowkis.com">crowkis.com</a></sub>
