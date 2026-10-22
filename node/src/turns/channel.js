"use strict";

/**
 * What a channel is able to do, as the rules and the turn steps read it (plan §3.3). Rules read
 * these fields and never branch on the channel's name. Immutable.
 */
class Channel {
  constructor({ name, isolatesContext, budgetMs, audio, spoken, savesAnswers }) {
    Object.assign(this, { name, isolatesContext, budgetMs, audio, spoken, savesAnswers });
    Object.freeze(this);
  }
}

const VOICE = new Channel({ name: "voice", isolatesContext: true, budgetMs: 250, audio: true, spoken: true, savesAnswers: true });
const CHAT = new Channel({ name: "chat", isolatesContext: true, budgetMs: 1000, audio: false, spoken: false, savesAnswers: true });
const REALTIME = new Channel({ name: "realtime", isolatesContext: false, budgetMs: 250, audio: false, spoken: true, savesAnswers: false });

module.exports = { CHAT, Channel, REALTIME, VOICE };
