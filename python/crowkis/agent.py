from __future__ import annotations

import base64
import binascii
import functools
import json
from typing import Any, Callable, Iterable, List, Optional

from .client import CrowkisClient, CrowkisError


def _stable_args(args: tuple, kwargs: dict) -> str:
    try:
        return json.dumps([args, kwargs], sort_keys=True, default=repr)
    except (TypeError, ValueError):
        return repr((args, sorted(kwargs.items())))


class Agent:

    def __init__(
        self,
        agent_id: str,
        *,
        client: Optional[CrowkisClient] = None,
        host: str = "127.0.0.1",
        port: int = 6383,
        tenant: Optional[str] = None,
        auth_token: Optional[str] = None,
        shares_with: Iterable[str] = (),
    ) -> None:
        agent_id = (agent_id or "").strip()
        if not agent_id:
            raise ValueError(
                "Agent requires a stable agent_id. It is the address of this agent's "
                "memory, so it must be chosen by you and stay the same across restarts "
                "and configuration changes"
            )
        self.agent_id = agent_id
        self.tenant = tenant
        self._shares_with = tuple(s.strip() for s in shares_with if s and s.strip())
        self.route_counts = {"cache": 0, "cheap": 0, "expensive": 0}
        self.audio_hits = 0
        self.audio_misses = 0
        self.tool_hits = 0
        self.tool_misses = 0
        self._owns_client = client is None
        self._client = client or CrowkisClient(
            host=host, port=port, tenant=tenant, auth_token=auth_token
        )

    def remember(self, fact: str, *, ttl: Optional[int] = None) -> None:
        self._client.cmemset(self.agent_id, fact, ex=ttl, tenant=self.tenant)

    def recall(self, query: str, *, include_shared: bool = True) -> List[Any]:
        scopes = [self.agent_id]
        if include_shared:
            scopes.extend(self._shares_with)
        found: List[Any] = []
        for scope in scopes:
            result = self._client.cmemget(scope, query, tenant=self.tenant)
            if result:
                found.extend(result if isinstance(result, list) else [result])
        return found

    def history(self, query: str, *, k: int = 5) -> Any:
        return self._client.cmemhistory(
            self.agent_id, query, k=k, tenant=self.tenant
        )

    def forget(self) -> Any:
        return self._client.cmemforget(self.agent_id, tenant=self.tenant)

    def link(self, other: "Agent | str", relation: str, obj: Optional[str] = None) -> Any:
        target = other.agent_id if isinstance(other, Agent) else other
        return self._client.cmemlink(
            self.agent_id, self.agent_id, relation, obj or target, tenant=self.tenant
        )

    def graph(self, entity: Optional[str] = None) -> Any:
        return self._client.cmemgraph(
            self.agent_id, entity or self.agent_id, tenant=self.tenant
        )

    def tool(
        self, _fn: Optional[Callable] = None, *, ttl: Optional[int] = None, name: Optional[str] = None
    ):
        def decorate(fn: Callable) -> Callable:
            tool_name = name or fn.__name__

            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                key = _stable_args(args, kwargs)
                cached = self._client.ctoolget(tool_name, key, tenant=self.tenant)
                if cached is not None:
                    self.tool_hits += 1
                    raw = cached.decode("utf8", "replace") if isinstance(cached, bytes) else cached
                    try:
                        return json.loads(raw)
                    except (TypeError, ValueError):
                        return raw
                result = fn(*args, **kwargs)
                self.tool_misses += 1
                try:
                    payload = json.dumps(result, default=repr)
                except (TypeError, ValueError):
                    return result
                self._client.ctoolset(
                    tool_name, key, payload, ex=ttl, tenant=self.tenant
                )
                return result

            wrapper.crowkis_tool_name = tool_name
            return wrapper

        return decorate(_fn) if _fn is not None else decorate

    def ask(
        self,
        query: str,
        *,
        serve_above: float = 0.85,
        cheap_above: float = 0.60,
        template: bool = False,
        threshold: Optional[float] = None,
    ) -> dict:
        if not 0.0 <= cheap_above <= serve_above <= 1.0:
            raise ValueError(
                "thresholds must satisfy 0 <= cheap_above <= serve_above <= 1; "
                f"got cheap_above={cheap_above}, serve_above={serve_above}"
            )
        if threshold is not None and not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold must be in 0..1, got {threshold}")
        hit = self._client.cget_hit(
            query, tenant=self.tenant, template=template, threshold=threshold
        )
        if hit is None:
            self.route_counts["expensive"] += 1
            return {
                "route": "expensive",
                "answer": None,
                "confidence": 0.0,
                "similarity": 0.0,
            }
        confidence = float(hit.confidence)
        if confidence >= serve_above:
            route = "cache"
        elif confidence >= cheap_above:
            route = "cheap"
        else:
            route = "expensive"
        self.route_counts[route] += 1
        return {
            "route": route,
            "answer": hit.response.decode("utf8", "replace") if route == "cache" else None,
            "context": hit.response.decode("utf8", "replace"),
            "confidence": confidence,
            "similarity": float(hit.similarity),
        }

    def speak(
        self,
        text: str,
        synthesise: Callable[[str], bytes],
        *,
        voice: str,
        ttl: Optional[int] = None,
    ) -> bytes:
        voice = (voice or "").strip()
        if not voice:
            raise ValueError(
                "speak() requires a voice id. Audio is only reusable for the voice that "
                "produced it; serving one voice's audio for another is audible to the caller"
            )
        key = json.dumps({"voice": voice, "text": text}, sort_keys=True)
        cached = self._client.ctoolget("crowkis.tts", key, tenant=self.tenant)
        if cached is not None:
            raw = cached if isinstance(cached, bytes) else str(cached).encode()
            try:
                audio = base64.b64decode(raw, validate=True)
            except (ValueError, binascii.Error):
                audio = b""
            if audio:
                self.audio_hits += 1
                return audio
        audio = synthesise(text)
        self.audio_misses += 1
        if audio:
            self._client.ctoolset(
                "crowkis.tts",
                key,
                base64.b64encode(audio).decode("ascii"),
                ex=ttl,
                tenant=self.tenant,
            )
        return audio

    def audio_stats(self) -> dict:
        total = self.audio_hits + self.audio_misses
        return {
            "spoken": total,
            "from_cache": self.audio_hits,
            "synthesised": self.audio_misses,
            "tts_avoided_pct": round(100.0 * self.audio_hits / total, 2) if total else 0.0,
        }

    def learn(
        self,
        query: str,
        answer: str,
        *,
        ttl: Optional[int] = None,
        template: bool = False,
    ) -> None:
        self._client.cset(
            query, answer, ttl=ttl, tenant=self.tenant, template=template
        )

    def route_stats(self) -> dict:
        total = sum(self.route_counts.values())
        return {
            "asked": total,
            **self.route_counts,
            "served_without_a_model_pct": (
                round(100.0 * self.route_counts["cache"] / total, 2) if total else 0.0
            ),
        }

    def tool_stats(self) -> dict:
        total = self.tool_hits + self.tool_misses
        return {
            "calls": total,
            "cached": self.tool_hits,
            "executed": self.tool_misses,
            "avoided_pct": round(100.0 * self.tool_hits / total, 2) if total else 0.0,
        }

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "Agent":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"Agent({self.agent_id!r}, tenant={self.tenant!r})"


__all__ = ["Agent", "CrowkisError"]
