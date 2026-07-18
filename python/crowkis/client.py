from __future__ import annotations

import asyncio
import base64
import functools
import inspect
import json
import random
import socket
import time
from dataclasses import dataclass
from http.client import HTTPConnection
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    Union,
)
from urllib.parse import urlencode, urlparse

BytesLike = Union[str, bytes, bytearray, memoryview]


class CrowkisError(Exception):
    """Raised when Crowkis returns an error or an SDK protocol failure occurs."""


@dataclass(frozen=True)
class CacheHit:
    response: bytes
    similarity: float
    ttl_remaining: int
    matched_key: bytes
    confidence: float
    hit_type: str
    migration_pending: bool = False
    migration_from_model_version: Optional[str] = None
    migration_target_model_version: Optional[str] = None
    migration_canary_id: Optional[str] = None
    migration_planned_at: Optional[int] = None

    @property
    def text(self) -> str:
        return self.response.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class SimResult:
    key: bytes
    similarity: float


def _b(value: BytesLike) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return bytes(value)


def _image_b64(value: Optional[BytesLike]) -> Optional[bytes]:
    if value is None:
        return None
    return base64.b64encode(_b(value))


def _encode(args: Iterable[BytesLike]) -> bytes:
    chunks: List[bytes] = []
    materialised = [_b(arg) for arg in args]
    chunks.append(f"*{len(materialised)}\r\n".encode())
    for arg in materialised:
        chunks.append(f"${len(arg)}\r\n".encode())
        chunks.append(arg)
        chunks.append(b"\r\n")
    return b"".join(chunks)


def _read_line(sock: socket.socket) -> bytes:
    out = bytearray()
    while True:
        b = sock.recv(1)
        if not b:
            raise CrowkisError("connection closed")
        out.extend(b)
        if out.endswith(b"\r\n"):
            return bytes(out[:-2])


def _read_exact(sock: socket.socket, n: int) -> bytes:
    out = bytearray()
    while len(out) < n:
        chunk = sock.recv(n - len(out))
        if not chunk:
            raise CrowkisError("connection closed")
        out.extend(chunk)
    return bytes(out)


def _read_resp(sock: socket.socket) -> Any:
    line = _read_line(sock)
    if not line:
        raise CrowkisError("empty RESP frame")
    prefix, payload = line[:1], line[1:]

    if prefix == b"+":
        return payload.decode()
    if prefix == b"-":
        raise CrowkisError(payload.decode(errors="replace"))
    if prefix == b":":
        return int(payload)
    if prefix == b",":
        return float(payload)
    if prefix == b"_":
        return None
    if prefix == b"#":
        return payload == b"t"
    if prefix == b"$":
        length = int(payload)
        if length < 0:
            return None
        data = _read_exact(sock, length)
        _read_exact(sock, 2)
        return data
    if prefix == b"*":
        count = int(payload)
        if count < 0:
            return None
        return [_read_resp(sock) for _ in range(count)]
    if prefix == b"%":
        count = int(payload)
        out: Dict[Any, Any] = {}
        for _ in range(count):
            key = _read_resp(sock)
            value = _read_resp(sock)
            if isinstance(key, bytes):
                key = key.decode(errors="replace")
            out[key] = value
        return out
    if prefix == b">":
        count = int(payload)
        return [_read_resp(sock) for _ in range(count)]

    raise CrowkisError(f"unexpected RESP frame: {line!r}")


async def _aread_line(reader: asyncio.StreamReader) -> bytes:
    line = await reader.readline()
    if not line:
        raise CrowkisError("connection closed")
    return line.rstrip(b"\r\n")


async def _aread_resp(reader: asyncio.StreamReader) -> Any:
    line = await _aread_line(reader)
    if not line:
        raise CrowkisError("empty RESP frame")
    prefix, payload = line[:1], line[1:]

    if prefix == b"+":
        return payload.decode()
    if prefix == b"-":
        raise CrowkisError(payload.decode(errors="replace"))
    if prefix == b":":
        return int(payload)
    if prefix == b",":
        return float(payload)
    if prefix == b"_":
        return None
    if prefix == b"#":
        return payload == b"t"
    if prefix == b"$":
        length = int(payload)
        if length < 0:
            return None
        data = await reader.readexactly(length)
        await reader.readexactly(2)
        return data
    if prefix == b"*":
        count = int(payload)
        if count < 0:
            return None
        return [await _aread_resp(reader) for _ in range(count)]
    if prefix == b"%":
        count = int(payload)
        out: Dict[Any, Any] = {}
        for _ in range(count):
            key = await _aread_resp(reader)
            value = await _aread_resp(reader)
            if isinstance(key, bytes):
                key = key.decode(errors="replace")
            out[key] = value
        return out
    if prefix == b">":
        count = int(payload)
        return [await _aread_resp(reader) for _ in range(count)]

    raise CrowkisError(f"unexpected RESP frame: {line!r}")


