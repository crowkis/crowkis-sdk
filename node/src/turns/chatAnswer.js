"use strict";

/**
 * The model's answer to a shared Chat question, as Chat's save rules read it: the answer (`text`:
 * its words, spaces normalised), the shared question's verdict (its question and the attributes in
 * its key), the frame of the turn, the chat's state, and the system prompt the model read, with
 * `promptKey` naming whose prompts it is compared with.
 */
class ChatAnswer {
  constructor(text, verdict, frame, state, { instructions = "", promptKey = null, private: isPrivate = false } = {}) {
    this.text = text;
    // The app built this answer from a tool's result (ChatToolResult keeps it in the chat).
    this.private = isPrivate;
    this.verdict = verdict;
    this.frame = frame;
    this.state = state;
    this.instructions = instructions;
    this.promptKey = promptKey;
  }
}

module.exports = { ChatAnswer };
