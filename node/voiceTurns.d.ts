// Types for @crowkis/client/voiceTurns.
import type { VoiceSession } from "./index";

/** The tool name the basic (no Voice add-on) audio cache is kept under. */
export const TTS_TOOL: "crowkis.tts";

/** [kind, turn, question, messages] of a context sent to the LLM. */
export type AskedContext = [kind: "caller" | "tool", turn: number | null, question: string, messages: unknown[]];

/** An adapter's turn gate: the contexts sent to the LLM, oldest first (or none, for a gate with no queue). */
export interface TurnGate {
  asked?: Array<AskedContext | null>;
  question?: string;
  messages?: unknown[];
}

export interface AnswerReport {
  question: string;
  answer: string;
  messages: unknown[];
  saved: string;
  stored: boolean;
  notStored: string;
}

/** Keeps the spoken audio of a shareable answer, under the TTS run that said it. */
export class AudioClips {
  constructor(session: VoiceSession, sampleRate: number);
  readonly session: VoiceSession;
  readonly sampleRate: number;
  get(text: string): Promise<Buffer | null>;
  expect(text: string, options?: { shareable?: boolean }): void;
  reserve(text?: string | null, options?: { trusted?: boolean }): [string | null, boolean];
  release(slot: [string | null, boolean]): void;
  vouch(text: string): void;
  settle(text: string, shareable: boolean): Promise<void>;
  interrupted(): void;
  ttsStarted(): void;
  ttsText(text: string | null | undefined): void;
  ttsAudio(pcm: Uint8Array): void;
  ttsStopped(): Promise<void>;
}

/** Pairs each model answer with the turn it answers, and reports what happened to it. */
export class AnswerPairing {
  constructor(
    session: VoiceSession,
    gate: TurnGate,
    audio: AudioClips,
    options?: { onAnswer?: ((info: AnswerReport) => unknown) | null },
  );
  responseStart(): Promise<void>;
  responseText(text: string): void;
  speakRequested(text: string): void;
  toolCall(): void;
  toolsDone(): void;
  toolResult(): void;
  interrupted(): void;
  /** [context, answer] to pass to record() once the end of the response is passed on, or null. */
  responseEnd(): Promise<[AskedContext, string] | null>;
  queueContext(messages: unknown[]): boolean;
  callerMovedOn(): Promise<void>;
  settle(answered: boolean): Promise<void>;
  record(context: AskedContext, answer: string): Promise<void>;
}
