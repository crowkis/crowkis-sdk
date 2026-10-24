"use strict";

/**
 * One chat turn as read (the understanding model's frame), then as checked: the user's words (`text`,
 * spaces normalised), the frame read from them, the names given in the turn, whether it tells
 * something about the user (`aboutCaller`), the turn's number (`turnId`), and, once checked, the rule
 * checker's `verdict` (route, reasons, and for a shared question its key and segment). Immutable.
 */
class ChatReading {
  constructor(text, { frame = null, names = [], aboutCaller = false, turnId = 0, verdict = null } = {}) {
    Object.assign(this, { text, frame, names, aboutCaller, turnId, verdict });
    Object.freeze(this);
  }

  /** This reading with the check's verdict. */
  checkedAs(verdict) {
    const { frame, names, aboutCaller, turnId } = this;
    return new ChatReading(this.text, { frame, names, aboutCaller, turnId, verdict });
  }

  /** The shared question's key. */
  get key() {
    return this.verdict.key;
  }

  /** The shared question's segment, sent only when there is one (as Chat always did). */
  get lookupOptions() {
    return this.verdict.segment ? { segment: this.verdict.segment } : {};
  }
}

module.exports = { ChatReading };
