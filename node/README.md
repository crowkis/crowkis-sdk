<div align="center">

<img src="https://raw.githubusercontent.com/crowkis/crowkis-sdk/main/assets/banner.png" alt="Crowkis — the intelligent cache & memory for LLM apps, built in Rust" width="100%" />

<p>
<a href="https://www.npmjs.com/package/@crowkis/client"><b>npm</b></a> &nbsp;·&nbsp;
<b>TypeScript included</b> &nbsp;·&nbsp;
<a href="https://hub.docker.com/r/crowkis/crowkis"><b>Docker</b></a> &nbsp;·&nbsp;
<b>Apache 2.0</b>
</p>

<p>
<a href="https://www.crowkis.com"><b>Website</b></a> &nbsp;·&nbsp;
<a href="https://www.crowkis.com/docs/sdk-node"><b>Documentation</b></a> &nbsp;·&nbsp;
<a href="https://hub.docker.com/r/crowkis/crowkis"><b>Docker Hub</b></a>
</p>

</div>

## About Crowkis

Every LLM app quietly pays the same bill twice. Users ask the same questions worded a
hundred different ways, and each rewording is billed at full price. **Crowkis is an
intelligent, Redis-compatible cache and memory layer that sits between your app and your
model** — it recognises when a new question *means* the same as one it has already
answered, and serves that answer instantly, for free.

It is **model-agnostic**: you wrap the call you already make — to OpenAI, Anthropic, a
local model, or whatever comes next — and Crowkis handles the rest. It also gives your
agents **durable, semantic memory** that survives restarts and stays strictly isolated
per tenant. The engine is written in Rust and ships as a single small container.

This is the official **Node / TypeScript SDK**, with typings included.

## Install

```bash
npm install @crowkis/client
```

## Run a Crowkis server

```bash
docker run -d -p 6383:6383 -v "$(pwd)/.crow:/data/.crow" \
  crowkis/crowkis:latest server --data /data/.crow
```

The server listens on `6383` (cache/RESP), `6384` (dashboard/HTTP), and `6385` (gRPC).
Image → [hub.docker.com/r/crowkis/crowkis](https://hub.docker.com/r/crowkis/crowkis).

## Cache any model — the wrapper

Wrap any async function whose first argument is the prompt. It matches on **meaning**, so
rephrased prompts hit too. The body can call *any* provider.

```ts
import { Crowkis } from "@crowkis/client";

const cache = new Crowkis({ tenant: "my-app" });

const answer = cache.cached(async (prompt: string) => myModel(prompt), { ttl: 3600 });

await answer("How do refunds work?");         // miss → your model runs, result cached
await answer("What's the refund process?");   // semantic HIT → no model call, instant
```

Prefer an inline call?

```ts
const text = await cache.ask("How do refunds work?", async (p) => myModel(p), { ttl: 3600 });
```

## Read & write directly

```ts
const hit = await cache.lookup("what's the refund timeline?");
if (hit) {
  console.log(hit.text, hit.similarity, hit.confidence);
} else {
  await cache.store("what's the refund timeline?", "5–7 business days.", { ttl: 3600 });
}
```

## Streaming

```ts
for await (const chunk of cache.stream("Explain vector caches", async (p) => myStream(p), { ttl: 3600 })) {
  process.stdout.write(typeof chunk === "string" ? chunk : chunk.toString());
}
```

## LangChain.js

```ts
import { CrowkisCache } from "@crowkis/client/langchain";
import { OpenAI } from "@langchain/openai";

const llm = new OpenAI({ cache: new CrowkisCache({ tenant: "my-app", ttl: 3600 }) });
```

## Agent memory (LangGraph.js or any loop)

Durable, semantic, per-user memory. Every recall is scoped to its agent and user.

```ts
import { CrowkisMemory } from "@crowkis/client/memory";

const mem = new CrowkisMemory("support-bot", { user: "alice" });
await mem.remember("Alice prefers email over phone");
await mem.recall("how should I contact Alice?");   // semantic recall
```

## Conversations: chat and voice agents

A `Conversation` decides, per turn, what the model may read and whether its answer is
shared: a general question is read alone and shared; a follow-up is read with the
previous question and keyed by both; a personal turn ("Where is my order?", "I'm a farmer,
what suits me?") reads the whole conversation and is never shared; a non-answer is never
saved. It does no I/O, so any pipeline can drive it:

```js
const { Conversation } = require("@crowkis/client");

const conv = new Conversation({ maxTurns: 20 });   // one per chat thread or call
const plan = conv.plan(userMessage);
const hit = plan.action === "lookup" ? await myLookup(plan.key, plan.threshold) : null;
if (hit) reply = conv.served(plan, hit);
else {
  const answer = await myModel(conv.modelMessages(plan, SYSTEM_PROMPT));
  const saving = conv.settle(plan, answer);
  if (saving.write) await myStore(saving.key, saving.text);
}
```

`isPersonal`, `isContextDependent` and `isNonAnswer` expose the rules underneath, identical
to the Python SDK. `VoiceSession` (`@crowkis/client/voice`) is the same policy plus a voice
pipeline: `await session.answer(transcript, myLlm, { system })` runs cache or model end to
end, with a latency budget, cached audio per voice, fillers and barge-in.

## Authentication

If your server sets an auth token (`CROWKIS_AUTH_TOKEN`), pass it from your environment —
never hard-code it. Keep it in a gitignored `.env`.

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
|-------|---------|
| **Caching** | `cached()` · `ask()` · `stream()` · `lookup()` · `store()` · `similar()` · `embed()` · `flush()` |
| **Agent memory** | `cmemset` · `cmemget` · `cmemextract` · `cmemhistory` · `cmemforget` · `cmemlink` · `cmemgraph` |
| **Sessions / docs / pins / tools** | `csession*` · `cdoc*` · `cpin*` · `ctool*` |
| **Safety / cost / compliance** | `cguard` · `coutcheck` · `cbudget*` · `ckeylimit*` · `cpii*` |
| **Evals / prompts / freshness / ops** | `ceval` · `cprompt*` · `csource*` · `cscan` · `csave` · `compact` |

Full reference and guides at **[www.crowkis.com/docs/sdk-node](https://www.crowkis.com/docs/sdk-node)**.

## Contributing

Issues and pull requests are welcome at
[github.com/crowkis/crowkis-sdk](https://github.com/crowkis/crowkis-sdk). The client is
Apache-2.0 licensed and safe to fork, embed, and ship.

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
