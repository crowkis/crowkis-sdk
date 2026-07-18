"use strict";

// Semantic LLM cache for LangChain.js (and LangGraph.js) — drop-in.
//
//   const { CrowkisCache } = require("@crowkis/client/langchain");
//   const { OpenAI } = require("@langchain/openai");
//   const llm = new OpenAI({ cache: new CrowkisCache({ tenant: "my-app", ttl: 3600 }) });
//
// Unlike LangChain's built-in caches (exact match), Crowkis matches on MEANING,
// so rephrased prompts hit the cache. Duck-typed (lookup/update) — needs no
// @langchain/core dependency.

const { CrowkisClient } = require("./index.js");

class CrowkisCache {
  constructor(options = {}) {
    this.client = options.client || new CrowkisClient(options);
    this.ttl = options.ttl;
    this.threshold = options.threshold;
  }

  async lookup(prompt, llmKey) {
    const hit = await this.client.cgetHit(prompt, {
      model: llmKey,
      threshold: this.threshold,
    });
    if (!hit) return null;
    const text = hit.text || "";
    try {
      const arr = JSON.parse(text);
      if (Array.isArray(arr)) return arr.map((t) => ({ text: String(t) }));
    } catch (_) {
      // stored as plain text (older value / another writer)
    }
    return [{ text }];
  }

  async update(prompt, llmKey, value) {
    const texts = Array.isArray(value)
      ? value.map((g) => (g && g.text !== undefined ? g.text : String(g)))
      : [String(value)];
    await this.client.cset(prompt, JSON.stringify(texts), {
      ttl: this.ttl,
      model: llmKey,
    });
  }

  async clear() {
    if (typeof this.client.cflush === "function") await this.client.cflush();
  }
}

module.exports = { CrowkisCache };
