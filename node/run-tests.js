"use strict";
// Runs every test-*.js in its own process with the CROWKIS_* server settings removed
// from the environment, so a variable set for real work (CROWKIS_AUTH_TOKEN, ...)
// cannot reach tests that build a client with only a port. Tests that want the
// environment set it themselves.  Usage: npm test  (or node run-tests.js [files...])
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const NAMES = ["CROWKIS_HOST", "CROWKIS_PORT", "CROWKIS_AUTH_TOKEN", "CROWKIS_TOKEN", "CROWKIS_TENANT", "CROWKIS_URL"];
const env = { ...process.env };
for (const name of NAMES) delete env[name];

const files = process.argv.slice(2).length
  ? process.argv.slice(2)
  : fs.readdirSync(__dirname).filter((f) => /^test-.*\.js$/.test(f)).sort();

let failed = 0;
for (const file of files) {
  const run = spawnSync(process.execPath, [path.join(__dirname, file)], { env, stdio: "inherit" });
  if (run.status !== 0) {
    failed += 1;
    console.error(`FAILED: ${file}`);
  }
}
console.log(`${files.length - failed}/${files.length} test files passed`);
process.exit(failed ? 1 : 0);
