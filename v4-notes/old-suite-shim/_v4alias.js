"use strict";
// Scratch shim: old ./x.js requires resolve to names found in any v4 src module or test/conformance.js.
const fs = require("node:fs"), path = require("node:path");
let index = null;
const resolved = new Set(), missing = new Set();
function walk(d) {
  return fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => e.isDirectory() ? walk(path.join(d, e.name)) : /\.js$/.test(e.name) ? [path.join(d, e.name)] : []);
}
function build() {
  if (index) return index;
  index = new Map();
  const files = [...walk(path.join(__dirname, "src")), path.join(__dirname, "test", "conformance.js")];
  for (const f of files) {
    let m; try { m = require(f); } catch { continue; }
    const rel = path.relative(__dirname, f).split(path.sep).join("/");
    for (const k of Object.keys(m || {})) if (!index.has(k)) index.set(k, { rel, v: m[k] });
  }
  return index;
}
exports.make = (old) => new Proxy({}, {
  get(t, name) {
    if (typeof name === "symbol" || name === "__esModule" || name === "then") return undefined;
    if (name in t) return t[name];
    const hit = build().get(name);
    if (!hit) { missing.add(`${old}.${name}`); return undefined; }
    resolved.add(`${old}.${name} -> ${hit.rel}`);
    return hit.v;
  },
  set(t, k, v) { t[k] = v; return true; },
  has(t, k) { return k in t || build().has(k); },
  ownKeys() { return [...build().keys()]; },
  getOwnPropertyDescriptor(t, k) { return build().has(k) || k in t ? { enumerable: true, configurable: true, value: this.get(t, k) } : undefined; },
});
process.on("exit", () => {
  if (process.env.NODE_ALIAS_LOG) fs.appendFileSync(process.env.NODE_ALIAS_LOG, JSON.stringify({ file: path.basename(process.argv[1] || ""), resolved: [...resolved], missing: [...missing] }) + "\n");
});
