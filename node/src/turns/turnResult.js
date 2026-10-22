"use strict";

const { SHARED } = require("./routes.js");

class TurnResult {
  constructor(turnId, route, fields = {}) {
    this.turnId = turnId;
    this.route = route;
    this.text = fields.text ?? null;            // what to say now (cache hit or filler)
    this.needsModel = fields.needsModel ?? true;
    this.messages = fields.messages ?? null;    // what the model reads; null = the whole call
    this.frame = fields.frame ?? null;
    this.verdict = fields.verdict ?? null;
    this.reason = fields.reason ?? "";
  }

  get servedFromCache() {
    return this.route === SHARED && this.text !== null;
  }
}

module.exports = { TurnResult };
