# C: the original suite on v4 (P1, 2026-11-04)

The original repo's tests (`D:\Tarkova\crowkis-sdk`, `feat/voice-adapters`, read only) and its `examples/` were run against the v4 package. Copies lived in a scratch folder: Python in a fresh venv with v4 installed editable, Node with v4's `node/` files. The old repo was never written to. The same copied tests were also run against the old package as a baseline: **Python 690 passed / 91 skipped, Node 40/40 files** (frameworks not installed in that venv: their tests skip).

## Run 1: as written

Nothing reached an assertion. Every old test imports an internal path that v4 removed on purpose (owner exception **P5.6**; R1 moved the client files).
- **Python:** 51 errors (41 collection + 10 setup through `conftest.py`'s `crowkis.voice._reset_prompt_baselines`).
  - Missing modules: `crowkis.agent`, `crowkis.voice`, `crowkis.callstate`, `crowkis.chat`, `crowkis.voice_turns`, `crowkis.session`, `crowkis.openai_wrapper`.
  - Missing names: `CrowkisAdmin`, `CrowkisError`, `AsyncCrowkisClient` from the `crowkis.client` module (now a package).
- **Node:** 35 of 40 files failed. 33 of them were `MODULE_NOT_FOUND` (`./agent.js`, `./voice.js`, `./chat.js`, `./turn.js`, `./verify.js`, `./memory.js`, `./conformance.js`).

All of this is class **(a)**: internal paths moved. Apps that import only the public names are not affected; test A pins those names.

## Run 2: through an alias shim

The shims are kept in [old-suite-shim/](old-suite-shim/):
- `_v4_alias.py`: a `sys.meta_path` finder that maps each old module path to the v4 module defining the name.
- `_v4alias.js`: the Node equivalent; each old `./x.js` file is a one-line stub that calls it.

They resolved every name the old tests asked for. Then:

| Suite | Result |
|---|---|
| Python, old tests on v4 | 688 passed, 2 failed, 91 skipped (after retargeting two patches, below) |
| Node, old tests on v4 | 39/40 files; 500 pass, 1 fail, 30 skipped |
| `test_examples.py`, `test-examples.js` | pass |
| `examples/*` imported against v4 | all names resolve; LangChain example needs LangChain; two Node examples need a server |

Every failure, classified (Opus):

| Test | Class | Why |
|---|---|---|
| `test_help_names::test_the_openai_wrapper_is_named_where_it_lives` | (a) moved path | It expects the help text to say `crowkis.openai_wrapper.CachedOpenAI`. R1 moved it to `crowkis.integrations.openai.CachedOpenAI` and updated the help text. |
| `test_server_052_replies::NotStoredTests::test_cset_does_not_raise_and_warns_once_per_reason` | (b) approved change | `cset` returns `False`, not `None`, on a `NOTSTORED` reply. This is the MT2 fix, `acbd1f1` (v4 F3): the SDK said "saved" for answers the server refused. |
| `test_voice_slow_writes::test_a_hung_server_never_queues_writes_without_limit` | (a) | `patch.object(voice, "_WRITES_MAX", 3)` patched the shim, not `crowkis.channels.voice_session`. **Passes** once retargeted. |
| `test_voice_undecided_turns::test_a_long_history_is_checked_once_per_turn_text` | (a) | `mock.patch("crowkis.voice._sets_context")` patched the shim. **Passes** once retargeted to `crowkis.channels.voice_session._sets_context` (call count 300). |
| Node `test-package.js` | (a), the old test's assumption | It checks each `require("./x.js")` by its bare name against `package.json` `files`. `src/client/commands.js` requires `./config.js`, which is `src/client/config.js` and is listed. Test B walks every nested require from each export and checks the tarball, and that passes. |

**Class (c), real regressions: none.**

Not run here: the old framework tests (Pipecat, LiveKit, Bolna: no frameworks in the scratch venv; the v4 suites run them) and the old real-server mode (test G runs v4's conformance against the server).

Raw data (per-test lists and logs): `old-suite-raw.md` in this group's side-session notes folder.
