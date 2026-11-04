"use strict";

// Where a client finds its server: code, then the environment, then the defaults.
//
// A value passed in code always wins. When one is not passed, the client looks at
// CROWKIS_HOST, CROWKIS_PORT, CROWKIS_AUTH_TOKEN (or CROWKIS_TOKEN) and CROWKIS_TENANT,
// then at the parts of CROWKIS_URL (crowkis://:token@host:port/tenant), and only then
// uses the built-in default. An empty variable counts as not set.
//
// The environment is read when a client is created, not when the module loads, so a
// .env file loaded later (node --env-file, dotenv) still applies. The SDK never loads
// a .env file itself. Errors name the variable and never repeat its value, since a
// URL can carry the token. Same rule as python/crowkis/_config.py.

const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 6383;

function envVar(name) {
  const value = (process.env[name] || "").trim();
  return value || undefined;
}

function parsePort(text, name) {
  const port = /^\d+$/.test(text) ? Number(text) : 0;
  if (!(port >= 1 && port <= 65535)) {
    throw new Error(`${name} must be a port number from 1 to 65535`);
  }
  return port;
}

// Percent-decoding that, like Python's unquote, leaves a malformed escape ("%zz") as
// it is instead of throwing.
function unquote(text) {
  try {
    return decodeURIComponent(text);
  } catch {
    return text.replace(/(?:%[0-9a-fA-F]{2})+/g, (run) => {
      try {
        return decodeURIComponent(run);
      } catch {
        return run;
      }
    });
  }
}

// The parts CROWKIS_URL gives; a part it leaves out is undefined.
function fromUrl() {
  const text = envVar("CROWKIS_URL");
  if (text === undefined) return {};
  const problem = "CROWKIS_URL must look like crowkis://:token@host:port/tenant";
  let url;
  try {
    url = new URL(text);
  } catch {
    // Never pass the parser's message on: it quotes the URL, token and all.
    throw new Error(`${problem} (it could not be read; check its port is from 1 to 65535)`);
  }
  if (url.protocol !== "crowkis:") throw new Error(`${problem} (it must start with crowkis://)`);
  const host = url.hostname.replace(/^\[(.*)\]$/, "$1");
  if (!host) throw new Error(`${problem} (it has no host)`);
  if (url.port === "0") throw new Error(`${problem} (its port is not a number from 1 to 65535)`);
  const token = url.password || url.username;
  const tenant = url.pathname.replace(/^\/+|\/+$/g, "");
  return {
    host,
    port: url.port ? Number(url.port) : undefined,
    authToken: token ? unquote(token) : undefined,
    tenant: tenant ? unquote(tenant) : undefined,
  };
}

// Fills in each setting not passed in code. A variable is only read for a setting
// the code left out, so a bad CROWKIS_PORT does not stop a client given its port.
function resolveSettings({ host, port, authToken, tenant } = {}) {
  const url = host && port && authToken && tenant ? {} : fromUrl();
  if (!host) host = envVar("CROWKIS_HOST") || url.host || DEFAULT_HOST;
  if (!port) {
    const text = envVar("CROWKIS_PORT");
    port = text ? parsePort(text, "CROWKIS_PORT") : url.port || DEFAULT_PORT;
  }
  if (!authToken) authToken = envVar("CROWKIS_AUTH_TOKEN") || envVar("CROWKIS_TOKEN") || url.authToken;
  // An empty token or tenant counts as not passed, as an empty variable does.
  if (!tenant) tenant = envVar("CROWKIS_TENANT") || url.tenant || tenant;
  return { host, port, authToken, tenant };
}

module.exports = { resolveSettings, DEFAULT_HOST, DEFAULT_PORT };
