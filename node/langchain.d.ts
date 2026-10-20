// Types for @crowkis/client/langchain.
import type { CrowkisClient, CrowkisClientOptions } from "./index";

export interface CrowkisCacheOptions extends CrowkisClientOptions {
  /** A client to use; left out, one is built from the other options (and the environment). */
  client?: CrowkisClient;
  /** Seconds to keep a cached generation. */
  ttl?: number;
  /** Similarity a prompt needs to reuse a generation. */
  threshold?: number;
}

/** A LangChain.js cache that matches prompts on meaning (duck-typed: lookup / update / clear). */
export class CrowkisCache {
  constructor(options?: CrowkisCacheOptions);
  readonly client: CrowkisClient;
  ttl?: number;
  threshold?: number;
  lookup(prompt: string, llmKey: string): Promise<{ text: string }[] | null>;
  update(prompt: string, llmKey: string, value: Array<{ text?: string } | string> | string): Promise<void>;
  clear(): Promise<void>;
}
