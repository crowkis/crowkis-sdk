"use strict";

// Patterns Chat's save rules look for in an answer: an email, a long digit run (an ID, an account),
// a claim that something was done. Moved unchanged from session.js in v4 P3.

const EMAIL = /\S+@\S+/;
const LONG_DIGITS = /\d(?:[\s-]?\d){5,}/;
const ACTION_CLAIM = new RegExp(
  "\\b(i\\s*(have|'ve)|i\\s+just|we\\s*(have|'ve))\\s+(cancel+ed|booked|refunded|processed|changed|updated|" +
  "reset|sent|placed|scheduled|reserved|blocked|deleted|removed|added|issued)\\b" +
  "|\\b(has|have)\\s+been\\s+(cancel+ed|booked|refunded|processed|reserved|blocked|deleted)\\b", "i");

module.exports = { ACTION_CLAIM, EMAIL, LONG_DIGITS };
