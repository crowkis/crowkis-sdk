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
  /** True when the server's decision engine judged this answer. */
  judged: boolean;
  /** The engine was sure the answer is not personal and stands on its own. */
  vouched: boolean;
  /** How long the answer was judged to stay correct; null when it was not judged. */
  lifetime: string | null;
  /** The answer commits the business (a price, a refund, a policy). */
  commitment: boolean;
}

/** What the server's decision engine concluded about a question. */
export interface DecisionView {
  /** False when the server has no decision engine configured. */
  engine: boolean;
  cached: boolean;
  judged: boolean;
  /** Stored but not served yet: it is waiting to be judged. */
  pending: boolean;
  /** The engine was sure the stored answer may be shared. */
  vouched: boolean;
  commitment: boolean;
  lifetime?: string;
  ttl?: number;
  /**
   * Why an answer to this question was removed, while that is remembered:
   * "never", "personal", "context", "unsure" or "unrelated".
   */
  removed?: string;
  removed_at?: number;
}

/** What a notice had done to the cache by the time the server replied. */
export interface NoticeOutcome {
  id: string;
  /** Cached answers near enough to the notice to be looked at. */
  checked: number;
  /** Of those, the ones a server with no decision engine removes. */
  matched: number;
  /** Removed before the reply: only on a server with no decision engine. */
  removed: number;
  /**
   * Not served from the reply on. The engine's model removes the ones the
   * notice makes wrong and puts the rest back, usually within seconds.
   */
  checking: number;
  /** More answers were near the notice than are looked at in one go. */
  truncated: boolean;
  preview: boolean;
  until?: number;
}

export interface Notice {
  id: string;
  text: string;
  until: number;
}

export interface NoticeOptions {
  /** Seconds the notice stays active. */
  lasts?: number;
  /** Report what would be removed without removing it. */
  preview?: boolean;
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
  cdecision(query: string | Buffer | Uint8Array, options?: { tenant?: string }): Promise<DecisionView>;
  cnoticeAdd(text: string, options?: NoticeOptions & { tenant?: string }): Promise<NoticeOutcome>;
  cnoticeList(options?: { tenant?: string }): Promise<Notice[]>;
  cnoticeClear(noticeId: string, options?: { tenant?: string }): Promise<boolean>;
  /** Zero a tenant's spend counters (limits stay); replies with the budget snapshot. */
  cbudgetReset(tenant?: string): Promise<Record<string, unknown>>;
  /** Storage-engine counters; `{}` if the reply is not a map. */
  stats(): Promise<Record<string, number>>;
  /** Remove expired keys now; the number removed. */
  sweep(): Promise<number>;
  /** TENANT is sent only when passed, as cpromptSet/cpromptGet send none. */
  cpromptDel(name: string, options?: { tenant?: string }): Promise<boolean>;
  cpromptRollback(name: string, version: number, options?: { tenant?: string }): Promise<number>;
  cpromptRender(
    name: string,
    options?: { version?: number; vars?: Record<string, string | number>; tenant?: string },
  ): Promise<Buffer | null>;
  cpromptAb(name: string, options?: { subject?: string; tenant?: string }): Promise<{ version: number; template: Buffer } | null>;
  /** `{ version: weight }`; null or `{}` clears the split. */
  cpromptAbset(name: string, weights?: Record<number, number> | null, options?: { tenant?: string }): Promise<boolean>;
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
  /** A user's API key. Reading needs none on a node with no users. */
  apiKey?: string;
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
  /** The same question, not merely a similar one. */
  exact: boolean;
  /** What the server's decision engine recorded; null / false without one. */
  vouched: boolean;
  lifetime: string | null;
  commitment: boolean;
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
  /** Whether the server judges what it caches. Remembered for a few minutes; any failure is false. */
  decides(): Promise<boolean>;
  /** What the cache decided about a question. */
  explain(query: string): Promise<DecisionView>;
  /** Tell the cache something changed; cached answers it makes wrong are removed. */
  announce(notice: string, options?: NoticeOptions): Promise<NoticeOutcome>;
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
  /** Which turn of the call this is; an answer recorded for an older turn is dropped. */
  turn: number;
  /** After `answer()`: whether the model's answer was stored. */
  stored: boolean;
  /** After `answer()`: why the answer was not stored ("" when it was), e.g. the server's reason for refusing the write. */
  notStored: string;
  readonly servedFromCache: boolean;
  readonly servedFromFiller: boolean;
  readonly needsModel: boolean;
  /** After `answer()`: the model was asked and said nothing (action stays "infer"); retry, or speak a fallback. */
  readonly empty: boolean;
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

/**
 * How a cached answer that commits the business may be spoken: always, only
 * when the caller asked the same question, or never.
 */
export type Commitments = "serve" | "exact" | "never";

export interface VoiceSessionOptions {
  voice: string;
  serveAbove?: number;
  minWords?: number;
  synthesise?: Synthesise;
  ttl?: number;
  latencyBudgetMs?: number;
  fillers?: Record<string, string>;
  values?: VoiceValues;
  /** Defaults to "exact". Only matters when the server's decision engine flags a commitment. */
  commitments?: Commitments;
  /**
   * Answer turns shorter than `minWords` ("thank you") from cache when the
   * server's decision engine has vouched for the exact answer. Off by default.
   */
  shortTurns?: boolean;
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
  /** Cached commitments the `commitments` option did not allow speaking. */
  commitmentsSentToModel: number;
  /** Cached answers written for a screen (a link, code or markup), not spoken. */
  unspeakableAnswers: number;
  /** Model answers that were empty: never stored, reported as `decision.empty`. */
  emptyAnswers: number;
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
  readonly commitments: Commitments;
  readonly values: Record<string, string>;
  readonly transcript: TranscriptTurn[];
  served: number;
  inferred: number;
  filled: number;
  refusedShort: number;
  refusedPrivate: number;
  uncacheablePersonal: number;
  overBudget: number;
  bargeIns: number;
  emptyAnswers: number;
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

/** One past turn: what the caller said, then what the agent answered. */
export type PastTurn = readonly [callerSaid: string, agentSaid: string];

export interface WarmStartTotals {
  calls: number;
  turns: number;
  /** Answers not shared: personal, or repeating what that caller said. */
  keptPrivate: number;
  failedWrites: number;
  /** Stopped early: three calls in a row were not judged in time. */
  stalled: boolean;
}

/**
 * Fill the cache from past calls under the same rules as a live call. Nothing
 * is spoken or synthesised. Throws unless the server's decision engine is on
 * and holds answers until it has judged them. `wait` is the seconds the engine
 * is given to catch up after each call (default 30).
 */
export function warmFromCalls(
  agent: Agent,
  calls: Iterable<Iterable<PastTurn>>,
  options?: { wait?: number },
): Promise<WarmStartTotals>;

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
