"use strict";

const { CrowkisClient } = require("./index.js");

/** The server has no audio cache for this caller: its ENTERPRISE refusal, or a server from before it. */
function voiceAddonMissing(error) {
  const text = String((error && error.message) || error).trimStart();
  return text.startsWith("ENTERPRISE ") || text.startsWith("ERR ENTERPRISE ") || text.toLowerCase().includes("unknown command");
}

// How long "no Voice add-on" stands before the server is asked again (a licence may be renewed).
const ADDON_RECHECK_MS = 600000;

/** What the server's audio cache takes; anything else goes the basic way, never an error. */
function fitsAudioCache(text, labels) {
  const size = Buffer.byteLength(text, "utf8");
  return size > 0 && size <= 64 * 1024 &&
    labels.every((label) => label.length > 0 && label.length <= 64 && label.trim() && !/[\u0000-\u001f\u007f-\u009f]/.test(label));
}

// Storing a new clip never holds the caller: at most this many wait, past that
// a clip is not cached (it is stored the next time it is spoken).
const AUDIO_STORES_MAX = 64;
let audioStoresPending = 0;
const audioStores = new Set();

function storeLater(store) {
  if (audioStoresPending >= AUDIO_STORES_MAX) return false;
  audioStoresPending += 1;
  const pending = Promise.resolve()
    .then(store)
    .catch((error) => console.warn(`crowkis: an audio clip was not cached: ${error.message || error}`))
    .finally(() => {
      audioStoresPending -= 1;
      audioStores.delete(pending);
    });
  audioStores.add(pending);
  return true;
}

/** For tests: every clip handed to the background is stored. */
async function waitForAudioStores() {
  while (audioStores.size) await Promise.all([...audioStores]);
}

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
    // The server's audio cache (Voice add-on): null until the first clip asks.
    this._audioV2 = null;
    this._audioV2RecheckAt = 0;
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

  async ask(query, { serveAbove = 0.85, cheapAbove = 0.6, template = false, threshold, segment } = {}) {
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
    // Sent only when set: answers in one segment (a reply language, a region)
    // are never served to another.
    const hit = await this.client.cgetHit(query, {
      tenant: this.tenant,
      template,
      threshold,
      ...(segment ? { segment } : {}),
    });
    if (!hit) {
      this.routeCounts.expensive += 1;
      return {
        route: "expensive",
        answer: null,
        confidence: 0,
        similarity: 0,
        exact: false,
        vouched: false,
        lifetime: null,
        commitment: false,
      };
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
      // The same question, not a similar one. Two different questions can
      // score a similarity of exactly 1.
      exact: String(hit.hitType || "").endsWith("exact"),
      // What the server's decision engine recorded; defaults without one.
      vouched: Boolean(hit.vouched),
      lifetime: hit.lifetime || null,
      commitment: Boolean(hit.commitment),
    };
  }

  /**
   * Whether the server judges what it caches. A yes is remembered. A no is
   * asked again after a few minutes, so an engine switched on later is
   * noticed; a server that could not be reached reads as no for now.
   */
  async decides() {
    if (typeof this._decides === "boolean" && Date.now() - this._decidesAsked < 300000) return this._decides;
    if (!this._decidesPending) {
      // The pending question is kept, so turns that arrive together ask once.
      this._decidesPending = (async () => {
        try {
          const view = await this.client.cdecision("ping", { tenant: this.tenant });
          // A client set to fail softly answers nothing for a server it cannot reach.
          if (!view || typeof view !== "object") {
            this._holds = false;
            return false;
          }
          this._decides = Boolean(view.engine);
          this._decidesAsked = Date.now();
          // The engine holds an answer back until it has judged it.
          this._holds = this._decides && Boolean(view.holds);
          return this._decides;
        } catch (error) {
          // No engine is the safe reading of any failure. An older server
          // does not know the question: that is an answer.
          if (/unknown command/i.test(String(error && error.message))) {
            this._decides = false;
            this._decidesAsked = Date.now();
          }
          this._holds = false;
          return false;
        } finally {
          this._decidesPending = undefined;
        }
      })();
    }
    return this._decidesPending;
  }

  /**
   * What the cache decided about a question: is an answer cached, how long it
   * was judged to stay correct, or why its answer was removed.
   */
  async explain(query) {
    return this.client.cdecision(query, { tenant: this.tenant });
  }

  /**
   * Tell the cache something changed, in one sentence ("we close at 3pm
   * today"). Cached answers near it stop being served at once; the ones it
   * makes wrong are removed and the rest come back within seconds. With
   * `lasts` (seconds), answers given meanwhile expire when the notice does.
   */
  async announce(notice, { lasts, preview = false } = {}) {
    return this.client.cnoticeAdd(notice, { lasts, preview, tenant: this.tenant });
  }

  async speak(
    text,
    synthesise,
    { voice, ttl, language = "und", speed = "1", audioFormat = "default", bytesPerSecond } = {}
  ) {
    const voiceId = typeof voice === "string" ? voice.trim() : "";
    if (!voiceId) {
      throw new Error(
        "speak() requires a voice id. Audio is only reusable for the voice that " +
          "produced it; serving one voice's audio for another is audible to the caller"
      );
    }
    const labels = [voiceId, language || "und", String(speed || "1"), audioFormat || "default"];
    if (typeof this.client.caudioget !== "function") this._audioV2 = false;
    else if (this._audioV2 === false && this._audioV2RecheckAt && Date.now() >= this._audioV2RecheckAt) this._audioV2 = null;
    let useV2 = this._audioV2 !== false && fitsAudioCache(text, labels);
    if (useV2) {
      try {
        const clip = await this.client.caudioget(text, ...labels, { tenant: this.tenant });
        this._audioV2 = true;
        if (clip && clip.length) {
          this.audioHits += 1;
          return clip;
        }
      } catch (error) {
        if (!voiceAddonMissing(error)) throw error;
        this._audioV2 = false;
        this._audioV2RecheckAt = Date.now() + ADDON_RECHECK_MS;
        useV2 = false;
      }
    }
    const key = JSON.stringify({ text, voice: voiceId });
    if (!useV2) {
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
    }
    const audio = await synthesise(text);
    this.audioMisses += 1;
    if (audio && audio.length) {
      if (useV2) {
        const ms = bytesPerSecond ? Math.floor((audio.length * 1000) / bytesPerSecond) : undefined;
        // A copy now: the caller may reuse its buffer before the store runs.
        const clip = Buffer.from(audio);
        storeLater(() => this.client.caudioset(text, ...labels, clip, { ex: ttl, ms, tenant: this.tenant }));
      } else {
        await this.client.ctoolset(
          "crowkis.tts",
          key,
          Buffer.from(audio).toString("base64"),
          { ex: ttl, tenant: this.tenant }
        );
      }
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

  async learn(query, answer, { ttl, template = false, segment } = {}) {
    return this.client.cset(query, answer, { ttl, tenant: this.tenant, template, ...(segment ? { segment } : {}) });
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

module.exports = { Agent, voiceAddonMissing, waitForAudioStores };
