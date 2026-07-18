<div align="center">

<img src="https://raw.githubusercontent.com/crowkis/crowkis-sdk/main/assets/crowkis-logo.png" alt="Crowkis" width="96" />

# Crowkis — Python SDK

**Stop paying twice for answers you already have.**
A model-agnostic semantic cache & agent-memory client for LLM apps.

<p>
<a href="https://pypi.org/project/crowkis/"><img src="https://img.shields.io/pypi/v/crowkis?color=d62221&label=PyPI&logo=pypi&logoColor=white" alt="PyPI" /></a>
<img src="https://img.shields.io/pypi/pyversions/crowkis?color=d62221" alt="Python versions" />
<a href="https://hub.docker.com/r/crowkis/crowkis"><img src="https://img.shields.io/docker/pulls/crowkis/crowkis?color=d62221&label=Docker&logo=docker&logoColor=white" alt="Docker" /></a>
<img src="https://img.shields.io/badge/License-MIT-d62221" alt="MIT" />
</p>

<p>
<a href="https://www.crowkis.com"><b>Website</b></a> ·
<a href="https://www.crowkis.com/docs/sdk-python"><b>Docs</b></a> ·
<a href="https://hub.docker.com/r/crowkis/crowkis"><b>Docker Hub</b></a>
</p>

</div>

---

Crowkis is an intelligent, Redis-compatible cache and memory layer for LLM apps and
agents. It serves repeated and **rephrased** questions from a semantic cache — so you
stop paying twice — and it's **model-agnostic**: wrap the call you already make to any
provider (OpenAI, Anthropic, a local model, whatever comes next) and the repeats come
back free.

## Install

```bash
pip install crowkis
```

Zero dependencies. LangChain / OpenAI adapters use those libraries only if you already have them.

## Run a Crowkis server

```bash
docker run -d -p 6383:6383 -v "$(pwd)/.crow:/data/.crow" \
  crowkis/crowkis:latest server --data /data/.crow
```

→ [hub.docker.com/r/crowkis/crowkis](https://hub.docker.com/r/crowkis/crowkis)

## Cache any model — the decorator

Works like `functools.lru_cache`, but matches on **meaning**, so rephrased prompts hit too.

```python
from crowkis import Crowkis

cache = Crowkis(tenant="my-app")

@cache.cached(ttl=3600)
def answer(prompt: str) -> str:
    return my_model(prompt)          # OpenAI, Anthropic, a local model — anything

answer("How do refunds work?")       # miss → your model runs, result cached
answer("What's the refund process?") # semantic HIT → no model call
```

Prefer inline? `cache.ask("...", compute=lambda p: my_model(p), ttl=3600)`.

## Read & write directly

```python
hit = cache.lookup("what's the refund timeline?")   # semantic match
if hit:
    print(hit.text, hit.similarity, hit.confidence)
else:
    cache.store("what's the refund timeline?", "5–7 business days.", ttl=3600)
```

## LangChain & LangGraph

```python
from langchain_core.globals import set_llm_cache
from crowkis.integrations.langchain import CrowkisCache

set_llm_cache(CrowkisCache(tenant="my-app", ttl=3600))
# every LangChain / LangGraph model call is now cached by meaning
```

## Agent memory (LangGraph, CrewAI, AutoGen, custom)

```python
from crowkis import CrowkisMemory

mem = CrowkisMemory(agent="support-bot", user="alice")
mem.remember("Alice prefers email over phone")
mem.recall("how should I contact Alice?")   # semantic, per-user recall
```

## Authentication

If your server sets an auth token (`CROWKIS_AUTH_TOKEN`), pass it from your environment —
**never hard-code it.** Keep it in a gitignored `.env`.

```python
import os
from crowkis import Crowkis

cache = Crowkis(
    host=os.getenv("CROWKIS_HOST", "127.0.0.1"),
    port=int(os.getenv("CROWKIS_PORT", "6383")),
    tenant="my-app",
    auth_token=os.getenv("CROWKIS_TOKEN"),   # from .env, not the code
)
```

## Discover every command

```python
import crowkis
crowkis.help()            # grouped cheat-sheet of every feature
crowkis.help("memory")    # filter by topic
```

## Method reference

| Group | Methods |
|---|---|
| **Caching** | `cached()` · `ask()` · `stream()` · `lookup()` · `store()` · `similar()` · `embed()` · `flush()` |
| **Agent memory** | `remember` · `recall` · `extract` · `history` · `as_of` · `forget` · `link` · `graph` |
| **Sessions / docs / pins / tools** | `csession_*` · `cdoc_*` · `cpin*` · `ctool*` |
| **Safety & quality** | `cguard` · `coutcheck` · `cflag` · `ccheckbad` |
| **Cost / limits / compliance** | `cbudget_*` · `ckeylimit_*` · `cpii_*` · `cdedup` |
| **Evals / prompts / freshness** | `ceval` · `cprompt_*` · `csource_*` · `cstale` · `cinvalidate` |
| **Ops** | `cinfo` · `cscan` · `csave` · `creload` · `compact` |

Full reference: **[crowkis.com/docs/sdk-python](https://www.crowkis.com/docs/sdk-python)**.

## Author

<table>
<tr>
<td width="96"><img src="https://raw.githubusercontent.com/crowkis/crowkis-sdk/main/assets/founder.jpg" width="84" alt="Mohit Rohilla" /></td>
<td>
<b><a href="https://github.com/itsmohitrohilla">Mohit Rohilla</a></b> — founder &amp; creator of Crowkis.<br/>
Building the intelligent cache &amp; memory layer for the agentic era. Contributions and issues welcome.
</td>
</tr>
</table>

## License

MIT © Crowkis
