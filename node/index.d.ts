export interface CrowkisClientOptions {
  host?: string;
  port?: number;
  tenant?: string;
  model?: string;
  authToken?: string;
  auth_token?: string;
  timeoutMs?: number;
}

export interface CacheSetOptions {
  ttl?: number;
  tenant?: string;
  model?: string;
  modelVersion?: string;
  model_version?: string;
  image?: string | Buffer | Uint8Array;
  template?: boolean;
}

export interface CacheGetOptions {
  threshold?: number;
  tenant?: string;
  model?: string;
  modelVersion?: string;
  model_version?: string;
  migrationMode?: "miss" | "refresh" | "recompute" | "force_miss" | "force-miss" | string;
  migration_mode?: "miss" | "refresh" | "recompute" | "force_miss" | "force-miss" | string;
  image?: string | Buffer | Uint8Array;
  template?: boolean;
}

export interface StreamCacheOptions extends CacheGetOptions, CacheSetOptions {
  chunkTokens?: number;
  delayMs?: number;
}

export interface CacheHit {
  response: Buffer;
  text: string;
  similarity: number;
  ttlRemaining: number;
  matchedKey: Buffer;
  confidence: number;
  hitType: string;
  migrationPending: boolean;
  migrationFromModelVersion: string | null;
  migrationTargetModelVersion: string | null;
  migrationCanaryId: string | null;
  migrationPlannedAt: number | null;
}

export interface SimResult {
  key: Buffer;
  similarity: number;
}

export class CrowkisClient {
  constructor(options?: CrowkisClientOptions);
  connect(): Promise<void>;
  close(): void;
  execute(...args: Array<string | Buffer | Uint8Array>): Promise<unknown>;
  ping(): Promise<boolean>;
  get(key: string | Buffer | Uint8Array): Promise<Buffer | null>;
  set(key: string | Buffer | Uint8Array, value: string | Buffer | Uint8Array, options?: { ttl?: number }): Promise<void>;
  cset(query: string | Buffer | Uint8Array, response: string | Buffer | Uint8Array, options?: CacheSetOptions): Promise<void>;
  cget(query: string | Buffer | Uint8Array, options?: CacheGetOptions): Promise<Buffer | null>;
  cgetHit(query: string | Buffer | Uint8Array, options?: CacheGetOptions): Promise<CacheHit | null>;
  cimgget(image: string | Buffer | Uint8Array, options?: CacheGetOptions): Promise<Buffer | null>;
  csim(query: string | Buffer | Uint8Array, options?: { k?: number; tenant?: string }): Promise<SimResult[]>;
  cflush(options?: { tenant?: string }): Promise<number>;
  cvecCount(): Promise<number>;
  getOrCompute(
    query: string,
    fn: (query: string) => Promise<string | Buffer | Uint8Array> | string | Buffer | Uint8Array,
    options?: CacheGetOptions & CacheSetOptions,
  ): Promise<string>;
  streamGetOrCompute(
    query: string,
    fn: (
      query: string,
    ) =>
      | AsyncIterable<string | Buffer | Uint8Array>
      | Iterable<string | Buffer | Uint8Array>
      | Promise<AsyncIterable<string | Buffer | Uint8Array> | Iterable<string | Buffer | Uint8Array>>
      | string
      | Buffer
      | Uint8Array,
    options?: StreamCacheOptions,
  ): AsyncIterable<string | Buffer | Uint8Array>;
}

export interface CrowkisAdminOptions {
  baseUrl?: string;
  adminKey?: string;
  timeoutMs?: number;
}

export class CrowkisAdmin {
  constructor(options?: CrowkisAdminOptions);
  health(): Promise<Record<string, unknown>>;
  getStats(): Promise<Record<string, unknown>>;
  updateThreshold(config: Record<string, unknown>): Promise<Record<string, unknown>>;
  registerWebhook(webhook: Record<string, unknown>): Promise<Record<string, unknown>>;
  invalidateSource(sourceId: string, extra?: Record<string, unknown>): Promise<Record<string, unknown>>;
  flushTenant(tenantId: string): Promise<Record<string, unknown>>;
  cacheEntries(options?: { tenant?: string; limit?: number }): Promise<Record<string, unknown>>;
  migrationProgress(options?: {
    tenant?: string;
    canaryId?: string;
    canary_id?: string;
    fromModelVersion?: string;
    from_model_version?: string;
    targetModelVersion?: string;
    target_model_version?: string;
    limit?: number;
  }): Promise<Record<string, unknown>>;
  canaryMigrationProgress(id: string, options?: { tenant?: string; limit?: number }): Promise<Record<string, unknown>>;
  leaseMigrationWork(options?: Record<string, unknown>): Promise<Record<string, unknown>>;
  leaseCanaryMigrationWork(id: string, options?: Record<string, unknown>): Promise<Record<string, unknown>>;
  completeMigrationWork(item: Record<string, unknown>): Promise<Record<string, unknown>>;
  failMigrationWork(item: Record<string, unknown>): Promise<Record<string, unknown>>;
}

