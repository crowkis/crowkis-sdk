"use strict";

const TRIM = "\\s!-\\/:-@\\[-`{-~";

const TRIM_EDGES = new RegExp(`^[${TRIM}]+|[${TRIM}]+$`, "g");

const WORDS = /[\p{L}\p{N}]+/gu;

const SLOT = /\{([^{}\s]+)\}/g;

const CONTEXT_BOUND_THRESHOLD = 0.995;

const POSSESSIVES = new Set(["my", "our", "mine", "ours"]);

const HELD_RECORDS = new Set([
  "account", "order", "orders", "balance", "booking", "bookings",
  "reservation", "subscription", "payment", "payments", "invoice",
  "invoices", "refund", "delivery", "shipment", "ticket", "claim",
  "policy", "plan", "membership", "appointment", "prescription",
  "statement", "transaction", "transactions", "card", "loan", "mortgage",
  "benefits", "package", "parcel", "return", "returns", "profile",
  "password", "address", "phone", "email", "number", "contract",
  "renewal", "bill", "billing", "charge", "charges", "deposit",
  "withdrawal", "transfer", "case", "complaint",
]);

const PROCEDURAL = [
  ["how", "do", "i"],
  ["how", "do", "we"],
  ["how", "to"],
  ["how", "can", "i"],
  ["how", "can", "we"],
  ["steps", "to"],
  ["where", "do", "i"],
  ["can", "i"],
  ["can", "we"],
  ["is", "there", "a", "way"],
  ["walk", "me", "through"],
  ["help", "me"],
  ["guide"],
  ["tutorial"],
];

const OWNER_PREPOSITIONS = new Set([
  "from", "in", "on", "to", "at", "for", "with", "of", "about", "into",
  "onto", "under", "via",
]);

const STATE_LEADS = new Set([
  "what", "whats", "when", "where", "which", "who", "how", "is", "are",
  "has", "have", "had", "did", "do", "does", "show", "tell", "check",
  "status",
]);

const CONNECTIVES = new Set(["and", "so", "but", "or", "also", "then"]);

const CONNECTIVE_PAIRS = new Set(["what about", "how about", "ok and", "okay and"]);

const ELLIPSIS_LEADS = new Set([
  "for", "with", "about", "in", "on", "at", "to", "from", "by",
]);

const ANAPHOR_PHRASES = ["this one", "the second one", "the first one", "the other one"];

const ANAPHORS = new Set(["that", "those", "it", "them"]);

const DEMONSTRATIVES = new Set(["that", "those"]);

const FUNCTION_WORDS = new Set([
  "a", "about", "am", "an", "and", "any", "are", "as", "at", "be", "been",
  "but", "by", "can", "could", "did", "do", "does", "for", "from", "how",
  "i", "if", "in", "is", "it", "many", "me", "much", "my", "no", "not",
  "of", "ok", "okay", "on", "one", "or", "our", "please", "should", "so",
  "that", "the", "their", "them", "then", "there", "these", "they",
  "this", "those", "to", "us", "was", "were", "what", "whats", "when",
  "where", "which", "who", "why", "will", "with", "would", "you", "your",
]);

