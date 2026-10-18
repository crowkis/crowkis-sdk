import { CrowkisClient, CrowkisClientOptions } from "./index";

/** Durable, semantic, per-user agent memory. Every recall is scoped to its agent and user. */
export class CrowkisMemory {
  constructor(agent: string, options?: CrowkisClientOptions & { user?: string; client?: CrowkisClient });
  readonly agent: string;
  readonly user?: string;
  readonly client: CrowkisClient;
  remember(fact: string, options?: { ttl?: number }): Promise<unknown>;
  recall(query: string, options?: { k?: number }): Promise<unknown>;
  extract(conversation: string, options?: { ttl?: number }): Promise<unknown>;
  history(query: string, options?: { k?: number }): Promise<unknown>;
  forget(options?: { query?: string; threshold?: number }): Promise<unknown>;
  link(subject: string, relation: string, object: string): Promise<unknown>;
  graph(entity: string, options?: { depth?: number }): Promise<unknown>;
}
