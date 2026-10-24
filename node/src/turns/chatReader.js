"use strict";

const { names, told } = require("../understanding/chatDetails.js");
const { identifiers, instructs, tellsAboutCaller, wordsOf } = require("../understanding/wordRules/index.js");
const { ChatReading } = require("./chatReading.js");

/**
 * Reads a user's turn: its frame (`understanding`, a ChatUnderstanding, which fails open), then what the
 * user tells (an allergy, an age, a trip), the names and IDs they give and a language they ask for,
 * noted in the chat's state before any check, this turn's included. `session` is read live (state).
 */
class ChatReader {
  constructor(session, understanding) {
    this._session = session;
    this._understanding = understanding;
  }

  // Not async: the frame's own step runs the noting, so reading takes no extra step.
  read(said, turn) {
    const text = String(said || "").split(/\s+/).filter(Boolean).join(" ");
    const words = wordsOf(text);
    const aboutCaller = tellsAboutCaller(text);
    return this._understanding.frame(text, (frame) => this._noted(text, words, aboutCaller, frame, turn));
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