export class CrowkisError extends Error {}

export interface CrowkisGrpcClientOptions {
  target?: string;
  authToken?: string;
  protoPath?: string;
  credentials?: unknown;
}

export class CrowkisGrpcClient {
  constructor(options?: CrowkisGrpcClientOptions);
  get(query: string | Buffer | Uint8Array, options?: CacheGetOptions & StreamCacheOptions): Promise<Record<string, unknown>>;
  set(query: string | Buffer | Uint8Array, response: string | Buffer | Uint8Array, options?: CacheSetOptions & { ttlSecs?: number }): Promise<Record<string, unknown>>;
  getStream(query: string | Buffer | Uint8Array, options?: StreamCacheOptions): AsyncIterable<Record<string, unknown>>;
  stats(): Promise<Record<string, unknown>>;
  invalidate(options?: { tenant?: string }): Promise<Record<string, unknown>>;
  close(): void;
}

export function loadCrowkisGrpc(options?: { protoPath?: string }): unknown;

export type Synthesise = (
  text: string,
) => Buffer | Uint8Array | Promise<Buffer | Uint8Array>;

export interface AgentOptions {
  client?: CrowkisClient;
  host?: string;
  port?: number;
  tenant?: string;
  authToken?: string;
  sharesWith?: string[];
}

export interface AskOptions {
  serveAbove?: number;
  cheapAbove?: number;
  template?: boolean;
  threshold?: number;
}

export interface AskResult {
  route: "cache" | "cheap" | "expensive";
  answer: string | null;
  context?: string;
  confidence: number;
  similarity: number;
}

export interface RouteStats {
  asked: number;
  cache: number;
  cheap: number;
  expensive: number;
  servedWithoutAModelPct: number;
}

export interface ToolStats {
  calls: number;
  cached: number;
  executed: number;
  avoidedPct: number;
}

export interface AudioStats {
  spoken: number;
  fromCache: number;
  synthesised: number;
  ttsAvoidedPct: number;
}

export type CachedTool<F extends (...args: never[]) => unknown> = ((
  ...args: Parameters<F>
) => Promise<Awaited<ReturnType<F>>>) & { crowkisToolName: string };

export class Agent {
  constructor(agentId: string, options?: AgentOptions);
  readonly agentId: string;
  readonly tenant?: string;
  readonly sharesWith: string[];
  readonly client: CrowkisClient;
  routeCounts: { cache: number; cheap: number; expensive: number };
  audioHits: number;
  audioMisses: number;
  toolHits: number;
  toolMisses: number;
  remember(fact: string, options?: { ttl?: number }): Promise<unknown>;
  recall(query: string, options?: { includeShared?: boolean }): Promise<unknown[]>;
  history(query?: string): Promise<unknown>;
  forget(options?: { query?: string; user?: string; threshold?: number }): Promise<unknown>;
  link(other: Agent | string, relation: string, object?: string): Promise<unknown>;
  graph(entity?: string): Promise<unknown>;
  tool<F extends (...args: never[]) => unknown>(
    fn: F,
    options?: { ttl?: number; name?: string },
  ): CachedTool<F>;
  toolStats(): ToolStats;
  ask(query: string, options?: AskOptions): Promise<AskResult>;
  speak(
    text: string,
    synthesise: Synthesise,
    options: { voice: string; ttl?: number },
  ): Promise<Buffer>;
  audioStats(): AudioStats;
  learn(
    query: string,
    answer: string,
    options?: { ttl?: number; template?: boolean },
  ): Promise<void>;
  routeStats(): RouteStats;
  close(): Promise<void>;
}

export type TurnAction = "serve" | "filler" | "infer";

export interface TurnDecisionOptions {
  text?: string | null;
  audio?: Buffer | null;
  confidence?: number;
  reason?: string;
}

