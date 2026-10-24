"use strict";
// Phase 3: every voice adapter passes the same scenarios (fixtures/adapter-conformance.json),
// as python/tests/test_conformance.py does.
//
//   node --test test-conformance.js                                   # stand-in server
//   CROWKIS_CONFORMANCE_SERVER=1 node --test test-conformance.js      # a real server
//
// LiveKit runs when @livekit/agents is installed (pinned in CI: 1.9.3).
const test = require("node:test");
const assert = require("node:assert");
const { SPEC, REAL, DRIVERS, makeStore, runScenario, check, resources } = require("./conformance.js");

for (const driver of DRIVERS) {
  for (const scenario of SPEC.scenarios) {
    if (REAL && !scenario.real) continue;
    const skip = driver.supported ? false : `${driver.name}: framework not installed`;
    test(`${driver.name}: ${scenario.name}`, { skip }, async () => {
      const store = makeStore(scenario);
      const before = resources().length;
      try {
        const results = await runScenario(driver, scenario, store);
        check(assert, scenario, store, results);
      } finally {
        if (store.end) await store.end();
      }
      await new Promise((r) => setImmediate(r));
      assert.ok(resources().length <= before, `left running: ${resources().join(", ")}`);
    });
  }
}
