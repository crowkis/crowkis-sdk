# F3: golden decisions changed on purpose

## MT4: "I don't have that information" and "I need to know / please let me know" are non-answers

Rule `NonAnswer` (save stage). Phrases added to `_NON_ANSWER_PHRASES` (Python and Node).

- `chat/stress-v2.json`, "Do you have any sales this week?" answered "I'm sorry, but I don't have that information.":
  outcome `saved` -> `refused:non_answer` (the saved-answer count 5 -> 4, `save_refused` 0 -> 1, and the
  write is gone from the store log). This is the bug: a fallback answer was shared.
- `voice/stress-v2.json`, calls B02, B04, H06: only the `uncacheable_personal` counter is one lower
  (an answer that is a non-answer is stopped by `NonAnswer` before `PersonalTemplate` counts it). No turn's
  action, rule, save_rule or stored flag changed.
