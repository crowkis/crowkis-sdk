"use strict";

// Framework-agnostic long-term agent memory backed by Crowkis.
// Works in LangGraph.js, or any agent loop. No extra dependency.
//
//   const { CrowkisMemory } = require("@crowkis/client/memory");
//   const mem = new CrowkisMemory("support-bot", { user: "alice", tenant: "demo" });
//   await mem.remember("Alice prefers email over phone");
//   const hits = await mem.recall("how should I contact Alice?");

const { CrowkisClient } = require("./index.js");

class CrowkisMemory {
  constructor(agent, options = {}) {
    if (!agent) throw new Error("agent must be a non-empty name");
    this.agent = agent;
    this.user = options.user;
    this.client = options.client || new CrowkisClient(options);
  }

  remember(fact, { ttl } = {}) {
    return this.client.cmemset(this.agent, fact, { user: this.user, ex: ttl });
  }

  recall(query, { k = 5 } = {}) {
    return this.client.cmemget(this.agent, query, { user: this.user, k });
  }

  extract(conversation, { ttl } = {}) {
    return this.client.cmemextract(this.agent, conversation, { user: this.user, ex: ttl });
  }

  history(query, { k = 5 } = {}) {
    return this.client.cmemhistory(this.agent, query, { user: this.user, k });
  }

  forget({ query, threshold } = {}) {
    return this.client.cmemforget(this.agent, { query, user: this.user, threshold });
  }

  link(subject, relation, object) {
    return this.client.cmemlink(this.agent, subject, relation, object, { user: this.user });
  }

  graph(entity, { depth } = {}) {
    return this.client.cmemgraph(this.agent, entity, { user: this.user, depth });
  }
}

module.exports = { CrowkisMemory };
