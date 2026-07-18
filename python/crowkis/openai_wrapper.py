"""Drop-in OpenAI client wrapper backed by Crowkis.

Usage — change two lines, keep the rest of your code:

    from openai import OpenAI            # before
    client = OpenAI()

    from crowkis.openai_wrapper import CachedOpenAI   # after
    client = CachedOpenAI(tenant="my-app")

Every `client.chat.completions.create(...)` first asks Crowkis. On a
cache hit the response comes back in microseconds and costs nothing.
On a miss the real OpenAI client is called and the answer is cached
for next time.

Honesty notes:
- `stream=True` requests bypass the cache entirely (pass-through) —
  streaming responses are not reconstructed from cache in this version.
- Caching keys on the serialized message list + model, so changing
  any message or the model is a different cache entry.
- Requires the `openai` package only when a cache miss actually needs
  the upstream call — import is lazy.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .client import CrowkisClient


class _CompletionsProxy:
    def __init__(self, wrapper: "CachedOpenAI") -> None:
        self._wrapper = wrapper

    def create(self, **kwargs: Any) -> Any:
        return self._wrapper._chat_create(**kwargs)


class _ChatProxy:
    def __init__(self, wrapper: "CachedOpenAI") -> None:
        self.completions = _CompletionsProxy(wrapper)


class CachedResponse:
    """Duck-types the slice of the OpenAI response apps actually read:
    `response.choices[0].message.content`."""

    class _Message:
        def __init__(self, content: str) -> None:
            self.content = content
            self.role = "assistant"

    class _Choice:
        def __init__(self, content: str) -> None:
            self.message = CachedResponse._Message(content)
            self.finish_reason = "stop"
            self.index = 0

    def __init__(self, content: str, model: str) -> None:
        self.choices = [CachedResponse._Choice(content)]
        self.model = model
        self.crowkis_cache_hit = True


class CachedOpenAI:
    def __init__(
        self,
        *,
        crowkis_host: str = "127.0.0.1",
        crowkis_port: int = 6383,
        tenant: Optional[str] = None,
        ttl: int = 3600,
        openai_client: Any = None,
        **openai_kwargs: Any,
    ) -> None:
        self._crowkis = CrowkisClient(crowkis_host, crowkis_port, tenant=tenant)
        self._tenant = tenant
        self._ttl = ttl
        self._openai = openai_client
        self._openai_kwargs = openai_kwargs
        self.chat = _ChatProxy(self)

    def _upstream(self) -> Any:
        if self._openai is None:
            try:
                from openai import OpenAI  # lazy — only needed on a miss
            except ImportError as exc:
                raise RuntimeError(
                    "cache miss requires the `openai` package: pip install openai"
                ) from exc
            self._openai = OpenAI(**self._openai_kwargs)
        return self._openai

    @staticmethod
    def cache_key(model: str, messages: Any) -> str:
        return json.dumps({"model": model, "messages": messages}, sort_keys=True)

    def _chat_create(self, **kwargs: Any) -> Any:
        if kwargs.get("stream"):
            # Streaming bypasses the cache — pass straight through.
            return self._upstream().chat.completions.create(**kwargs)

        model = kwargs.get("model", "")
        messages = kwargs.get("messages", [])
        key = self.cache_key(model, messages)

        cached = self._crowkis.cget(key, tenant=self._tenant, model=model)
        if cached is not None:
            content = cached.decode() if isinstance(cached, (bytes, bytearray)) else str(cached)
            return CachedResponse(content, model)

        response = self._upstream().chat.completions.create(**kwargs)
        try:
            content = response.choices[0].message.content or ""
            if content:
                self._crowkis.cset(
                    key, content, ttl=self._ttl, tenant=self._tenant, model=model
                )
        except Exception:
            # Caching is best-effort: a cache write failure must never
            # break the application's completion call.
            pass
        return response

    def close(self) -> None:
        self._crowkis.close()
