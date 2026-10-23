"use strict";


/**
 * Adapter: the call a VoiceSession offers its rules (the VoiceCall interface: its settings and
 * what it has heard so far). It only forwards to the session's own settings and checks, so the
 * rules depend on the interface, not the session. The one change a rule makes is markTainted().
 */
class SessionCall {
  constructor(session) {
    this._session = session;
  }

  get channel() {
    return this._session.channel;
  }

  get tainted() {
    return this._session._tainted;
  }

  get values() {
    return this._session.values;
  }

  get hasValues() {
    return this._session._hasValues();
  }

  get minWords() {
    return this._session.minWords;
  }

  get shortTurns() {
    return this._session.shortTurns;
  }

  get serveAbove() {
    return this._session.serveAbove;
  }

  get commitments() {
    return this._session.commitments;
  }

  isPersonal(text) {
    return this._session._callReadings.isPersonal(text);
  }

  isContextDependent(text) {
    return this._session._callReadings.isContextDependent(text);
  }

  stated() {
    return this._session._callReadings.stated;
  }

  markPrivate(text) {
    this._session._callReadings.markPrivate(text);
  }

  markTainted() {
    this._session._tainted = true;
  }

  engineVouches() {
    return this._session._engineVouches();
  }

  chain() {
    return this._session._chain();
  }

  afterUrgent(text) {
    return this._session._afterUrgent(text);
  }

  contextKey(said, text) {
    return this._session._contextKey(said, text);
  }

  answersAnotherQuestion(asked, answer, spentMs) {
    return this._session._answersAnotherQuestion(asked, answer, spentMs);
  }

  saidIdentifiers() {
    return this._session._saidIdentifiers();
  }

  agentKey() {
    return this._session._agentKey();
  }
}

module.exports = { SessionCall };
