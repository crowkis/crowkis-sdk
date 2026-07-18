<div align="center">

<img src="https://raw.githubusercontent.com/crowkis/crowkis-sdk/main/assets/crowkis-logo.png" alt="Crowkis" width="96" />

# Crowkis — Node / TypeScript SDK

**Stop paying twice for answers you already have.**
A model-agnostic semantic cache & agent-memory client for LLM apps.

<p>
<a href="https://www.npmjs.com/package/@crowkis/client"><img src="https://img.shields.io/npm/v/@crowkis/client?color=d62221&label=npm&logo=npm&logoColor=white" alt="npm" /></a>
<img src="https://img.shields.io/badge/TypeScript-included-d62221?logo=typescript&logoColor=white" alt="TypeScript" />
<a href="https://hub.docker.com/r/crowkis/crowkis"><img src="https://img.shields.io/docker/pulls/crowkis/crowkis?color=d62221&label=Docker&logo=docker&logoColor=white" alt="Docker" /></a>
<img src="https://img.shields.io/badge/License-MIT-d62221" alt="MIT" />
</p>

<p>
<a href="https://www.crowkis.com"><b>Website</b></a> ·
<a href="https://www.crowkis.com/docs/sdk-node"><b>Docs</b></a> ·
<a href="https://hub.docker.com/r/crowkis/crowkis"><b>Docker Hub</b></a>
</p>

</div>

---

Crowkis is an intelligent, Redis-compatible cache and memory layer for LLM apps and
agents. It serves repeated and **rephrased** questions from a semantic cache — so you
stop paying twice — and it's **model-agnostic**: wrap the call you already make to any
provider (OpenAI, Anthropic, a local model, whatever comes next) and the repeats come
back free. TypeScript typings included.

## Install

```bash
npm install @crowkis/client
```

## Run a Crowkis server

```bash
docker run -d -p 6383:6383 -v "$(pwd)/.crow:/data/.crow" \
  crowkis/crowkis:latest server --data /data/.crow
```

→ [hub.docker.com/r/crowkis/crowkis](https://hub.docker.com/r/crowkis/crowkis)

## Demo — cache any model

```ts
import { Crowkis } from "@crowkis/client";

const cache = new Crowkis({ tenant: "my-app" });

// Wrap any async model call. Matches on MEANING, so rephrased prompts hit too.
const answer = cache.cached(async (prompt: string) => myModel(prompt), { ttl: 3600 });

await answer("How do refunds work?");         // miss → your model runs, result cached
await answer("What's the refund process?");   // semantic HIT → no model call
```

Prefer inline? `await cache.ask("...", async (p) => myModel(p), { ttl: 3600 })`.

## Read & write directly

```ts
const hit = await cache.lookup("what's the refund timeline?");
if (hit) {
  console.log(hit.text, hit.similarity, hit.confidence);
} else {
  await cache.store("what's the refund timeline?", "5–7 business days.", { ttl: 3600 });
}
```

## LangChain.js

```ts
import { CrowkisCache } from "@crowkis/client/langchain";
import { OpenAI } from "@langchain/openai";

const llm = new OpenAI({ cache: new CrowkisCache({ tenant: "my-app", ttl: 3600 }) });
```

## Agent memory (LangGraph.js or any loop)

```ts
import { CrowkisMemory } from "@crowkis/client/memory";

const mem = new CrowkisMemory("support-bot", { user: "alice" });
await mem.remember("Alice prefers email over phone");
await mem.recall("how should I contact Alice?");   // semantic, per-user recall
```

## Authentication

If your server sets an auth token (`CROWKIS_AUTH_TOKEN`), pass it from your environment —
**never hard-code it.** Keep it in a gitignored `.env`.

```ts
const cache = new Crowkis({
  host: process.env.CROWKIS_HOST ?? "127.0.0.1",
  port: Number(process.env.CROWKIS_PORT ?? 6383),
  tenant: "my-app",
  authToken: process.env.CROWKIS_TOKEN,   // from .env, not the code
});
```

## Method reference

| Group | Methods |
|---|---|
| **Caching** | `cached()` · `ask()` · `stream()` · `lookup()` · `store()` · `similar()` · `embed()` · `flush()` |
| **Agent memory** | `cmemset` · `cmemget` · `cmemextract` · `cmemhistory` · `cmemforget` · `cmemlink` · `cmemgraph` |
| **Sessions / docs / pins / tools** | `csession*` · `cdoc*` · `cpin*` · `ctool*` |
| **Safety / cost / compliance** | `cguard` · `coutcheck` · `cbudget*` · `ckeylimit*` · `cpii*` |
| **Evals / prompts / freshness / ops** | `ceval` · `cprompt*` · `csource*` · `cscan` · `csave` · `compact` |

Full reference: **[crowkis.com/docs/sdk-node](https://www.crowkis.com/docs/sdk-node)**.

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