export class TurnDecision {
  constructor(action: TurnAction, options?: TurnDecisionOptions);
  readonly action: TurnAction;
  readonly text: string | null;
  readonly audio: Buffer | null;
  readonly confidence: number;
  readonly reason: string;
  /** For a model turn: the messages the model must read. null means the whole call. */
  messages: TranscriptTurn[] | null;
  /** Whether the model's answer to this turn is shared with later callers. */
  cacheable: boolean;
  readonly servedFromCache: boolean;
  readonly servedFromFiller: boolean;
  readonly needsModel: boolean;
  toString(): string;
}

export interface TranscriptTurn {
  role: "user" | "assistant";
  content: string;
}

/** A message handed to the model by `VoiceSession.answer`. */
export interface ModelMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

/** The app's model: reads exactly the messages Crowkis chose, returns its answer. */
export type ModelCall = (messages: ModelMessage[]) => string | Promise<string>;

export interface VoiceValues {
  [slot: string]: string | number | null | undefined;
}

/** What a Conversation decided to do with one turn. */
export type TurnPlanAction = "filler" | "lookup" | "model";

export interface TurnPlan {
  readonly said: string;
  readonly action: TurnPlanAction;
  /** filler | lookup | empty | short | personal_no_values | no_prior_turn | unplanned */
  readonly reason: string;
  /** Cache key for both the lookup and the save; null when none can be built. */
  readonly key: string | null;
  readonly personal: boolean;
  /** Look up / save an answer shape filled with this conversation's values. */
  readonly template: boolean;
  /** Near-exact bar for a turn that only means something after the previous one. */
  readonly threshold: number | null;
  /** What the model reads on a miss; null means the whole conversation. */
  readonly messages: TranscriptTurn[] | null;
  /** Whether the model's answer may be shared with later callers. */
  readonly shareable: boolean;
  readonly filler: string | null;
  readonly modelSees: "question" | "question + previous" | "whole conversation";
}

export type SavingOutcome =
  | "saved" | "template" | "kept" | "private" | "non_answer" | "interrupted" | "not_saved";

export interface Saving {
  readonly outcome: SavingOutcome;
  readonly key: string | null;
  readonly text: string | null;
  readonly template: boolean;
  /** Whether the app should write `text` under `key` now. */
  readonly write: boolean;
}

export interface ConversationOptions {
  minWords?: number;
  values?: VoiceValues;
  fillers?: Record<string, string>;
  /** Caller turns of history a whole-conversation model call carries; null keeps all. */
  maxTurns?: number | null;
}

/**
 * One call's or chat thread's cache decisions, with no I/O: what to look up, what the
 * model reads, what may be saved. VoiceSession uses it; a chat backend can drive it
 * with its own client and storage format.
 */
export class Conversation {
  constructor(options?: ConversationOptions);
  readonly minWords: number;
  readonly maxTurns: number | null;
  readonly values: Record<string, string>;
  readonly transcript: TranscriptTurn[];
  setValues(values: VoiceValues): void;
  registerFiller(trigger: string, response: string): void;
  registerFillers(pairs: Record<string, string>): void;
  /** Decide what to do with what the caller just said. Opens the turn. */
  plan(said: string): TurnPlan;
  /** A plan for an answer with no decision behind it: never shared. */
  unplanned(said: string): TurnPlan;
  /** The cache answered: what to say, or null when a shape has an unfillable slot. */
  served(plan: TurnPlan, cached: string): string | null;
  /** Exactly what the model must read for this turn, `system` first. */
  modelMessages(plan: TurnPlan, system?: string | null): ModelMessage[];
  /** The model answered: remember the turn, decide what may be saved. */
  settle(plan: TurnPlan, answer: string): Saving;
  /** Remember a turn that is never cached; false when the turn was cancelled. */
  keepPrivate(said: string, answer: string): boolean;
  /** Abandon the open turn (barge-in): no trace, nothing saved. */
  cancel(): boolean;
}

/** Whether a turn is about the caller (records, who they are, what suits them): never shared. */
export function isPersonal(text: string): boolean;
/** Whether a turn only means something after the previous one ("how long does it take?"). */
export function isContextDependent(text: string): boolean;
/** Whether a model answer does not answer (only questions, or leads with "I'm not sure"). */
export function isNonAnswer(answer: string): boolean;

