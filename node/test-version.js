"use strict";
// The package's version is readable as @crowkis/client/package.json (the exports map would
// otherwise hide it), and matches the Python package. Mirrors python/tests/test_version.py.
const assert = require("node:assert");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");

test("package.json is exported and its version matches the Python package", () => {
  const pkg = require("./package.json");
  assert.ok(pkg.exports["./package.json"], "package.json is in the exports map");
  const pyproject = fs.readFileSync(path.join(__dirname, "..", "python", "pyproject.toml"), "utf8");
  assert.strictEqual(pkg.version, /^version = "([^"]+)"/m.exec(pyproject)[1]);
});
