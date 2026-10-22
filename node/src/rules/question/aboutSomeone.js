"use strict";

// The AboutSomeone rule (stage 1, question; Chat, V4).

const { Verdict } = require("../../turns/verdict.js");
const { NOT_GENERAL_TYPES } = require("../../../turn.js");

/** An owned record, an own purchase or another person in the frame contradicts "general". */
class AboutSomeone {
  get name() {
    return "AboutSomeone";
  }

  get floor() {
    return true;
  }

  check(turn) {
    if (!turn.frame.entities.some((e) => NOT_GENERAL_TYPES.has(e.type))) return null;
    return new Verdict(this.name, "V4_about_someone");
  }
}

module.exports = { AboutSomeone };