export interface VoiceSessionOptions {
  voice: string;
  serveAbove?: number;
  minWords?: number;
  synthesise?: Synthesise;
  ttl?: number;
  latencyBudgetMs?: number;
  fillers?: Record<string, string>;
  values?: VoiceValues;
  /** Caller turns of history a whole-call model turn carries; null keeps all. */
  maxTurns?: number | null;
}

export interface VoiceStats {
  turns: number;
  servedFromCache: number;
  answeredByFiller: number;
  modelCalls: number;
  refusedTooShort: number;
  refusedToShareAPrivateAnswer: number;
  uncacheablePersonal: number;
  missedLatencyBudget: number;
  bargeIns: number;
  /** Lookups that failed (cache down or refusing); each went to the model. */
  cacheUnavailable: number;
  /** Model answers that could not be cached (refused write); the call went on. */
  failedWrites: number;
  /** Shareable-looking model answers that were kept to this call (a declared value in them, or a private turn). */
  notShareable: number;
  /** Model answers that did not answer (a question back, "I'm not sure", a refusal): spoken, never saved. */
  nonAnswersNotSaved: number;
  cacheHitPct: number;
  fillerHitPct: number;
  modelCallsAvoidedPct: number;
}

export class VoiceSession {
  constructor(agent: Agent, options: VoiceSessionOptions);
  readonly agent: Agent;
  readonly voice: string;
  readonly serveAbove: number;
  readonly minWords: number;
  readonly synthesise?: Synthesise;
  readonly ttl?: number;
  readonly latencyBudgetMs?: number;
  readonly values: Record<string, string>;
  readonly transcript: TranscriptTurn[];
  /** The decisions behind every turn of this call. */
  readonly conversation: Conversation;
  served: number;
  inferred: number;
  filled: number;
  refusedShort: number;
  refusedPrivate: number;
  uncacheablePersonal: number;
  overBudget: number;
  bargeIns: number;
  setValues(values: VoiceValues): void;
  registerFiller(trigger: string, response: string): void;
  registerFillers(pairs: Record<string, string>): void;
  decide(callerSaid: string): Promise<TurnDecision>;
  cancel(): boolean;
  /**
   * One caller turn end to end: answered from the cache, or by `llm` reading exactly
   * the messages Crowkis chose, then remembered. `text` on the result is what to speak.
   */
  answer(callerSaid: string, llm: ModelCall, options?: { system?: string }): Promise<TurnDecision>;
  /** Keep a turn in the transcript, never cached: for a model that holds the whole call itself. */
  recordPrivateTurn(callerSaid: string, modelSaid: string): void;
  injections(): TranscriptTurn[];
  stats(): VoiceStats;
}

/**
 * Names of the three events this realtime provider uses. They are data, not
 * constants: a wrong name means the gate never fires and every turn is billed.
 */
export interface RealtimeAdapterOptions {
  /** Server event announcing a finished transcript of the caller's speech. */
  transcriptEvent: string;
  /** Field holding the transcript text; a dotted path walks nested objects. */
  transcriptField: string;
  /** Client event that appends a conversation item without running inference. */
  injectEvent: string;
  /** Client event that asks the provider to answer. Never sent on a hit. */
  respondEvent: string;
  /** Field naming the speaker on an injected item. Defaults to "role". */
  roleField?: string;
  /** Field carrying the text on an injected item. Defaults to "text". */
  textField?: string;
  /**
   * Full inject message with "{role}" and "{text}" placeholders at any depth,
   * for providers that nest the text (e.g. item.content[] or turns[].parts[]).
   */
  injectTemplate?: Record<string, unknown> | null;
  /** Full respond message; "{text}" receives the caller's words. */
  respondTemplate?: Record<string, unknown> | null;
  /** The provider's name for the model's turns. Defaults to "assistant". */
  assistantRole?: string;
  /**
   * false when the provider already holds the caller's turn (server-side voice
   * activity detection commits the audio as an item). Defaults to true.
   */
  injectUser?: boolean;
}

export interface RealtimeInjectEvent {
  [field: string]: unknown;
}

export interface RealtimeRespondEvent {
  [field: string]: unknown;
}

export type RealtimeClientEvent = RealtimeInjectEvent | RealtimeRespondEvent;

