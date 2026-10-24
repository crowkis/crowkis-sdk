"use strict";

const { names, told } = require("../understanding/chatDetails.js");
const { TurnFrame } = require("../understanding/turnFrame.js");
const { identifiers, instructs, tellsAboutCaller, wordsOf } = require("../understanding/wordRules/index.js");
const { ChatReading } = require("./chatReading.js");
const { isThenable } = require("./turnCore.js");

const REPLAY_ONLY = "replay_only";
const TIMEOUT = Symbol("timeout");

/** Resolve within `ms`, else TIMEOUT. The late promise keeps running and is ignored. */
function within(promiseOrValue, ms) {
  const work = Promise.resolve(promiseOrValue);
  if (ms === null || ms === undefined) return work;
  let timer;
  const late = new Promise((resolve) => { timer = setTimeout(() => resolve(TIMEOUT), ms); });
  return Promise.race([work, late]).finally(() => clearTimeout(timer));
}

/**
 * Reads a user's turn with the understanding model, within its budget; late or failing, the safe
 * fallback (`replay`, exact repeats only) reads it, or the frame is an uncertain one. What the user
 * tells (an allergy, an age, a trip), the names and IDs they give and a language they ask for are
 * noted in the chat's state before any check, this turn's included. `session` is read live (state,
 * counts, mode, understander, replay, understandBudgetMs): an app may change them between turns.
 */
class ChatReader {
  constructor(session) {
    this._session = session;
  }

  async read(said, turn) {
    const session = this._session;
    const text = String(said || "").split(/\s+/).filter(Boolean).join(" ");
    const words = wordsOf(text);
    const aboutCaller = tellsAboutCaller(text);
    // The model is awaited here, not in a step of its own, so reading takes no extra step.
    let frame;
    if (session.mode === REPLAY_ONLY) {
      frame = this._replayOnly(text);
    } else {
      try {
        // The model gets its own copy of the state: a late answer can never see a later turn's state.
        const answered = await within(session.understander.understand(text, session.state.clone()), session.understandBudgetMs);
        if (answered === TIMEOUT) session.counts.understand_timeouts += 1;
        else frame = answered || TurnFrame.fromDict(null);
      } catch {
        session.counts.understand_errors += 1;
      }
      if (frame === undefined) frame = this._fallback(text);
    }
    if (isThenable(frame)) frame = await frame;
    return this._noted(text, words, aboutCaller, frame, turn);
  }

  // With sharing in replay-only mode: the safe fallback's frame, or an uncertain one without it.
  _replayOnly(text) {
    const session = this._session;
    if (!session.replay) return TurnFrame.fromDict(null);
    session.counts.fallback_used += 1;
    return session.replay.understand(text, session.state);
  }

  // The model was late or failed: the safe fallback's frame, or an uncertain one.
  _fallback(text) {
    const session = this._session;
    if (session.replay && session.replay !== session.understander) {
      session.counts.fallback_used += 1;
      try { return session.replay.understand(text, session.state); } catch { /* fall through */ }
    }
    return TurnFrame.fromDict(null);
  }

  // What the user told, the names and IDs they gave and the language they asked for, noted in the
  // chat's state before any check: the turn as read.
  _noted(text, words, aboutCaller, frame, turn) {
    const state = this._session.state;
    let named = new Set();
    if (aboutCaller) {
      let toldDetails;
      [named, toldDetails] = told(text, frame);
      state.noteStated(words.filter((w) => !named.has(w)).join(" "));
      state.noteDetails(toldDetails);
    }
    // On every turn and before the check: a name given in this very turn ("Hi, I'm Sarah. What is the
    // refund policy?") is never in a shared question or answer.
    const given = [...new Set([...names(text, frame, aboutCaller), ...named])].sort();
    state.noteNames(given);
    state.noteIdentifiers(identifiers([text]));
    if (frame.language && instructs(text, words)) state.language = frame.language; // kept for the rest of the chat
    return new ChatReading(text, { frame, names: given, aboutCaller, turnId: turn });
  }
}

module.exports = { ChatReader };
