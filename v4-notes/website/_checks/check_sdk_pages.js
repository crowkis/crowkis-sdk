"use strict";
// The Node SDK and Quickstart pages' code, against a real server (CROWKIS_* in the
// environment; NODE_PATH reaching @crowkis/client). Every name a page uses must exist.
const results = [];
const check = (name, ok, detail = "") => { results.push(Boolean(ok)); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? `  [${detail}]` : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const word = Array.from({ length: 3 }, () => "bcdfghjklmnpqrstvwxz"[Math.floor(Math.random() * 20)] + "aeiou"[Math.floor(Math.random() * 5)]).join("");

(async () => {
  const sdk = require("@crowkis/client");
  const { Crowkis, CrowkisAdmin, Agent, Chat, LLMUnderstander, voiceSession } = sdk;
  for (const name of ["cached", "ask", "stream", "lookup", "store", "similar", "flush", "close"]) {
    check(`Crowkis#${name} exists`, typeof Crowkis.prototype[name] === "function");
  }
  check("Agent, Chat, LLMUnderstander, voiceSession, CrowkisAdmin exported", [Agent, Chat, LLMUnderstander, voiceSession, CrowkisAdmin].every((x) => typeof x === "function"));
  const { CrowkisMemory } = require("@crowkis/client/memory");
  for (const name of ["remember", "recall", "extract", "history", "forget", "link", "graph"]) {
    check(`CrowkisMemory#${name} exists`, typeof CrowkisMemory.prototype[name] === "function");
  }
  for (const sub of ["livekit", "langchain", "memory", "chat", "session", "voice", "agent", "realtime", "voiceTurns"]) {
    let loaded = false;
    try { require(`@crowkis/client/${sub}`); loaded = true; } catch (e) { loaded = /@livekit/.test(String(e)) ? "needs @livekit" : false; }
    check(`@crowkis/client/${sub} imports`, loaded, typeof loaded === "string" ? loaded : "");
  }
  const tokenOnly = new Crowkis({ token: "x" });
  check("new Crowkis({ token }) is accepted", Boolean(tokenOnly));
  await tokenOnly.close();

  const cache = new Crowkis();
  const calls = [];
  const answer = cache.cached(async (prompt) => { calls.push(prompt); return `The ${word} plan costs nothing.`; }, { ttl: 3600 });
  const q = `what does the ${word} plan cost`;
  await answer(q);
  await sleep(1500);
  await answer(q);
  check("wrapper: the second ask is served from the cache", calls.length === 1, JSON.stringify(calls));
  await cache.store(`when does the ${word} office open`, "At nine.", { ttl: 3600 });
  await sleep(1500);
  const hit = await cache.lookup(`when does the ${word} office open`);
  check("store then lookup", hit && hit.text === "At nine.", JSON.stringify(hit && hit.text));
  const chunks = [];
  for await (const chunk of cache.stream(`explain ${word} caches`, async function* () { yield "Vector "; yield "caches."; }, { ttl: 3600 })) chunks.push(String(chunk));
  check("stream(prompt, compute) streams", chunks.join("") === "Vector caches.", JSON.stringify(chunks));
  await cache.close();
  const admin = new CrowkisAdmin({ baseUrl: "http://127.0.0.1:6384", token: process.env.CROWKIS_AUTH_TOKEN });
  const health = await admin.health();
  check("CrowkisAdmin on 6384: health()", Boolean(health), JSON.stringify(health).slice(0, 80));
  console.log(`${results.filter(Boolean).length}/${results.length} passed`);
  process.exit(results.every(Boolean) ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
