"use strict";
// agent.tenant says which tenant the agent works in, also when it comes from the
// environment or from the client given. As in Python (test_agent_tenant.py).
const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("./agent.js");
const { CrowkisClient } = require("./index.js");

test("the tenant from the environment is shown", () => {
  process.env.CROWKIS_TENANT = "acme";
  try {
    assert.strictEqual(new Agent("support").tenant, "acme");
  } finally {
    delete process.env.CROWKIS_TENANT;
  }
});

test("the tenant of a given client is shown", () => {
  assert.strictEqual(new Agent("support", { client: new CrowkisClient({ tenant: "globex" }) }).tenant, "globex");
});

test("must still work: an explicit tenant wins, and none stays none", () => {
  process.env.CROWKIS_TENANT = "acme";
  try {
    assert.strictEqual(new Agent("support", { tenant: "initech" }).tenant, "initech");
  } finally {
    delete process.env.CROWKIS_TENANT;
  }
  assert.ok(new Agent("support").tenant == null);
});
