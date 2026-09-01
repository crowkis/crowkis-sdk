"""LangChain integration for Crowkis — a semantic LLM cache.

    pip install crowkis[langchain]

    from langchain_core.globals import set_llm_cache
    from crowkis.integrations.langchain import CrowkisCache

    set_llm_cache(CrowkisCache(tenant="my-app"))
    # every LLM / chat-model call now checks Crowkis first

Unlike LangChain's built-in caches (exact string match only), Crowkis matches on
MEANING, so paraphrased prompts hit the cache — that is where the token savings
come from. This also covers LangGraph, which runs on LangChain LLMs, so a single
`set_llm_cache(...)` caches every model call inside a graph too.

For long-term agent memory in LangGraph/CrewAI/AutoGen, use
:class:`crowkis.CrowkisMemory` (no extra dependency).
"""

from __future__ import annotations

from typing import Any, Optional

from ..client import CrowkisClient

try:
    from langchain_core.caches import RETURN_VAL_TYPE, BaseCache
    from langchain_core.load import dumps, loads
    from langchain_core.outputs import Generation
except ImportError as exc:  # pragma: no cover - exercised only without langchain
    raise ImportError(
        "CrowkisCache requires LangChain. Install it with: pip install crowkis[langchain]"
    ) from exc


class CrowkisCache(BaseCache):
    """A LangChain ``BaseCache`` backed by Crowkis semantic lookup.

    Args:
        client: an existing :class:`CrowkisClient`; if omitted one is built from
            the host/port/tenant arguments.
        ttl: seconds to keep a cached generation (None = server default).
        threshold: optional similarity threshold override for the lookup.
    """

    def __init__(
        self,
        client: Optional[CrowkisClient] = None,
        *,
        ttl: Optional[int] = None,
        threshold: Optional[float] = None,
        tenant: Optional[str] = None,
        host: str = "127.0.0.1",
        port: int = 6383,
        auth_token: Optional[str] = None,
    ) -> None:
        self.client = client or CrowkisClient(
            host, port, tenant=tenant, auth_token=auth_token
        )
        self.ttl = ttl
        self.threshold = threshold

    def lookup(self, prompt: str, llm_string: str) -> Optional[RETURN_VAL_TYPE]:
        hit = self.client.cget_hit(prompt, model=llm_string, threshold=self.threshold)
        if hit is None:
            return None
        try:
            # Full-fidelity restore (handles chat vs completion generations).
            return loads(hit.text)
        except Exception:
            # Value predates serialization or came from another writer — treat as text.
            return [Generation(text=hit.text)]

    def update(self, prompt: str, llm_string: str, return_val: RETURN_VAL_TYPE) -> None:
        try:
            payload: Any = dumps(return_val)
        except Exception:
            payload = return_val[0].text if return_val else ""
        self.client.cset(prompt, payload, ttl=self.ttl, model=llm_string)

    def clear(self, **_: Any) -> None:
        self.client.cflush()


# Descriptive alias.
CrowkisSemanticCache = CrowkisCache
