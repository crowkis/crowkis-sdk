"use strict";

// Stage 1 rules (question): the turn's shape (empty, short, cut off, no question, a filler, a task step, unsure).

const { Verdict } = require("../../turns/values.js");
const { COUNTER } = require("../../runtime/stats.js");
const { unfinished } = require("../../understanding/wordRules/followUp.js");
const { normalise } = require("../../understanding/wordRules/text.js");
const { TASK } = require("../../turns/results.js");
const { FUNCTION, QUESTION_WORDS, stem, toks } = require("../../understanding/wordRules/chat.js");

/** An empty transcript goes to the model. */
class EmptyTurn {
  get name() {
    return "EmptyTurn";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (turn.text) return null;
    return new Verdict(this.name, "empty transcript", [COUNTER.REFUSED_SHORT]);
  }
}

/**
 * A turn too short to match on meaning ("thank you") is not looked up, unless short turns are
 * on and the server's decision engine vouches for what it caches.
 */
class TooShort {
  get name() {
    return "TooShort";
  }

  get floor() {
    return false;
  }

  // Asks the server only when it must (a short turn, short turns on): then a promise.
  check(turn) {
    if (!turn.isShort) return null;
    const verdict = new Verdict(this.name, "transcript too short to match safely", [COUNTER.REFUSED_SHORT]);
    if (!turn.call.shortTurns) return verdict;
    return Promise.resolve(turn.call.engineVouches()).then((vouches) => (vouches ? null : verdict));
  }
}

/**
 * A cut-off question ("do you deliver on") is close in meaning to a full one but asks something
 * else: never served a stored answer, never stored.
 */
class CutOff {
  get name() {
    return "CutOff";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (!unfinished(turn.text)) return null;
    return new Verdict(this.name, "the turn was cut off mid-question", [COUNTER.REFUSED_SHORT]);
  }
}

// The NoQuestion rule (stage 1, question; Chat, V3).
/** A frame with no stand-alone question has nothing to look up or share. */
class NoQuestion {
  get name() {
    return "NoQuestion";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (turn.question) return null;
    return new Verdict(this.name, "V3_no_question");
  }
}

// The RegisteredFiller rule (stage 1, question; operational).
const FILLER_ROUTE = "filler";
const FILLER_REASON = "registered filler, answered without a lookup or a model";

/**
 * A turn the app registered a filler for ("hello") is answered with it at once: no lookup and no
 * model. `fillers` is the session's own Map (normalised trigger to reply), read live.
 */
class RegisteredFiller {
  constructor({ fillers = new Map() } = {}) {
    // The session passes its own Map, read live; a plain object (in tests) is copied once.
    this._fillers = fillers instanceof Map ? fillers : new Map(Object.entries(fillers));
  }

  get name() {
    return "RegisteredFiller";
  }

  get floor() {
    return false;
  }

  check(turn) {
    const filler = this._fillers.get(normalise(turn.text));
    if (filler === undefined) return null;
    return new Verdict(this.name, FILLER_REASON, [COUNTER.FILLED], null, FILLER_ROUTE, filler);
  }
}

// The TaskStep rule (stage 1, question; Chat, V9).
/**
 * A step of a task in progress (booking, ordering, a reply to the agent's own question during one)
 * goes to the agent and is never shared.
 */
// A clock time ("8:45 PM", "9 am", "21:30"): while a task runs it is one of the task's own details.
const CLOCK_TIME = /\b\d{1,2}(:\d{2})\s*(am|pm|a\.m\.|p\.m\.)?\b|\b\d{1,2}\s*(am|pm|a\.m\.|p\.m\.)(?!\w)/i;

class TaskStep {
  get name() {
    return "TaskStep";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (!(turn.frame.taskStep || TaskStep._answersAgentDuringTask(turn) || TaskStep._namesATimeDuringTask(turn))) return null;
    return new Verdict(this.name, "V9_task_step", [], null, TASK);
  }

  /** While a task is running, a reply to the agent's own question is a step of it. */
  /**
   * While a task runs, a question naming a clock time is about the task ("Does the 8:45 PM flight have a
   * meal?" while a flight is being changed: v4, misfire C01), never a general question.
   */
  static _namesATimeDuringTask(turn) {
    return turn.state.task !== "none" && CLOCK_TIME.test(turn.text || "");
  }

  static _answersAgentDuringTask(turn) {
    const state = turn.state;
    return state.task !== "none" && state.lastReply.trimEnd().endsWith("?") && !String(turn.text || "").includes("?");
  }
}

// The UncertainFrame rule (stage 1, question; Chat, V2).
/** The understanding model abstained, or is less sure than the confidence floor. */
class UncertainFrame {
  constructor({ confidenceFloor }) {
    this._confidenceFloor = confidenceFloor;
  }

  get name() {
    return "UncertainFrame";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (!(turn.frame.abstain || turn.frame.confidence < this._confidenceFloor)) return null;
    return new Verdict(this.name, "V2_uncertain");
  }
}

// The Ungrounded rule (stage 1, question; Chat, V6).
const SHOWN_WORDS = 3;
// A stem that starts another of at least this many letters is the same word ("visit", "visitor").
const SHARED_STEM = 5;

/** A content word of the key that is not in the turn or the call state (grounding). */
class Ungrounded {
  get name() {
    return "Ungrounded";
  }

  get floor() {
    return false;
  }

  check(turn) {
    const added = Ungrounded._ungrounded(turn.question, turn.text, turn.state);
    if (!added.length) return null;
    return new Verdict(this.name, "V6_ungrounded:" + added.slice(0, SHOWN_WORDS).join(","));
  }

  static _ungrounded(question, text, state) {
    const source = new Set(toks(text));
    for (const t of state.groundingSources()) for (const w of toks(t)) source.add(w);
    const stems = new Set([...source].map(stem));
    return toks(question).filter((w) => !FUNCTION.has(w) && !source.has(w) && !Ungrounded._grounded(stem(w), stems)
      && !QUESTION_WORDS.has(w));
  }

  /** The stem, or one it starts or is started by (v4, misfire B03: "visitors" after "visiting"). */
  static _grounded(wordStem, stems) {
    if (stems.has(wordStem)) return true;
    return [...stems].some((other) => Math.min(wordStem.length, other.length) >= SHARED_STEM
      && (wordStem.startsWith(other) || other.startsWith(wordStem)));
  }
}

// The NotGeneral rule (stage 1, question; Chat, V3).
/** A turn that is not a general question about no one in particular is not shared. */
class NotGeneral {
  get name() {
    return "NotGeneral";
  }

  get floor() {
    return true;
  }

  check(turn) {
    if (turn.frame.kind === "general" && turn.frame.subject === "none") return null;
    return new Verdict(this.name, "V3_not_general");
  }
}

module.exports = { EmptyTurn, TooShort, CutOff, NoQuestion, RegisteredFiller, TaskStep, UncertainFrame, Ungrounded, NotGeneral };
