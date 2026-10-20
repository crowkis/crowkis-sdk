// Type-checks the README's examples against index.d.ts: `npm run typecheck`.
import { Agent, Chat, ChatReply, Crowkis, CrowkisClient, LLMUnderstander, MemoryStore } from "@crowkis/client";
import { CrowkisMemory } from "@crowkis/client/memory";
import { CrowkisCache } from "@crowkis/client/langchain";

declare function myModel(prompt: string): Promise<string>;
declare function complete(messages: Array<{ role: string; content: string }>): Promise<string>;

async function readme(): Promise<void> {
  const cache = new Crowkis({ tenant: "my-app" });
  const answer = cache.cached(async (prompt: string) => myModel(prompt), { ttl: 3600 });
  const text: string = await answer("How do refunds work?");
  const asked: string = await cache.ask("How do refunds work?", myModel);
  const hit = await cache.lookup("what's the refund timeline?");
  if (hit) console.log(hit.text, text, asked);
  await cache.store("what's the refund timeline?", "5–7 business days.", { ttl: 3600 });
  for await (const chunk of cache.stream("Tell me a story", myModel)) console.log(chunk);

  const mem = new CrowkisMemory("support-bot", { user: "alice" });
  await mem.remember("Alice prefers email over phone");
  await mem.recall("how should I contact Alice?");
  new CrowkisCache({ tenant: "my-app", ttl: 3600 });

  const client = new CrowkisClient({ tenant: "acme" });
  const chat = new Chat(new Agent("support-bot", { client }), new LLMUnderstander(complete),
    { system: "You are Acme's assistant.", store: new MemoryStore() });
  const reply: ChatReply = await chat.turn("thread-1", [{ role: "user", content: "hi" }], complete);
  console.log(reply.text, reply.fromCache, reply.outcome, reply.reason);
  client.close();
}
void readme;
