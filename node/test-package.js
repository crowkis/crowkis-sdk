"use strict";

// The published package must hold every local file its files require (Chat was missing from npm).
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");

test("every file a packaged file requires is packaged", () => {
  const files = new Set(require("./package.json").files);
  for (const file of files) {
    if (!file.endsWith(".js")) continue;
    const src = fs.readFileSync(path.join(__dirname, file), "utf8");
    // Relative to the requiring file, so files in src/ folders are followed too ("./", "../").
    for (const [, dep] of src.matchAll(/require\("(\.\.?\/[^"]+)"\)/g)) {
      const resolved = path.posix.normalize(path.posix.join(path.posix.dirname(file), dep));
      const name = path.extname(resolved) ? resolved : `${resolved}.js`;
      assert.ok(files.has(name), `${file} requires ${dep}, which package.json "files" leaves out`);
    }
  }
});
