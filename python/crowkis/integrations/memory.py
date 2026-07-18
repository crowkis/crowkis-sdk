"""Framework-agnostic long-term agent memory backed by Crowkis.

No third-party dependencies — works in a LangGraph node, CrewAI, AutoGen, or a
plain loop. This is the recommended way to give any agent durable, semantic,
per-user memory.

    from crowkis import CrowkisMemory

    mem = CrowkisMemory(agent="support-bot", user="alice")
    mem.remember("Alice prefers email over phone")
    hits = mem.recall("how should I contact Alice?")     # semantic recall

In a LangGraph node:

    mem = CrowkisMemory(agent="planner", user=state["user_id"])
    def node(state):
        context = mem.recall(state["input"], k=5)
        ...  # feed `context` into the prompt
        mem.remember(f"user asked: {state['input']}")
        return state
"""

from __future__ import annotations

from typing import Any, Optional

from ..client import CrowkisClient


class CrowkisMemory:
    """Durable, semantic, per-user memory for a named agent.

    Pass an existing :class:`CrowkisClient`, or connection details to build one.
    """

    def __init__(
        self,
        agent: str,
        client: Optional[CrowkisClient] = None,
        *,
        user: Optional[str] = None,
        host: str = "127.0.0.1",
        port: int = 6383,
        tenant: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> None:
        if not agent:
            raise ValueError("agent must be a non-empty name")
        self.agent = agent
        self.user = user
        self._owns_client = client is None
        self.client = client or CrowkisClient(
            host, port, tenant=tenant, auth_token=auth_token
        )

    def remember(self, fact: str, *, ttl: Optional[int] = None) -> Any:
        """Store a fact this agent should recall later."""
        return self.client.cmemset(self.agent, fact, user=self.user, ex=ttl)

    def recall(self, query: str, *, k: int = 5) -> Any:
        """Semantically recall the k facts most relevant to `query`."""
        return self.client.cmemget(self.agent, query, user=self.user, k=k)

    def extract(self, conversation: str, *, ttl: Optional[int] = None) -> Any:
        """Extract and store salient facts from a conversation transcript."""
        return self.client.cmemextract(self.agent, conversation, user=self.user, ex=ttl)

    def history(self, query: str, *, k: int = 5) -> Any:
        """Recall including superseded/older versions of matching facts."""
        return self.client.cmemhistory(self.agent, query, user=self.user, k=k)

    def as_of(self, query: str, unix_ms: int, *, k: int = 5) -> Any:
        """Recall the memory as it stood at a point in time (unix ms)."""
        return self.client.cmemasof(self.agent, query, unix_ms, user=self.user, k=k)

    def forget(
        self, *, query: Optional[str] = None, threshold: Optional[float] = None
    ) -> Any:
        """Forget matching facts (or all of this agent's facts if no query)."""
        return self.client.cmemforget(
            self.agent, query=query, user=self.user, threshold=threshold
        )

    def link(self, subject: str, relation: str, obj: str) -> Any:
        """Record a knowledge-graph edge (subject -relation-> object)."""
        return self.client.cmemlink(self.agent, subject, relation, obj, user=self.user)

    def graph(self, entity: str, *, depth: Optional[int] = None) -> Any:
        """Walk the knowledge graph outward from an entity."""
        return self.client.cmemgraph(self.agent, entity, user=self.user, depth=depth)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "CrowkisMemory":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
