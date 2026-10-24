"""Crowkis in a Bolna voice agent.

The one-line setup: register the provider once at start-up, then name it in the agent.

    from crowkis.integrations.bolna import register_crowkis

    register_crowkis()                 # adds provider "crowkis", in front of Bolna's "openai" LLM
    # agent config:  "llm_config": {"provider": "crowkis", "model": "gpt-4o-mini", ...}

    register_crowkis(name="crowkis-azure", base="azure", session_options={"latency_budget_ms": 250})

Bolna builds one LLM per call and picks its class by provider name. The class registered
here wraps Bolna's own LLM (a Decorator) and owns one Crowkis voice session per call, built
from ``session_options`` (server settings from the CROWKIS_* environment variables) or by
``session_factory``. The same privacy rules as the Pipecat and LiveKit adapters apply.

Cached: a caller's general question. A hit is streamed to Bolna's speech side without
calling the model; on a miss the model reads the app's system prompt and the question alone.

Never cached: a turn with anything personal in it, and everything after a caller told the
call something about themselves (those answers read the whole call and stay in it); tool
calls and their follow-ups; speculative (eager) turns; keypad and language-switch turns;
silence nudges; JSON requests; graph, knowledge-base and multi-agent tasks; an answer that
repeats a caller detail the system prompt holds.

Saved: a model answer is saved only once Bolna has written it to its history in full, so a
reply trimmed or dropped by a barge-in never is. It is settled when the next turn starts
and when the call ends (``close()``).

A failure in Crowkis never breaks a call: the model answers instead.

Needs ``bolna`` (0.10.x). Nothing outside this package imports it.
"""

from .errors import CrowkisBolnaError
from .llm import CrowkisLLM
from .registration import register_crowkis

__all__ = ["CrowkisLLM", "register_crowkis", "CrowkisBolnaError"]
