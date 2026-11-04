"use strict";

// The turn core's value objects: a turn's verdicts, what the cache and the model said to it, a hit, the channel.

const { fill } = require("../understanding/wordRules/index.js");

/**
 * What happened to a model's answer: the words callers see in `decision.notStored`, a voice record's
 * `outcome`, Chat's outcomes and its "answer" events. Named constants, like COUNTER.
 */
const OUTCOME = Object.freeze({
  SAVED: "saved",
  TEMPLATE: "template",
  KEPT: "kept",
  PRIVATE: "private",
  NON_ANSWER: "non_answer",
  NOT_SAVED: "not_saved",
  INTERRUPTED: "interrupted",
  NOT_SHARED: "not_shared",
  CANCELLED: "cancelled",
  STALE: "stale",
  SLOW_WRITE: "slow_write",
  REFUSED: "refused",
});

/** Chat's form of an outcome with its reason: "refused:<why>". */
function because(outcome, why) {
  return `${outcome}:${why}`;
}

/**
 * What a rule says when it objects. `rule` names the rule (in decisions, logs and stats()),
 * `reason` says why in words, `counts` are the session counters it adds to, `outcome` is, for a
 * save rule, what happened to the answer (an OUTCOME; Chat's refusal adds its reason:
 * `because(OUTCOME.REFUSED, why)`), and `route` is, for a Chat
 * rule that decides alone, where the turn goes ("urgent", "task", "filler"), and `answer` is what to
 * say at once when the rule answers the turn itself (a filler). Immutable.
 */
class Verdict {
  /**
   * @param {string} rule
   * @param {string} reason
   * @param {string[]} [counts]
   * @param {string|null} [outcome]
   * @param {string|null} [route]
   * @param {string|null} [answer]
   */
  constructor(rule, reason, counts = [], outcome = null, route = null, answer = null) {
    this.rule = rule;
    this.reason = reason;
    this.counts = Object.freeze([...counts]);
    this.outcome = outcome;
    this.route = route;
    this.answer = answer;
    Object.freeze(this);
  }
}

/**
 * A step's subject (the turn, the answer) as the next step reads it, and the objection that stops
 * the turn there, if any (null: none). As a rule chain answers, the objection may still be pending
 * (a promise) when a rule had to ask the server; TurnCore awaits only a pending one. Immutable.
 */
class Checked {
  constructor(subject, objection = null) {
    this.subject = subject;
    this.objection = objection;
    Object.freeze(this);
  }
}

/**
 * The cache's raw `hit` for a turn (null when there was none in time), the hit as the hit rules read
 * it (`cached`, null when no hit was checked), and the objection that sends the turn to the model
 * instead, if any (pending, as in Checked, until TurnCore awaits it). Immutable.
 */
class LookedUp {
  constructor(hit, cached = null, objection = null) {
    this.hit = hit;
    this.cached = cached;
    this.objection = objection;
    Object.freeze(this);
  }
}

const CACHE_ROUTE = "cache";

/**
 * What the cache returned for a turn's key, typed once at the lookup: its route ("cache" when confident
 * enough to speak), the answer text, the confidence, and the flags the server's decision engine set (an
 * exact match, vouched for, a commitment such as a price or a policy). Immutable.
 */
class Hit {
  constructor({ route, answer = null, confidence = 0, exact = false, vouched = false, commitment = false, unjudged = false }) {
    Object.assign(this, { route, answer, confidence, exact, vouched, commitment, unjudged });
    Object.freeze(this);
  }

  /** Built once from Agent.ask's result. */
  static fromAgent(hit) {
    return new Hit({
      route: hit.route, answer: hit.answer ?? null, confidence: hit.confidence ?? 0, exact: Boolean(hit.exact),
      vouched: Boolean(hit.vouched), commitment: Boolean(hit.commitment), unjudged: Boolean(hit.unjudged),
    });
  }

  get isConfident() {
    return this.route === CACHE_ROUTE;
  }
}

/**
 * What the cache returned for a turn: a voice VoiceTurn, or the shared question a chat looked up
 * (ChatHitTurn, never personal). `started` is when the lookup began (performance.now()).
 */
class CachedAnswer {
  constructor(turn, hit, started) {
    this.turn = turn;
    this.hit = hit;
    this.started = started;
    this._answer = undefined;
  }

  /**
   * The text to speak: for a personal turn, the shared answer shape filled with this call's
   * values, or null when a slot has no value. Read only for a confident hit.
   */
  get answer() {
    if (this._answer === undefined) {
      this._answer = this.turn.isPersonal ? fill(this.hit.answer, this.turn.call.values) : this.hit.answer;
    }
    return this._answer;
  }
}

/**
 * What a channel is able to do, as the rules and the turn steps read it (plan §3.3). Rules read
 * these fields and never branch on the channel's name. Immutable. `understandBudgetMs`: how long a
 * plugged-in classifier and rewriter may take on a turn before the word rules read it instead. Today
 * the rules read `spoken` and the factories the budgets; `isolatesContext`, `audio` and `savesAnswers`
 * describe the channel for the merged core (P5).
 */
class Channel {
  constructor({ name, isolatesContext, budgetMs, audio, spoken, savesAnswers, understandBudgetMs = 250 }) {
    Object.assign(this, { name, isolatesContext, budgetMs, audio, spoken, savesAnswers, understandBudgetMs });
    Object.freeze(this);
  }

  /** A channel, or the profile with that name ("voice", "chat", "realtime"). */
  static of(channel) {
    if (channel instanceof Channel) return channel;
    const found = CHANNELS.get(String(channel).trim().toLowerCase());
    if (!found) throw new Error(`channel must be one of ${[...CHANNELS.keys()].sort().join(", ")} or a Channel, got ${channel}`);
    return found;
  }
}

const VOICE = new Channel({ name: "voice", isolatesContext: true, budgetMs: 250, audio: true, spoken: true, savesAnswers: true });
const CHAT = new Channel({ name: "chat", isolatesContext: true, budgetMs: 1000, audio: false, spoken: false, savesAnswers: true });
const REALTIME = new Channel({ name: "realtime", isolatesContext: false, budgetMs: 250, audio: false, spoken: true, savesAnswers: false });

const CHANNELS = new Map([VOICE, CHAT, REALTIME].map((channel) => [channel.name, channel]));

module.exports = { CACHE_ROUTE, CHANNELS, CHAT, CachedAnswer, Channel, Checked, Hit, LookedUp, OUTCOME, REALTIME, VOICE, Verdict, because };
