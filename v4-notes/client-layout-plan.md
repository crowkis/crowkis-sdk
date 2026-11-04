# Plan: the client in its own folder, and a package root with three files (2026-11-04)

The owner wants the client split and the package root files moved into folders that mean something. This plan
builds on `client-ultra-audit.md`: its deletions and folds run first, then the files move. Nothing changes
behaviour: golden files stay identical, public names and every Node subpath stay the same. Python and Node change
together.

## Target layout

```
python/crowkis/
  __init__.py        public names (repointed imports only)                                          ~109
  privacy.py         unchanged                                                                         11
  _help.py           help text (one path in it changes: crowkis.integrations.openai.CachedOpenAI)    109
  client/            talking to a Crowkis server
    __init__.py      docstring only
    connection.py    the RESP wire: CrowkisError, BytesLike, _b, _encode, _read_frame/_read_resp,
                     _aread_frame, MAX_LINE_BYTES, BUSY_* + _busy_retry_seconds, TRANSPORT_FAILURES,
                     _transport_error, _auth_refused, _Conn, _AsyncConn, ASYNC_TRANSPORT_FAILURES           ~245
    commands.py      CrowkisClient and AsyncCrowkisClient (pool, retries, every server command),
                     Crowkis/AsyncCrowkis, CacheHit, SimResult and the reply helpers (_cache_hit, _plain,
                     _token_chunks, _memextract_parts, _scope, _tenant_model, _stream_values, MEMEXTRACT_*)  ~1,720
    admin.py         CrowkisAdmin (HTTP management API), _API_KEY_WARNED                                   ~130
    config.py        from _config.py, unchanged                                                            117
    agent.py         from agent.py (Agent, audio stores, tts key)                                          ~474
    grpc_stub.py     from grpc_stub.py; imports _b, BytesLike from connection                            ~273
    crowkis.proto    unchanged                                                                              76
  integrations/
    openai.py        from openai_wrapper.py (CachedOpenAI)                                                 128
    (langchain, memory, livekit, pipecat, voice_turns, bolna/: unchanged but for imports)

node/
  index.js           the package entry, thin: requires src/client/*, src/turns/results.js, and keeps every
                     export and every lazy getter                                                        ~100
  index.mjs, *.d.ts  unchanged, at the root
  src/client/
    connection.js    CrowkisError, toBuffer, encode, RespReader, sleep, busyRetryMs, NO_SERVER_TOKEN      ~190
    commands.js      CrowkisClient (+ _cgetArgs) and its helpers (imageBase64, bufferToString, plain,
                     extractParts, warnNotStored, tokenChunks, streamValues)                              ~1,010
    admin.js         CrowkisAdmin                                                                         ~125
    config.js        from config.js                                                                         88
    agent.js         from agent.js                                                                         454
    grpc.js          from grpc.js; requires toBuffer from connection                                     ~115
    crowkis.proto    unchanged (grpc.js loads it from its own folder, so the path code doesn't change)      76
  src/integrations/
    voiceTurns.js    unchanged but for one require
    langchain.js, memory.js, livekit.js   from the root (Python's twins are in integrations/)
  test/
    conformance.js, golden.js   from the root: test helpers, like test/rules/fakeCall.js
```

| | Files now → after | Lines now → after (approx.) |
|---|---|---|
| Python root | 9 → 3 | 3,464 → 229 |
| Python `client/` + `integrations/openai.py` | 0 → 9 | 0 → ~3,370 |
| Node root code | 10 → 1 | 3,304 → ~100 |
| Node `src/client/` + 3 integrations + 2 test helpers | 0 → 12 | 0 → ~3,210 |

Why these groups:
- **`client/`**: everything that talks to the server. One file per job: the wire (`connection`), the client
  classes (`commands`), the HTTP admin (`admin`), where the settings come from (`config`), the per-agent cache built
  on the client (`agent`), and the optional gRPC client (`grpc_stub` + its proto).
- **`connection` apart from `commands`**: the wire is pure functions, an error type and two holders, with no client
  state. It is the one part of `client.py` that is clearly independent. Every other module that only needs
  `CrowkisError` (rules, channels, Bolna, voice_turns) then imports a 245-line file, not the 1,720-line one.
