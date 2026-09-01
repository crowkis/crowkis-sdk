"use strict";

const { CrowkisClient } = require("./index.js");

function stableArgs(args) {
  try {
    return JSON.stringify(args);
  } catch (e) {
    return String(args);
  }
}

class Agent {
  constructor(agentId, options = {}) {
    const id = typeof agentId === "string" ? agentId.trim() : "";
    if (!id) {
      throw new Error(
        "Agent requires a stable agentId. It is the address of this agent's memory, " +
          "so it must be chosen by you and stay the same across restarts and " +
          "configuration changes"
      );
    }
    this.agentId = id;
    this.tenant = options.tenant;
    this.sharesWith = (options.sharesWith || [])
      .map((s) => (typeof s === "string" ? s.trim() : ""))
      .filter(Boolean);
    this.routeCounts = { cache: 0, cheap: 0, expensive: 0 };
    this.audioHits = 0;
    this.audioMisses = 0;
    this.toolHits = 0;
    this.toolMisses = 0;
    this._ownsClient = !options.client;
    this.client =
      options.client ||
      new CrowkisClient({
        host: options.host || "127.0.0.1",
        port: options.port || 6383,
        tenant: options.tenant,
        authToken: options.authToken,
      });
  }

  async remember(fact, { ttl } = {}) {
    return this.client.cmemset(this.agentId, fact, {
      ex: ttl,
      tenant: this.tenant,
    });
  }

  async recall(query, { includeShared = true } = {}) {
    const scopes = [this.agentId];
    if (includeShared) scopes.push(...this.sharesWith);
    const found = [];
    for (const scope of scopes) {
      const result = await this.client.cmemget(scope, query, {
        tenant: this.tenant,
      });
      if (result) found.push(...(Array.isArray(result) ? result : [result]));
    }
    return found;
  }

  async history(query) {
    return this.client.cmemhistory(this.agentId, query, {
      tenant: this.tenant,
    });
  }

  async forget(options = {}) {
    return this.client.cmemforget(this.agentId, {
      ...options,
      tenant: this.tenant,
    });
  }

  async link(other, relation, object) {
    const target = other instanceof Agent ? other.agentId : other;
    return this.client.cmemlink(this.agentId, target, relation, object, {
      tenant: this.tenant,
    });
  }

  async graph(entity) {
    return this.client.cmemgraph(this.agentId, entity || this.agentId, {
      tenant: this.tenant,
    });
  }

  tool(fn, { ttl, name } = {}) {
    const toolName = name || fn.name;
    if (!toolName) {
      throw new Error(
        "agent.tool() needs a named function or an explicit { name }, because the " +
          "name is part of the cache key"
      );
    }
    const agent = this;
    const wrapped = async function (...args) {
      const key = stableArgs(args);
      const cached = await agent.client.ctoolget(toolName, key, {
        tenant: agent.tenant,
      });
      if (cached !== null && cached !== undefined) {
        agent.toolHits += 1;
        const raw = Buffer.isBuffer(cached) ? cached.toString("utf8") : cached;
        try {
          return JSON.parse(raw);
        } catch (e) {
          return raw;
        }
      }
      const result = await fn.apply(this, args);
      agent.toolMisses += 1;
      let payload;
      try {
        payload = JSON.stringify(result);
      } catch (e) {
        return result;
      }
      if (payload === undefined) return result;
      await agent.client.ctoolset(toolName, key, payload, {
        ex: ttl,
        tenant: agent.tenant,
      });
      return result;
    };
    wrapped.crowkisToolName = toolName;
    return wrapped;
  }

  toolStats() {
    const total = this.toolHits + this.toolMisses;
    return {
      calls: total,
      cached: this.toolHits,
      executed: this.toolMisses,
      avoidedPct: total ? Math.round((10000 * this.toolHits) / total) / 100 : 0,
    };
  }

  async ask(query, { serveAbove = 0.85, cheapAbove = 0.6, template = false, threshold } = {}) {
    if (!(cheapAbove >= 0 && cheapAbove <= serveAbove && serveAbove <= 1)) {
      throw new Error(
        `thresholds must satisfy 0 <= cheapAbove <= serveAbove <= 1; got ` +
          `cheapAbove=${cheapAbove}, serveAbove=${serveAbove}`
      );
    }
    if (
      threshold !== undefined &&
      !(typeof threshold === "number" && threshold >= 0 && threshold <= 1)
    ) {
      throw new Error(`threshold must be in 0..1, got ${threshold}`);
    }
    const hit = await this.client.cgetHit(query, {
      tenant: this.tenant,
      template,
      threshold,
    });
    if (!hit) {
      this.routeCounts.expensive += 1;
      return { route: "expensive", answer: null, confidence: 0, similarity: 0 };
    }
    const confidence = Number(hit.confidence);
    const route =
      confidence >= serveAbove ? "cache" : confidence >= cheapAbove ? "cheap" : "expensive";
    this.routeCounts[route] += 1;
    const text = Buffer.isBuffer(hit.response)
      ? hit.response.toString("utf8")
      : hit.response;
    return {
      route,
      answer: route === "cache" ? text : null,
      context: text,
      confidence,
      similarity: Number(hit.similarity),
    };
  }

  async speak(text, synthesise, { voice, ttl } = {}) {
    const voiceId = typeof voice === "string" ? voice.trim() : "";
    if (!voiceId) {
      throw new Error(
        "speak() requires a voice id. Audio is only reusable for the voice that " +
          "produced it; serving one voice's audio for another is audible to the caller"
      );
    }
    const key = JSON.stringify({ text, voice: voiceId });
    const cached = await this.client.ctoolget("crowkis.tts", key, {
      tenant: this.tenant,
    });
    if (cached !== null && cached !== undefined) {
      const raw = Buffer.isBuffer(cached) ? cached.toString("utf8") : String(cached);
      const audio = Buffer.from(raw, "base64");
      if (audio.length && audio.toString("base64") === raw) {
        this.audioHits += 1;
        return audio;
      }
    }
    const audio = await synthesise(text);
    this.audioMisses += 1;
    if (audio && audio.length) {
      await this.client.ctoolset(
        "crowkis.tts",
        key,
        Buffer.from(audio).toString("base64"),
        { ex: ttl, tenant: this.tenant }
      );
    }
    return audio;
  }

  audioStats() {
    const total = this.audioHits + this.audioMisses;
    return {
      spoken: total,
      fromCache: this.audioHits,
      synthesised: this.audioMisses,
      ttsAvoidedPct: total
        ? Math.round((10000 * this.audioHits) / total) / 100
        : 0,
    };
  }

  async learn(query, answer, { ttl, template = false } = {}) {
    return this.client.cset(query, answer, { ttl, tenant: this.tenant, template });
  }

  routeStats() {
    const total =
      this.routeCounts.cache + this.routeCounts.cheap + this.routeCounts.expensive;
    return {
      asked: total,
      ...this.routeCounts,
      servedWithoutAModelPct: total
        ? Math.round((10000 * this.routeCounts.cache) / total) / 100
        : 0,
    };
  }

  async close() {
    if (this._ownsClient) await this.client.close();
  }
}

module.exports = { Agent };
