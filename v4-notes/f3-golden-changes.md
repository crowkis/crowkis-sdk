# F3: golden decisions changed on purpose

## MT4: "I don't have that information" and "I need to know / please let me know" are non-answers

Rule `NonAnswer` (save stage). Phrases added to `_NON_ANSWER_PHRASES` (Python and Node).

- `chat/stress-v2.json`, "Do you have any sales this week?" answered "I'm sorry, but I don't have that information.":
  outcome `saved` -> `refused:non_answer` (the saved-answer count 5 -> 4, `save_refused` 0 -> 1, and the
  write is gone from the store log). This is the bug: a fallback answer was shared.
- `voice/stress-v2.json`, calls B02, B04, H06: only the `uncacheable_personal` counter is one lower
  (an answer that is a non-answer is stopped by `NonAnswer` before `PersonalTemplate` counts it). No turn's
  action, rule, save_rule or stored flag changed.

## VD3: a recap of the caller's own call is private

Rule `OwnRecords` (question stage, via `_never_share`): phrases "so far", "know about me", "have on me / about me",
"on file for me", "recap" added to the memory-of-this-call phrases (Python and Node).

- `voice/stress-v1.json` and `voice/stress-v2.json`, the insurance call with "So what details do you have so far?"
  after the caller told the call their details: `save_rule` `TaintedCall` -> `PersonalTemplate`, `not_stored` text
  changes accordingly, `stored` stays false. The turn is now read as personal (whole call, never shared) instead of
  only being kept out by the call's taint, so it also holds in a call that told nothing. Counters follow
  (`not_shareable` 15 -> 14, `TaintedCall` 14 -> 13, `PersonalTemplate` 13 -> 14).
