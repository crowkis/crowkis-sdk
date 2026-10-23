---
title: Voice agents
path: /docs/voice
sdk_version: 0.5.2
---

# Voice agents

*Crowkis SDK 0.5.2 · Python and Node.js*

Most of what callers ask a voice bot has been asked before: opening hours, a refund policy, how to reset a password. Crowkis answers those from its cache, so the LLM never runs, and with cached audio the TTS doesn't either. The caller hears the answer sooner, and you pay for fewer model and speech calls.

Every other turn goes to your LLM as before. Its answer is saved for the next caller only when it is safe to share.

## Pick your setup

| You use | Page | How Crowkis plugs in |
|---|---|---|
| Pipecat | [Pipecat](/docs/voice/pipecat) | Wrap your LLM and TTS services: `CrowkisLLM(...)`, `CrowkisTTS(...)` |
| LiveKit Agents (Python) | [LiveKit, Python](/docs/voice/livekit-python) | Add `CrowkisVoice` to your `Agent` class |
| LiveKit Agents (Node.js) | [LiveKit, Node.js](/docs/voice/livekit-node) | Wrap your agent: `withCrowkis(agent)` |
| Your own loop (STT → LLM → TTS), Python | [Custom loop, Python](/docs/voice/custom-loop-python) | One call per caller turn: `session.respond(...)` |
| Your own loop, Node.js | [Custom loop, Node.js](/docs/voice/custom-loop-node) | One call per caller turn: `session.respond(...)` |

## Before you start

You need:
1. **A running Crowkis server** (see [Docker deployment](/docs/docker)).
2. **The SDK:** `pip install crowkis` or `npm install @crowkis/client`.
3. **The server's details in the environment** (or a `.env` file). Every page below reads them:

```bash
# .env
CROWKIS_HOST=10.0.0.5
CROWKIS_PORT=6383
# if the server sets one
CROWKIS_AUTH_TOKEN=change-me
# optional
CROWKIS_TENANT=my-app
```

The SDK doesn't load `.env` files itself. Use `python-dotenv`, `dotenv` (Node), `node --env-file=.env` (Node 20.6+), or your platform's settings.

## What Crowkis promises on every setup

- **One caller's private details never reach another caller.** These stay in that call and are never shared:
  - a turn about the caller's own records ("my order 48213…");
  - a turn after the caller tells the call something an answer depends on ("I'm allergic to peanuts");
  - an answer built from a tool's result;
  - an answer that repeats a caller detail from your system prompt.
- **An interrupted answer is never saved.** If the caller talks over the bot, that half-spoken answer is never served to anyone.
- **A cut-off question is never answered from the cache.** "Do you deliver on…" goes to the LLM.
- **A slow or broken server never breaks a call.**
  - A turn waits for Crowkis at most 250 ms, then goes to your LLM as normal.
  - Saving a new answer waits at most 500 ms, then finishes in the background.
  - If the audio cache fails, the text is still spoken.

## Check it's working

Every setup gives you the session's `stats()`. After a few calls that repeat a question:

```text
{'turns': 12, 'served_from_cache': 7, 'model_calls': 5, 'cache_hit_pct': 58.33, ...}
```

`stats()` has more counters than the table shows, one per reason a turn wasn't cached; all start at 0. The full set (Python names; Node uses camelCase) is: `turns`, `served_from_cache`, `answered_by_filler`, `model_calls`, `refused_too_short`, `refused_to_share_a_private_answer`, `uncacheable_personal`, `missed_latency_budget`, `barge_ins`, `cache_unavailable`, `failed_writes`, `slow_writes`, `different_question`, `not_shareable`, `commitments_sent_to_model`, `unspeakable_answers`, `empty_answers`, `audio_unavailable`, `cache_hit_pct`, `filler_hit_pct`, `model_calls_avoided_pct`.

| Field | What it tells you |
|---|---|
| `served_from_cache` / `servedFromCache` | Turns answered without the LLM. |
| `model_calls` / `modelCalls` | Turns your LLM answered. |
| `cache_unavailable` / `cacheUnavailable` | Lookups that failed (server down or refusing); each went to the LLM. |
| `missed_latency_budget` / `missedLatencyBudget` | Lookups slower than 250 ms; each went to the LLM. |
| `slow_writes` / `slowWrites` | New answers the turn stopped waiting to save (a slow server); they finish in the background. |
| `audio_unavailable` / `audioUnavailable` | Turns whose cached audio couldn't be used; the text was spoken. |

If `served_from_cache` stays at 0 while callers repeat questions, see [Troubleshooting](#troubleshooting).

## Choosing a test question

To see a hit, ask **the same general question twice**. Crowkis keeps some questions private on purpose, so they never hit:

| Never cached | Examples |
|---|---|
| About the caller's own records | "where is **my** order", "my account balance" |
| With an ID-like word, a long number, an email, or a person's or pet's name | "order 48213", "code ab12cd", "a dog **named** Rex", "I'm Asha" |
| After the caller tells the call something | "I'm diabetic", then any later question in that call |
| Cut off mid-question | "do you deliver on" |

A **commitment** (a price, a refund, a policy) is served only for the exact same words, never for a rewording.

Place, product and business names are fine ("the Riverside Museum").

Use real, distinct words in tests, and check that the **first** turn is `infer`. On a server other people use, a first-turn `serve` means someone else's answer matched: print `decision.text` to see what was served. Made-up words carry almost no meaning to the matching model, so two different made-up names can match each other.

With a local server, a repeat is found at once. Allow about a second on a busy server or with the decision engine. Running a test a second time serves both turns, because the first run taught the cache the answer.

## What `decision.reason` means

| `action` | `reason` (start of it) | Meaning |
|---|---|---|
| `serve` | `confident cache hit` | Answered from the cache. |
| `filler` | `registered filler…` | One of your `fillers` answered it. |
| `infer` | `confidence below the spoken-answer bar of 0.92` | No stored answer was close enough. This includes an empty cache, so it's the usual reason for a first-time question. |
| `infer` | `the caller asked about their own records…` | A personal question: never cached. |
| `infer` | `the caller has told this call something…` | Every later turn in this call is private. |
| `infer` | `a follow-up to a private turn…` | Leans on an earlier private turn. |
| `infer` | `the turn was cut off mid-question` / `transcript too short…` | Not a complete question. |
| `infer` | `the cached answer was saved for a different question…` | A stored answer matched, but its question asks about something else ("the airport bus" vs "the harbour ferry", "Saturday" vs "Sunday"). Your LLM answers instead of a wrong answer being served. |

After the answer is recorded, `decision.stored` says whether it was saved for the next caller, and `decision.not_stored` (`notStored` in Node) says why not. It's empty when there's nothing to explain: the answer was saved, or the turn was served from the cache. On a served turn `stored` is `false`, because nothing new needed saving.

## Troubleshooting

| You see | Likely cause |
|---|---|
| `cache_unavailable` goes up every turn | The bot can't reach the server. Check `CROWKIS_HOST` / `CROWKIS_PORT` / `CROWKIS_AUTH_TOKEN`. |
| `missed_latency_budget` goes up | The server is more than 250 ms away. Run it closer to the bot, or raise `latency_budget_ms` (Node: `latencyBudgetMs`). |
| Repeated questions never hit | Is the answer personal ("my order…"), or a commitment (a price, a refund, a policy)? A commitment is served only to the exact same question. With the decision engine on, a new answer is served once the engine has checked it, usually within a second. |
| A hit is spoken by the TTS anyway | The audio is cached on the next hit, not the first. Audio is also kept separately per voice, language, speed and format. |