def _cache_hit(payload: Dict[str, Any]) -> CacheHit:
    def optional_text(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    return CacheHit(
        response=payload.get("response") or b"",
        similarity=float(payload.get("similarity") or 0.0),
        ttl_remaining=int(payload.get("ttl") or 0),
        matched_key=payload.get("key") or b"",
        confidence=float(payload.get("confidence") or 0.0),
        hit_type=(payload.get("hit_type") or b"unknown").decode()
        if isinstance(payload.get("hit_type"), bytes)
        else str(payload.get("hit_type") or "unknown"),
        migration_pending=bool(payload.get("migration_pending") or False),
        migration_from_model_version=optional_text(payload.get("migration_from_model_version")),
        migration_target_model_version=optional_text(payload.get("migration_target_model_version")),
        migration_canary_id=optional_text(payload.get("migration_canary_id")),
        migration_planned_at=int(payload["migration_planned_at"])
        if payload.get("migration_planned_at") is not None
        else None,
    )


def _token_chunks(text: str, chunk_tokens: int) -> Iterable[str]:
    chunk_tokens = max(1, min(int(chunk_tokens or 4), 128))
    words = text.split()
    for idx in range(0, len(words), chunk_tokens):
        yield " ".join(words[idx : idx + chunk_tokens])


async def _stream_values(value: Any) -> AsyncIterator[Any]:
    if inspect.isawaitable(value):
        value = await value
    if isinstance(value, (str, bytes, bytearray, memoryview)):
        yield value
        return
    if hasattr(value, "__aiter__"):
        async for chunk in value:
            yield chunk
        return
    for chunk in value:
        yield chunk


class CrowkisClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 6379,
        *,
        tenant: Optional[str] = None,
        model: Optional[str] = None,
        auth_token: Optional[str] = None,
        timeout: float = 5.0,
        max_retries: int = 2,
        backoff_base: float = 0.1,
    ) -> None:
        self.host = host
        self.port = port
        self.tenant = tenant
        self.model = model
        self.auth_token = auth_token
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.backoff_base = max(0.0, backoff_base)
        self._sock: Optional[socket.socket] = None
        self._resp3 = False

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None
            self._resp3 = False

    def __enter__(self) -> "CrowkisClient":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def connect(self) -> None:
        if self._sock is None:
            self._sock = socket.create_connection((self.host, self.port), self.timeout)
            if self.auth_token:
                self._sock.sendall(_encode(["AUTH", self.auth_token]))
                _read_resp(self._sock)

    def execute(self, *args: BytesLike) -> Any:
        # Retry connection-level failures with exponential backoff +
        # jitter. RESP-level errors (CrowkisError) are NOT retried —
        # the server answered; retrying a rejected command is wrong.
        attempt = 0
        while True:
            try:
                self.connect()
                assert self._sock is not None
                self._sock.sendall(_encode(args))
                return _read_resp(self._sock)
            except (OSError, ConnectionError) as exc:
                self.close()
                if attempt >= self.max_retries:
                    raise CrowkisError(
                        f"connection to {self.host}:{self.port} failed after "
                        f"{attempt + 1} attempt(s): {exc}"
                    ) from exc
                delay = self.backoff_base * (2 ** attempt)
                delay += random.uniform(0, delay * 0.1)
                time.sleep(delay)
                attempt += 1

    def _hello3(self) -> None:
        if not self._resp3:
            self.execute("HELLO", "3")
            self._resp3 = True

    def ping(self) -> bool:
        return self.execute("PING") in ("PONG", b"PONG")

    def get(self, key: BytesLike) -> Optional[bytes]:
        value = self.execute("GET", key)
        return value if isinstance(value, bytes) else None

    def set(self, key: BytesLike, value: BytesLike, *, ttl: Optional[int] = None) -> None:
        args: List[BytesLike] = ["SET", key, value]
        if ttl is not None:
            args += ["EX", str(ttl)]
        self.execute(*args)

    def cset(
        self,
        query: BytesLike,
        response: BytesLike,
        *,
        ttl: Optional[int] = None,
        tenant: Optional[str] = None,
        model: Optional[str] = None,
        model_version: Optional[str] = None,
        image: Optional[BytesLike] = None,
    ) -> None:
        args: List[BytesLike] = ["CSET", query, response]
        if ttl is not None:
            args += ["EX", str(ttl)]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant or ""]
        if model or self.model:
            args += ["MODEL", model or self.model or ""]
        if model_version is not None:
            args += ["MODEL_VERSION", model_version]
        image_payload = _image_b64(image)
        if image_payload is not None:
            args += ["IMAGE", image_payload]
        self.execute(*args)

    def cget(
        self,
        query: BytesLike,
        *,
        threshold: Optional[float] = None,
        tenant: Optional[str] = None,
        model: Optional[str] = None,
        model_version: Optional[str] = None,
        migration_mode: Optional[str] = None,
        image: Optional[BytesLike] = None,
    ) -> Optional[bytes]:
        args: List[BytesLike] = ["CGET", query]
        if threshold is not None:
            args += ["THRESHOLD", str(threshold)]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant or ""]
        if model or self.model:
            args += ["MODEL", model or self.model or ""]
        if model_version is not None:
            args += ["MODEL_VERSION", model_version]
        if migration_mode is not None:
            args += ["MIGRATION_MODE", migration_mode]
        image_payload = _image_b64(image)
        if image_payload is not None:
            args += ["IMAGE", image_payload]
        value = self.execute(*args)
        if isinstance(value, dict):
            return value.get("response")
        return value if isinstance(value, bytes) else None

    def cget_hit(self, query: BytesLike, **kwargs: Any) -> Optional[CacheHit]:
        self._hello3()
        args: List[BytesLike] = ["CGET", query]
        threshold = kwargs.get("threshold")
        tenant = kwargs.get("tenant") or self.tenant
        model = kwargs.get("model") or self.model
        model_version = kwargs.get("model_version")
        migration_mode = kwargs.get("migration_mode")
        image_payload = _image_b64(kwargs.get("image"))
        if threshold is not None:
            args += ["THRESHOLD", str(threshold)]
        if tenant:
            args += ["TENANT", tenant]
        if model:
            args += ["MODEL", model]
        if model_version is not None:
            args += ["MODEL_VERSION", model_version]
        if migration_mode is not None:
            args += ["MIGRATION_MODE", migration_mode]
        if image_payload is not None:
            args += ["IMAGE", image_payload]
        value = self.execute(*args)
        return _cache_hit(value) if isinstance(value, dict) else None

    def cimgget(
        self,
        image: BytesLike,
        *,
        threshold: Optional[float] = None,
        tenant: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[bytes]:
        args: List[BytesLike] = ["CIMGGET", _image_b64(image) or b""]
        if threshold is not None:
            args += ["THRESHOLD", str(threshold)]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant or ""]
        if model or self.model:
            args += ["MODEL", model or self.model or ""]
        value = self.execute(*args)
        if isinstance(value, dict):
            return value.get("response")
        return value if isinstance(value, bytes) else None

    def csim(self, query: BytesLike, *, k: int = 10, tenant: Optional[str] = None) -> List[SimResult]:
        self._hello3()
        args: List[BytesLike] = ["CSIM", query, "K", str(max(1, k))]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant or ""]
        value = self.execute(*args)
        return [
            SimResult(key=item.get("key") or b"", similarity=float(item.get("similarity") or 0.0))
            for item in (value or [])
            if isinstance(item, dict)
        ]

    def cflush(self, *, tenant: Optional[str] = None) -> int:
        args: List[BytesLike] = ["CFLUSH"]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant or ""]
        return int(self.execute(*args))

    def cveccount(self) -> int:
        return int(self.execute("CVECCOUNT"))

    def cembed(self, text: str) -> List[float]:
        value = self.execute("CEMBED", text)
        return [float(v) for v in value] if isinstance(value, list) else []

    def creuse(self, query: str) -> Any:
        return self.execute("CREUSE", query)

    def cthink(self, query: str, cot_trace: str) -> Any:
        return self.execute("CTHINK", query, cot_trace)

    def cwhyevict(self, query: str, tenant: Optional[str] = None) -> Any:
        args: List[BytesLike] = ["CWHYEVICT", query]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant]
        return self.execute(*args)

    def cstale(self, query: str, tenant: Optional[str] = None) -> Any:
        args: List[BytesLike] = ["CSTALE", query]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant]
        return self.execute(*args)

    def cinvalidate(
        self,
        instruction: str,
        *,
        tenant: Optional[str] = None,
        threshold: Optional[float] = None,
        limit: Optional[int] = None,
        commit: bool = False,
    ) -> Any:
        args: List[BytesLike] = ["CINVALIDATE", instruction]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant]
        if threshold is not None:
            args += ["THRESHOLD", str(threshold)]
        if limit is not None:
            args += ["LIMIT", str(limit)]
        if commit:
            args.append("COMMIT")
        return self.execute(*args)

    def cmemset(self, agent: str, fact: str, *, user: Optional[str] = None, ex: Optional[int] = None) -> Any:
        args: List[BytesLike] = ["CMEMSET", agent, fact]
        if user:
            args += ["USER", user]
        if ex is not None:
            args += ["EX", str(ex)]
        return self.execute(*args)

    def cmemget(self, agent: str, query: str, *, user: Optional[str] = None, k: Optional[int] = None) -> Any:
        args: List[BytesLike] = ["CMEMGET", agent, query]
        if user:
            args += ["USER", user]
        if k is not None:
            args += ["K", str(k)]
        return self.execute(*args)

    def cmemextract(self, agent: str, conversation: str, *, user: Optional[str] = None, ex: Optional[int] = None) -> Any:
        args: List[BytesLike] = ["CMEMEXTRACT", agent, conversation]
        if user:
            args += ["USER", user]
        if ex is not None:
            args += ["EX", str(ex)]
        return self.execute(*args)

    def cmemhistory(self, agent: str, query: str, *, user: Optional[str] = None, k: Optional[int] = None) -> Any:
        args: List[BytesLike] = ["CMEMHISTORY", agent, query]
        if user:
            args += ["USER", user]
        if k is not None:
            args += ["K", str(k)]
        return self.execute(*args)

    def cmemasof(self, agent: str, query: str, unix_ms: int, *, user: Optional[str] = None, k: Optional[int] = None) -> Any:
        args: List[BytesLike] = ["CMEMASOF", agent, query, str(unix_ms)]
        if user:
            args += ["USER", user]
        if k is not None:
            args += ["K", str(k)]
        return self.execute(*args)

    def cmemforget(self, agent: str, *, query: Optional[str] = None, user: Optional[str] = None, threshold: Optional[float] = None) -> Any:
        args: List[BytesLike] = ["CMEMFORGET", agent]
        if query:
            args.append(query)
        if user:
            args += ["USER", user]
        if threshold is not None:
            args += ["THRESHOLD", str(threshold)]
        return self.execute(*args)

    def cmemlink(self, agent: str, subject: str, relation: str, obj: str, *, user: Optional[str] = None) -> Any:
        args: List[BytesLike] = ["CMEMLINK", agent, subject, relation, obj]
        if user:
            args += ["USER", user]
        return self.execute(*args)

    def cmemgraph(self, agent: str, entity: str, *, user: Optional[str] = None, depth: Optional[int] = None) -> Any:
        args: List[BytesLike] = ["CMEMGRAPH", agent, entity]
        if user:
            args += ["USER", user]
        if depth is not None:
            args += ["DEPTH", str(depth)]
        return self.execute(*args)

    def cdoc_add(self, doc_id: str, text: str, *, tenant: Optional[str] = None, ex: Optional[int] = None) -> Any:
        args: List[BytesLike] = ["CDOC", "ADD", doc_id, text]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant]
        if ex is not None:
            args += ["EX", str(ex)]
        return self.execute(*args)

    def cdoc_search(self, query: str, *, k: Optional[int] = None, tenant: Optional[str] = None) -> Any:
        args: List[BytesLike] = ["CDOC", "SEARCH", query]
        if k is not None:
            args += ["K", str(k)]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant]
        return self.execute(*args)

    def csession_add(self, session: str, role: str, text: str, *, ex: Optional[int] = None) -> Any:
        args: List[BytesLike] = ["CSESSION", "ADD", session, role, text]
        if ex is not None:
            args += ["EX", str(ex)]
        return self.execute(*args)

    def csession_recent(self, session: str, *, n: Optional[int] = None) -> Any:
        args: List[BytesLike] = ["CSESSION", "RECENT", session]
        if n is not None:
            args += ["N", str(n)]
        return self.execute(*args)

    def csession_search(self, session: str, query: str, *, k: Optional[int] = None) -> Any:
        args: List[BytesLike] = ["CSESSION", "SEARCH", session, query]
        if k is not None:
            args += ["K", str(k)]
        return self.execute(*args)

    def cpin(self, query: str, answer: str, *, by: Optional[str] = None, tenant: Optional[str] = None) -> Any:
        args: List[BytesLike] = ["CPIN", query, answer]
        if by:
            args += ["BY", by]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant]
        return self.execute(*args)

    def cpinget(self, query: str, *, tenant: Optional[str] = None, threshold: Optional[float] = None) -> Any:
        args: List[BytesLike] = ["CPINGET", query]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant]
        if threshold is not None:
            args += ["THRESHOLD", str(threshold)]
        return self.execute(*args)

    def cpinlist(self, *, tenant: Optional[str] = None) -> Any:
        args: List[BytesLike] = ["CPINLIST"]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant]
        return self.execute(*args)

    def cunpin(self, query: str, *, tenant: Optional[str] = None) -> Any:
        args: List[BytesLike] = ["CUNPIN", query]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant]
        return self.execute(*args)

    def ctoolset(self, tool: str, args_str: str, result: str, *, ex: Optional[int] = None, tenant: Optional[str] = None) -> Any:
        parts: List[BytesLike] = ["CTOOLSET", tool, args_str, result]
        if ex is not None:
            parts += ["EX", str(ex)]
        if tenant or self.tenant:
            parts += ["TENANT", tenant or self.tenant]
        return self.execute(*parts)

    def ctoolget(self, tool: str, args_str: str, *, tenant: Optional[str] = None) -> Any:
        parts: List[BytesLike] = ["CTOOLGET", tool, args_str]
        if tenant or self.tenant:
            parts += ["TENANT", tenant or self.tenant]
        return self.execute(*parts)

    def cflag(self, query: str, bad_answer: str, *, reason: Optional[str] = None, tenant: Optional[str] = None) -> Any:
        args: List[BytesLike] = ["CFLAG", query, bad_answer]
        if reason:
            args += ["REASON", reason]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant]
        return self.execute(*args)

    def ccheckbad(self, query: str, *, tenant: Optional[str] = None, threshold: Optional[float] = None) -> Any:
        args: List[BytesLike] = ["CCHECKBAD", query]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant]
        if threshold is not None:
            args += ["THRESHOLD", str(threshold)]
        return self.execute(*args)

    def cguard(self, text: str) -> Any:
        return self.execute("CGUARD", text)

    def coutcheck(self, text: str) -> Any:
        return self.execute("COUTCHECK", text)

    def cscan(
        self,
        cursor: Union[str, int] = "0",
        *,
        match: Optional[str] = None,
        count: Optional[int] = None,
        intent: Optional[str] = None,
    ) -> Tuple[str, List[bytes]]:
        """Cursor-scan cached entries, optionally filtered by intent class.
        Returns ``(next_cursor, keys)``; keep calling until next_cursor == "0"."""
        args: List[BytesLike] = ["CSCAN", str(cursor)]
        if match is not None:
            args += ["MATCH", match]
        if count is not None:
            args += ["COUNT", str(count)]
        if intent is not None:
            args += ["INTENT", intent]
        value = self.execute(*args)
        if isinstance(value, list) and len(value) == 2:
            nxt = value[0].decode() if isinstance(value[0], bytes) else str(value[0])
            keys = list(value[1] or [])
            return nxt, keys
        return "0", []

    def ceval(
        self,
        evaluator: str,
        input: str,
        output: str,
        *,
        expect: Optional[str] = None,
        threshold: Optional[float] = None,
    ) -> Any:
        """Score an ``output`` for an ``input`` with a named evaluator (or ``SUITE``).
        Returns rows of ``(name, score, passed, detail)`` — LLM-as-judge style evals."""
        args: List[BytesLike] = ["CEVAL", evaluator, input, output]
        if expect is not None:
            args += ["EXPECT", expect]
        if threshold is not None:
            args += ["THRESHOLD", str(threshold)]
        return self.execute(*args)

    def cprompt_set(self, name: str, template: BytesLike) -> int:
        """Store a new version of a named prompt template. Returns the version number."""
        return int(self.execute("CPROMPT", "SET", name, template))

    def cprompt_get(self, name: str, *, version: Optional[int] = None) -> Optional[bytes]:
        """Fetch a prompt template (latest, or a specific ``version``)."""
        args: List[BytesLike] = ["CPROMPT", "GET", name]
        if version is not None:
            args.append(str(version))
        value = self.execute(*args)
        return value if isinstance(value, bytes) else None

    def cprompt_list(self) -> List[Any]:
        """List all stored prompt names (prompt versioning / A/B)."""
        value = self.execute("CPROMPT", "LIST")
        return value if isinstance(value, list) else []

    def cprompt_versions(self, name: str) -> Any:
        """List the versions of a named prompt."""
        return self.execute("CPROMPT", "VERSIONS", name)

    def csource_link(self, source_id: str, query: BytesLike, *, tenant: Optional[str] = None) -> bool:
        """Link a cached query to a data source, so a source change can invalidate it."""
        args: List[BytesLike] = ["CSOURCE", "LINK", source_id, query]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant or ""]
        return self.execute(*args) in ("OK", b"OK")

    def csource_purge(self, source_id: str) -> int:
        """Purge every cached entry linked to ``source_id``. Returns the count purged."""
        return int(self.execute("CSOURCE", "PURGE", source_id))

    def csource_list(self, source_id: str) -> List[Any]:
        """List the queries linked to a data source."""
        value = self.execute("CSOURCE", "LIST", source_id)
        return value if isinstance(value, list) else []

    def compact(self) -> Any:
        """Trigger a storage-engine compaction pass (reclaim space, GC deletes)."""
        return self.execute("COMPACT")

    # ── Phase 0.1 operator surface ───────────────────────────────────────

    def cinfo(self, section: Optional[str] = None) -> str:
        args: List[BytesLike] = ["CINFO"]
        if section:
            args.append(section)
        value = self.execute(*args)
        return value.decode() if isinstance(value, bytes) else str(value)

    def cbudget_get(self, tenant: Optional[str] = None) -> Dict[str, Any]:
        self._hello3()
        value = self.execute("CBUDGET", "GET", tenant or self.tenant or "default")
        return value if isinstance(value, dict) else {}

    def cbudget_alerts(self) -> List[Dict[str, Any]]:
        self._hello3()
        value = self.execute("CBUDGET", "ALERTS")
        return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []

    def cbudget_set(
        self,
        tenant: Optional[str] = None,
        *,
        daily_usd: Optional[float] = None,
        monthly_usd: Optional[float] = None,
        cost_per_1k: Optional[float] = None,
        alert_pct: Optional[float] = None,
        circuit_pct: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Set a tenant's spend budget. The gateway enforces it: cost-aware
        routing past the alert %, and a hard block on upstream calls past the
        circuit-breaker %."""
        self._hello3()
        args: List[BytesLike] = ["CBUDGET", "SET", tenant or self.tenant or "default"]
        if daily_usd is not None:
            args += ["DAILY", str(daily_usd)]
        if monthly_usd is not None:
            args += ["MONTHLY", str(monthly_usd)]
        if cost_per_1k is not None:
            args += ["COST", str(cost_per_1k)]
        if alert_pct is not None:
            args += ["ALERT", str(alert_pct)]
        if circuit_pct is not None:
            args += ["CIRCUIT", str(circuit_pct)]
        value = self.execute(*args)
        return value if isinstance(value, dict) else {}

    def cdedup(self, tenant: Optional[str] = None) -> Dict[str, Any]:
        self._hello3()
        args: List[BytesLike] = ["CDEDUP"]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant or ""]
        value = self.execute(*args)
        return value if isinstance(value, dict) else {}

    def cpii_report(self, tenant: Optional[str] = None) -> Dict[str, Any]:
        self._hello3()
        args: List[BytesLike] = ["CPII", "REPORT"]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant or ""]
        value = self.execute(*args)
        return value if isinstance(value, dict) else {}

    def cpii_erase(self, identifier: str, *, tenant: Optional[str] = None) -> Dict[str, Any]:
        self._hello3()
        args: List[BytesLike] = ["CPII", "ERASE", identifier]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant or ""]
        value = self.execute(*args)
        return value if isinstance(value, dict) else {}

    def csave(self, dest: str) -> bool:
        return self.execute("CSAVE", dest) in ("OK", b"OK")

    def cbgsave(self, dest: str) -> bool:
        value = self.execute("CBGSAVE", dest)
        return value in ("BGSAVE-STARTED", b"BGSAVE-STARTED")

    def creload(self) -> Dict[str, Any]:
        self._hello3()
        value = self.execute("CRELOAD")
        return value if isinstance(value, dict) else {}

    def ckeylimit_set(self, tenant: str, *, rpm: int, tpm: Optional[int] = None) -> bool:
        args: List[BytesLike] = ["CKEYLIMIT", "SET", tenant, "RPM", str(rpm)]
        if tpm is not None:
            args += ["TPM", str(tpm)]
        return self.execute(*args) in ("OK", b"OK")

    def ckeylimit_get(self, tenant: str) -> Optional[Dict[str, Any]]:
        self._hello3()
        value = self.execute("CKEYLIMIT", "GET", tenant)
        return value if isinstance(value, dict) else None

    def ckeylimit_del(self, tenant: str) -> bool:
        return self.execute("CKEYLIMIT", "DEL", tenant) == 1

    def get_or_compute(
        self,
        query: str,
        fn: Callable[[str], Union[str, bytes]],
        *,
        threshold: Optional[float] = None,
        ttl: Optional[int] = None,
        tenant: Optional[str] = None,
        model: Optional[str] = None,
        model_version: Optional[str] = None,
        migration_mode: Optional[str] = None,
        image: Optional[BytesLike] = None,
    ) -> str:
        cached = self.cget(
            query,
            threshold=threshold,
            tenant=tenant,
            model=model,
            model_version=model_version,
            migration_mode=migration_mode,
            image=image,
        )
        if cached is not None:
            return cached.decode("utf-8", errors="replace")
        response = fn(query)
        response_bytes = _b(response)
        self.cset(
            query,
            response_bytes,
            ttl=ttl,
            tenant=tenant,
            model=model,
            model_version=model_version,
            image=image,
        )
        return response_bytes.decode("utf-8", errors="replace")

    # ── High-level, model-agnostic cache API ────────────────────────────────
    # These work with ANY model or provider. You bring the call; Crowkis caches
    # it by meaning. Nothing here is tied to OpenAI, Anthropic, or any vendor.

    def lookup(self, prompt: BytesLike, **kwargs: Any) -> Optional[CacheHit]:
        """Semantic lookup. Returns a :class:`CacheHit` (``.text``, ``.similarity``,
        ``.confidence``) if a cached answer means the same thing, else ``None``."""
        return self.cget_hit(prompt, **kwargs)

    def store(self, prompt: BytesLike, answer: BytesLike, **kwargs: Any) -> None:
        """Cache ``answer`` for ``prompt`` (optionally ``ttl=`` seconds)."""
        self.cset(prompt, answer, **kwargs)

    def ask(
        self,
        prompt: str,
        compute: Callable[[str], Union[str, bytes]],
        **kwargs: Any,
    ) -> str:
        """Return the cached answer for ``prompt``; otherwise call ``compute(prompt)``
        — which may invoke **any** model — cache the result, and return it."""
        return self.get_or_compute(prompt, compute, **kwargs)

    def cached(
        self,
        *,
        ttl: Optional[int] = None,
        threshold: Optional[float] = None,
        tenant: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., str]]:
        """Decorator that adds a semantic cache to **any** function whose first
        argument is the prompt. Model-agnostic — the wrapped call can hit any
        provider. Works like ``functools.lru_cache``, but matches on meaning.

        Example::

            cache = Crowkis(tenant="my-app")

            @cache.cached(ttl=3600)
            def answer(prompt: str) -> str:
                return any_model(prompt)   # OpenAI, Claude, a local model — anything
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., str]:
            @functools.wraps(fn)
            def wrapper(prompt: str, *args: Any, **kw: Any) -> str:
                hit = self.cget(prompt, threshold=threshold, tenant=tenant, model=model)
                if hit is not None:
                    return hit.decode("utf-8", errors="replace")
                result = fn(prompt, *args, **kw)
                self.cset(prompt, _b(result), ttl=ttl, tenant=tenant, model=model)
                return (
                    result
                    if isinstance(result, str)
                    else _b(result).decode("utf-8", errors="replace")
                )

            return wrapper

        return decorator

    def similar(self, prompt: BytesLike, *, k: int = 10, tenant: Optional[str] = None) -> List[SimResult]:
        """The ``k`` most semantically similar cached prompts."""
        return self.csim(prompt, k=k, tenant=tenant)

    def embed(self, text: str) -> List[float]:
        """Return the raw embedding vector for ``text`` (computed server-side)."""
        return self.cembed(text)

    def flush(self, *, tenant: Optional[str] = None) -> int:
        """Clear this tenant's cache; returns the number of entries removed."""
        return self.cflush(tenant=tenant)


