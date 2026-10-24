"use strict";

/**
 * The app's chat hooks (onUrgent, onTools, onEvent), inside their one error boundary: an urgent-turn
 * hook or a monitoring hook that fails changes nothing, and a failing tool means the model answers.
 * Never ends the chat. The callers call a hook only when the app set one. `session` is read live: an
 * app may change its hooks between turns.
 *
 * `urgent` and `tools` await the app's hook and hand the result to `then` in the same step, so a turn
 * with a hook takes no extra step.
 */
class AppHooks {
  constructor(session) {
    this._session = session;
  }

  /** The app's onUrgent hook, told of an urgent turn; then `then()`. */
  async urgent(text, frame, then) {
    try { await this._session.onUrgent(text, frame); } catch { /* the hook must not take the call down */ }
    return then();
  }

  /** The app's onTools answer to a personal or live turn (null when it fails), handed to `then`. */
  async tools(text, frame, then) {
    let answered = null;
    try { answered = await this._session.onTools(text, frame); } catch { answered = null; /* a failing tool means the model answers */ }
    return then(answered);
  }

  /** The app's onEvent monitoring hook, sent one event. */
  event(event) {
    try { this._session.onEvent(event); } catch { /* monitoring must never affect the call */ }
  }
}

module.exports = { AppHooks };
