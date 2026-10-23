# Website docs for Crowkis 0.5.2: what changed and what to do

This folder holds the rewritten and new docs pages as Markdown. Each file names its URL path and the version it describes at the top. The pages' code was exercised against a real 0.5.2 server by the scripts in `_checks/`. They run the voice loops as written and check every name the SDK pages use. Every snippet was also syntax-checked on its own (`_checks/check_syntax.py`). Nothing here has been published.

## Pages to replace

| File | URL | What changed |
|---|---|---|
| `docs/quickstart.md` | `/docs/quickstart` | Ports 6383 (cache), 6384 (dashboard), 6385 (gRPC), 6386 (probes), instead of 6379/6380/6381. A `docker run` that works locally. The `Crowkis` class with `cached()` instead of `CrowkisClient` + `get_or_compute(model=)`. SDK settings from the environment. |
| `docs/docker.md` | `/docs/docker` | The real ports and which are published. **`CROWKIS_ADMIN_KEY` is gone** (retired in 0.5.2, ignored by the server); one secret, `CROWKIS_AUTH_TOKEN`, guards everything. Protected mode, 1 GB memory, a compose file shown inline, the probe port, a pinned `:0.5.2` tag, how clients send the token. |
| `docs/configuration.md` | `/docs/configuration` | Correct variable names and defaults from the server code (`CROWKIS_PORT`, not `CROWKIS_BIND_PORT`). The environment wins over the config file. Decision engine, voice add-on and license settings. The Community cap is **50,000 entries** (the site says 100K). New section: SDK settings (`CROWKIS_HOST` / `PORT` / `AUTH_TOKEN` / `TENANT` / `URL`). |
| `docs/sdk-python.md` | `/docs/sdk-python` | One naming scheme (`Crowkis` with `cached` / `ask` / `lookup` / `store` / `stream`). An install line per extra. Connecting through the environment, the token, `CrowkisAdmin` on port 6384 (it was used without an import), Chat, voice. |
| `docs/sdk-node.md` | `/docs/sdk-node` | The same, for Node: import paths per subpath, the token option, Chat, voice. |
| `changelog.md` | `/changelog` | Real versions and dates (0.5.0, 0.5.1, 0.5.2), what's in 0.5.2, and upgrade notes. **Two dates need the release owner:** 0.5.2's (at release) and 0.5.1's (not recorded in the repos). |

## New pages

| File | URL |
|---|---|
| `docs/voice/index.md` | `/docs/voice` (it is a 404 today) |
| `docs/voice/pipecat.md` | `/docs/voice/pipecat` |
| `docs/voice/livekit-python.md` | `/docs/voice/livekit-python` |
| `docs/voice/livekit-node.md` | `/docs/voice/livekit-node` |
| `docs/voice/custom-loop-python.md` | `/docs/voice/custom-loop-python` |
| `docs/voice/custom-loop-node.md` | `/docs/voice/custom-loop-node` |

Add a "Voice agents" group to the sidebar under SDKs & integrations, with these six pages.

## Other pages: not rewritten, but wrong today

| Page | Problem |
|---|---|
| `/docs` (overview) | The cards promise "get_or_compute, multimodal" (Python) and "retry/backoff, CachedOpenAI wrapper" (Node). The SDK pages show neither. Suggest "Sync + async, decorator, streaming, voice, chat" and "Typed client, ESM + CommonJS, voice, chat". There's no voice card. |
| `/docs/commands` | Lists 8 of about 30 C* commands. Says the schema is "in the repository", while the FAQ says the product is closed source. |
| `/docs/frameworks` | The sidebar says "LangChain, LangGraph & Shell", but the page title is "…LlamaIndex & CrewAI". `crowkis server --port 6379` should be 6383. |
| `/docs/security` | The auth table lists `CROWKIS_ADMIN_KEY` and RBAC API keys. In 0.5.2 there is one token (`CROWKIS_AUTH_TOKEN`), and the dashboard and reads need none. |
| `/faq` | Ports 6379/6380/6381. `get_or_compute` / `stream_get_or_compute` naming. 100K entries for Community (the code says 50,000). |

## Before publishing

- **Always pass `CrowkisAdmin` its URL** (`http://<host>:6384`). The 0.5.2 SDKs still default it to port 6380, which nothing listens on. That's an SDK bug, reported separately.

- **The server image.** The server repo's own notes say the latest *published* image is 0.5.1. The pages say `crowkis/crowkis:0.5.2`, so publish the image first, or the commands won't pull.
- **The SDK packages.** PyPI and npm have 0.5.0. Everything on the voice and Chat pages needs the 0.5.2 packages.