function normalise(text) {
  return String(text === null || text === undefined ? "" : text)
    .replace(TRIM_EDGES, "")
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

function wordsOf(text) {
  const source = String(text === null || text === undefined ? "" : text).toLowerCase();
  return source.match(WORDS) || [];
}

function splitPlain(text) {
  return text.split(/\s+/).filter(Boolean);
}

function contains(words, phrase) {
  for (let start = 0; start + phrase.length <= words.length; start += 1) {
    let same = true;
    for (let offset = 0; offset < phrase.length; offset += 1) {
      if (words[start + offset] !== phrase[offset]) {
        same = false;
        break;
      }
    }
    if (same) return true;
  }
  return false;
}

function ownedRecordAt(words) {
  for (let index = 0; index < words.length; index += 1) {
    if (!POSSESSIVES.has(words[index])) continue;
    for (const near of words.slice(index + 1, index + 3)) {
      if (HELD_RECORDS.has(near)) return index;
    }
  }
  return -1;
}

function isStateInterrogative(words) {
  return STATE_LEADS.has(words[0]) || words.includes("status");
}

function isPersonal(text) {
  const words = wordsOf(text);
  const index = ownedRecordAt(words);
  if (index < 0) return false;
  for (const phrase of PROCEDURAL) {
    if (contains(words, phrase)) return false;
  }
  if (index > 0 && OWNER_PREPOSITIONS.has(words[index - 1])) {
    return isStateInterrogative(words);
  }
  return true;
}

function hasAntecedent(before) {
  return before.some((word) => !FUNCTION_WORDS.has(word));
}

function hasBareAnaphor(words) {
  const joined = words.join(" ");
  for (const phrase of ANAPHOR_PHRASES) {
    const at = joined.indexOf(phrase);
    if (at >= 0 && !hasAntecedent(splitPlain(joined.slice(0, at)))) return true;
  }
  for (let index = 0; index < words.length; index += 1) {
    const word = words[index];
    if (!ANAPHORS.has(word)) continue;
    const follows = index + 1 < words.length ? words[index + 1] : null;
    if (DEMONSTRATIVES.has(word) && follows !== null && !FUNCTION_WORDS.has(follows)) {
      continue;
    }
    if (!hasAntecedent(words.slice(0, index))) return true;
  }
  return false;
}

function isContextDependent(text) {
  const words = wordsOf(text);
  if (!words.length) return false;
  if (CONNECTIVES.has(words[0])) return true;
  if (CONNECTIVE_PAIRS.has(words.slice(0, 2).join(" "))) return true;
  if (ELLIPSIS_LEADS.has(words[0])) return true;
  return hasBareAnaphor(words);
}

function slotNames(shape) {
  return [...String(shape).matchAll(SLOT)].map((found) => found[1]);
}

function fill(shape, values) {
  let filled = String(shape);
  for (const name of slotNames(shape)) {
    const value = values[name];
    if (value === undefined || value === null) return null;
    filled = filled.split(`{${name}}`).join(value);
  }
  return filled;
}

function abstract(answer, values) {
  let shaped = String(answer);
  const pairs = Object.entries(values).sort(
    (left, right) => String(right[1] || "").length - String(left[1] || "").length
  );
  for (const [name, value] of pairs) {
    if (value) shaped = shaped.split(value).join(`{${name}}`);
  }
  return shaped;
}

function flatten(text) {
  return wordsOf(text).join("");
}

function leaks(shaped, values) {
  const flat = flatten(shaped);
  return Object.values(values).some((value) => value && flat.includes(flatten(value)));
}

class TurnDecision {
  constructor(action, { text = null, audio = null, confidence = 0, reason = "" } = {}) {
    this.action = action;
    this.text = text;
    this.audio = audio;
    this.confidence = confidence;
    this.reason = reason;
  }

  get servedFromCache() {
    return this.action === "serve";
  }

  get servedFromFiller() {
    return this.action === "filler";
  }

  get needsModel() {
    return this.action === "infer";
  }

  toString() {
    return (
      `TurnDecision('${this.action}', confidence=${this.confidence.toFixed(4)}, ` +
      `reason='${this.reason}')`
    );
  }
}

class VoiceSession {
  constructor(
    agent,
    {
      voice,
      serveAbove = 0.92,
      minWords = 3,
      synthesise,
      ttl,
      latencyBudgetMs,
      fillers,
      values,
    } = {}
  ) {
    if (!(serveAbove >= 0 && serveAbove <= 1)) {
      throw new Error(`serveAbove must be in 0..1, got ${serveAbove}`);
    }
    if (latencyBudgetMs !== undefined && latencyBudgetMs !== null && !(latencyBudgetMs > 0)) {
      throw new Error(`latencyBudgetMs must be positive, got ${latencyBudgetMs}`);
    }
    const voiceId = typeof voice === "string" ? voice.trim() : "";
    if (!voiceId) {
      throw new Error(
        "VoiceSession requires a voice id. Cached audio is only reusable for the " +
          "voice that produced it, and switching voices mid-call is audible"
      );
    }
    this.agent = agent;
    this.voice = voiceId;
    this.serveAbove = serveAbove;
    this.minWords = minWords;
    this.synthesise = synthesise;
    this.ttl = ttl;
    this.latencyBudgetMs = latencyBudgetMs;
    this.values = Object.create(null);
    this.transcript = [];
    this.served = 0;
    this.inferred = 0;
    this.filled = 0;
    this.refusedShort = 0;
    this.refusedPrivate = 0;
    this.uncacheablePersonal = 0;
    this.overBudget = 0;
    this.bargeIns = 0;
    this._fillers = new Map();
    this._open = false;
    this._cancelled = false;
    this._turnMark = 0;
    if (values) this.setValues(values);
    if (fillers) this.registerFillers(fillers);
  }

  setValues(values = {}) {
    for (const [name, value] of Object.entries(values)) {
      if (value === null || value === undefined) delete this.values[name];
      else this.values[name] = String(value);
    }
  }

  registerFiller(trigger, response) {
    const key = normalise(trigger);
    if (!key) throw new Error("a filler trigger must contain something to match on");
    if (!(typeof response === "string" && response.trim())) {
      throw new Error("a filler response must not be empty");
    }
    this._fillers.set(key, response);
  }

  registerFillers(pairs = {}) {
    for (const [trigger, response] of Object.entries(pairs)) {
      this.registerFiller(trigger, response);
    }
  }

  async decide(callerSaid) {
    this._turnMark = this.transcript.length;
    this._open = true;
    this._cancelled = false;

    const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
    if (!text) {
      this.refusedShort += 1;
      return new TurnDecision("infer", { reason: "empty transcript" });
    }

    const filler = this._fillers.get(normalise(text));
    if (filler !== undefined) {
      this.filled += 1;
      return new TurnDecision("filler", {
        text: filler,
        audio: await this._voiced(filler),
        confidence: 1,
        reason: "registered filler, answered without a lookup or a model",
      });
    }

    if (text.split(/\s+/).length < this.minWords) {
      this.refusedShort += 1;
      return new TurnDecision("infer", {
        reason: "transcript too short to match safely",
      });
    }

    const personal = isPersonal(text);
    if (personal && !this._hasValues()) {
      this.refusedPrivate += 1;
      this.inferred += 1;
      return new TurnDecision("infer", {
        reason:
          "the caller asked about their own records and this session has no values " +
          "to fill a shared answer shape with, so nothing can be answered from " +
          "cache without one caller's answer reaching the next",
      });
    }

    const contextBound = isContextDependent(text);
    const keyed = this._contextKey(callerSaid, text);
    if (keyed === null) {
      this.inferred += 1;
      return new TurnDecision("infer", {
        reason:
          "the utterance only has meaning against an earlier turn and this call " +
          "has none, so no cache key can be built for it",
      });
    }

    const started = performance.now();
    const hit = await this.agent.ask(keyed, {
      serveAbove: this.serveAbove,
      cheapAbove: Math.min(0.6, this.serveAbove),
      template: personal,
      threshold: contextBound ? CONTEXT_BOUND_THRESHOLD : undefined,
    });
    const tookMs = performance.now() - started;

    if (this.latencyBudgetMs !== undefined && this.latencyBudgetMs !== null && tookMs > this.latencyBudgetMs) {
      this.overBudget += 1;
      this.inferred += 1;
      return new TurnDecision("infer", {
        confidence: hit.confidence,
        reason:
          `lookup took ${tookMs.toFixed(1)}ms, past the ${this.latencyBudgetMs}ms ` +
          "voice budget; a late hit is worse than a fast miss",
      });
    }

    if (hit.route !== "cache") {
      this.inferred += 1;
      return new TurnDecision("infer", {
        confidence: hit.confidence,
        reason: `confidence below the spoken-answer bar of ${this.serveAbove}`,
      });
    }

    let answer = hit.answer;
    if (personal) {
      answer = fill(answer, this.values);
      if (answer === null) {
        this.refusedPrivate += 1;
        this.inferred += 1;
        return new TurnDecision("infer", {
          confidence: hit.confidence,
          reason:
            "the shared answer shape has a slot this call has no value for; " +
            "speaking a half-filled answer is worse than a model call",
        });
      }
    }

    this.served += 1;
    this.transcript.push({ role: "user", content: callerSaid });
    this.transcript.push({ role: "assistant", content: answer });
    return new TurnDecision("serve", {
      text: answer,
      audio: await this._voiced(answer, { cacheable: !personal }),
      confidence: hit.confidence,
      reason: "confident cache hit",
    });
  }

  cancel() {
    if (!this._open) return false;
    this._open = false;
    this._cancelled = true;
    this.bargeIns += 1;
    this.transcript.length = this._turnMark;
    return true;
  }

  async recordModelTurn(callerSaid, modelSaid) {
    if (this._cancelled) return;
    this._open = false;
    const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
    const keyed = this._contextKey(callerSaid, text);
    this.transcript.push({ role: "user", content: callerSaid });
    this.transcript.push({ role: "assistant", content: modelSaid });
    if (!(typeof modelSaid === "string" && modelSaid.trim()) || keyed === null) return;
    if (isPersonal(text)) {
      await this._learnPersonal(keyed, modelSaid);
      return;
    }
    await this.agent.learn(keyed, modelSaid, { ttl: this.ttl });
  }

  injections() {
    return this.transcript.slice();
  }

  stats() {
    const total = this.served + this.inferred + this.filled;
    const pct = (count) => (total ? Math.round((10000 * count) / total) / 100 : 0);
    return {
      turns: total,
      servedFromCache: this.served,
      answeredByFiller: this.filled,
      modelCalls: this.inferred,
      refusedTooShort: this.refusedShort,
      refusedToShareAPrivateAnswer: this.refusedPrivate,
      uncacheablePersonal: this.uncacheablePersonal,
      missedLatencyBudget: this.overBudget,
      bargeIns: this.bargeIns,
      cacheHitPct: pct(this.served),
      fillerHitPct: pct(this.filled),
      modelCallsAvoidedPct: pct(this.served + this.filled),
    };
  }

  _hasValues() {
    return Object.keys(this.values).length > 0;
  }

  _priorUser() {
    for (let index = this.transcript.length - 1; index >= 0; index -= 1) {
      if (this.transcript[index].role === "user") return this.transcript[index].content;
    }
    return null;
  }

  _contextKey(callerSaid, text) {
    if (!isContextDependent(text)) return callerSaid;
    const prior = this._priorUser();
    if (prior === null || prior === undefined) return null;
    return `${prior} || ${callerSaid}`;
  }

  async _learnPersonal(keyed, modelSaid) {
    const shaped = abstract(modelSaid, this.values);
    if (this._hasValues() && slotNames(shaped).length && !leaks(shaped, this.values)) {
      await this.agent.learn(keyed, shaped, { ttl: this.ttl, template: true });
      return;
    }
    this.uncacheablePersonal += 1;
  }

  async _voiced(answer, { cacheable = true } = {}) {
    if (!this.synthesise) return null;
    if (!cacheable) return this.synthesise(answer);
    return this.agent.speak(answer, this.synthesise, {
      voice: this.voice,
      ttl: this.ttl,
    });
  }
}

module.exports = {
  VoiceSession,
  TurnDecision,
  _isPersonal: isPersonal,
  _isContextDependent: isContextDependent,
};