#: Idiomatic short name for the client — ``crowkis.Crowkis(...)`` (like ``redis.Redis``).
Crowkis = CrowkisClient


class AsyncCrowkisClient(CrowkisClient):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def aclose(self) -> None:
        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()
        self._reader = None
        self._writer = None
        self._resp3 = False

    async def __aenter__(self) -> "AsyncCrowkisClient":
        await self.aconnect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aconnect(self) -> None:
        if self._reader is None or self._writer is None:
            self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
            if self.auth_token:
                self._writer.write(_encode(["AUTH", self.auth_token]))
                await self._writer.drain()
                await _aread_resp(self._reader)

    async def execute_async(self, *args: BytesLike) -> Any:
        await self.aconnect()
        assert self._reader is not None and self._writer is not None
        self._writer.write(_encode(args))
        await self._writer.drain()
        return await _aread_resp(self._reader)

    async def cget_async(self, query: BytesLike, **kwargs: Any) -> Optional[bytes]:
        args: List[BytesLike] = ["CGET", query]
        if kwargs.get("threshold") is not None:
            args += ["THRESHOLD", str(kwargs["threshold"])]
        tenant = kwargs.get("tenant") or self.tenant
        model = kwargs.get("model") or self.model
        if tenant:
            args += ["TENANT", tenant]
        if model:
            args += ["MODEL", model]
        model_version = kwargs.get("model_version")
        if model_version is not None:
            args += ["MODEL_VERSION", model_version]
        migration_mode = kwargs.get("migration_mode")
        if migration_mode is not None:
            args += ["MIGRATION_MODE", migration_mode]
        image_payload = _image_b64(kwargs.get("image"))
        if image_payload is not None:
            args += ["IMAGE", image_payload]
        value = await self.execute_async(*args)
        if isinstance(value, dict):
            return value.get("response")
        return value if isinstance(value, bytes) else None

    async def cset_async(self, query: BytesLike, response: BytesLike, **kwargs: Any) -> None:
        args: List[BytesLike] = ["CSET", query, response]
        if kwargs.get("ttl") is not None:
            args += ["EX", str(kwargs["ttl"])]
        tenant = kwargs.get("tenant") or self.tenant
        model = kwargs.get("model") or self.model
        if tenant:
            args += ["TENANT", tenant]
        if model:
            args += ["MODEL", model]
        model_version = kwargs.get("model_version")
        if model_version is not None:
            args += ["MODEL_VERSION", model_version]
        image_payload = _image_b64(kwargs.get("image"))
        if image_payload is not None:
            args += ["IMAGE", image_payload]
        await self.execute_async(*args)

    async def get_or_compute_async(
        self,
        query: str,
        fn: Callable[[str], Awaitable[Union[str, bytes]]],
        **kwargs: Any,
    ) -> str:
        cached = await self.cget_async(query, **kwargs)
        if cached is not None:
            return cached.decode("utf-8", errors="replace")
        response = await fn(query)
        response_bytes = _b(response)
        await self.cset_async(query, response_bytes, **kwargs)
        return response_bytes.decode("utf-8", errors="replace")

    async def stream_get_or_compute(
        self,
        query: str,
        fn: Callable[[str], Any],
        *,
        threshold: Optional[float] = None,
        ttl: Optional[int] = None,
        tenant: Optional[str] = None,
        model: Optional[str] = None,
        model_version: Optional[str] = None,
        migration_mode: Optional[str] = None,
        chunk_tokens: int = 4,
        delay_ms: int = 20,
    ) -> AsyncIterator[Union[str, bytes]]:
        cached = await self.cget_async(
            query,
            threshold=threshold,
            tenant=tenant,
            model=model,
            model_version=model_version,
            migration_mode=migration_mode,
        )
        if cached is not None:
            text = cached.decode("utf-8", errors="replace")
            for chunk in _token_chunks(text, chunk_tokens):
                yield chunk
                if delay_ms > 0:
                    await asyncio.sleep(min(delay_ms, 2_000) / 1000.0)
            return

        assembled = bytearray()
        completed = False
        try:
            async for chunk in _stream_values(fn(query)):
                assembled.extend(_b(chunk))
                yield chunk
            completed = True
        finally:
            if completed:
                await self.cset_async(
                    query,
                    bytes(assembled),
                    ttl=ttl,
                    tenant=tenant,
                    model=model,
                    model_version=model_version,
                )

    # ── High-level async API (clean names, model-agnostic) ──────────────────

    async def ask(
        self,
        prompt: str,
        compute: Callable[[str], Awaitable[Union[str, bytes]]],
        **kwargs: Any,
    ) -> str:
        """Async recall-or-compute: return the cached answer, or ``await compute(prompt)``
        for any model, cache it, and return it."""
        return await self.get_or_compute_async(prompt, compute, **kwargs)

    def stream(
        self,
        prompt: str,
        compute: Callable[[str], Any],
        **kwargs: Any,
    ) -> AsyncIterator[Union[str, bytes]]:
        """Stream a cached answer in chunks (feels like live model output), or stream
        the model on a miss and cache the assembled result."""
        return self.stream_get_or_compute(prompt, compute, **kwargs)

    async def store(self, prompt: BytesLike, answer: BytesLike, **kwargs: Any) -> None:
        """Async cache write."""
        await self.cset_async(prompt, answer, **kwargs)


