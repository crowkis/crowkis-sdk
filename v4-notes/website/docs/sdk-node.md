---
title: Node.js / TypeScript SDK
path: /docs/sdk-node
sdk_version: 0.5.2
---

# Node.js / TypeScript SDK

*`@crowkis/client` 0.5.2 · Node.js 18+ (`--env-file` needs 20.6+) · works with server 0.5.2*

## Install

```bash
npm install @crowkis/client
```

One package covers everything; TypeScript types are included. CommonJS and ES modules both work:

```js
const { Crowkis } = require("@crowkis/client");   // CommonJS
// ES modules: import { Crowkis } from "@crowkis/client";
```

| Import from | For |
|---|---|
| `@crowkis/client` | The client, voice sessions, Chat |
| `@crowkis/client/livekit` | LiveKit Agents voice bots |
| `@crowkis/client/langchain` | LangChain.js cache |
| `@crowkis/client/memory` | Agent memory |
| `@crowkis/client/chat`, `/session` | Chat and CallSession on their own |
| `@crowkis/client/voice`, `/agent`, `/realtime`, `/voiceTurns` | The voice building blocks |

gRPC needs the optional peers `@grpc/grpc-js` and `@grpc/proto-loader`.

## The one idea

Ask Crowkis before you ask your model. If someone already asked the same thing, even in other words, you get the stored answer and the model isn't called. If not, your model answers and Crowkis keeps the answer for next time.

## Connect

```bash
# .env  (load it with dotenv, or run: node --env-file=.env app.js on Node 20.6+)
CROWKIS_HOST=10.0.0.5
CROWKIS_PORT=6383
# the server's token, if it sets one
CROWKIS_AUTH_TOKEN=change-me
CROWKIS_TENANT=my-app
```

```js
const cache = new Crowkis();      // every client reads the settings above
```

An option passed in code wins: `new Crowkis({ host: "10.0.0.6", port: 7000, tenant: "other", token })` (`authToken` works too). With nothing set, the client uses `127.0.0.1:6383`. See [Configuration](/docs/configuration#sdk-settings).

A client keeps one connection and doesn't hold your process open while it's idle. Call `close()` when a server shuts down.

## Cache any model: the wrapper

```ts
const answer = cache.cached(async (prompt: string) => myModel(prompt), { ttl: 3600 });

await answer("How do refunds work?");         // miss: your model runs, the answer is kept
await answer("What's the refund process?");   // a hit by meaning: no model call
```

Or inline: `await cache.ask("How do refunds work?", async (p) => myModel(p), { ttl: 3600 })`.

## Read and write directly

```ts
const hit = await cache.lookup("what's the refund timeline?");
if (hit) console.log(hit.text, hit.similarity, hit.confidence);
else await cache.store("what's the refund timeline?", "5–7 business days.", { ttl: 3600 });
```

## Streaming

```ts
for await (const chunk of cache.stream("Explain vector caches", async (p) => myStream(p), { ttl: 3600 })) {
  process.stdout.write(String(chunk));
}
```

## LangChain.js

```ts
import { CrowkisCache } from "@crowkis/client/langchain";
import { OpenAI } from "@langchain/openai";

const llm = new OpenAI({ cache: new CrowkisCache({ tenant: "my-app", ttl: 3600 }) });
```

## Agent memory

```ts
import { CrowkisMemory } from "@crowkis/client/memory";

const mem = new CrowkisMemory("support-bot", { user: "alice" });
await mem.remember("Alice prefers email over phone");
await mem.recall("how should I contact Alice?");
```

## Chat apps

`complete(messages)` is your model: it takes OpenAI-style messages and resolves to the reply. `messages` is the whole chat so far, and `threadId` names the conversation.

```js
import { Agent, Chat, LLMUnderstander } from "@crowkis/client";

const chat = new Chat(new Agent("support-bot"), new LLMUnderstander(complete), { system: "You are Acme's assistant." });
const reply = await chat.turn(threadId, messages, complete);   // messages: the whole chat so far
console.log(reply.text, reply.outcome);                        // served | saved | not_shared | refused:<why>
```

Anything personal, urgent, part of a booking or unclear is answered with the whole chat and never cached. Keep user details out of `system`: an answer that repeats one is answered but never saved (`refused:prompt_detail`).

## Voice agents

See [Voice agents](/docs/voice) for LiveKit and your own loop. In short:

```js
import { voiceSession } from "@crowkis/client";
const session = voiceSession();                                 // one per phone call
const stream = await session.respond(callerSaid, myLlm);        // cached, or your LLM's words as they arrive
```

## Authentication

The server has one secret, `CROWKIS_AUTH_TOKEN`. The cache clients send it for you. The admin client takes it explicitly:

```js
const { CrowkisAdmin } = require("@crowkis/client");
const admin = new CrowkisAdmin({ baseUrl: "http://127.0.0.1:6384", token: process.env.CROWKIS_AUTH_TOKEN });
```

## Method reference

```text
cache.cached(fn, { ttl, threshold })   // wrap any async model call
cache.ask(prompt, compute, { ttl })    // the stored answer, or compute() and keep it
cache.stream(prompt, compute, opts)    // the same, as an async iterator of chunks
cache.lookup(prompt)                   // { text, similarity, confidence } or null
cache.store(prompt, answer, { ttl })   // keep an answer for a prompt
cache.similar(prompt, { k })           // the k closest stored prompts
cache.flush()                          // clear this tenant's cache
cache.close()                          // close the connection

mem.remember(fact, { ttl })  ·  mem.recall(query, { k })  ·  mem.extract(conversation)
mem.history(query, { k })    ·  mem.forget({ query })     ·  mem.link(subj, rel, obj)  ·  mem.graph(entity, { depth })
```
