"""Chat: cache a chat app's answers safely, in a few lines.

    chat = Chat(agent, LLMUnderstander(complete), system="You are Acme's assistant.")
    reply = chat.turn("thread-42", messages, answer=my_model)   # messages: the whole chat
    print(reply.text)

Each user turn becomes one stand-alone question that carries what the user said earlier
("Is pad thai safe for someone with a peanut allergy?"). Fixed rules check it; then it is
looked up, and on a miss the model answers that question alone (with ``system``) and the
answer is saved for every user. Anything personal, urgent, part of a booking or unclear is
answered by the model with the whole chat and never cached. Per thread, only a small memory
(facts, topic, language) is kept in ``store``, never the transcript.
"""

from __future__ import annotations

import dataclasses
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from .callstate import CallState
from .session import CallSession, TurnResult, _masked
from .turn import TurnFrame
from .understand import Understander, _normalise
from .verify import SHARED, RuleChecker

Message = Dict[str, str]


class ChatConflict(RuntimeError):
    """Another request saved this thread's memory first: retry the turn."""


class MemoryStore:
    """Threads' memory in this process, with a version per thread. Bounded: the oldest
    threads are forgotten past ``max_threads``. For several chat servers pass any object
    with the same ``load`` / ``save``."""

    def __init__(self, max_threads: int = 100_000) -> None:
        self._data: "OrderedDict[str, Tuple[Dict[str, Any], int]]" = OrderedDict()
        self._lock = threading.Lock()
        self.max_threads = max_threads

    def load(self, thread_id: str) -> Tuple[Optional[Dict[str, Any]], int]:
        with self._lock:
            entry = self._data.get(thread_id)
            return (entry[0], entry[1]) if entry else (None, 0)

    def save(self, thread_id: str, data: Dict[str, Any], version: int) -> bool:
        """Store ``data`` if the thread is still at ``version``; False if it moved on."""
        with self._lock:
            current = self._data.get(thread_id, (None, 0))[1]
            if current != version:
                return False
            self._data[thread_id] = (data, version + 1)
            self._data.move_to_end(thread_id)
            while len(self._data) > self.max_threads:
                self._data.popitem(last=False)
            return True

    def delete(self, thread_id: str) -> None:
        with self._lock:
            self._data.pop(thread_id, None)


def _settled(state: CallState) -> bool:
    """The thread's memory holds nothing that can change an answer: no fact, detail, region or
    tier, reply language or task."""
    return not (state.facts or state.stated or state.details or state.attributes or state.language
                or state.task != "none")


class _Repeats:
    """Reads a turn without a model call when the model already read it: word for word a question
    that an earlier turn asked on its own (not rewritten, not leaning on its chat), in a thread
    whose memory could not change it, and that the rules shared. The rules still check every turn.
    In this process only, at most ``max_questions``."""

    def __init__(self, understander: Understander, max_questions: int = 10_000) -> None:
        self.understander = understander
        self.max_questions = max_questions
        self._known: "OrderedDict[str, TurnFrame]" = OrderedDict()
        self._lock = threading.Lock()

    def understand(self, turn: str, state: CallState) -> TurnFrame:
        if _settled(state):
            with self._lock:
                frame = self._known.get(_normalise(turn))
            if frame is not None:
                return frame
        return self.understander.understand(turn, state)

    def remember(self, turn: str, settled: bool, result: TurnResult) -> None:
        frame, verdict = result.frame, result.verdict
        if not settled or result.route != SHARED or frame is None or verdict is None or frame.uses_state:
            return
        key = _normalise(turn)
        if not key or key != _normalise(verdict.question or ""):
            return
        with self._lock:
            # A region or tier comes from the thread that asked; the next thread's own memory gives its own.
            self._known[key] = dataclasses.replace(frame, attributes={})
            self._known.move_to_end(key)
            while len(self._known) > self.max_questions:
                self._known.popitem(last=False)


@dataclass
class ChatReply:
    text: str
    route: str
    from_cache: bool
    outcome: str  # saved | not_shared | refused:<why> | served; refused:non_answer with `text` answered from the whole chat
    reason: str = ""  # why it went this route ("V3_not_general", "cache hit", ...)