#: Idiomatic short name for the async client — ``crowkis.AsyncCrowkis(...)`` (like ``AsyncOpenAI``).
AsyncCrowkis = AsyncCrowkisClient


class CrowkisAdmin:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:6380",
        *,
        admin_key: Optional[str] = None,
        timeout: float = 5.0,
    ) -> None:
        parsed = urlparse(base_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 6380
        self.admin_key = admin_key
        self.timeout = timeout

    def _request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        payload = None if body is None else json.dumps(body).encode()
        headers = {"content-type": "application/json"}
        if self.admin_key:
            headers["x-crowkis-admin-key"] = self.admin_key
        conn = HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            data = response.read()
            if response.status >= 400:
                raise CrowkisError(data.decode(errors="replace"))
            if not data:
                return None
            content_type = response.getheader("content-type") or ""
            if "json" in content_type or data[:1] in (b"{", b"["):
                return json.loads(data)
            return data.decode(errors="replace")
        finally:
            conn.close()

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/health")

    def get_stats(self) -> Dict[str, Any]:
        return self._request("GET", "/stats")

    def update_threshold(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("PUT", "/config/thresholds", config)

    def register_webhook(self, webhook: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/api/v1/webhooks", webhook)

    def invalidate_source(self, source_id: str, **extra: Any) -> Dict[str, Any]:
        return self._request("POST", "/api/v1/invalidate", {"source_id": source_id, **extra})

    def flush_tenant(self, tenant_id: str) -> Dict[str, Any]:
        return self._request("POST", f"/api/v1/tenants/{tenant_id}/flush", {})

    def cache_entries(self, *, tenant: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        query = urlencode({k: v for k, v in {"tenant": tenant, "limit": limit}.items() if v is not None})
        suffix = f"?{query}" if query else ""
        return self._request("GET", f"/api/v1/cache/entries{suffix}")

    def migration_progress(
        self,
        *,
        tenant: Optional[str] = None,
        canary_id: Optional[str] = None,
        from_model_version: Optional[str] = None,
        target_model_version: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        query = urlencode(
            {
                k: v
                for k, v in {
                    "tenant": tenant,
                    "canary_id": canary_id,
                    "from_model_version": from_model_version,
                    "target_model_version": target_model_version,
                    "limit": limit,
                }.items()
                if v is not None
            }
        )
        suffix = f"?{query}" if query else ""
        return self._request("GET", f"/api/v1/llm/migrations/progress{suffix}")

    def canary_migration_progress(
        self,
        canary_id: str,
        *,
        tenant: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        query = urlencode({k: v for k, v in {"tenant": tenant, "limit": limit}.items() if v is not None})
        suffix = f"?{query}" if query else ""
        return self._request("GET", f"/api/v1/llm/canaries/{canary_id}/migration-progress{suffix}")

    def lease_migration_work(self, **options: Any) -> Dict[str, Any]:
        return self._request("POST", "/api/v1/llm/migrations/lease", options)

    def lease_canary_migration_work(self, canary_id: str, **options: Any) -> Dict[str, Any]:
        return self._request("POST", f"/api/v1/llm/canaries/{canary_id}/migration-lease", options)

    def complete_migration_work(self, **item: Any) -> Dict[str, Any]:
        return self._request("POST", "/api/v1/llm/migrations/complete", item)

    def fail_migration_work(self, **item: Any) -> Dict[str, Any]:
        return self._request("POST", "/api/v1/llm/migrations/fail", item)
