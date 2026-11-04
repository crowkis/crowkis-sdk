# Plan: `understanding/` in the fewest files, grouped in meaningful subfolders (2026-11-04)

The owner wants the fewest files, each in a subfolder that means something. This plan builds on
`understanding-ultra-audit.md`: its deletions and folds run first, then the files are regrouped. Nothing changes
behaviour: golden files stay identical and public names stay the same. Python and Node change together.

## Target layout

```
understanding/                  how a caller's turn is read
  __init__.py      docstring only
  slots.py         the slots and their default fill:                                              ~200
                   Reading, Classifier, Rewriter (slots), WordReading + WordRuleClassifier
                   (word_rule_classifier), NoRewrite (no_rewrite), TextOnlyClassifier (text_only_classifier),
                   BudgetedReading + BudgetedUnderstanding (budgeted_understanding: the budget and fallback)
  model/           what a model makes of a turn, and the checks on it
    __init__.py    empty
    frame.py       TurnFrame, Entity, FactRelevance, Attribute (turn_frame) + FrameReading (frame_reading)  ~230
    understanders.py  Understander, ReplayUnderstander, LLMUnderstander, WithFallback, INSTRUCTIONS
                   (understanders) + LLMClassifier, LLMRewriter, ReplayRewriter (llm_classifier,
                   llm_rewriter, replay_rewriter): the model and its two slot adapters                    ~270
    checks.py      accepted_rewrite (rewrite_check) + stated_fact_irrelevant (fact_relevance):
                   what may come of a model's output                                                     ~85
  word_rules/      the fixed English word checks (default, no model)
    __init__.py    docstring only
    text.py        text + phrases (shared vocabulary and phrase matching)                                ~700
    personal.py    personal + identifiers                                                                 ~860
    urgent.py      unchanged                                                                              137
    follow_up.py   unchanged                                                                              201
    call_context.py  call_context + high_risk                                                             ~365
    answers.py     answers + prompt_details (checks on a model's answer)                                  ~315
    chat.py        Chat's own word checks: frame_words + chat_details + answer_patterns                   ~210
```

Node has the same shape in camelCase: `slots.js`, `model/{frame,understanders,checks}.js`, and
`wordRules/{text,personal,urgent,followUp,callContext,answers,chat}.js`. It has no `index.js`, no `__init__`, no
Protocols and no `TextOnlyClassifier`.

| | Files now → after | Lines now → after (approx.) |
|---|---|---|
| Python `understanding/` | 28 → 14 (11 code files + 3 `__init__.py`) | 3,933 → ~3,630 |
| Node `understanding/` | 25 → 11 | 3,415 → ~3,380 |

Why these groups:
- **`slots.py`**: everything a `VoiceSession` plugs together. The budget and fallback live here because
  `BudgetedUnderstanding` is the slots' one error boundary.
- **`model/`**: a model's output from parse (`frame`), to who produces it (`understanders`), to what the SDK
  accepts of it (`checks`).
- **`word_rules/`**: every fixed English check. Chat's checks join as `chat.py`: they are word rules too, tuned
  separately (the audit's "Keep" lists why they stay apart from the voice ones).
- The small word-rule modules join the module that already imports them (`high_risk` → `call_context`) or that
  covers the same ground (`phrases` → `text`, `identifiers` → `personal`, `prompt_details` → `answers`). `urgent`
  and `follow_up` stay on their own. `personal` would pass 1,000 lines with `urgent` in it.

**Name clash in `word_rules/chat.py`.** `answer_patterns._EMAIL` / `_LONG_DIGITS` differ from `frame_words`'
(the audit lists how). The answer ones become `_ANSWER_EMAIL` / `_ANSWER_LONG_DIGITS` (Node: `ANSWER_EMAIL`,
`ANSWER_LONG_DIGITS`). Callers: `rules/save/caller_specific` (py and node) and `chat_details` itself.

**Import cycles (checked).**
- `model/frame` imports nothing from the SDK.
- `word_rules/chat` needs `TurnFrame` only for annotations in Python, so it goes under `TYPE_CHECKING`. In Node it
  reads `NOT_GENERAL_TYPES` at load, and `model/frame.js` requires nothing back, so there is no cycle.
- `model/checks` imports `frame`, `word_rules/{chat,text,call_context}`, and `SessionCall` under `TYPE_CHECKING`.
  This is why the checks are not in `frame.py`: `word_rules/chat` → `frame` → `chat` would be a cycle in Node.
- `slots` imports `word_rules` and `runtime/stats`. `model/understanders` imports `state/call_state`, which imports
  `slots`, `model/frame`, `word_rules/chat` and `word_rules`. None of these import `understanders` back.

## Steps (each one commit; full Python + Node suites after each; golden files unchanged)

1. **Deletions** (audit #1-#4, #7, #8): re-export blocks and unused imports go, every importer imports from the
   defining module, and `word_rules/__init__.py` becomes a docstring. Node's `wordRules/index.js` is deleted.
2. **Folds** (audit #5, #6): `stated_fact_irrelevant` and `accepted_rewrite` become functions, with a test each
   first.
3. **The move.** Each new file is made with `git mv` from its biggest source, so history follows, and the rest is
   appended. Every import is repointed (the caller lists are in the audit; after step 1 every importer names its
   module directly, so the repoint is a path rename). `crowkis/__init__.py` and Node `index.js` lazy getters point
   at `model/understanders` and `model/frame`.
4. **Check.** Frameworks (Pipecat, LiveKit Py/JS, Bolna; `integrations/bolna/synthesizer.py` imports
   `word_rules.text`, `tests/test_bolna.py` imports `word_rules.prompt_details` → `answers`), `graphify update .`,
   and one Opus review: is it a pure move, did any cycle appear, are public names unchanged.

## Choices for the owner

- **`word_rules/` flat or merged further?** 7 files is the plan. Merging `urgent` and `follow_up` too gives 5,
  but `personal.py` would pass 1,000 lines.
- **`slots.py` at the top, or a `slots/` folder?** One file is fewer. The brief allowed either.
