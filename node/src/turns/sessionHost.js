"use strict";

/**
 * Adapter: the TurnHost a VoiceSession offers its TurnCore (the call's transcript, the agent, its
 * settings, the audio for a spoken answer and the writes of an answer). It only forwards to the
 * session, so the core depends on the interface, not the session's private parts.
 */
class SessionHost {
  constructor(session) {
    this._session = session;
  }

  get transcript() {
    return this._session.transcript;
  }

  get agent() {
    return this._session.agent;
  }

  get serveAbove() {
    return this._session.serveAbove;
  }

  get latencyBudgetMs() {
    return this._session.latencyBudgetMs;
  }

  get ttl() {
    return this._session.ttl;
  }

  get segment() {
    return this._session._segment;
  }

  voiced(answer, options) {
    return this._session._voiced(answer, options);
  }

  learn(key, answer, options) {
    return this._session._learn(key, answer, options);
  }

  learnPersonal(key, answer) {
    return this._session._learnPersonal(key, answer);
  }

  keepQuestion(question, answer) {
    this._session._keepQuestion(question, answer);
  }

  contextKey(said, text) {
    return this._session._contextKey(said, text);
  }

  noteStored(key) {
    this._session._lastStored = key;
  }
}

module.exports = { SessionHost };
