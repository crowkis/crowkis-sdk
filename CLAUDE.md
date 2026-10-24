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

## 4. Engineering rules for new and refactored code

These apply to every class written or rewritten, and to the whole v4 refactor
(`../sdk-docs/v4-refactor-plan.md`). The change wall above wins any conflict: public behaviour never changes
to satisfy a style rule. Code nobody is touching is not rewritten just to comply.

**Design**
- OOP and SOLID. One reason to change per class; if it needs "and" to describe, split it.
- Add behaviour by adding classes (a new rule, a new understander, a new channel), not by adding branches
  to existing ones. A long `if` chain over the same thing becomes a Strategy, a Chain of Responsibility or
  a list of objects.
- Small interfaces (`Classifier`, `Rewriter`, `QuestionRule`, `HitRule`, `SaveRule`, `Channel`). Inject
  collaborators through the constructor. Only factories (`voice_session()`, `async_voice_session()`,
  `voiceSession()`) and facades build them: they are the composition roots.
- Name the pattern in the class docstring when one is used, and use one only where it removes a real
  branch or coupling.

**Structure**
- Organise by responsibility (turns core, rules per stage, understanding, call state, cache keys, runtime,
  channels, integrations), one class per file unless the classes are tiny and tightly related (a family of
  small rules may share a file).
- No `utils` / `helpers` / `common` / `misc` / `manager` modules. No glue functions that only reshape data
  between two parts: fix the contract or add a named Adapter.
- Dependencies point one way: the core depends on interfaces, rules and understanders implement them.
  No circular imports.
- Old import paths (`crowkis.voice`, `crowkis.session`, `crowkis.verify`, `node/voice.js`, ...) keep working as
  re-exports. Python and Node keep the same layout and the same class names (camelCase methods in Node).

**Errors: fail open, in one place**
- A live call never ends because of Crowkis. That is not "swallowing": each concern (lookup, write,
  understanding, audio, reporting) has exactly one boundary that turns a failure into a typed outcome
  (`slow_write`, `refused`, an uncertain frame), counts it in `stats()` and logs it. Nothing else catches.
- Inner code raises specific errors from one small hierarchy rooted in `CrowkisError`. No empty catch
  blocks, no magic return values, no error codes.
- Validate once at the boundary by building typed objects; no defensive re-checks inside.
- Deadlines, retries and bounded writes live in their own runtime components, never inline.

**Readability**
- Full, intention-revealing names. Functions short and doing one thing (aim under 20 lines).
- No magic numbers or strings: thresholds, budgets and outcomes are named constants or enums.
- Privacy rules are word lists by nature. Keep the phrases as named data (constants or `fixtures/`), and
  any regex in a named constant with a comment and a test. No clever one-liners or nested comprehensions.
- Comments say why, never what. Docstrings on every public class and method. Type hints everywhere
  (`*.d.ts` in Node); prefer immutable value objects (`TurnFrame`, `Verdict`, `Channel`).
- No dead code, commented-out code or speculative features.

**Debuggability**
- The flow reads top-down: factory, facade, turn core, stages, rules.
- No global mutable state or singletons with hidden state: thread pools, pending-write sets and caches are
  injected runtime objects. No monkey patching.
- Log only at component boundaries through an injected logger. Every decision carries the name of the rule
  that made it, and `stats()` counts per rule.
- Every class is testable alone with injected fakes.

**The one rule above these:** the refactor puts readability, OOP and SOLID first, but anything that
works today must still work after it. (How that is kept in practice: `../sdk-docs/v4-refactor-plan.md`, appendix A.)

**Server independence:** every call to the server goes through one protocol layer (`transport/`). The rest of the
SDK never builds commands or reads raw replies, so a server change touches that layer only, or nothing.

**Before finishing**, check: one responsibility per class; no new branch that should be a class; no glue
or helper modules; dependencies injected; one error boundary per concern; no magic values or dead code;
a newcomer can follow the flow; both languages' tests pass, with failing-first tests for behaviour changes.
