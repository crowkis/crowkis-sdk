"use strict";
// The management API listens on 6384 (the RESP port + 1); 6380 is nothing. As in Python.
const assert = require("node:assert");
const { test } = require("node:test");
const { CrowkisAdmin } = require("./index.js");

test("the default URL is the management port", () => {
  assert.strictEqual(new CrowkisAdmin().baseUrl, "http://127.0.0.1:6384");
});

test("must still work: a given URL wins", () => {
  assert.strictEqual(new CrowkisAdmin({ baseUrl: "http://10.0.0.5:7000" }).baseUrl, "http://10.0.0.5:7000");
});
