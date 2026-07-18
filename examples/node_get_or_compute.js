"use strict";

const { CrowkisClient } = require("../node");

async function main() {
  const cache = new CrowkisClient({ tenant: "node-demo", model: "gpt-4o" });
  const answer = await cache.getOrCompute(
    "Explain semantic caches",
    async (query) => `LLM response for: ${query}`,
    { ttl: 3600, threshold: 0.88 },
  );
  console.log(answer);
  cache.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