export class RealtimeAdapter {
  constructor(options: RealtimeAdapterOptions);
  readonly transcriptEvent: string;
  readonly transcriptField: string;
  readonly injectEvent: string;
  readonly respondEvent: string;
  readonly roleField: string;
  readonly textField: string;
  readonly transcriptPath: string[];
  isTranscript(event: unknown): boolean;
  transcriptOf(event: unknown): string | null;
  inject(role: string, text: string): RealtimeInjectEvent;
  respond(): RealtimeRespondEvent;
  toString(): string;
}

export interface RealtimeStats {
  /** Every event handed to the gate, transcript or not. */
  events: number;
  /** Events that carried a non-blank transcript and reached the cache. */
  transcripts: number;
  /** Turns answered from cache or by a filler. */
  served: number;
  /** Turns sent on to the provider with a respond event. */
  forwarded: number;
  /** Inferences avoided. One suppressed respond event is one turn not billed. */
  suppressed: number;
}

export interface RealtimeTurnSource {
  decide(callerSaid: string): TurnDecision | Promise<TurnDecision>;
}

export class RealtimeGate {
  constructor(session: VoiceSession | RealtimeTurnSource, adapter: RealtimeAdapter);
  readonly session: VoiceSession | RealtimeTurnSource;
  readonly adapter: RealtimeAdapter;
  eventsSeen: number;
  transcripts: number;
  served: number;
  forwarded: number;
  suppressed: number;
  /** The decision for the last served turn, or null. Cleared by the next turn or takePendingAudio(). */
  pendingDecision: TurnDecision | null;
  /** Cached audio for the last served turn, or null. Kept until taken or the next turn. */
  readonly pendingAudio: Buffer | null;
  /**
   * The cached answer's audio for the app to play, handed over once. The
   * provider is never asked to speak it (that would be a billed inference);
   * stop playback yourself on barge-in.
   */
  takePendingAudio(): Buffer | null;
  /**
   * Never throws and never rejects: a malformed event, or a session that
   * raises, forwards the turn instead of killing the call.
   */
  handle(event: unknown): Promise<RealtimeClientEvent[]>;
  stats(): RealtimeStats;
  toString(): string;
}

// --- Turn understanding v2.2 (CallSession) ---------------------------------------------

export type TurnKind = "general" | "personal" | "live" | "action" | "dialogue" | "chitchat" | "sensitive" | "unclear";
export type Route = "urgent" | "task" | "shared" | "personal" | "tools" | "agent" | "filler";
export type QuestionType = "policy" | "how_to" | "product_fact" | "place_fact" | "search" | "other";

export class Entity {
  text: string;
  type: string;
  identifying: boolean;
  answerRelevant: boolean;
  static fromDict(data: Record<string, unknown>): Entity;
}

export class Attribute {
  value: string;
  normalised: string;
  changesAnswer: boolean;
  static fromDict(data: unknown): Attribute | null;
}

/** What turn understanding says about one caller turn. Parsing is fail-closed. */
export class TurnFrame {
  kind: TurnKind;
  urgent: boolean;
  subject: "none" | "self" | "other";
  taskStep: boolean;
  confidence: number;
  abstain: boolean;
  entities: Entity[];
  attributes: Record<string, Attribute>;
  usesState: boolean;
  question: string | null;
  questionType: QuestionType;
  static fromDict(data: unknown): TurnFrame;
  readonly identifyingTexts: string[];
  readonly details: Entity[];
  readonly memorable: Entity[];
  readonly isPureAcknowledgement: boolean;
}

/** Per-call memory as structure, not transcript. */
export class CallState {
  activeQuestion: string | null;
  activeKind: string | null;
  facts: string[];
  agentMentions: string[];
  task: "none" | "searching" | "booking" | "ordering" | "account_action";
  attributes: Record<string, Attribute>;
  subjectFocus: string;
  identity: "anonymous" | "identified" | "verified";
  lastReply: string;
  noteAgentReply(text: string, mentions?: string[], task?: string | null): void;
  startTask(task: string): void;
  endTask(): void;
  setIdentity(identity: "anonymous" | "identified" | "verified"): void;
  apply(frame: TurnFrame, options: { shared: boolean }): void;
  snapshot(): Record<string, unknown>;
  groundingSources(): string[];
  clone(): CallState;
}

export class Verdict {
  shared: boolean;
  route: Route;
  reasons: string[];
  question: string | null;
  attributes: Record<string, string>;
  key: string | null;
  ttl: number | null;
}

