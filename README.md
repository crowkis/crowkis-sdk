# Crowkis SDKs

Official client SDKs for [**Crowkis**](https://crowkis.com) — an intelligent,
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
docs: **[crowkis.com/docs](https://crowkis.com/docs)**.

## Run a server

```bash
docker run -d -p 6379:6379 -v "$(pwd)/.crow:/data/.crow" \
  crowkis/crowkis:latest server --data /data/.crow
```

## Releasing

Tag a release and the GitHub Actions workflows publish automatically:

- **Python → PyPI** via Trusted Publishing (OIDC, no stored token — configure the
  trusted publisher once on PyPI for this repo + `publish-python.yml`).
- **Node → npm** with provenance (set the `NPM_TOKEN` repo secret).

## License

MIT — see [LICENSE](./LICENSE).
