"use strict";
// Public API contract: every export, class method and declared type name is pinned in
// fixtures/public-api.json (section "node"). A name in the snapshot that is gone now (removed or
// renamed) fails; a new public name fails too, so adding to the API is a deliberate snapshot update.
// The ESM/CJS parity of index.js vs index.mjs is already checked in test-packaging.js.
// Regenerate (rewrites only the "node" section):
//   CROWKIS_UPDATE_API_SNAPSHOT=1 node --test test-public-api.js
const assert = require("node:assert");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const FIXTURE = path.join(__dirname, "..", "fixtures", "public-api.json");
const pkg = require("./package.json");

function shapes(mod) {
  const out = [];
  for (const key of Object.keys(mod).sort()) {
    out.push(key);
    const value = mod[key];
    if (typeof value !== "function" || !value.prototype) continue;
    for (let proto = value.prototype; proto && proto !== Object.prototype; proto = Object.getPrototypeOf(proto)) {
      for (const name of Object.getOwnPropertyNames(proto)) {
        if (name !== "constructor" && !name.startsWith("_")) out.push(`${key}.${name}`);
      }
    }
  }
  return [...new Set(out)].sort();
}

function declared(file) {
  const text = fs.readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  const names = [];
  for (const m of text.matchAll(/^export\s+(?:declare\s+)?(?:abstract\s+)?(?:class|function|const|let|var|interface|type|enum|namespace)\s+([A-Za-z_$][\w$]*)/gm)) names.push(m[1]);
  for (const m of text.matchAll(/^export\s*\{([^}]*)\}/gm)) {
    for (const part of m[1].split(",")) {
      const name = part.trim().split(/\s+as\s+/).pop();
      if (name) names.push(name);
    }
  }
  return [...new Set(names)].sort();
}

async function current() {
  const now = { "index.js": shapes(require("./index.js")) };
  now["index.mjs"] = Object.keys(await import(pathToFileURL(path.join(__dirname, "index.mjs")).href)).sort();
  for (const [sub, target] of Object.entries(pkg.exports)) {
    if (sub === "." || sub === "./package.json") continue;
    now[sub] = shapes(require(path.join(__dirname, target.default)));
  }
  for (const file of fs.readdirSync(__dirname).filter((f) => f.endsWith(".d.ts")).sort()) {
    now[`dts.${file}`] = declared(path.join(__dirname, file));
  }
  return now;
}

test("public API matches fixtures/public-api.json", async () => {
  const now = await current();
  const data = fs.existsSync(FIXTURE) ? JSON.parse(fs.readFileSync(FIXTURE, "utf8")) : {};
  if (process.env.CROWKIS_UPDATE_API_SNAPSHOT === "1") {
    data.node = now;
    const sort = (o) => Object.fromEntries(Object.keys(o).sort().map((k) => [k, Array.isArray(o[k]) ? o[k] : sort(o[k])]));
    fs.writeFileSync(FIXTURE, JSON.stringify(sort(data), null, 2) + "\n");
    return;
  }
  const snap = data.node;
  const problems = [];
  for (const key of [...new Set([...Object.keys(snap), ...Object.keys(now)])].sort()) {
    const a = new Set(snap[key] || []), b = new Set(now[key] || []);
    const gone = [...a].filter((n) => !b.has(n)), added = [...b].filter((n) => !a.has(n));
    if (gone.length) problems.push(`node.${key}: missing now (removed or renamed): ${JSON.stringify(gone)}`);
    if (added.length) problems.push(`node.${key}: new public name: update fixtures/public-api.json on purpose: ${JSON.stringify(added)}`);
  }
  assert.deepStrictEqual(problems, []);
});
