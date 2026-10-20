// Types for @crowkis/client/memory.
import type { CrowkisClient, CrowkisClientOptions } from "./index";

export interface CrowkisMemoryOptions extends CrowkisClientOptions {
  /** A client to use; left out, one is built from the other options (and the environment). */
  client?: CrowkisClient;
  /** Keep memories per user of this agent. */
  user?: string;
}

/** Long-term agent memory backed by Crowkis, for LangGraph.js or any agent loop. */
export class CrowkisMemory {
  constructor(agent: string, options?: CrowkisMemoryOptions);
  readonly agent: string;
  readonly user?: string;
  readonly client: CrowkisClient;
  remember(fact: string, options?: { ttl?: number }): Promise<unknown>;
  recall(query: string, options?: { k?: number }): Promise<unknown>;
  extract(conversation: unknown, options?: { ttl?: number }): Promise<unknown>;
  history(query?: string, options?: { k?: number }): Promise<unknown>;
  forget(options?: { query?: string; threshold?: number }): Promise<unknown>;
  link(subject: string, relation: string, object?: string): Promise<unknown>;
  graph(entity?: string, options?: { depth?: number }): Promise<unknown>;
}
