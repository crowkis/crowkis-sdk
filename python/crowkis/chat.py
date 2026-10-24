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

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from .session import CallSession, _masked
from .understand import Understander
from .verify import RuleChecker

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
        self.store = store if store is not None else MemoryStore()
        self.system = system.strip()
        session_options.setdefault("checker", RuleChecker(channel=channel, knowledge_version=knowledge_version))
        # What the model reads with a shared question: an answer repeating a user's detail from it is never saved.
        session_options.setdefault("instructions", self.system)
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
            session = CallSession.restore(self.agent, self.understander, data, **self.session_options)
            result = session.handle(text)
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
