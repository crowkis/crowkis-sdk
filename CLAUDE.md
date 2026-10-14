# Crowkis SDK — the change wall

The SDK runs inside customers' production apps, including live voice calls. Nothing that already
works may break. Every change, however small, goes through these steps, in order, every time.

## 1. Find the place through the graph, then change only that

- The knowledge graph of the SDK is in `graphify-out/` (built locally from the code). Start there:
  - `graphify query "<what you are looking for>"`, `graphify explain "<function or class>"`,
    `graphify affected "<function or class>" --depth 2`, `graphify path "<A>" "<B>"`;
  - `graphify-out/wiki/index.md` for a module map, `graphify-out/GRAPH_REPORT.md` for the overview.
- Read the files the graph points to before editing; grep every caller.
- Change only what was asked. Smallest root-cause fix; no drive-by refactors, no over-engineering.
- Never change an existing public function: same name, arguments, return values, errors and
  behaviour. New things are additions only. Python and Node change together and stay in parity.
- Graph missing or stale: `graphify update .` (local, seconds; also runs after every commit).

## 2. Prove it with tests

- A test that fails before the change and passes after it, for every behaviour changed or fixed,
  in both Python and Node, plus "must still work" controls for the opposite case.
- Edge cases that apply: empty, very long, Unicode and non-Latin text, Hinglish and other
  Latin-script languages, numbers with separators or in words, concurrent calls, server errors.
- Voice privacy: a caller's private detail must never be shared with another caller. When unsure,
  keep it private; over-privacy only costs savings.
- Existing tests are not edited to make a change pass, unless they asserted the bug (say which).
- Run the full Python and Node suites, more than once.

## 3. Review, then commit

- Independent code review, privacy/security review (no personal data shared or logged, no secrets),
  and a check through the real server for user-visible behaviour.
- No co-author trailer in commits. Nothing is pushed until the owner has seen the change.
