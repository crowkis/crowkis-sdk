from __future__ import annotations

import base64
import binascii
import functools
import json
import logging
import queue
import threading
import time
import unicodedata
from typing import Any, Callable, Iterable, List, Optional

from .client import CrowkisClient, CrowkisError

_log = logging.getLogger("crowkis")

# Storing a new clip runs here, never in the caller's way: the caller has its
# audio as soon as it is synthesised. Daemon threads, so a program never waits
# for them at exit. At most this many wait; past that a clip is not cached
# (it is stored the next time it is spoken).
_AUDIO_QUEUE: "queue.Queue[tuple]" = queue.Queue(maxsize=64)
_AUDIO_WORKERS = 4
_audio_workers_started = False
_audio_workers_lock = threading.Lock()

# How long "no Voice add-on" stands before the server is asked again (a licence
# may have been installed or renewed meanwhile).
_ADDON_RECHECK_SECS = 600.0
# What the server's audio cache takes; anything else goes the basic way.
_AUDIO_MAX_ANSWER_BYTES = 64 * 1024
_AUDIO_MAX_LABEL = 64


def _audio_worker() -> None:
    while True:
        store, args, kwargs = _AUDIO_QUEUE.get()
        try:
            store(*args, **kwargs)
        except Exception as err:  # the cache is an optimisation: never fail a call over it
            _log.warning("crowkis: an audio clip was not cached: %s", err)
        finally:
            _AUDIO_QUEUE.task_done()


def _store_later(store: Callable[..., Any], *args: Any, **kwargs: Any) -> bool:
    """Run `store` in the background. False when too many are already waiting."""
    global _audio_workers_started
    with _audio_workers_lock:
        if not _audio_workers_started:
            for n in range(_AUDIO_WORKERS):
                threading.Thread(target=_audio_worker, name=f"crowkis-audio-store-{n}", daemon=True).start()
            _audio_workers_started = True
    try:
        _AUDIO_QUEUE.put_nowait((store, args, kwargs))
    except queue.Full:
        _log.warning("crowkis: too many audio clips waiting to be stored; this one is not cached")
        return False
    return True


def _wait_for_audio_stores() -> None:
    """For tests: every clip handed to the background is stored."""
    _AUDIO_QUEUE.join()


