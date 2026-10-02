"""Discoverable, human-friendly help for the Crowkis SDK.

    import crowkis
    crowkis.help()            # everything, grouped
    crowkis.help("memory")    # just the agent-memory commands
"""

from __future__ import annotations

from typing import List, Optional, Tuple

# (group title, [(call, one-line description), ...])
_GROUPS: List[Tuple[str, List[Tuple[str, str]]]] = [
    (
        "Semantic cache — stop paying twice for repeated & rephrased prompts",
        [
            ("client.get_or_compute(query, fn)", "return the cached answer, else run fn() and cache it"),
            ("client.cget_hit(query)", "semantic lookup; returns a CacheHit (text, similarity, confidence)"),
            ("client.cset(query, answer, ttl=3600)", "cache an answer for a query"),
            ("client.csim(query, k=10)", "the k most similar cached queries"),
            ("client.cflush()", "clear this tenant's cache"),
        ],
    ),
    (
        "Turn understanding — chat & voice agents  (see CallSession)",
        [
            ("CallSession(agent, understander, on_urgent=..., replay=...)", "one call: understand, check, route, cache safely"),
            ("session.handle(turn)", "TurnResult: cached text, or exactly what the model may read"),
            ("session.record_answer(result, answer, mentions=..., task=...)", "save if allowed; update the call state"),
            ("session.cancel()", "barge-in: nothing from this turn is saved"),
            ("session.set_mode('off' | 'replay_only' | 'full')", "kill switch / run without a model"),
            ("LLMUnderstander(complete) / ReplayUnderstander(known)", "interim model over any LLM / exact repeats only"),
            ("RuleChecker(confidence_floor=, ttl=, knowledge_version=)", "the fixed sharing rules and key builder"),
        ],
    ),
    (
        "Agent memory — durable, semantic, per-user  (see CrowkisMemory)",
        [
            ("CrowkisMemory(agent, user=...)", "one object for an agent's long-term memory"),
            ("mem.remember(fact)", "store a fact to recall later"),
            ("mem.recall(query, k=5)", "semantically recall relevant facts"),
            ("mem.extract(conversation)", "pull salient facts out of a transcript"),
            ("mem.forget(query=...)", "forget matching facts"),
        ],
    ),
    (
        "Sessions — short-term conversation memory",
        [
            ("client.csession_add(session, role, text)", "append a turn"),
            ("client.csession_recent(session, n=...)", "the last n turns"),
            ("client.csession_search(session, query, k=...)", "search within a session"),
        ],
    ),
    (
        "Quality & safety",
        [
            ("client.cpin(query, answer)", "pin a curated answer that always wins"),
            ("client.cflag(query, bad_answer)", "mark a bad answer so it stops being served"),
            ("client.cguard(text) / client.coutcheck(text)", "input / output safety checks"),
        ],
    ),
    (
        "Cost & FinOps",
        [
            ("client.cbudget_set(tenant, daily_usd=...)", "set a spend budget the gateway enforces"),
            ("client.cbudget_get(tenant)", "current spend vs budget"),
            ("client.ckeylimit_set(tenant, rpm=...)", "per-tenant rate limits"),
        ],
    ),
    (
        "Operations — CrowkisAdmin (HTTP management API)",
        [
            ("CrowkisAdmin(base_url).get_stats()", "cache stats & hit rate"),
            ("admin.register_webhook({...})", "source-linked cache invalidation"),
            ("client.csave(dest) / client.creload()", "snapshot / reload persistence"),
        ],
    ),
    (
        "Framework integrations",
        [
            ("crowkis.integrations.langchain.CrowkisCache", "set_llm_cache(...) — semantic cache for LangChain & LangGraph"),
            ("crowkis.CrowkisMemory", "agent memory for LangGraph / CrewAI / AutoGen / custom loops"),
            ("crowkis.CachedOpenAI", "drop-in OpenAI client wrapper (change 2 lines)"),
        ],
    ),
]

_INTRO = (
    "Crowkis — intelligent, Redis-compatible cache & memory for LLM apps and agents.\n"
    "Connect:  client = crowkis.CrowkisClient(tenant=\"my-app\")\n"
    "Docs:     https://crowkis.com\n"
)


def render(topic: Optional[str] = None) -> str:
    """Return the help text (call :func:`help` to print it)."""
    lines: List[str] = [_INTRO]
    needle = topic.lower().strip() if topic else None
    shown = 0
    for title, items in _GROUPS:
        if needle and needle not in title.lower() and not any(
            needle in call.lower() or needle in desc.lower() for call, desc in items
        ):
            continue
        shown += 1
        lines.append(f"\n{title}")
        width = max((len(call) for call, _ in items), default=0)
        for call, desc in items:
            lines.append(f"  {call.ljust(width)}  {desc}")
    if needle and shown == 0:
        lines.append(f"\n(no help topic matched {topic!r}; call crowkis.help() for everything)")
    return "\n".join(lines) + "\n"


def help(topic: Optional[str] = None) -> None:  # noqa: A001 - intentional friendly name
    """Print a grouped cheat-sheet of Crowkis features. Optionally filter by `topic`."""
    print(render(topic))