class Chat:
    """``agent`` a crowkis Agent; ``understander`` turns a turn into a frame (an
    ``LLMUnderstander`` over any model); ``system`` the business's instructions for answers
    that are shared; other keyword options go to ``CallSession`` (``urgent_reply``,
    ``on_tools``, ``fillers``...)."""

    def __init__(self, agent: Any, understander: Understander, *, store: Any = None, system: str = "",
                 channel: str = "chat", knowledge_version: str = "1", **session_options: Any) -> None:
        self.agent = agent
        self.understander = understander
        self._repeats = _Repeats(understander)
        self.store = store if store is not None else MemoryStore()
        self.system = system.strip()
        session_options.setdefault("checker", RuleChecker(channel=channel, knowledge_version=knowledge_version))
        # A chat waits for its model anyway: understanding gets seconds, not a voice turn's 250 ms.
        session_options.setdefault("understand_budget_ms", 10_000.0)
        self.session_options = session_options
        # One turn at a time per thread in this process. A thread's lock exists only while one
        # of its turns runs, so unrelated chats never wait on each other.
        self._locks: Dict[str, List[Any]] = {}
        self._guard = threading.Lock()

    def turn(self, thread_id: str, messages: List[Message], answer: Callable[[List[Message]], str]) -> ChatReply:
        """Answer the last user message of ``messages`` (the whole chat, OpenAI style).

        ``answer`` is the app's model: it gets chat messages and returns the reply text.
        Raises ``ChatConflict`` when another request answered this thread at the same time.
        """
        thread_id = str(thread_id)
        text = next((_content(m.get("content")) for m in reversed(messages or [])
                     if isinstance(m, dict) and m.get("role") == "user"), "")
        with self._thread_lock(thread_id):
            data, version = self.store.load(thread_id)
            session = CallSession.restore(self.agent, self._repeats, data, **self.session_options)
            settled = _settled(session.state)
            result = session.handle(text)
            self._repeats.remember(text, settled, result)
            if not result.needs_model and result.text is not None:
                reply, outcome = result.text, "served"
            else:
                if result.messages is None:
                    asked = list(messages or [])  # personal or unclear: the whole chat, never cached
                else:
                    asked = ([{"role": "system", "content": self.system}] if self.system else []) + result.messages
                reply = answer(asked)
                outcome = session.record_answer(result, reply)
                if outcome == "refused:non_answer" and result.messages is not None:
                    # The question alone did not carry enough ("What were the steps again?"): the user is
                    # answered from the whole chat instead, and nothing is saved.
                    reply = answer(list(messages or []))
                    session.state.note_agent_reply(_masked(reply))  # what the user saw, names masked
            if not self.store.save(thread_id, session.export(), version):
                raise ChatConflict(f"thread {thread_id!r} was answered by another request at the same time")
        return ChatReply(text=reply, route=result.route, from_cache=result.served_from_cache, outcome=outcome,
                         reason=result.reason or "")

    def forget(self, thread_id: str) -> None:
        """Erase a thread's memory (a user's right to erasure). Its shared answers hold nothing of it."""
        delete = getattr(self.store, "delete", None)
        if delete is None:
            raise TypeError("this store cannot delete; give it a delete(thread_id) method")
        delete(str(thread_id))

    def _thread_lock(self, thread_id: str) -> "_Held":
        with self._guard:
            entry = self._locks.setdefault(thread_id, [threading.Lock(), 0])
            entry[1] += 1
        return _Held(self, thread_id, entry)


class _Held:
    def __init__(self, chat: Chat, thread_id: str, entry: List[Any]) -> None:
        self.chat, self.thread_id, self.entry = chat, thread_id, entry

    def __enter__(self) -> None:
        self.entry[0].acquire()

    def __exit__(self, *exc: Any) -> None:
        self.entry[0].release()
        with self.chat._guard:
            self.entry[1] -= 1
            if self.entry[1] == 0:
                self.chat._locks.pop(self.thread_id, None)


def _content(content: Any) -> str:
    """A message's text: a string, or the text parts of a list of parts (OpenAI style)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p if isinstance(p, str) else str(p.get("text", "")) for p in content
                        if isinstance(p, str) or (isinstance(p, dict) and p.get("type", "text") == "text"))
    return "" if content is None else str(content)


__all__ = ["Chat", "ChatReply", "ChatConflict", "MemoryStore"]
