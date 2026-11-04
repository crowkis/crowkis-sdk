"use strict";

const { LATE, within } = require("../runtime/deadline.js");
const { names, told } = require("../understanding/chatDetails.js");
const { identifiers, instructs, tellsAboutCaller, wordsOf } = require("../understanding/wordRules/index.js");
const { TurnFrame } = require("../understanding/turnFrame.js");
const { ChatReading } = require("./chatReading.js");
const { isThenable } = require("./turnCore.js");

const REPLAY_ONLY = "replay_only";

/**
 * Reads a user's turn: its frame, then what the user tells (an allergy, an age, a trip), the names and
 * IDs they give and a language they ask for, noted in the chat's state before any check, this turn's
 * included. `session` is read live (state, counts, mode, understander, replay, understandBudgetMs).
 *
 * The frame is the one place a chat's understanding fails open: the model reads the turn within its
 * budget (runtime/deadline, with its own copy of the state); late or failing, the safe fallback
 * (`replay`, exact repeats only) reads it, or the frame is an uncertain one. Each such turn is counted
 * in the chat's counts (understand_timeouts, understand_errors, fallback_used); nothing is logged, as
 * Chat never logged them. In replay-only mode the fallback alone reads every turn.
 */
class ChatReader {
  constructor(session) {
    this._session = session;
  }

  // Not async: the frame's own step runs the noting, so reading takes no extra step.
  read(said, turn) {
    const text = String(said || "").split(/\s+/).filter(Boolean).join(" ");
    const words = wordsOf(text);
    const aboutCaller = tellsAboutCaller(text);
    return this._frame(text, (frame) => this._noted(text, words, aboutCaller, frame, turn));
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

  /**
   * The turn's frame, handed to `then`: the model is awaited here and `then` runs in the same step, so
   * reading a turn takes no extra step.
   */
  async _frame(text, then) {
    const session = this._session;
    let frame;
    if (session.mode === REPLAY_ONLY) {
      frame = this._replayOnly(text);
    } else {
      try {
        // The model gets its own copy of the state: a late answer can never see a later turn's state.
        const work = session.understander.understand(text, session.state.clone());
        const budgetMs = session.understandBudgetMs;
        const answered = budgetMs === null || budgetMs === undefined ? await work : await within(budgetMs, work);
        if (answered === LATE) session.counts.understand_timeouts += 1;
        else frame = answered || TurnFrame.fromDict(null);
      } catch {
        session.counts.understand_errors += 1;
      }
      if (frame === undefined) frame = this._fallback(text);
    }
    if (isThenable(frame)) frame = await frame;
    return then(frame);
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
      try { return session.replay.understand(text, session.state); } catch { /* the fallback failing too leaves an uncertain frame */ }
    }
    return TurnFrame.fromDict(null);
  }
}

module.exports = { ChatReader };
