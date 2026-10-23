"""VoiceSession for asyncio: the same rules, with every wait off the event loop.

AsyncVoiceSession wraps a VoiceSession. The calls that wait on the server (decide,
answer, record, respond, report_stats, close) run on a dedicated thread pool, so one
call's slow lookup never stalls the others sharing the loop; a sync model runs there
too. Calls that never wait (cancel, stats, injections, set_values, ...) pass straight
through. The privacy rules are the VoiceSession's own: nothing here decides what is
shared.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import threading
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from .agent import Agent
from .voice import TurnDecision, VoiceSession, voice_session

# Two pools for every async session in the process. Server calls: a turn holds a
# worker for at most its latency budget (lookup) or the client timeout (saving the
# answer), so 64 workers serve far more than 64 concurrent calls. Sync models (and
# reading a sync stream) have a pool of their own: a model holds its worker for as long
# as it writes, and must never make a lookup wait for a thread.
_POOL_SIZE = 64
_MODEL_POOL_SIZE = 256
_pools: Dict[str, concurrent.futures.ThreadPoolExecutor] = {}
_pool_lock = threading.Lock()
_END = object()


def _pool(kind: str = "server") -> concurrent.futures.ThreadPoolExecutor:
    with _pool_lock:
        if kind not in _pools:
            _pools[kind] = concurrent.futures.ThreadPoolExecutor(
                max_workers=_POOL_SIZE if kind == "server" else _MODEL_POOL_SIZE,
                thread_name_prefix=f"crowkis-voice-{kind}",
            )
        return _pools[kind]


def _default_pool() -> concurrent.futures.ThreadPoolExecutor:
    return _pool("server")


async def _off_loop(executor, fn: Callable, *args: Any, **kwargs: Any) -> Any:
    loop = asyncio.get_running_loop()
    if kwargs:
        return await loop.run_in_executor(executor, lambda: fn(*args, **kwargs))
    return await loop.run_in_executor(executor, fn, *args)


def _is_async_callable(fn: Callable) -> bool:
    return inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(getattr(fn, "__call__", None))


async def _call_model(executor, llm: Callable, messages: List[Dict[str, str]]) -> Any:
    """Call the model: an async one on the loop, a sync one on the model pool."""
    if _is_async_callable(llm) or inspect.isasyncgenfunction(llm):
        result = llm(messages)
    else:
        result = await _off_loop(executor, llm, messages)
    if inspect.isawaitable(result):
        result = await result
    return result


class AsyncVoiceResponse:
    """What AsyncVoiceSession.respond() returns: read it with ``async for`` for the text
    to speak, piece by piece as the model writes it.

    ``decision`` is ready at once (``served_from_cache``, ``audio``). Read once. Python
    does not close an async iterator when you ``break`` out of ``async for``: call
    ``await stream.close()`` after stopping early so the model's stream is closed at once.
    """

    def __init__(self, owner: "AsyncVoiceSession", decision: TurnDecision, caller_said: str,
                 llm, system, private) -> None:
        self.decision = decision
        self._owner = owner
        self._caller_said = caller_said
        self._llm = llm
        self._system = system
        self._private = private
        self._pieces: Optional[AsyncIterator[str]] = None
        self._closed = False

    def __aiter__(self) -> AsyncIterator[str]:
        if self._pieces is not None:
            raise RuntimeError("an AsyncVoiceResponse is read once")
        self._pieces = self._run()
        return self._pieces

    async def close(self) -> None:
        """Stop early: the model's stream is closed and nothing is stored."""
        self._closed = True
        if self._pieces is None:
            self._pieces = _empty()
        else:
            await self._pieces.aclose()  # type: ignore[attr-defined]

    def _stopped(self) -> bool:
        session = self._owner.session
        return self.decision._recorded or session._moved_on(self.decision)

    async def _run(self) -> AsyncIterator[str]:
        session, decision = self._owner.session, self.decision
        executor, model_executor = self._owner._executor, self._owner._model_executor
        if not decision.needs_model:
            if decision.text:
                yield decision.text
            return
        if self._stopped():  # talked over before a word was read: never call the model
            session._interrupted(decision, "")
            return
        decision._said = self._caller_said
        messages = decision.messages
        if messages is None:
            messages = session.injections() + [{"role": "user", "content": self._caller_said}]
        if self._system:
            messages = [{"role": "system", "content": self._system}] + messages
        source = await _call_model(model_executor, self._llm, messages)
        if isinstance(source, (bytes, bytearray)):
            raise TypeError("respond() expects the model to give text (str), got bytes; decode it first")
        if isinstance(source, str):
            source = [source]
        is_async = hasattr(source, "__aiter__")
        if is_async:
            upstream: Any = source.__aiter__()
        else:
            try:
                upstream = iter(source)
            except TypeError:
                raise TypeError(
                    f"respond() expects the model to give text: a str, or an (async) iterable of "
                    f"str pieces; got {type(source).__name__}"
                ) from None
        parts: List[str] = []
        ended = moved_on = False
        reading: Optional[concurrent.futures.Future] = None
        try:
            while True:
                if is_async:
                    piece = await upstream.__anext__()
                else:
                    # A sync stream may block on the network between pieces: read it on
                    # the model pool, never on the loop.
                    reading = model_executor.submit(next, upstream, _END)
                    piece = await asyncio.wrap_future(reading)
                    if piece is _END:
                        raise StopAsyncIteration
                if piece is None:
                    continue
                if not isinstance(piece, str):
                    raise TypeError(
                        f"respond() expects the model to give text pieces (str), got "
                        f"{type(piece).__name__}; map each chunk to its text first"
                    )
                if self._stopped():
                    moved_on = True
                    break
                parts.append(piece)
                if piece:
                    yield piece
        except StopAsyncIteration:
            ended = True
        finally:
            if is_async:
                await _close_async(upstream)
            else:
                _close_sync_later(upstream, reading, model_executor)
            if moved_on:
                session._interrupted(decision, "".join(parts))
            elif ended and not self._closed:
                with session._turn_lock:
                    recorded, decision._recorded = decision._recorded, True
                if not recorded:
                    await _off_loop(executor, session._record_decision, decision, "".join(parts),
                                    private=self._private, system=self._system)


