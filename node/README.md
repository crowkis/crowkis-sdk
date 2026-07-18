# Crowkis Node SDK

Official Node.js and TypeScript client for Crowkis — an intelligent,
Redis-compatible cache and memory layer for LLM apps and AI agents.

## Install

```bash
npm install @crowkis/client
```

## LangChain.js — semantic LLM cache

```js
const { CrowkisCache } = require("@crowkis/client/langchain");
const { OpenAI } = require("@langchain/openai");

// Matches on MEANING (not exact text), so rephrased prompts hit the cache.
const llm = new OpenAI({ cache: new CrowkisCache({ tenant: "my-app", ttl: 3600 }) });
```

## Agent memory (LangGraph.js or any agent loop)

```js
const { CrowkisMemory } = require("@crowkis/client/memory");

const mem = new CrowkisMemory("support-bot", { user: "alice" });
await mem.remember("Alice prefers email over phone");
const hits = await mem.recall("how should I contact Alice?");
```

## Server Defaults

If you start Crowkis with:

```bash
./target/release/crowkis server --port 6383 --data ./crowkis.data
```

then the default ports are:

- RESP: `6383`
- dashboard / management HTTP: `6384`

## Quick Start

```ts
import { CrowkisClient } from "@crowkis/client";

const cache = new CrowkisClient({
  host: "127.0.0.1",
  port: 6383,
  tenant: "demo",
  model: "gpt-4o",
});

const answer = await cache.getOrCompute(
  "Explain vector caches",
  async (query) => callLLM(query),
  { ttl: 3600 },
);

console.log(Buffer.isBuffer(answer) ? answer.toString() : answer);
cache.close();
```

## Semantic Cache

```ts
import { CrowkisClient } from "@crowkis/client";

const cache = new CrowkisClient({
  host: "127.0.0.1",
  port: 6383,
  tenant: "demo",
  model: "gpt-4o",
});

await cache.cset(
  "Explain vector caches",
  "Explain vector caches as reusable cached answers for similar queries.",
  { ttl: 3600 },
);

const cached = await cache.cget("Explain vector caches");
console.log(cached ? cached.toString() : "miss");
cache.close();
```

## Streaming Cache

```ts
for await (const chunk of cache.streamGetOrCompute(
  "Explain vector caches",
  async (query) => openAIStream(query),
  { ttl: 3600, chunkTokens: 4, delayMs: 20 },
)) {
  process.stdout.write(Buffer.isBuffer(chunk) ? chunk.toString() : String(chunk));
}
```

## Multi-Modal Cache

```ts
import fs from "node:fs";
import { CrowkisClient } from "@crowkis/client";

const image = await fs.promises.readFile("receipt.png");
const cache = new CrowkisClient({
  host: "127.0.0.1",
  port: 6383,
  tenant: "demo",
  model: "gpt-4o-vision",
});

await cache.cset(
  "What is the total on this receipt?",
  "The receipt total is $42.15.",
  { ttl: 3600, image },
);

const cached = await cache.cget("What is the total on this receipt?", { image });
console.log(cached ? cached.toString() : "miss");
cache.close();
```

## Image-Only Lookup

```ts
const answer = await cache.cimgget(image, { tenant: "demo" });
```

## gRPC API

```ts
import { CrowkisGrpcClient } from "@crowkis/client";

const grpcCache = new CrowkisGrpcClient({ target: "127.0.0.1:6381" });

await grpcCache.set("Explain vector caches", "Explain vector caches as reusable cached answers for similar queries.", {
  tenant: "demo",
  model: "gpt-4o",
  ttl: 3600,
});

const hit = await grpcCache.get("Explain vector caches", { tenant: "demo" });
console.log(hit.response.toString());
grpcCache.close();
```

Install `@grpc/grpc-js` and `@grpc/proto-loader` to use the gRPC helper. RESP users do not need those packages.

## Management API

The management client talks to the dashboard / management HTTP port, usually `6384` when the RESP server is on `6383`.
