import { CrowkisClient, CrowkisClientOptions } from "./index";

/** A semantic LLM cache for LangChain.js: `new OpenAI({ cache: new CrowkisCache({ tenant }) })`. */
export class CrowkisCache {
  constructor(options?: CrowkisClientOptions & { client?: CrowkisClient; ttl?: number; threshold?: number });
  lookup(prompt: string, llmKey: string): Promise<Array<{ text: string }> | null>;
  update(prompt: string, llmKey: string, value: Array<{ text?: string } | string> | string): Promise<void>;
  clear(): Promise<void>;
}