async def _empty() -> AsyncIterator[str]:
    return
    yield  # pragma: no cover


async def _close_async(upstream: Any) -> None:
    """Close an async model stream: ``aclose()``, or ``close()`` as the OpenAI and
    Anthropic async streams have. A failure to close never breaks the turn."""
    closer = getattr(upstream, "aclose", None) or getattr(upstream, "close", None)
    if closer is None:
        return
    try:
        result = closer()
        if inspect.isawaitable(result):
            await result
    except Exception:  # noqa: BLE001 — the stream is over either way
        pass


def _close_sync(upstream: Any) -> None:
    closer = getattr(upstream, "close", None)
    if closer is not None:
        try:
            closer()
        except Exception:  # noqa: BLE001 — the stream is over either way
            pass


def _close_sync_later(upstream: Any, reading: Optional[concurrent.futures.Future], pool) -> None:
    """Close a sync model stream off the loop. If a pool thread is still reading it (the
    consuming task was cancelled mid-read), close it as soon as that read returns: a
    generator cannot be closed while it is running."""
    if reading is not None and not reading.done():
        reading.add_done_callback(lambda _: _close_sync(upstream))
    else:
        pool.submit(_close_sync, upstream)


class AsyncVoiceSession:
    """VoiceSession for asyncio: the same rules, with every wait off the event loop.

    Build it like a VoiceSession (``AsyncVoiceSession(agent, voice=..., ...)``), wrap
    one you have (``AsyncVoiceSession.wrap(session)``), or use
    ``crowkis.async_voice_session()`` for one with live-call defaults. ``executor`` is
    the thread pool the server calls run on (by default one shared pool of 64 workers);
    ``model_executor`` runs a sync model and reads a sync stream (by default a separate
    shared pool of 256), so a slow model never makes a lookup wait for a thread. An
    AsyncVoiceSession is not a VoiceSession: pass ``.session`` to code that needs one.

    ``decide``, ``answer``, ``record``, ``respond``, ``report_stats`` and ``close`` are
    coroutines. Everything else (``cancel``, ``stats``, ``injections``, ``set_values``,
    ``register_filler``, ``transcript``, ``agent``, ...) is the VoiceSession's own.
    """

    _OWN = ("session", "_executor", "_model_executor")

    def __init__(self, agent: Agent, *, voice: str,
                 executor: Optional[concurrent.futures.Executor] = None,
                 model_executor: Optional[concurrent.futures.Executor] = None, **options: Any) -> None:
        self._setup(VoiceSession(agent, voice=voice, **options), executor, model_executor)

    @classmethod
    def wrap(cls, session: VoiceSession, *,
             executor: Optional[concurrent.futures.Executor] = None,
             model_executor: Optional[concurrent.futures.Executor] = None) -> "AsyncVoiceSession":
        """An AsyncVoiceSession over a VoiceSession you already have."""
        self = cls.__new__(cls)
        self._setup(session, executor, model_executor)
        return self

    def _setup(self, session, executor, model_executor) -> None:
        object.__setattr__(self, "session", session)
        object.__setattr__(self, "_executor", executor or _default_pool())
        object.__setattr__(self, "_model_executor", model_executor or _pool("model"))

    def __getattr__(self, name: str) -> Any:
        # Only reached for what this class does not define: the session's quick calls
        # and attributes. The coroutines above always win.
        if name in AsyncVoiceSession._OWN:
            raise AttributeError(name)
        return getattr(self.session, name)

    def __setattr__(self, name: str, value: Any) -> None:
        # A setting changed here must reach the session the turns run on
        # (``s.latency_budget_ms = 500``), never stop at this wrapper.
        if name in AsyncVoiceSession._OWN:
            object.__setattr__(self, name, value)
        else:
            setattr(self.session, name, value)

    async def decide(self, caller_said: str) -> TurnDecision:
        return await _off_loop(self._executor, self.session.decide, caller_said)

    async def answer(self, caller_said: str, llm: Callable, *, system: Optional[str] = None) -> TurnDecision:
        """VoiceSession.answer(): ``llm`` may be async (awaited on the loop) or sync (run
        on the pool)."""
        session = self.session
        decision = await self.decide(caller_said)
        if not decision.needs_model:
            return decision
        messages = decision.messages
        if messages is None:
            messages = session.injections() + [{"role": "user", "content": caller_said}]
        if system:
            messages = [{"role": "system", "content": system}] + messages
        text = await _call_model(self._model_executor, llm, messages)
        decision._said = caller_said
        return await _off_loop(self._executor, session._record_decision, decision, text, private=False,
                               system=system)

    async def record(self, decision: TurnDecision, answer: Optional[str], *, private: bool = False,
                     system: Optional[str] = None) -> TurnDecision:
        """VoiceSession.record()."""
        return await _off_loop(self._executor, self.session.record, decision, answer, private=private,
                               system=system)

    async def respond(self, caller_said: str, llm: Callable, *, system: Optional[str] = None,
                      private: bool = False) -> AsyncVoiceResponse:
        """VoiceSession.respond(), for asyncio. ``llm`` may give an async iterable, a sync
        iterable (read on the pool), a str, or an awaitable of either."""
        decision = await self.decide(caller_said)
        return AsyncVoiceResponse(self, decision, caller_said, llm, system, private)

    async def report_stats(self) -> bool:
        return await _off_loop(self._executor, self.session.report_stats)

    async def close(self) -> None:
        """Close the agent (and the client it opened)."""
        await _off_loop(self._executor, self.session.agent.close)


def async_voice_session(*, executor: Optional[concurrent.futures.Executor] = None,
                        model_executor: Optional[concurrent.futures.Executor] = None,
                        **options: Any) -> AsyncVoiceSession:
    """crowkis.voice_session() for asyncio: the same arguments and live-call defaults,
    as an AsyncVoiceSession. ``executor`` runs its server calls, ``model_executor`` a
    sync model (and reading a sync stream)."""
    return AsyncVoiceSession.wrap(voice_session(**options), executor=executor, model_executor=model_executor)
