"use strict";

/**
 * A user's turn in a chat (`text`), the understanding model's frame of it, and the chat's state so
 * far. `question` is the frame's stand-alone question (null when it gave none).
 */
class ChatTurn {
  constructor(frame, text, state) {
    this.frame = frame;
    this.text = text;
    this.state = state;
  }

  get question() {
    return this.frame.question;
  }
}

module.exports = { ChatTurn };