- **`commands` holds both classes**: the commands need `self`, so they can't leave the class without a mixin or a
  forwarder per command (the audit's "Keep"). `AsyncCrowkisClient` subclasses `CrowkisClient` and reuses its
  `_args_*` builders and ten private helpers; its own file would import all of them.
- **`admin` apart**: it shares only `CrowkisError` with the rest and uses HTTP, not RESP.
- **`openai.py` in `integrations/`**: it is a wrapper around a third-party SDK, like `langchain` and `memory`.
  Inside it, `from openai import OpenAI` stays an absolute import, so the module's own name doesn't shadow the SDK.
- **gRPC flat in `client/`, not `client/grpc/`**: `pyproject.toml` uses `packages.find`, which skips a folder with no
  `__init__.py`. A `grpc/` folder needs an extra `__init__.py` to ship; the flat layout needs none.
  (Choice for the owner below.)
- **Node `test/` for `conformance.js` and `golden.js`**: they are test helpers, not package code (`files` leaves them
  out), and `test/rules/fakeCall.js` is the precedent. Python's twins live in `python/tests/`. Cost: 5 test files
  repoint, and the two helpers change `..` to `../..` for `fixtures/`.
- **Node root `.d.ts` files stay**: `exports.types` points at them and each imports `"./index"`; moving them buys
  nothing (the audit's "Keep").

**`crowkis/client/__init__.py` is a docstring only.** No re-export block. Every importer names the defining module
(`from ..client.connection import CrowkisError`), and public users keep `from crowkis import ...`. The cost:
`from crowkis.client import CrowkisClient` stops working. That path is internal; v4 is unpublished, and the owner
allowed moving internal paths. `crowkis.openai_wrapper.CachedOpenAI` is the one moved path the help text shows to
users; `_help.py` and `tests/test_help_names.py` change with it.

## Import cycles (checked)

**Python.** `crowkis/__init__.py` imports eagerly (it is not lazy). Its order stays: client names first, then grpc,
memory, help, agent, channels.
- `client/connection` imports nothing from the SDK.
- `client/config` imports nothing from the SDK.
- `client/commands` imports `connection` and `config`.
- `client/admin` imports `connection`. `client/grpc_stub` imports `connection`.
- `client/agent` imports `commands` and `connection`.
- `channels/*`, `rules/chain`, `integrations/*` import `client/agent`, `client/commands` or `client/connection`.
  Nothing under `client/` imports them back, so there is no cycle. `client/__init__.py` imports nothing, so loading
  any `crowkis.client.*` module adds no load order of its own.

**Node.** Today `src/rules/chain.js` requires `../../index.js` at load (`class … extends require(…).CrowkisError`),
and `voiceSession.js` requires `../../index.js` and `../../agent.js`. That works only because `index.js` loads
`src/turns/results.js` (which doesn't reach `chain.js`) and loads the channels lazily through getters.
- After the move, nothing under `src/` requires `index.js`. `chain.js` requires `../client/connection.js`;
  `voiceSession.js` requires `../client/agent.js` and `../client/commands.js`.
- `src/client/agent.js` requires `./commands.js` (today `./index.js`), so the `agent.js` ↔ `index.js` pair goes away.
- `index.js` requires at load: `src/client/{connection,commands,admin,grpc}.js` and `src/turns/results.js`.
  It keeps its getters for `Agent`, the channels, the state, the rules and the understanders, so `require
  ("@crowkis/client")` loads no more than today.
- `src/integrations/{langchain,memory}.js` require `../client/commands.js`; `livekit.js` requires
  `../channels/voiceSession.js` and `./voiceTurns.js`. None is required by `index.js`.

## Steps (each one commit; full Python + Node suites after each; golden files unchanged)

1. **Deletions** (audit #1-#4): `_aread_resp`, the two pipecat re-import lines, the unused `_store_later` /
   `storeLater` imports, `agent.py`'s `__all__`.
2. **Folds** (audit #6): Node `_cgetArgs`. No signature changes, so no new test; `test-segment.js` and
   `test-client.js` cover the frames. (Audit #5 runs inside step 3, because `connection` doesn't exist yet.)
3. **The Python move.**
   - `git mv crowkis/client.py crowkis/client/commands.py` (the biggest source, so history follows), then cut
     `connection.py` and `admin.py` out of it. `git mv` `_config.py` → `client/config.py`, `agent.py` →
     `client/agent.py`, `grpc_stub.py` → `client/grpc_stub.py`, `crowkis.proto` → `client/crowkis.proto`,
     `openai_wrapper.py` → `integrations/openai.py`. Add `client/__init__.py` (docstring).
   - Audit #5: `grpc_stub.py` imports `_b`, `BytesLike` from `.connection`.
   - Repoint every caller in the audit's list (package 14 files, tests 23 files). `test_auth_token.py` imports
     `crowkis.client.admin as client_mod`, so its `_API_KEY_WARNED` reset still reaches the real global.
   - `pyproject.toml`: `crowkis = ["client/crowkis.proto"]`.
   - Check the wheel: `python -m pip wheel python --no-deps -w $S/wheel`, then `python -m zipfile -l
     $S/wheel/crowkis-0.5.2-*.whl` lists `crowkis/client/crowkis.proto` and every `crowkis/client/*.py`. Delete the
     stale, untracked `python/build/` and `python/crowkis.egg-info/` first, so an old copy can't hide a missing file.
4. **The Node move.**
   - `git mv index.js src/client/commands.js`, then rebuild a thin `index.js` from its export block, and cut
     `connection.js` and `admin.js` out of `commands.js`. `git mv` `config.js`, `agent.js`, `grpc.js`,
     `crowkis.proto` → `src/client/`; `langchain.js`, `memory.js`, `livekit.js` → `src/integrations/`;
     `conformance.js`, `golden.js` → `test/`. (`git mv index.js` keeps history with the 1,000 lines that move;
     the new `index.js` is a new file.)
   - Audit #5: `src/client/grpc.js` requires `toBuffer` from `./connection.js`.
   - Repoint every require in the audit's list (src 3 files, the moved integrations 3, tests 39 + the two helpers).
   - `package.json`: `exports` `./agent`, `./livekit`, `./langchain`, `./memory` get the new `default` paths (their
     `types` stay); `files` drops `config.js`, `agent.js`, `grpc.js`, `crowkis.proto`, `langchain.js`, `memory.js`,
     `livekit.js` and adds `src/client/{connection,commands,admin,config,agent,grpc}.js`,
     `src/client/crowkis.proto`, `src/integrations/{langchain,memory,livekit}.js`.
   - `test-package.js` proves every packaged require is packaged; `test-packaging.js` proves ESM names, subpaths and
     types; `npm pack --dry-run` must list `src/client/crowkis.proto`.
5. **Check.** Frameworks: Pipecat (`integrations/pipecat.py`), LiveKit Python and JS (`livekit.js` moved), Bolna
   (`integrations/bolna/__init__.py` imports `CrowkisError`; `tests/test_bolna.py` imports `crowkis.client.agent`).
   The examples tests (`test_examples.py`, `test-examples.js`). `graphify update .`. One Opus review: is it a pure
   move, did any cycle appear, are public names and subpaths unchanged, is the proto in the wheel and the tarball.
   Then update the file map in `D:\Tarkova\sdk-docs\CODEBASE-GUIDE.md` and `v4-notes/progress.md`.

## Choices for the owner

- **gRPC flat (`client/grpc_stub.py` + `client/crowkis.proto`) or a `client/grpc/` folder?** Flat is one file
  fewer. A folder needs `client/grpc/__init__.py` to ship, and `package-data` becomes
  `crowkis = ["client/grpc/crowkis.proto"]`.
- **`AsyncCrowkisClient` in `commands.py` or its own `client/async_commands.py` (~320 lines)?** Together keeps one
  file per job and no helper imports; apart leaves `commands.py` at ~1,400 lines.
- **The behaviour fixes the audit lists** (CGET/CSET frames and the async `TEMPLATE` drop, the line cap, admin
  empty bodies, the gRPC default port) are separate, owner-approved changes. None is part of this move.

## Decided (R1 session, 2026-11-04)

- **gRPC goes in a `client/grpc/` folder,** as the owner's brief drew it: Python `client/grpc/__init__.py`
  (docstring), `client/grpc/grpc_stub.py`, `client/grpc/crowkis.proto`; package data
  `crowkis = ["client/grpc/crowkis.proto"]`. Node `src/client/grpc/{grpc.js,crowkis.proto}`.
- **`AsyncCrowkisClient` stays in `commands.py`** (one file per job, no helper imports).
- The behaviour fixes stay out of this job.
