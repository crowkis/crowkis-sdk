"use strict";

const { LATE, within } = require("../runtime/deadline.js");
const { TurnFrame } = require("../understanding/turnFrame.js");
const { isThenable } = require("./turnCore.js");

const REPLAY_ONLY = "replay_only";

/**
 * A chat turn's frame from the app's understander, inside its one error boundary: the model reads the
 * turn within its budget (runtime/deadline, with its own copy of the state); late or failing, the safe
 * fallback (`replay`, exact repeats only) reads it, or the frame is an uncertain one. Each such turn is
 * counted in the chat's counts (understand_timeouts, understand_errors, fallback_used); nothing is
 * logged, as Chat never logged them. In replay-only mode the fallback alone reads every turn.
 * `session` is read live (state, counts, mode, understander, replay, understandBudgetMs).
 */
class ChatUnderstanding {
  constructor(session) {
    this._session = session;
  }

  /**
   * The turn's frame, handed to `then`: the model is awaited here and `then` runs in the same step, so
   * reading a turn takes no extra step.
   */
  async frame(text, then) {
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

module.exports = { ChatUnderstanding };
