// Types for @crowkis/client/livekit.
import type { VoiceSession, VoiceSessionFactoryOptions } from "./index";

export interface WithCrowkisOptions {
  /** The Crowkis session to use; left out, voiceSession(options) is made on first use. */
  crowkis?: VoiceSession | null;
  /** Options for voiceSession() when no `crowkis` is given. */
  options?: VoiceSessionFactoryOptions;
}

/**
 * Crowkis in a LiveKit Agents (Node) agent: wraps its llmNode and ttsNode and returns the
 * same agent, with `agent.crowkis` the session. Needs @livekit/agents 1.x.
 */
export function withCrowkis<A extends { llmNode: unknown; ttsNode: unknown }>(
  agent: A,
  options?: WithCrowkisOptions,
): A & { readonly crowkis: VoiceSession };
