"use strict";

const { CrowkisError } = require("./connection.js");

let apiKeyWarned = false;

class CrowkisAdmin {
  constructor(options = {}) {
    this.baseUrl = options.baseUrl || "http://127.0.0.1:6384"; // the management port (the RESP port + 1)
    // The server's CROWKIS_AUTH_TOKEN; reading needs none. `apiKey` is its old name.
    // Not enumerable: logging or JSON.stringify of a client must not print them.
    for (const name of ["token", "apiKey"]) {
      Object.defineProperty(this, name, { value: options[name], enumerable: false, writable: true });
    }
    if (options.apiKey && !apiKeyWarned) {
      apiKeyWarned = true;
      process.emitWarning(
        "CrowkisAdmin({ apiKey }) is deprecated: users and API keys were removed in Crowkis 0.5.2. "
          + "Pass the server's CROWKIS_AUTH_TOKEN as { token } instead.",
        "DeprecationWarning",
      );
    }
    this.timeoutMs = options.timeoutMs || 5000;
  }

  async _request(method, path, body) {
    const token = this.token || this.apiKey;
    // fetch's own error for a bad header value quotes the value.
    if (token && /[\r\n]/.test(token)) throw new CrowkisError("token must be a single line");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    const headers = { "content-type": "application/json" };
    if (this.token) headers.authorization = `Bearer ${token}`;
    else if (token) headers["x-crowkis-api-key"] = token;
    try {
      const response = await fetch(new URL(path, this.baseUrl), {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      const text = await response.text();
      if (!response.ok) throw new CrowkisError(text || response.statusText);
      if (!text) return {};
      try {
        return JSON.parse(text);
      } catch (_) {
        return { text };
      }
    } finally {
      clearTimeout(timeout);
    }
  }

  health() {
    return this._request("GET", "/health");
  }

  getStats() {
    return this._request("GET", "/stats");
  }

  updateThreshold(config) {
    return this._request("PUT", "/config/thresholds", config);
  }

  registerWebhook(webhook) {
    return this._request("POST", "/api/v1/webhooks", webhook);
  }

  invalidateSource(sourceId, extra = {}) {
    return this._request("POST", "/api/v1/invalidate", { source_id: sourceId, ...extra });
  }

  flushTenant(tenantId) {
    return this._request("POST", `/api/v1/tenants/${encodeURIComponent(tenantId)}/flush`, {});
  }

  cacheEntries(options = {}) {
    const query = new URLSearchParams();
    if (options.tenant) query.set("tenant", options.tenant);
    if (options.limit) query.set("limit", String(options.limit));
    const suffix = query.toString() ? `?${query}` : "";
    return this._request("GET", `/api/v1/cache/entries${suffix}`);
  }

  migrationProgress(options = {}) {
    const query = new URLSearchParams();
    if (options.tenant) query.set("tenant", options.tenant);
    if (options.canaryId || options.canary_id) query.set("canary_id", options.canaryId || options.canary_id);
    if (options.fromModelVersion || options.from_model_version) {
      query.set("from_model_version", options.fromModelVersion || options.from_model_version);
    }
    if (options.targetModelVersion || options.target_model_version) {
      query.set("target_model_version", options.targetModelVersion || options.target_model_version);
    }
    if (options.limit !== undefined) query.set("limit", String(options.limit));
    const suffix = query.toString() ? `?${query}` : "";
    return this._request("GET", `/api/v1/llm/migrations/progress${suffix}`);
  }

  canaryMigrationProgress(id, options = {}) {
    const query = new URLSearchParams();
    if (options.tenant) query.set("tenant", options.tenant);
    if (options.limit !== undefined) query.set("limit", String(options.limit));
    const suffix = query.toString() ? `?${query}` : "";
    return this._request("GET", `/api/v1/llm/canaries/${encodeURIComponent(id)}/migration-progress${suffix}`);
  }

  leaseMigrationWork(options = {}) {
    return this._request("POST", "/api/v1/llm/migrations/lease", options);
  }

  leaseCanaryMigrationWork(id, options = {}) {
    return this._request("POST", `/api/v1/llm/canaries/${encodeURIComponent(id)}/migration-lease`, options);
  }

  completeMigrationWork(item) {
    return this._request("POST", "/api/v1/llm/migrations/complete", item);
  }

  failMigrationWork(item) {
    return this._request("POST", "/api/v1/llm/migrations/fail", item);
  }
}

module.exports = { CrowkisAdmin };
