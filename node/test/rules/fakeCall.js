"use strict";

// FakeCall: a SessionCall for testing one rule alone. The fixtures name its settings as Python
// does (min_words, short_turns, ...); every check answers what the test set.

const { CHAT, REALTIME, VOICE } = require("../../src/turns/values.js");
const { isContextDependent, isPersonal } = require("../../src/understanding/wordRules/index.js");

const CHANNELS = { voice: VOICE, chat: CHAT, realtime: REALTIME };

const SETTING_NAMES = {
  min_words: "minWords", short_turns: "shortTurns", serve_above: "serveAbove", urgent_before: "urgentBefore",
  another_question: "anotherQuestion", stated_turns: "statedTurns",
};

class FakeCall {
  constructor(settings = {}) {
    Object.assign(this, {
      tainted: false, values: {}, minWords: 3, shortTurns: false, serveAbove: 0.92, commitments: "exact",
      vouches: false, earlier: [], urgentBefore: false, key: "the key", anotherQuestion: false, identifiers: [],
      channel: VOICE, readPersonal: new Set(), statedTurns: [], private: [],
    });
    for (const [name, value] of Object.entries(settings)) this[SETTING_NAMES[name] || name] = value;
    if (typeof this.channel === "string") this.channel = CHANNELS[this.channel];
  }

  get hasValues() {
    return Object.keys(this.values).length > 0;
  }

  isPersonal(text) {
    return this.readPersonal.has(text.trim()) || isPersonal(text);
  }

  isContextDependent(text) {
    return isContextDependent(text);
  }

  stated() {
    return this.statedTurns;
  }

  facts() {
    return [];
  }

  markPrivate(text) {
    this.readPersonal.add(text.trim());
  }

  privateWords() {
    return new Set(this.private);
  }

  markTainted() {
    this.tainted = true;
  }

  async engineVouches() {
    return this.vouches;
  }

  chain() {
    return this.earlier;
  }

  afterUrgent() {
    return this.urgentBefore;
  }

  contextKey() {
    return this.key;
  }

  async answersAnotherQuestion() {
    return this.anotherQuestion;
  }

  saidIdentifiers() {
    return new Set(this.identifiers);
  }

  agentKey() {
    return [null, null];
  }
}

module.exports = { FakeCall };