def _fits_audio_cache(text: str, labels: tuple) -> bool:
    """What the server's audio cache accepts: an answer up to 64 KB and labels of
    1 to 64 characters of text. Anything else uses the basic path, never an error."""
    size = len(text.encode("utf-8"))
    return 0 < size <= _AUDIO_MAX_ANSWER_BYTES and all(
        0 < len(label) <= _AUDIO_MAX_LABEL
        and label.strip()
        and not any(unicodedata.category(c) == "Cc" for c in label)
        for label in labels
    )


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
        # The server's audio cache (Voice add-on): None until the first clip
        # asks, then whether this server has it.
        self._audio_v2: Optional[bool] = None
        self._audio_v2_recheck_at = 0.0
        self.tool_hits = 0
        self.tool_misses = 0
        self._decides: Optional[bool] = None
        self._decides_asked = 0.0
        # The engine holds an answer back until it has judged it.
        self._holds = False
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
                "exact": False,
                "vouched": False,
                "lifetime": None,
                "commitment": False,
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
            # The same question, not a similar one. Two different questions
            # can score a similarity of exactly 1.
            "exact": hit.hit_type.endswith("exact"),
            # What the server's decision engine recorded; defaults without one.
            "vouched": hit.vouched,
            "lifetime": hit.lifetime,
            "commitment": hit.commitment,
        }

    def decides(self) -> bool:
        """Whether the server judges what it caches. The answer is remembered
        for a few minutes and then asked again, so an engine switched on or off
        is noticed; a server that could not be reached reads as no for now."""
        if self._decides is not None and time.monotonic() - self._decides_asked < 300:
            return self._decides
        try:
            view = self._client.cdecision("ping", tenant=self.tenant)
        except Exception as error:  # noqa: BLE001 — no engine is the safe reading of any failure
            # An older server does not know the question: that is an answer.
            if "unknown command" in str(error).lower():
                self._decides, self._decides_asked = False, time.monotonic()
            self._holds = False
            return False
        # A client set to fail softly answers None for a server it cannot reach.
        if not isinstance(view, dict):
            self._holds = False
            return False
        self._decides, self._decides_asked = bool(view.get("engine")), time.monotonic()
        self._holds = self._decides and bool(view.get("holds"))
        return self._decides

    def explain(self, query: str) -> dict:
        """What the cache decided about a question: is an answer cached, how long
        it was judged to stay correct, or why its answer was removed."""
        return self._client.cdecision(query, tenant=self.tenant)

    def announce(self, notice: str, *, lasts: Optional[int] = None, preview: bool = False) -> dict:
        """Tell the cache something changed, in one sentence ("we close at 3pm
        today"). Cached answers near it stop being served at once; the ones it
        makes wrong are removed and the rest come back within seconds. With
        `lasts` (seconds), answers given meanwhile expire when the notice does."""
        return self._client.cnotice_add(notice, lasts=lasts, preview=preview, tenant=self.tenant)

    def speak(
        self,
        text: str,
        synthesise: Callable[[str], bytes],
        *,
        voice: str,
        ttl: Optional[int] = None,
        language: str = "und",
        speed: str = "1",
        audio_format: str = "default",
        bytes_per_second: Optional[int] = None,
    ) -> bytes:
        """The spoken `text`: replayed from the cache when this voice already said
        it, otherwise `synthesise(text)` once and kept. With the server's Voice
        add-on the clip is keyed by voice, language, speed and format and stored
        as raw bytes; without it, by voice and text as before. `bytes_per_second`
        lets the Voice page count the seconds of speech saved."""
        voice = (voice or "").strip()
        if not voice:
            raise ValueError(
                "speak() requires a voice id. Audio is only reusable for the voice that "
                "produced it; serving one voice's audio for another is audible to the caller"
            )
        labels = (voice, language or "und", str(speed or "1"), audio_format or "default")
        use_v2 = self._audio_cache_usable(text, labels)
        skip_store = False
        if use_v2:
            try:
                audio = self._client.caudioget(text, *labels, tenant=self.tenant)
            except CrowkisError as err:
                use_v2, skip_store = self._audio_cache_failed(err)
            else:
                self._audio_v2 = True
                if audio:
                    self.audio_hits += 1
                    return audio
        key = json.dumps({"voice": voice, "text": text}, sort_keys=True)
        if not use_v2 and not skip_store:
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
        if audio and not skip_store:
            if use_v2:
                ms = len(audio) * 1000 // bytes_per_second if bytes_per_second else None
                _store_later(self._client.caudioset, text, *labels, bytes(audio), ex=ttl, ms=ms, tenant=self.tenant)
            else:
                self._client.ctoolset(
                    "crowkis.tts",
                    key,
                    base64.b64encode(audio).decode("ascii"),
                    ex=ttl,
                    tenant=self.tenant,
                )
        return audio

    def _audio_cache_usable(self, text: str, labels: tuple) -> bool:
        """Whether to ask the server's audio cache for this clip."""
        if not hasattr(self._client, "caudioget"):
            self._audio_v2 = False
            return False
        if self._audio_v2 is False and self._audio_v2_recheck_at and time.monotonic() >= self._audio_v2_recheck_at:
            self._audio_v2 = None  # ask again: a licence may have been installed or renewed
        return self._audio_v2 is not False and _fits_audio_cache(text, labels)

    def _audio_cache_failed(self, err: CrowkisError) -> tuple:
        """After the audio cache answered an error: (use it, skip storing).
        No Voice add-on: the basic path, asked again later. With fail_soft any
        other error is a miss with nothing stored; without it, it is raised."""
        if _voice_addon_missing(err):
            self._audio_v2 = False
            self._audio_v2_recheck_at = time.monotonic() + _ADDON_RECHECK_SECS
            return False, False
        if getattr(self._client, "fail_soft", False):
            _log.warning("crowkis: the audio cache could not be read: %s", err)
            return True, True
        raise err

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


def _voice_addon_missing(err: CrowkisError) -> bool:
    """The server has no audio cache for this caller: no Voice add-on (its
    ENTERPRISE refusal), or a server from before it. Any other error is not this."""
    text = str(err).lstrip()
    return text.startswith(("ENTERPRISE ", "ERR ENTERPRISE ")) or "unknown command" in text.lower()


__all__ = ["Agent", "CrowkisError"]
