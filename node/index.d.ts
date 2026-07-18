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
