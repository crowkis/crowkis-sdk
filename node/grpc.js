"use strict";

const path = require("node:path");

function loadCrowkisGrpc(options = {}) {
  let grpc;
  let protoLoader;
  try {
    grpc = require("@grpc/grpc-js");
    protoLoader = require("@grpc/proto-loader");
  } catch (error) {
    throw new Error("Crowkis gRPC support requires npm packages @grpc/grpc-js and @grpc/proto-loader");
  }

  const protoPath = options.protoPath || path.join(__dirname, "crowkis.proto");
  const definition = protoLoader.loadSync(protoPath, {
    defaults: true,
    enums: String,
    keepCase: false,
    longs: Number,
    oneofs: true,
  });
  return grpc.loadPackageDefinition(definition).crowkis.v1;
}

class CrowkisGrpcClient {
  constructor(options = {}) {
    const target = options.target || "127.0.0.1:6381";
    const api = loadCrowkisGrpc(options);
    let credentials;
    if (options.credentials) {
      credentials = options.credentials;
    } else {
      const grpc = require("@grpc/grpc-js");
      credentials = grpc.credentials.createInsecure();
    }
    this.client = new api.CrowkisCache(target, credentials);
    this.authToken = options.authToken;
  }

  metadata() {
    if (!this.authToken) return undefined;
    const grpc = require("@grpc/grpc-js");
    const metadata = new grpc.Metadata();
    metadata.set("x-crowkis-auth-token", this.authToken);
    return metadata;
  }

  get(query, options = {}) {
    return unary(this.client, "Get", request(query, options), this.metadata());
  }

  set(query, response, options = {}) {
    return unary(
      this.client,
      "Set",
      {
        query: toBuffer(query),
        response: toBuffer(response),
        ttlSecs: Number(options.ttlSecs || options.ttl || 0),
        tenant: options.tenant || "",
        model: options.model || "",
        image: options.image ? toBuffer(options.image) : Buffer.alloc(0),
      },
      this.metadata(),
    );
  }

  getStream(query, options = {}) {
    return this.client.GetStream(request(query, options), this.metadata());
  }

  stats() {
    return unary(this.client, "Stats", {}, this.metadata());
  }

  invalidate(options = {}) {
    return unary(this.client, "Invalidate", { tenant: options.tenant || "" }, this.metadata());
  }

  close() {
    this.client.close();
  }
}

function unary(client, method, payload, metadata) {
  return new Promise((resolve, reject) => {
    const callback = (error, response) => (error ? reject(error) : resolve(response));
    if (metadata) client[method](payload, metadata, callback);
    else client[method](payload, callback);
  });
}

function request(query, options = {}) {
  const payload = {
    query: toBuffer(query),
    tenant: options.tenant || "",
    model: options.model || "",
    format: options.format || "",
  };
  if (options.threshold !== undefined) payload.threshold = Number(options.threshold);
  if (options.chunkTokens !== undefined || options.chunk_tokens !== undefined) {
    payload.chunkTokens = Number(options.chunkTokens ?? options.chunk_tokens);
  }
  if (options.delayMs !== undefined || options.delay_ms !== undefined) {
    payload.delayMs = Number(options.delayMs ?? options.delay_ms);
  }
  if (options.image) payload.image = toBuffer(options.image);
  return payload;
}

function toBuffer(value) {
  if (Buffer.isBuffer(value)) return value;
  if (value instanceof Uint8Array) return Buffer.from(value);
  return Buffer.from(String(value));
}

module.exports = {
  CrowkisGrpcClient,
  loadCrowkisGrpc,
};
