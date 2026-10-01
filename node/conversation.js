"use strict";

// One conversation's cache decisions, with no I/O. Mirrors crowkis/conversation.py.
//
// For every turn a Conversation decides:
//   plan()    whether to look the turn up, under which key, and what the model must
//             read on a miss: the question alone, the question before it plus this
//             one (a follow-up), or the whole conversation (a personal turn)
//   served()  what to say when the cache answered (a shape is filled with values)
//   settle()  after the model answered: whether its answer may be saved, as what,
//             and under which key
//
// The app does its own reads and writes and asks the conversation for every
// decision, so channels with very different pipelines (a voice agent, an HTTP chat
// backend) follow one set of rules. VoiceSession is such an app.
//
// The safety rule underneath: an answer may be shared only when the model saw
// nothing but its cache key, so nothing else the caller said can end up inside it.

const {
  CONTEXT_BOUND_THRESHOLD,
  abstract,
  fill,
  isContextDependent,
  isNonAnswer,
  isPersonal,
  leaks,
  normalise,
  slotNames,
} = require("./rules.js");

// TurnPlan.action
const FILLER = "filler"; // answer with plan.filler: no lookup, no model
const LOOKUP = "lookup"; // look plan.key up; on a miss, ask the model
const MODEL = "model"; // ask the model straight away (plan.reason says why)

// Saving.outcome
const SAVED = "saved";
const TEMPLATE = "template";
const KEPT = "kept";
const PRIVATE = "private";
const NON_ANSWER = "non_answer";
const INTERRUPTED = "interrupted";
const NOT_SAVED = "not_saved";

function wordCount(text) {
  return text.split(/\s+/).filter(Boolean).length;
}

class TurnPlan {
  constructor({ said, action, reason, key, personal, template, threshold, messages, shareable, filler = null }) {
    this.said = said;
    this.action = action;
    this.reason = reason; // filler | lookup | empty | short | personal_no_values | no_prior_turn | unplanned
    this.key = key; // cache key for both the lookup and the save; null when none can be built
    this.personal = personal;
    this.template = template; // look up / save an answer shape filled with this conversation's values
    this.threshold = threshold; // near-exact bar for a turn that only means something after the last
    this.messages = messages; // what the model reads on a miss; null = the whole conversation
    this.shareable = shareable; // the model's answer may be shared with later callers
    this.filler = filler;
    Object.freeze(this);
  }

  get modelSees() {
    if (this.messages === null) return "whole conversation";
    return this.messages.length === 1 ? "question" : "question + previous";
  }
}

class Saving {
  constructor(outcome, { key = null, text = null, template = false } = {}) {
    this.outcome = outcome;
    this.key = key;
    this.text = text;
    this.template = template;
    Object.freeze(this);
  }

  // Whether the app should write `text` under `key` now.
  get write() {
    return this.outcome === SAVED || this.outcome === TEMPLATE;
  }
}

class Conversation {
  constructor({ minWords = 3, values = null, fillers = null, maxTurns = null } = {}) {
    if (!(minWords >= 1)) throw new Error(`minWords must be at least 1, got ${minWords}`);
    if (maxTurns !== null && maxTurns !== undefined && !(maxTurns >= 1)) {
      throw new Error(`maxTurns must be at least 1, got ${maxTurns}`);
    }
    this.minWords = minWords;
    // How many caller turns of history a whole-conversation model call carries.
    // null keeps everything; a long chat thread should set it.
    this.maxTurns = maxTurns === undefined ? null : maxTurns;
    this.values = Object.create(null);
    this.transcript = [];
    this._fillers = new Map();
    this._mark = 0;
    this._open = false;
    this._cancelled = false;
    if (values) this.setValues(values);
    if (fillers) this.registerFillers(fillers);
  }

