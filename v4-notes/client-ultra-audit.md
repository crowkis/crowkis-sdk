# C2: ponytail ultra pass over the client and the package root files (2026-11-04)

Read-only, at `e5e36f9` (after U1). Scope: the Python package root (`client.py`, `_config.py`, `agent.py`,
`grpc_stub.py`, `crowkis.proto`, `openai_wrapper.py`, `__init__.py`, `privacy.py`, `_help.py`) and the Node root
(`index.js`, `config.js`, `agent.js`, `grpc.js`, `crowkis.proto`, `langchain.js`, `memory.js`, `livekit.js`,
`conformance.js`, `golden.js`, `index.mjs`, the root `.d.ts` files). Nothing in the code changed. Callers were counted
with an AST pass over `python/` (package, tests; `python/build/` is a stale, untracked build copy and was left out), a
`require` pass over `node/` (src, tests, `index.js`, `index.mjs`, every `.d.ts`), `examples/`, the READMEs and the
Bolna integration.

**Hard limits kept.** No proposal changes a decision or a reply (golden files would stay identical). Public names
don't change: `from crowkis import Crowkis, CrowkisClient, AsyncCrowkisClient, CrowkisAdmin, CrowkisError, CacheHit,
SimResult, Agent, CrowkisGrpcStub, ...`, `crowkis.privacy`, and Node `index.js` / `index.mjs` / every subpath
(`/agent`, `/livekit`, `/langchain`, `/memory`, ...). None of the names this report deletes is public.

**Risk:** *none* = imports only; *low* = code moves between modules; *needs tests* = a signature or a wire frame
could change.

---

## What the pass found

- **Almost no dead code.** Every top-level name in the Python root files is read somewhere except `_aread_resp`.
  Every top-level name in the Node root files is read. No function has an unused parameter.
- **`client.py` is three things in one file:** the RESP wire (encode, two frame readers, the error type, the
  transport errors, the two connection holders), the two client classes (pool, retries and every server command),
  and `CrowkisAdmin` (HTTP; it shares only `CrowkisError` with the rest). Node's `index.js` is the same three things
  plus the package's export block.
- **The commands can't leave the client class honestly.** `CrowkisClient`'s 100+ command methods call
  `self.execute`, `self.tenant`, `self._args_*` and the pool. Moving them out means a mixin or free functions that
  take the client, and every public method would become a forwarder. So the classes stay whole. The split is
  wire / classes / admin. `AsyncCrowkisClient` subclasses `CrowkisClient` and reuses its `_args_*` builders, so it
  stays in the same file.
- **The import surface is small.** Package code imports these modules from 14 files, tests from 23 files (Python) and
  39 files (Node). No test patches a module path by string; one test resets a module global (`_API_KEY_WARNED`).

## Files and lines

| | Files before → after | Lines before → after (approx.) |
|---|---|---|
| Python root | 9 → 3 (`__init__.py`, `privacy.py`, `_help.py`) | 3,464 → 229 |
| Python `client/` (new) | 0 → 8 | 0 → ~3,240 |
| Python `integrations/openai.py` (new) | 0 → 1 | 0 → 128 |
| Python in all | 9 → 12 | 3,464 → ~3,600 (+~30 import headers in the split files, −17 from the findings) |
| Node root code (`.js`, `.proto`; not `.d.ts`, `index.mjs`, tests) | 10 → 1 (`index.js`, thin) | 3,304 → ~100 |
| Node `src/client/` (new) | 0 → 7 | 0 → ~2,080 |
| Node `src/integrations/` | 1 → 4 | 432 → 928 |
| Node `test/` helpers | 1 → 3 | — (+625 moved in) |
| Node in all | 10 → 12 | 3,304 → ~3,310 |

The file count goes up by three in each language: the owner asked for the split, and each new file holds one
thing. The lines barely move. This pass is a regrouping, not a cleanup.

---

## Ranked findings

Callers are listed as `py:` / `node:` paths relative to `python/` and `node/`.

| # | Finding | Files (Python / Node) | Action | Lines saved (py / node) | Risk | Callers to repoint |
|---|---|---|---|---|---|---|
| 1 | **`_aread_resp` has no caller.** The async client reads frames with `_aread_frame` and raises itself. | `client.py:238` / — | **delete** | −6 / 0 | none | — |
| 2 | **`integrations/pipecat.py:87-88` re-imports `_store_later`, `_tts_key` and `CrowkisError` "kept importable from here", and nobody reads them there.** Tests import them from `crowkis.agent`. | `integrations/pipecat.py` / — | **delete the two lines** | −2 / 0 | none | — |
| 3 | **`channels/voice_session.py:13` imports `_store_later` and never uses it.** Node `voiceSession.js:3` imports `storeLater` and never uses it either. | `channels/voice_session.py` / `src/channels/voiceSession.js` | **drop the name** from the import | 0 / 0 (part of a line) | none | — |
| 4 | **`agent.py` `__all__ = ["Agent", "CrowkisError"]`.** Nothing star-imports it; it is the last place that re-exports `CrowkisError` from `agent`. | `agent.py:475` / — | **delete** | −1 / 0 | none | — |
| 5 | **`grpc_stub.py` repeats `BytesLike` and `_b` from `client.py`** (same body). Node `grpc.js:112` repeats `toBuffer` from `index.js` (same body). | `grpc_stub.py:7,104` / `grpc.js:112` | **import** them from `client/connection` (`src/client/connection.js`) after the move | −8 / −6 | low | — (both are private to the file) |
| 6 | **Node `cget` and `cgetHit` build the same CGET frame, line for line** (`index.js:513-530` and `:533-549`). | — / `index.js` | **fold** into one private `_cgetArgs(query, options)` in the class; same order, same frame | 0 / −14 | low | — |
| | **Total** | | | **−17 / −20** | | |

The Python twin of #6 is not here: Python's three CGET builders and two CSET builders differ on the wire (see
"Only with a behaviour change").

---

## Every caller to repoint for the move

The move is a path rename; after it every importer names the module that defines the name. `crowkis.client` becomes
a package whose `__init__.py` is a docstring only (no re-export block; U1 deleted those). So `from crowkis.client
import X` fails loudly with ImportError, which the suite catches. Public users keep `from crowkis import X`.

Where each Python name goes: `CrowkisError`, `BytesLike`, `_encode`, `_read_resp`, `_busy_retry_seconds` →
`crowkis.client.connection`; `CrowkisClient`, `AsyncCrowkisClient`, `Crowkis`, `AsyncCrowkis`, `CacheHit`,
`SimResult`, `_cache_hit`, `_plain` → `crowkis.client.commands`; `CrowkisAdmin`, `_API_KEY_WARNED` →
`crowkis.client.admin`; `_config` → `crowkis.client.config`; `crowkis.agent` → `crowkis.client.agent`;
`crowkis.grpc_stub` → `crowkis.client.grpc_stub`; `crowkis.openai_wrapper` → `crowkis.integrations.openai`.

**Python package code (14 files)**
- `crowkis/__init__.py:3-13` (client names, grpc), `:18` (Agent), `:43` (comment naming `crowkis.openai_wrapper`).
- `crowkis/client.py:31` (`from . import _config`; becomes `from . import config` inside `client/commands.py`).
- `crowkis/agent.py:14` → `from .commands import CrowkisClient` and `from .connection import CrowkisError`.
- `crowkis/channels/voice_session.py:13,14`; `crowkis/channels/async_voice_session.py:21`.
- `crowkis/rules/chain.py:7`.
- `crowkis/integrations/voice_turns.py:36,37`; `integrations/pipecat.py:87,88` (deleted by #2);
  `integrations/langchain.py:25`; `integrations/memory.py:27`; `integrations/bolna/__init__.py:50`.
- `crowkis/openai_wrapper.py:8` (docstring usage line), `:30`.
- `crowkis/_help.py:75` (the help text names `crowkis.openai_wrapper.CachedOpenAI`).
- `crowkis/_config.py:47` (docstring: "Same as node/config.js").

**Python tests (35 lines in 23 files)**
- `crowkis.client`: `test_agent_voice.py:13,1383`; `test_auth_token.py:11` (`from crowkis import client as
  client_mod`, then `client_mod._API_KEY_WARNED = False` at `:49`: must become `from crowkis.client import admin as
  client_mod`, or the reset silently stops working), `:12`; `test_realtime.py:12`; `test_sdk.py:43,234`;
  `test_server_052_replies.py:11`; `test_voice_addon.py:12`; `test_voice_stress_bugs.py:18`.
- `crowkis.agent`: `conformance.py:27`; `test_agent_voice.py:12`; `test_bolna.py:37`; `test_pipecat.py:64,89`;
  `test_realtime.py:11`; `test_voice_addon.py:11,151`; `test_voice_announce.py:15`; `test_voice_audio_failopen.py:18`;
  `test_voice_different_question.py:13`; `test_voice_identifiers.py:12`; `test_voice_rereview_fixes.py:15`;
  `test_voice_review_fixes.py:14`; `test_voice_security_audit.py:9`; `test_voice_slow_writes.py:14`;
  `test_voice_stress_bugs.py:17`; `understanding/test_budgeted_understanding.py:7`;
  `understanding/test_knowledge_segment.py:6`; `voice_turns_scenarios.py:20`.
- `crowkis.openai_wrapper`: `test_env_config.py:16`; `test_help_names.py:11-13`. This test asserts the old path in
  the help text, so it changes with the path (the asserted path is what moves, not a bug).
- No `mock.patch("crowkis.client...")`, `monkeypatch.setattr("crowkis.agent...")` or `crowkis._config` import exists
  in any test. `test_env_config.py` tests the config through the public classes only.

**Python examples, READMEs:** none (`examples/*.py` and `python/examples/` import from `crowkis` or
`crowkis.integrations.langchain`).

**Packaging:** `python/pyproject.toml:43` `crowkis = ["crowkis.proto"]`.

**Node package code**
- `src/channels/voiceSession.js:3` (`../../agent.js`), `:4` (`../../index.js` for `CrowkisClient`).
- `src/integrations/voiceTurns.js:27` (`../../agent.js`).
- `src/rules/chain.js:4,12` (`class … extends require("../../index.js").CrowkisError`): repoint to
  `../client/connection.js`. This is the only load-time require of `index.js` from `src/`, and the move removes it.
- `agent.js:3`, `langchain.js:13`, `memory.js:11` (`./index.js` for `CrowkisClient`) → `commands.js`.
- `livekit.js:32,33` (`./src/channels/…`, `./src/integrations/…`) → `../channels/…`, `./voiceTurns.js`.
- `index.js:4` (`./config.js`), `:1361` (`...require("./grpc")`), `:1363` (`./agent.js` getter).

**Node tests**
- `./agent.js` or `../../agent.js`: 39 test files (`test-*.js` 29, `test/**/*.test.js` 10), plus `conformance.js:16`
  and `golden.js:10`. The full list: `test-agent-feature-gaps`, `test-agent-tenant`, `test-decision-rules`,
  `test-env-config`, `test-examples`, `test-livekit`, `test-realtime`, `test-segment`, `test-stated-context`,
  `test-voice-addon`, `test-voice-announce`, `test-voice-audio-failopen`, `test-voice-crisis-and-structures`,
  `test-voice-different-question`, `test-voice-identifiers`, `test-voice-prompt-guard`, `test-voice-record`,
  `test-voice-rereview-fixes`, `test-voice-respond`, `test-voice-review-fixes`, `test-voice-security-audit`,
  `test-voice-session-factory`, `test-voice-slow-writes`, `test-voice-stress-bugs`, `test-voice-turns`,
  `test-voice-undecided-turns`, `test-voice`, `test/runtime/stats`, `test/turns/{mergedSaveCheck,
  recordThenDecide,turnCore}`, `test/understanding/{budgetedUnderstanding,knowledgeSegment,llmSlots,rewriteSafety,
  slotsWired,statedFactsVoice}`.
- `./langchain.js`, `./memory.js`: `test-env-config.js:13,14`; `test-server-replies.js:9`.
- `./livekit.js`: `test-livekit.js:91,291,311`; `conformance.js:285`.
- `./conformance.js` (if it moves to `test/`): `test-agent-feature-gaps.js:113`, `test-conformance.js:11`,
  `test-voice-different-question.js:8`, `test-voice-identifiers.js:8`. `./golden.js`: `test-golden.js:10`. Inside
  them: `conformance.js:14-17,19,285` and `golden.js:10-17` (the `..` to `fixtures/` becomes `../..`).
- `./index.js` requires stay valid: `index.js` stays where it is.
- `test-package.js` checks that every packaged file's relative requires are packaged, so `files` must list every
  new `src/client/*.js` and `src/integrations/*.js`. It does not see `grpc.js` loading `crowkis.proto` by path, so
  the `.proto` entry must be added by hand.
- `test-packaging.js` expectations do not change (same exports, same subpaths, same types). It must still pass.
- `.d.ts` relative imports: all root `.d.ts` files import `"./index"`; they stay at the root, so none change.
- `examples/node_get_or_compute.js:3` (`../node`), `examples/node_realtime_voice_agent.js:43`
  (`../node/index.js`): unchanged.

**Outside this repo (listed, no edits planned)**
- `D:\Tarkova\sdk-docs\website\`: no reference to a moved module path or file. It uses only the subpaths
  `@crowkis/client/livekit`, `/langchain`, `/memory` (`docs/sdk-node.md:27-29,88,97`,
  `docs/voice/livekit-node.md:17,21,62`, `_checks/check_sdk_pages.js:16`, `_checks/check_voice_node.js:69`), and
  those stay. `README-for-the-website-owner.md:34` mentions "CachedOpenAI wrapper" for Node, which never existed.
- `D:\Tarkova\crowkis-testing-scripts\`: no reference to a moved path. It still imports the pre-P5.6 paths
  `crowkis.voice`, `crowkis.session`, `crowkis.understand`, `crowkis.verify` (`demo/chat-api/chat/turn_policy.py:26`,
  `demo/voice-agent/reports.py:9`, `demo/voice-agent/tests/voice_stress_test.py:308-310`), which are already broken
  on v4. `.archify/.../candidate.json:26,88` is an old diagram note.
- Stale after the move: the file map in `D:\Tarkova\sdk-docs\CODEBASE-GUIDE.md` (`client.py`, `_config.py`,
  `agent.py`, `index.js`, `config.js`, `agent.js`).

---

## Keep, and why

- **`CrowkisClient` and `AsyncCrowkisClient` as single classes.** Their commands need `self` (pool, tenant, model,
  retries). A split would need a mixin or a forwarder per command.
- **The sync and async RESP frame readers** (`_read_frame`, `_aread_frame`, ~45 lines each). One reads a file-like,
  the other awaits a stream. One body for both needs a sans-IO parser: new code and a new risk on the hot path.
- **`_read_resp`.** Only `tests/test_sdk.py` calls it (7 asserts). It is 5 lines and is the readable test target.
- **`_Conn` and `_AsyncConn`.** Two tiny holders with a safe `close()`. They are data, not interfaces.
- **`_CompletionsProxy`, `_ChatProxy`, `CachedResponse`** in `openai_wrapper.py`. They give `CachedOpenAI` the
  `client.chat.completions.create(...)` shape of the OpenAI SDK.
- **`Crowkis` / `AsyncCrowkis` aliases, `CacheHit`, `SimResult`, `GrpcCacheHit`, `GrpcStreamChunk`.** Public.
- **`crowkis.proto` in Python.** The Python stub encodes protobuf by hand and never reads the file. It ships for users
  who generate their own stubs, and the owner wants it shipped.
- **The root `.d.ts` files.** They are the typed surface of each subpath, `package.json` `exports` points `types` at
  them, and each imports `"./index"`. Moving them changes every `exports` entry and every import for no gain.
- **`index.mjs`.** It must name every export; the names don't change.
- **Python `__init__.py` imports eagerly** (it is not lazy, unlike Node's getters). It stays so: `import crowkis`
  already loads the client, the agent and the channels today.

## Only with a behaviour change (not done)

- **Python's CGET and CSET frames are built five times and differ.** `cget_hit` sends `SEGMENT` right after
  `TENANT`; `cget` sends it last. `cget_async` and `cset_async` drop `template=True` (no `TEMPLATE` on the wire),
  while `cget` / `cset` send it. One `_args_cget` / `_args_cset` (the class's own `_args_*` pattern) saves ~45 lines,
  but changes `cget_hit`'s argument order and makes the async pair send `TEMPLATE`. The async drop looks like a bug
  (a templated answer stored by `cset_async` is stored as a plain answer). It needs the owner's call and a
  failing-first test in both languages.
- **Line length cap.** Python sync reads a reply line up to 512 KiB (`MAX_LINE_BYTES`); Python async uses asyncio's
  default 64 KiB; Node has no cap. One cap for all three changes what a very long status line does.
- **`CrowkisAdmin` empty and non-JSON bodies.** Python returns `None` and a string; Node returns `{}` and
  `{ text }`. Public return values.
- **gRPC default target `127.0.0.1:6381`** in both languages, while the server's gRPC port is 6385. Changing the
  default is a public change.

---

## Order of work

1. **Deletions (risk none):** #1 to #4. Python and Node.
2. **Folds:** #5 (after the move, since `connection` is new) and #6. No signature changes, so no failing-first test
   is needed; the full suites and the golden files prove it.
3. **The move:** `client-layout-plan.md`.
4. **Frameworks** (Pipecat, LiveKit Py/JS, Bolna), `graphify update .`, the wheel and `npm pack` checks, one Opus
   review.
