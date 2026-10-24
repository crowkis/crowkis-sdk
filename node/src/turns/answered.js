"use strict";

/**
 * A voice turn's answer, as VoiceSession hands it to TurnCore.record(): what the caller said, what the
 * model said, the turn it answers (null or undefined: the latest), whether it was built from a tool's
 * result (`private`), the system prompt the model read, and, once paired, whether decide() let it be
 * shared (`shareable`). Immutable.
 */
class VoiceAnswered {
  constructor(said, modelSaid, turn, isPrivate, instructions, shareable = false) {
    Object.assign(this, { said, modelSaid, turn, private: isPrivate, instructions, shareable });
    Object.freeze(this);
  }

  /** This answer, paired with its turn: `shareable` is what decide() said for that turn. */
  paired(shareable) {
    return new VoiceAnswered(this.said, this.modelSaid, this.turn, this.private, this.instructions, shareable);
  }
}

/**
 * A chat turn's answer, as CallSession hands it to TurnCore.record(): the turn's result, the agent's
 * answer, the places / products / options it named (`mentions`), the task it started collecting
 * details for, and whether the app built it from a tool's result (`private`). Immutable.
 */
class ChatAnswered {
  constructor(result, answer, mentions = [], task = null, isPrivate = false) {
    Object.assign(this, { result, answer, mentions, task, private: isPrivate });
    Object.freeze(this);
  }
}

module.exports = { ChatAnswered, VoiceAnswered };
