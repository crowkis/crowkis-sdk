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
    for (const [, dep] of src.matchAll(/require\("\.\/([^"]+)"\)/g)) {
      const name = path.extname(dep) ? dep : `${dep}.js`;
      assert.ok(files.has(name), `${file} requires ./${dep}, which package.json "files" leaves out`);
    }
  }
});