  // --- this conversation's facts ----------------------------------------------------------

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
    for (const [trigger, response] of Object.entries(pairs)) this.registerFiller(trigger, response);
  }

  // --- one turn ---------------------------------------------------------------------------

  // Decide what to do with what the caller just said. Opens the turn.
  plan(said) {
    this._mark = this.transcript.length;
    this._open = true;
    this._cancelled = false;
    const text = typeof said === "string" ? said.trim() : "";
    const [messages, shareable] = this._modelMessages(said, text);
    const base = { said, key: this._contextKey(said, text), messages, shareable };
    const none = { template: false, threshold: null };

    if (!text) return new TurnPlan({ ...base, ...none, action: MODEL, reason: "empty", personal: false });
    const filler = this._fillers.get(normalise(text));
    if (filler !== undefined) {
      return new TurnPlan({ ...base, ...none, action: FILLER, reason: "filler", personal: false, filler });
    }
    if (wordCount(text) < this.minWords) {
      return new TurnPlan({ ...base, ...none, action: MODEL, reason: "short", personal: false });
    }
    const personal = isPersonal(text);
    if (personal && !this._hasValues()) {
      return new TurnPlan({ ...base, ...none, action: MODEL, reason: "personal_no_values", personal: true });
    }
    if (base.key === null) {
      return new TurnPlan({ ...base, ...none, action: MODEL, reason: "no_prior_turn", personal });
    }
    return new TurnPlan({
      ...base,
      action: LOOKUP,
      reason: "lookup",
      personal,
      template: personal,
      threshold: isContextDependent(text) ? CONTEXT_BOUND_THRESHOLD : null,
    });
  }

  // A plan for an answer that arrived with no decision behind it: never shared.
  unplanned(said) {
    const text = typeof said === "string" ? said.trim() : "";
    return new TurnPlan({
      said, action: MODEL, reason: "unplanned", key: this._contextKey(said, text),
      personal: text ? isPersonal(text) : false, template: false, threshold: null, messages: null, shareable: false,
    });
  }

  // The cache answered: what to say. null when a shape has a slot this conversation
  // cannot fill. The turn stays open, so a barge-in can still cancel it.
  served(plan, cached) {
    let answer = cached;
    if (plan.template) {
      answer = fill(cached, this.values);
      if (answer === null) return null;
    }
    this.transcript.push({ role: "user", content: plan.said });
    this.transcript.push({ role: "assistant", content: answer });
    return answer;
  }

  // Exactly what the model must read for this turn, `system` first.
  modelMessages(plan, system = null) {
    let messages = plan.messages !== null
      ? plan.messages.slice()
      : [...this._history(), { role: "user", content: plan.said }];
    if (system) messages = [{ role: "system", content: system }, ...messages];
    return messages;
  }

  // The model answered `plan`: remember the turn, and decide what may be saved.
  settle(plan, answer) {
    if (this._cancelled) return new Saving(INTERRUPTED);
    this._open = false;
    this.transcript.push({ role: "user", content: plan.said });
    this.transcript.push({ role: "assistant", content: answer });
    if (!(typeof answer === "string" && answer.trim()) || plan.key === null) return new Saving(NOT_SAVED);
    if (isNonAnswer(answer)) return new Saving(NON_ANSWER);
    if (plan.personal) {
      const shaped = abstract(answer, this.values);
      if (this._hasValues() && slotNames(shaped).length && !leaks(shaped, this.values)) {
        return new Saving(TEMPLATE, { key: plan.key, text: shaped, template: true });
      }
      return new Saving(PRIVATE);
    }
    if (!plan.shareable || leaks(answer, this.values)) return new Saving(KEPT);
    return new Saving(SAVED, { key: plan.key, text: answer });
  }

  // Remember a turn that is never cached. false when the turn was cancelled.
  keepPrivate(said, answer) {
    if (this._cancelled) return false;
    this._open = false;
    this.transcript.push({ role: "user", content: said });
    this.transcript.push({ role: "assistant", content: answer });
    return true;
  }

  // Abandon the open turn (barge-in): it leaves no trace and nothing is saved.
  cancel() {
    if (!this._open) return false;
    this._open = false;
    this._cancelled = true;
    this.transcript.length = this._mark;
    return true;
  }

  // --- internals --------------------------------------------------------------------------

  _modelMessages(said, text) {
    if (wordCount(text) < this.minWords || isPersonal(text)) return [null, false];
    if (!isContextDependent(text)) return [[{ role: "user", content: said }], true];
    const prior = this._priorUser();
    if (prior === null || isPersonal(prior)) return [null, false];
    return [[{ role: "user", content: prior }, { role: "user", content: said }], true];
  }

  _history() {
    if (this.maxTurns === null) return this.transcript.slice();
    return this.transcript.slice(-2 * this.maxTurns);
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

  _contextKey(said, text) {
    if (!isContextDependent(text)) return said;
    const prior = this._priorUser();
    if (prior === null || prior === undefined) return null;
    return `${prior} || ${said}`;
  }
}

module.exports = {
  Conversation, TurnPlan, Saving,
  FILLER, LOOKUP, MODEL,
  SAVED, TEMPLATE, KEPT, PRIVATE, NON_ANSWER, INTERRUPTED, NOT_SAVED,
};