export interface RuleCheckerOptions {
  /** Calibrate per business on real calls. Default 0.6. */
  confidenceFloor?: number;
  /** Expiry per question type in seconds; null = until the knowledge version changes. */
  ttl?: Partial<Record<QuestionType, number | null>>;
  /** Bump when policies or prices change: every old key retires at once. */
  knowledgeVersion?: string;
}

/** The fixed sharing rules (V1-V9) and the key builder. */
export class RuleChecker {
  constructor(options?: RuleCheckerOptions);
  check(frame: TurnFrame, turn: string, state: CallState): Verdict;
  buildKey(question: string, attrs: Record<string, string>): string;
}

export interface Understander {
  understand(turn: string, state: CallState): TurnFrame | Promise<TurnFrame>;
}

/** Exact repeats of already-verified questions only: the safe fallback with no model. */
export class ReplayUnderstander implements Understander {
  constructor(known?: Record<string, QuestionType | string>);
  remember(turn: string, question: string, questionType?: string): void;
  understand(turn: string, state?: CallState): TurnFrame;
  readonly size: number;
}

export type ChatMessage = { role: string; content: string };

/** Interim understander over the app's own LLM (adds one model call per turn). */
export class LLMUnderstander implements Understander {
  constructor(complete: (messages: ChatMessage[]) => string | Promise<string>, options?: { business?: string });
  messages(turn: string, state: CallState): ChatMessage[];
  understand(turn: string, state: CallState): Promise<TurnFrame>;
}

export class WithFallback implements Understander {
  constructor(primary: Understander, fallback: Understander);
  primaryFailures: number;
  understand(turn: string, state: CallState): Promise<TurnFrame>;
}

export class TurnResult {
  turnId: number;
  route: Route;
  /** What to say now (cache hit or filler), else null. */
  text: string | null;
  needsModel: boolean;
  /** Exactly what the model reads; null = the whole call. */
  messages: ChatMessage[] | null;
  frame: TurnFrame | null;
  verdict: Verdict | null;
  reason: string;
  readonly servedFromCache: boolean;
}

export interface CallSessionOptions {
  checker?: RuleChecker;
  onUrgent?: (turn: string, frame: TurnFrame) => void | Promise<void>;
  replay?: ReplayUnderstander;
  serveAbove?: number;
  /** Hard limit on the cache lookup (ms). Default 300. */
  latencyBudgetMs?: number | null;
  /** Hard limit on understanding (ms); past it the safe fallback or the agent decides. Default 250. */
  understandBudgetMs?: number | null;
  fillers?: Record<string, string>;
  /** "full" (default), "replay_only" (no model) or "off" (share nothing). */
  mode?: "full" | "replay_only" | "off";
  /** Monitoring: routes, reasons, de-identified keys; never the caller's raw words. */
  onEvent?: (event: Record<string, unknown>) => void;
}

/** One call or chat thread on turn understanding v2.2. */
export class CallSession {
  constructor(agent: Agent, understander: Understander, options?: CallSessionOptions);
  state: CallState;
  handle(turn: string): Promise<TurnResult>;
  recordAnswer(result: TurnResult, answer: string, options?: { mentions?: string[]; task?: string | null }): Promise<string>;
  cancel(): boolean;
  setMode(mode: "full" | "replay_only" | "off"): void;
  registerShape(field: string, template: string, options?: { requires?: "anonymous" | "identified" | "verified" }): void;
  phrase(field: string, value: unknown, options?: { subject?: string }): string | null;
  saveCheck(answer: string, verdict: Verdict, frame?: TurnFrame | null): string | null;
  stats(): Record<string, number>;
}

export interface BridgeDecision {
  action: "play_audio" | "speak_text" | "model";
  text?: string;
  audio?: Buffer;
  messages?: Array<Record<string, unknown>>;
  tools?: unknown;
  result?: TurnResult;
}

/** Framework-free voice-pipeline logic for CallSession (audio cached only for shared answers). */
export class CallBridge {
  constructor(session: CallSession, options: { voice: string; sampleRate: number; audioFormat?: string; audioBudgetMs?: number; audioTtl?: number });
  onContext(messages: Array<Record<string, unknown>>, tools?: unknown): Promise<BridgeDecision>;
  onAnswer(text: string, options?: { mentions?: string[]; task?: string | null }): Promise<string>;
  onTtsAudio(pcm: Buffer | Uint8Array): void;
  onBotStopped(): Promise<boolean>;
  onInterruption(): void;
}
