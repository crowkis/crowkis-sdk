<div align="center">

<img src="https://raw.githubusercontent.com/crowkis/crowkis-sdk/main/assets/crowkis-logo.png" alt="Crowkis" width="110" />

# Crowkis SDKs

**Stop paying twice for answers you already have.**
Model-agnostic semantic cache & agent memory for LLM apps — Python & Node.

<p>
<a href="https://pypi.org/project/crowkis/"><img src="https://img.shields.io/pypi/v/crowkis?color=d62221&label=PyPI&logo=pypi&logoColor=white" alt="PyPI" /></a>
<a href="https://www.npmjs.com/package/@crowkis/client"><img src="https://img.shields.io/npm/v/@crowkis/client?color=d62221&label=npm&logo=npm&logoColor=white" alt="npm" /></a>
<a href="https://hub.docker.com/r/crowkis/crowkis"><img src="https://img.shields.io/docker/pulls/crowkis/crowkis?color=d62221&label=Docker&logo=docker&logoColor=white" alt="Docker" /></a>
<img src="https://img.shields.io/badge/License-MIT-d62221" alt="MIT" />
</p>

<p>
<a href="https://www.crowkis.com"><b>Website</b></a> ·
<a href="https://www.crowkis.com/docs"><b>Docs</b></a> ·
<a href="https://hub.docker.com/r/crowkis/crowkis"><b>Docker Hub</b></a>
</p>

</div>

---

Official client SDKs for [**Crowkis**](https://www.crowkis.com) — an intelligent,
Redis-compatible cache and memory layer for LLM apps and AI agents. Crowkis serves
repeated and rephrased questions from a semantic cache, so you stop paying twice for
answers you already have. It's **model-agnostic**: wrap the call you already make to
any provider, and the repeats come back free.

| SDK | Install | Source |
|---|---|---|
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
docs: **[crowkis.com/docs](https://www.crowkis.com/docs)**.

## Run a server

```bash
docker run -d -p 6383:6383 -v "$(pwd)/.crow:/data/.crow" \
  crowkis/crowkis:latest server --data /data/.crow
```

## Releasing

Tag a release and the GitHub Actions workflows publish automatically:

- **Python → PyPI** via Trusted Publishing (OIDC, no stored token — configure the
  trusted publisher once on PyPI for this repo + `publish-python.yml`).
- **Node → npm** with provenance (set the `NPM_TOKEN` repo secret).

## License

MIT — see [LICENSE](./LICENSE).
