# F8 step 3: Chat's protections replayed through `voice_session(channel="chat")`

How: `v4-notes/tools/f8_chat_replay.py` (from `python/`; `--stub` plugs in a stub LLM = `LLMClassifier` +
`LLMRewriter` over the frozen stand-in frames) replays every call of `fixtures/golden/inputs.json` (the
277 phrases, stress v1/v2, conformance, hit-guards: 1413 turns) through the chat-channel voice session and
compares each turn Chat kept private or refused to save (1039 turns) with what voice does. The Chat cases
of the privacy fuzz run through `voice_session(channel="chat")` with no LLM and with a stub LLM
(`test_privacy_fuzz.py::ChatOnVoiceFuzz`, `test-privacy-fuzz.js` "chat on voice"): 0 leaks. The V-rules
(V3-V10) are frame-driven, so a word-rules replay can only compare the turns' texts; the Chat unit
cases (`test_verify.py`, `test_chat.py`) were probed by text (see "Chat rules, one by one").

## Golden inputs: 107 turns without an LLM, 99 with the stub (all hit gains)

| Chat's reason | turns | voice does | decision |
|---|---|---|---|
| V5_untagged_name (78 / 73) | "Do you ship to Australia?", "What is the capital of Australia?" | shares and saves | **Hit gain.** The stand-in frame has no entity tags, so Chat read every capital word as a name. Voice shares a place; a model's tag, not fixed code, tells "Priya" from "Australia". |
| V10_unresolved (22 / 20) | "How long does it take?" after "Do you deliver to Port Blair?" | looks up and saves keyed on the chain of earlier shareable turns | **Hit gain.** The key is the chain; a chain with a private turn is private (`PrivateChain`). |
| cache hit, outcome None (4) | "Is the store open on Sundays?" | miss in the replay | Not a difference (counted because a served hit has no outcome). |
| refused:private_word (2) | "And by express?" after a private parcel question | chain-keyed, saved | **Hit gain**, same as V10. |
| V3_not_general (1, no LLM only) | "Hmm, how long does standard shipping, uh, take?" | shares | **Hit gain**: fillers do not make a question private. |

No turn Chat kept private for a *privacy* reason was shared by voice in this replay.

## Chat rules, one by one

| Chat rule | On voice | Decision |
|---|---|---|
| V4 AboutSomeone ("my mother", "the shoes I bought") | `OwnRecords` / `_names_someone`: private | covered |
| V5 IdentifyingDetails (email, phone, long number, id) | `_never_share`: private | covered |
| V5 formatted ids ("AB-123-456", "ZB1234XY"), card numbers | private | covered (probe) |
| V5 URLs | **shared** | **gap G3** (below) |
| V5 QuestionNamesCaller / UntaggedName | person in the question: private only near a record word | **gap G2** (below); "for Sarah" is a hit gain, see G2 |
| TaskStep ("book it", "under 100 dollars for two", an answer to the agent's question) | `TooShort`, `ConfidenceBar`/follow-up chain, `OwnRecords`: private | covered (probe, 2-turn flows) |
| V6 ungrounded / V7 lost (rewrite checks) | `accepted_rewrite`, `stated_fact_irrelevant`, kept for a future LLM | covered when an LLM is plugged in |
| V10 unresolved follow-up | chain-keyed | hit gain |
| `PrivateWord` (answer repeats a caller word) | `VoicePrivateWord` only with an understander | **gap G1** |
| pasted paragraph / very long turn | `_MAX_TURN_CHARS`: private | covered |
| urgent, sensitive | `_urgent`, `_sensitive_self`: private | covered |

## Real gaps, closed here (shared by both channels; failing-first tests in both languages)

- **G1: a caller's private words in a shared answer, without an understander.** The words of turns the
  rules kept private (names, numbers, capitalised words) were only remembered when a classifier was
  plugged in, and `VoicePrivateWord` was only in `RuleSet.understood()`. A model that already knows the
  caller (system prompt, app history) could write the name into an answer to a general question and
  voice saved it shared. Now `CallState` always remembers them and `VoicePrivateWord` is in the base
  voice save chain (`rules/save/caller_specific.py`). Tests: `test_chat_on_voice.py` /
  `chatOnVoice.test.js` (name the model knows; clean answer after a private turn still saves).
- **G2: a question naming a person.** "What did Priya order last week?", "Has Sarah paid yet?", "asks Anita
  about the refund policy", "the manager named Rahul": the name went into the shared key and the answer is
  about that person. `_capitalised_name` (`understanding/word_rules/text.py`, behind `OwnRecords`) now
  also reads a capitalised word right after `named / called / asks / says` as a person, and after
  `did / does / has / had / was / will` only when a person's action follows ("did Priya order", "has Sarah
  paid"); "does Netflix have a plan" is a brand and stays shared (the Opus review found the first, wider
  version made brand questions private). **Not** "for": the rules cannot tell "for Sarah" from "for Goa", so
  "What time is check-in for Sarah?" stays shared (accepted: low severity, the answer is general; an LLM's
  entity tag handles it when one is plugged in). Lower-case names from speech-to-text are not read (known
  limit; the same as before).
- **G3: a link in the question.** `https://...` and `www....` may carry a token or an id; `_never_share`
  now keeps the turn private.

## Not done on purpose (hit gains accepted)

V5_untagged_name on any capital word, V10 on any follow-up, and "for <Name>" (see G2). Each costs hits and
protects only what a model tag handles better.
