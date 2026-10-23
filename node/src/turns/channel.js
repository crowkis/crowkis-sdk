"use strict";

/**
 * What a channel is able to do, as the rules and the turn steps read it (plan §3.3). Rules read
 * these fields and never branch on the channel's name. Immutable. `understandBudgetMs`: how long a
 * plugged-in classifier and rewriter may take on a turn before the word rules read it instead. Today
 * the rules read `spoken` and the factories the budgets; `isolatesContext`, `audio` and `savesAnswers`
 * describe the channel for the merged core (P5).
 */
class Channel {
  constructor({ name, isolatesContext, budgetMs, audio, spoken, savesAnswers, understandBudgetMs = 250 }) {
    Object.assign(this, { name, isolatesContext, budgetMs, audio, spoken, savesAnswers, understandBudgetMs });
    Object.freeze(this);
  }

  /** A channel, or the profile with that name ("voice", "chat", "realtime"). */
  static of(channel) {
    if (channel instanceof Channel) return channel;
    const found = CHANNELS.get(String(channel).trim().toLowerCase());
    if (!found) throw new Error(`channel must be one of ${[...CHANNELS.keys()].sort().join(", ")} or a Channel, got ${channel}`);
    return found;
  }
}

const VOICE = new Channel({ name: "voice", isolatesContext: true, budgetMs: 250, audio: true, spoken: true, savesAnswers: true });
const CHAT = new Channel({ name: "chat", isolatesContext: true, budgetMs: 1000, audio: false, spoken: false, savesAnswers: true });
const REALTIME = new Channel({ name: "realtime", isolatesContext: false, budgetMs: 250, audio: false, spoken: true, savesAnswers: false });

const CHANNELS = new Map([VOICE, CHAT, REALTIME].map((channel) => [channel.name, channel]));

module.exports = { CHANNELS, CHAT, Channel, REALTIME, VOICE };
