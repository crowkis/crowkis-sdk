from __future__ import annotations

import asyncio
import base64
import functools
import inspect
import json
import logging
import random
import socket
import threading
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

    retryable = True


_LOG = logging.getLogger("crowkis")

MAX_LINE_BYTES = 512 * 1024
BUSY_DEFAULT_RETRY_SECONDS = 0.05
BUSY_MAX_RETRY_SECONDS = 2.0


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


def _read_line(reader: Any) -> bytes:
    line = reader.readline(MAX_LINE_BYTES)
    if not line.endswith(b"\r\n"):
        raise CrowkisError("connection closed")
    return line[:-2]


def _read_exact(reader: Any, n: int) -> bytes:
    if n == 0:
        return b""
    data = reader.read(n)
    if data is None or len(data) != n:
        raise CrowkisError("connection closed")
    return data


def _read_frame(reader: Any) -> Any:
    line = _read_line(reader)
    if not line:
        raise CrowkisError("empty RESP frame")
    prefix, payload = line[:1], line[1:]

    if prefix == b"+":
        return payload.decode(errors="replace")
    if prefix == b"-":
        return CrowkisError(payload.decode(errors="replace"))
    if prefix == b":":
        return int(payload)
    if prefix == b",":
        return float(payload)
    if prefix == b"_":
        return None
    if prefix == b"#":
        return payload == b"t"
    if prefix in (b"$", b"=", b"!"):
        length = int(payload)
        if length < 0:
            return None
        data = _read_exact(reader, length)
        _read_exact(reader, 2)
        return CrowkisError(data.decode(errors="replace")) if prefix == b"!" else data
    if prefix in (b"*", b"~", b">"):
        count = int(payload)
        if count < 0:
            return None
        return [_read_frame(reader) for _ in range(count)]
    if prefix in (b"%", b"|"):
        count = int(payload)
        out: Dict[Any, Any] = {}
        for _ in range(count):
            key = _read_frame(reader)
            value = _read_frame(reader)
            if isinstance(key, bytes):
                key = key.decode(errors="replace")
            out[key] = value
        if prefix == b"|":
            return _read_frame(reader)
        return out
    if prefix == b"(":
        return int(payload)

    raise CrowkisError(f"unexpected RESP frame: {line!r}")


def _read_resp(reader: Any) -> Any:
    reply = _read_frame(reader)
    if isinstance(reply, CrowkisError):
        raise reply
    return reply


async def _aread_line(reader: asyncio.StreamReader) -> bytes:
    line = await reader.readline()
    if not line.endswith(b"\r\n"):
        raise CrowkisError("connection closed")
    return line[:-2]


async def _aread_frame(reader: asyncio.StreamReader) -> Any:
    line = await _aread_line(reader)
    if not line:
        raise CrowkisError("empty RESP frame")
    prefix, payload = line[:1], line[1:]

    if prefix == b"+":
        return payload.decode(errors="replace")
    if prefix == b"-":
        return CrowkisError(payload.decode(errors="replace"))
    if prefix == b":":
        return int(payload)
    if prefix == b",":
        return float(payload)
    if prefix == b"_":
        return None
    if prefix == b"#":
        return payload == b"t"
    if prefix in (b"$", b"=", b"!"):
        length = int(payload)
        if length < 0:
            return None
        data = await reader.readexactly(length)
        await reader.readexactly(2)
        return CrowkisError(data.decode(errors="replace")) if prefix == b"!" else data
    if prefix in (b"*", b"~", b">"):
        count = int(payload)
        if count < 0:
            return None
        return [await _aread_frame(reader) for _ in range(count)]
    if prefix in (b"%", b"|"):
        count = int(payload)
        out: Dict[Any, Any] = {}
        for _ in range(count):
            key = await _aread_frame(reader)
            value = await _aread_frame(reader)
            if isinstance(key, bytes):
                key = key.decode(errors="replace")
            out[key] = value
        if prefix == b"|":
            return await _aread_frame(reader)
        return out
    if prefix == b"(":
        return int(payload)

    raise CrowkisError(f"unexpected RESP frame: {line!r}")


async def _aread_resp(reader: asyncio.StreamReader) -> Any:
    reply = await _aread_frame(reader)
    if isinstance(reply, CrowkisError):
        raise reply
    return reply


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


def _scope(
    tenant: Optional[str], user: Optional[str], topic: Optional[str]
) -> List[BytesLike]:
    args: List[BytesLike] = []
    if tenant:
        args += ["TENANT", tenant]
    if user:
        args += ["USER", user]
    if topic:
        args += ["TOPIC", topic]
    return args


def _tenant_model(tenant: Optional[str], model: Optional[str]) -> List[BytesLike]:
    args: List[BytesLike] = []
    if tenant:
        args += ["TENANT", tenant]
    if model:
        args += ["MODEL", model]
    return args


def _busy_retry_seconds(error: BaseException) -> Optional[float]:
    message = str(error)
    if not message.upper().startswith("BUSY"):
        return None
    marker = "retry-after-ms"
    at = message.find(marker)
    if at < 0:
        return BUSY_DEFAULT_RETRY_SECONDS
    digits = ""
    for char in message[at + len(marker) :].lstrip(" ="):
        if not char.isdigit():
            break
        digits += char
    if not digits:
        return BUSY_DEFAULT_RETRY_SECONDS
    return min(max(int(digits) / 1000.0, 0.001), BUSY_MAX_RETRY_SECONDS)


TRANSPORT_FAILURES = (OSError, CrowkisError, ValueError, RecursionError)


def _transport_error(host: str, port: int, attempts: int, cause: BaseException) -> CrowkisError:
    if isinstance(cause, CrowkisError) and not cause.retryable:
        return cause
    return CrowkisError(
        f"connection to {host}:{port} failed after {attempts} attempt(s): {cause}"
    )


class _Conn:
    __slots__ = ("sock", "reader")

    def __init__(self, sock: socket.socket, reader: Any) -> None:
        self.sock = sock
        self.reader = reader

    def close(self) -> None:
        try:
            self.reader.close()
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class _AsyncConn:
    __slots__ = ("reader", "writer")

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    def close(self) -> None:
        try:
            self.writer.close()
        except (OSError, ConnectionError):
            pass


ASYNC_TRANSPORT_FAILURES = TRANSPORT_FAILURES + (asyncio.TimeoutError,)


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
        port: int = 6383,
        *,
        tenant: Optional[str] = None,
        model: Optional[str] = None,
        user: Optional[str] = None,
        auth_token: Optional[str] = None,
        timeout: float = 5.0,
        connect_timeout: Optional[float] = None,
        read_timeout: Optional[float] = None,
        max_retries: int = 2,
        backoff_base: float = 0.1,
        pool_size: int = 8,
        fail_soft: bool = False,
        on_error: Optional[Callable[[BaseException], None]] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.tenant = tenant
        self.model = model
        self.user = user
        self.auth_token = auth_token
        self.timeout = timeout
        self.connect_timeout = float(timeout if connect_timeout is None else connect_timeout)
        self.read_timeout = float(timeout if read_timeout is None else read_timeout)
        self.max_retries = max(0, max_retries)
        self.backoff_base = max(0.0, backoff_base)
        self.pool_size = max(1, int(pool_size))
        self.fail_soft = bool(fail_soft)
        self.on_error = on_error
        self._pool: List[_Conn] = []
        self._pool_lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(self.pool_size)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(host={self.host!r}, port={self.port}, "
            f"tenant={self.tenant!r}, model={self.model!r})"
        )

    def scoped_tenant(self, tenant: Optional[str] = None) -> Optional[str]:
        return tenant or self.tenant

    def scoped_model(self, model: Optional[str] = None) -> Optional[str]:
        return model or self.model

    def scoped_user(self, user: Optional[str] = None) -> Optional[str]:
        return user or self.user

    def close(self) -> None:
        with self._pool_lock:
            pool, self._pool = self._pool, []
        for conn in pool:
            conn.close()

    def __enter__(self) -> "CrowkisClient":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _open(self) -> _Conn:
        sock = socket.create_connection((self.host, self.port), self.connect_timeout)
        sock.settimeout(self.read_timeout)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        conn = _Conn(sock, sock.makefile("rb"))
        try:
            if self.auth_token:
                sock.sendall(_encode(["AUTH", self.auth_token]))
                denied = _read_frame(conn.reader)
                if isinstance(denied, CrowkisError):
                    denied.retryable = False
                    raise denied
            sock.sendall(_encode(["HELLO", "3"]))
            _read_frame(conn.reader)
        except BaseException:
            conn.close()
            raise
        return conn

    def _take(self) -> _Conn:
        with self._pool_lock:
            if self._pool:
                return self._pool.pop()
        return self._open()

    def _give(self, conn: _Conn) -> None:
        with self._pool_lock:
            if len(self._pool) < self.pool_size:
                self._pool.append(conn)
                return
        conn.close()

    def connect(self) -> None:
        self._give(self._take())

    def _report(self, error: BaseException) -> None:
        handler = self.on_error
        if handler is None:
            _LOG.warning("crowkis request failed, treated as a cache miss: %s", error)
            return
        try:
            handler(error)
        except Exception:
            pass

    def _backoff(self, attempt: int) -> float:
        delay = self.backoff_base * (2 ** attempt)
        return delay + random.uniform(0, delay * 0.1)

    def execute(self, *args: BytesLike) -> Any:
        frame = _encode(args)
        try:
            return self.execute_strict(frame)
        except CrowkisError as exc:
            if not self.fail_soft:
                raise
            self._report(exc)
            return None

    def execute_strict(self, frame: bytes) -> Any:
        attempt = 0
        while True:
            delay: Optional[float] = None
            reply: Any = None
            self._slots.acquire()
            try:
                conn = self._take()
                try:
                    conn.sock.sendall(frame)
                    reply = _read_frame(conn.reader)
                except BaseException:
                    conn.close()
                    raise
                self._give(conn)
            except TRANSPORT_FAILURES as exc:
                if not getattr(exc, "retryable", True) or attempt >= self.max_retries:
                    raise _transport_error(self.host, self.port, attempt + 1, exc) from exc
                delay = self._backoff(attempt)
            finally:
                self._slots.release()

            if delay is None:
                if isinstance(reply, CrowkisError):
                    busy = _busy_retry_seconds(reply)
                    if busy is None or attempt >= self.max_retries:
                        raise reply
                    delay = busy
                else:
                    return reply
            time.sleep(delay)
            attempt += 1

    def pipeline(self, *commands: Iterable[BytesLike]) -> List[Any]:
        batch = list(commands)
        if not batch:
            return []
        frame = b"".join(_encode(command) for command in batch)
        self._slots.acquire()
        try:
            conn = self._take()
            try:
                conn.sock.sendall(frame)
                replies = [_read_frame(conn.reader) for _ in batch]
            except BaseException:
                conn.close()
                raise
            self._give(conn)
            return replies
        except TRANSPORT_FAILURES as exc:
            failure = _transport_error(self.host, self.port, 1, exc)
            if not self.fail_soft:
                raise failure from exc
            self._report(failure)
            return [None] * len(batch)
        finally:
            self._slots.release()

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
        template: bool = False,
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
        if template:
            args += ["TEMPLATE"]
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
        template: bool = False,
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
        if template:
            args += ["TEMPLATE"]
        value = self.execute(*args)
        if isinstance(value, dict):
            return value.get("response")
        return value if isinstance(value, bytes) else None

    def cget_hit(self, query: BytesLike, **kwargs: Any) -> Optional[CacheHit]:
        args: List[BytesLike] = ["CGET", query]
        threshold = kwargs.get("threshold")
        tenant = kwargs.get("tenant") or self.tenant
        model = kwargs.get("model") or self.model
        model_version = kwargs.get("model_version")
        migration_mode = kwargs.get("migration_mode")
        image_payload = _image_b64(kwargs.get("image"))
        template = bool(kwargs.get("template"))
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
        if template:
            args += ["TEMPLATE"]
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

    def csim(
        self,
        query: BytesLike,
        *,
        k: int = 10,
        tenant: Optional[str] = None,
        model: Optional[str] = None,
    ) -> List[SimResult]:
        args: List[BytesLike] = ["CSIM", query, "K", str(max(1, k))]
        args += _tenant_model(self.scoped_tenant(tenant), self.scoped_model(model))
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
        return int(self.execute(*args) or 0)

    def cveccount(self) -> int:
        return int(self.execute("CVECCOUNT") or 0)

    def cembed(self, text: str) -> List[float]:
        value = self.execute("CEMBED", text)
        return [float(v) for v in value] if isinstance(value, list) else []


    def _args_creuse(
        self, query: str, *, tenant: Optional[str] = None, model: Optional[str] = None
    ) -> List[BytesLike]:
        args: List[BytesLike] = ["CREUSE", query]
        args += _tenant_model(self.scoped_tenant(tenant), self.scoped_model(model))
        return args

    def creuse(
        self, query: str, *, tenant: Optional[str] = None, model: Optional[str] = None
    ) -> Any:
        return self.execute(*self._args_creuse(query, tenant=tenant, model=model))


    def _args_cthink(
        self,
        query: str,
        cot_trace: str,
        *,
        tenant: Optional[str] = None,
        model: Optional[str] = None,
    ) -> List[BytesLike]:
        args: List[BytesLike] = ["CTHINK", query, cot_trace]
        args += _tenant_model(self.scoped_tenant(tenant), self.scoped_model(model))
        return args

    def cthink(
        self,
        query: str,
        cot_trace: str,
        *,
        tenant: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Any:
        return self.execute(*self._args_cthink(query, cot_trace, tenant=tenant, model=model))

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


    def _args_cmemset(
        self,
        agent: str,
        fact: str,
        *,
        user: Optional[str] = None,
        ex: Optional[int] = None,
        tenant: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> List[BytesLike]:
        args: List[BytesLike] = ["CMEMSET", agent, fact]
        args += _scope(self.scoped_tenant(tenant), self.scoped_user(user), topic)
        if ex is not None:
            args += ["EX", str(ex)]
        return args

    def cmemset(
        self,
        agent: str,
        fact: str,
        *,
        user: Optional[str] = None,
        ex: Optional[int] = None,
        tenant: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> Any:
        return self.execute(*self._args_cmemset(agent, fact, user=user, ex=ex, tenant=tenant, topic=topic))


    def _args_cmemget(
        self,
        agent: str,
        query: str,
        *,
        user: Optional[str] = None,
        k: Optional[int] = None,
        tenant: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> List[BytesLike]:
        args: List[BytesLike] = ["CMEMGET", agent, query]
        args += _scope(self.scoped_tenant(tenant), self.scoped_user(user), topic)
        if k is not None:
            args += ["K", str(k)]
        return args

    def cmemget(
        self,
        agent: str,
        query: str,
        *,
        user: Optional[str] = None,
        k: Optional[int] = None,
        tenant: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> Any:
        return self.execute(*self._args_cmemget(agent, query, user=user, k=k, tenant=tenant, topic=topic))


    def _args_cmemextract(
        self,
        agent: str,
        conversation: str,
        *,
        user: Optional[str] = None,
        ex: Optional[int] = None,
        tenant: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> List[BytesLike]:
        args: List[BytesLike] = ["CMEMEXTRACT", agent, conversation]
        args += _scope(self.scoped_tenant(tenant), self.scoped_user(user), topic)
        if ex is not None:
            args += ["EX", str(ex)]
        return args

    def cmemextract(
        self,
        agent: str,
        conversation: str,
        *,
        user: Optional[str] = None,
        ex: Optional[int] = None,
        tenant: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> Any:
        return self.execute(*self._args_cmemextract(agent, conversation, user=user, ex=ex, tenant=tenant, topic=topic))


    def _args_cmemhistory(
        self,
        agent: str,
        query: str,
        *,
        user: Optional[str] = None,
        k: Optional[int] = None,
        tenant: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> List[BytesLike]:
        args: List[BytesLike] = ["CMEMHISTORY", agent, query]
        args += _scope(self.scoped_tenant(tenant), self.scoped_user(user), topic)
        if k is not None:
            args += ["K", str(k)]
        return args

    def cmemhistory(
        self,
        agent: str,
        query: str,
        *,
        user: Optional[str] = None,
        k: Optional[int] = None,
        tenant: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> Any:
        return self.execute(*self._args_cmemhistory(agent, query, user=user, k=k, tenant=tenant, topic=topic))


    def _args_cmemasof(
        self,
        agent: str,
        query: str,
        unix_ms: int,
        *,
        user: Optional[str] = None,
        k: Optional[int] = None,
        tenant: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> List[BytesLike]:
        args: List[BytesLike] = ["CMEMASOF", agent, query, str(unix_ms)]
        args += _scope(self.scoped_tenant(tenant), self.scoped_user(user), topic)
        if k is not None:
            args += ["K", str(k)]
        return args

    def cmemasof(
        self,
        agent: str,
        query: str,
        unix_ms: int,
        *,
        user: Optional[str] = None,
        k: Optional[int] = None,
        tenant: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> Any:
        return self.execute(*self._args_cmemasof(agent, query, unix_ms, user=user, k=k, tenant=tenant, topic=topic))


    def _args_cmemforget(
        self,
        agent: str,
        *,
        query: Optional[str] = None,
        user: Optional[str] = None,
        threshold: Optional[float] = None,
        tenant: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> List[BytesLike]:
        args: List[BytesLike] = ["CMEMFORGET", agent, query or ""]
        args += _scope(self.scoped_tenant(tenant), self.scoped_user(user), topic)
        if threshold is not None:
            args += ["THRESHOLD", str(threshold)]
        return args

    def cmemforget(
        self,
        agent: str,
        *,
        query: Optional[str] = None,
        user: Optional[str] = None,
        threshold: Optional[float] = None,
        tenant: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> Any:
        return self.execute(*self._args_cmemforget(agent, query=query, user=user, threshold=threshold, tenant=tenant, topic=topic))


    def _args_cmemlink(
        self,
        agent: str,
        subject: str,
        relation: str,
        obj: str,
        *,
        user: Optional[str] = None,
        tenant: Optional[str] = None,
    ) -> List[BytesLike]:
        args: List[BytesLike] = ["CMEMLINK", agent, subject, relation, obj]
        args += _scope(self.scoped_tenant(tenant), self.scoped_user(user), None)
        return args

    def cmemlink(
        self,
        agent: str,
        subject: str,
        relation: str,
        obj: str,
        *,
        user: Optional[str] = None,
        tenant: Optional[str] = None,
    ) -> Any:
        return self.execute(*self._args_cmemlink(agent, subject, relation, obj, user=user, tenant=tenant))


    def _args_cmemgraph(
        self,
        agent: str,
        entity: str,
        *,
        user: Optional[str] = None,
        depth: Optional[int] = None,
        tenant: Optional[str] = None,
    ) -> List[BytesLike]:
        args: List[BytesLike] = ["CMEMGRAPH", agent, entity]
        args += _scope(self.scoped_tenant(tenant), self.scoped_user(user), None)
        if depth is not None:
            args += ["DEPTH", str(depth)]
        return args

    def cmemgraph(
        self,
        agent: str,
        entity: str,
        *,
        user: Optional[str] = None,
        depth: Optional[int] = None,
        tenant: Optional[str] = None,
    ) -> Any:
        return self.execute(*self._args_cmemgraph(agent, entity, user=user, depth=depth, tenant=tenant))

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


    def _args_csession_add(
        self,
        session: str,
        role: str,
        text: str,
        *,
        ex: Optional[int] = None,
        tenant: Optional[str] = None,
    ) -> List[BytesLike]:
        args: List[BytesLike] = ["CSESSION", "ADD", session, role, text]
        args += _scope(self.scoped_tenant(tenant), None, None)
        if ex is not None:
            args += ["EX", str(ex)]
        return args

    def csession_add(
        self,
        session: str,
        role: str,
        text: str,
        *,
        ex: Optional[int] = None,
        tenant: Optional[str] = None,
    ) -> Any:
        return self.execute(*self._args_csession_add(session, role, text, ex=ex, tenant=tenant))


    def _args_csession_recent(
        self, session: str, *, n: Optional[int] = None, tenant: Optional[str] = None
    ) -> List[BytesLike]:
        args: List[BytesLike] = ["CSESSION", "RECENT", session]
        args += _scope(self.scoped_tenant(tenant), None, None)
        if n is not None:
            args += ["N", str(n)]
        return args

    def csession_recent(
        self, session: str, *, n: Optional[int] = None, tenant: Optional[str] = None
    ) -> Any:
        return self.execute(*self._args_csession_recent(session, n=n, tenant=tenant))


    def _args_csession_search(
        self, session: str, query: str, *, k: Optional[int] = None, tenant: Optional[str] = None
    ) -> List[BytesLike]:
        args: List[BytesLike] = ["CSESSION", "SEARCH", session, query]
        args += _scope(self.scoped_tenant(tenant), None, None)
        if k is not None:
            args += ["K", str(k)]
        return args

    def csession_search(
        self, session: str, query: str, *, k: Optional[int] = None, tenant: Optional[str] = None
    ) -> Any:
        return self.execute(*self._args_csession_search(session, query, k=k, tenant=tenant))

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
        args: List[BytesLike] = ["CEVAL", evaluator, input, output]
        if expect is not None:
            args += ["EXPECT", expect]
        if threshold is not None:
            args += ["THRESHOLD", str(threshold)]
        return self.execute(*args)

    def cprompt_set(self, name: str, template: BytesLike) -> int:
        return int(self.execute("CPROMPT", "SET", name, template) or 0)

    def cprompt_get(self, name: str, *, version: Optional[int] = None) -> Optional[bytes]:
        args: List[BytesLike] = ["CPROMPT", "GET", name]
        if version is not None:
            args.append(str(version))
        value = self.execute(*args)
        return value if isinstance(value, bytes) else None

    def cprompt_list(self) -> List[Any]:
        value = self.execute("CPROMPT", "LIST")
        return value if isinstance(value, list) else []

    def cprompt_versions(self, name: str) -> Any:
        return self.execute("CPROMPT", "VERSIONS", name)

    def csource_link(self, source_id: str, query: BytesLike, *, tenant: Optional[str] = None) -> bool:
        args: List[BytesLike] = ["CSOURCE", "LINK", source_id, query]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant or ""]
        return self.execute(*args) in ("OK", b"OK")

    def csource_purge(self, source_id: str) -> int:
        return int(self.execute("CSOURCE", "PURGE", source_id) or 0)

    def csource_list(self, source_id: str) -> List[Any]:
        value = self.execute("CSOURCE", "LIST", source_id)
        return value if isinstance(value, list) else []

    def compact(self) -> Any:
        return self.execute("COMPACT")


    def cinfo(self, section: Optional[str] = None) -> str:
        args: List[BytesLike] = ["CINFO"]
        if section:
            args.append(section)
        value = self.execute(*args)
        if value is None:
            return ""
        return value.decode(errors="replace") if isinstance(value, bytes) else str(value)

    def cbudget_get(self, tenant: Optional[str] = None) -> Dict[str, Any]:
        value = self.execute("CBUDGET", "GET", tenant or self.tenant or "default")
        return value if isinstance(value, dict) else {}

    def cbudget_alerts(self) -> List[Dict[str, Any]]:
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
        args: List[BytesLike] = ["CDEDUP"]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant or ""]
        value = self.execute(*args)
        return value if isinstance(value, dict) else {}

    def cpii_report(self, tenant: Optional[str] = None) -> Dict[str, Any]:
        args: List[BytesLike] = ["CPII", "REPORT"]
        if tenant or self.tenant:
            args += ["TENANT", tenant or self.tenant or ""]
        value = self.execute(*args)
        return value if isinstance(value, dict) else {}

    def cpii_erase(self, identifier: str, *, tenant: Optional[str] = None) -> Dict[str, Any]:
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
        value = self.execute("CRELOAD")
        return value if isinstance(value, dict) else {}

    def ckeylimit_set(self, tenant: str, *, rpm: int, tpm: Optional[int] = None) -> bool:
        args: List[BytesLike] = ["CKEYLIMIT", "SET", tenant, "RPM", str(rpm)]
        if tpm is not None:
            args += ["TPM", str(tpm)]
        return self.execute(*args) in ("OK", b"OK")

    def ckeylimit_get(self, tenant: str) -> Optional[Dict[str, Any]]:
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


    def lookup(self, prompt: BytesLike, **kwargs: Any) -> Optional[CacheHit]:
        return self.cget_hit(prompt, **kwargs)

    def store(self, prompt: BytesLike, answer: BytesLike, **kwargs: Any) -> None:
        self.cset(prompt, answer, **kwargs)

    def ask(
        self,
        prompt: str,
        compute: Callable[[str], Union[str, bytes]],
        **kwargs: Any,
    ) -> str:
        return self.get_or_compute(prompt, compute, **kwargs)

    def cached(
        self,
        *,
        ttl: Optional[int] = None,
        threshold: Optional[float] = None,
        tenant: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., str]]:

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
        return self.csim(prompt, k=k, tenant=tenant)

    def embed(self, text: str) -> List[float]:
        return self.cembed(text)

    def flush(self, *, tenant: Optional[str] = None) -> int:
        return self.cflush(tenant=tenant)


Crowkis = CrowkisClient


class AsyncCrowkisClient(CrowkisClient):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._apool: List[_AsyncConn] = []
        self._aslots: Optional[asyncio.Semaphore] = None

    def _slots_async(self) -> asyncio.Semaphore:
        if self._aslots is None:
            self._aslots = asyncio.Semaphore(self.pool_size)
        return self._aslots

    async def _aopen(self) -> _AsyncConn:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), self.connect_timeout
        )
        conn = _AsyncConn(reader, writer)
        try:
            if self.auth_token:
                writer.write(_encode(["AUTH", self.auth_token]))
                await writer.drain()
                denied = await _aread_frame(reader)
                if isinstance(denied, CrowkisError):
                    denied.retryable = False
                    raise denied
            writer.write(_encode(["HELLO", "3"]))
            await writer.drain()
            await _aread_frame(reader)
        except BaseException:
            conn.close()
            raise
        return conn

    async def _atake(self) -> _AsyncConn:
        while self._apool:
            conn = self._apool.pop()
            if not conn.reader.at_eof():
                return conn
            conn.close()
        return await self._aopen()

    def _agive(self, conn: _AsyncConn) -> None:
        if len(self._apool) < self.pool_size:
            self._apool.append(conn)
        else:
            conn.close()

    async def aclose(self) -> None:
        pool, self._apool = self._apool, []
        for conn in pool:
            conn.close()
            try:
                await conn.writer.wait_closed()
            except (OSError, ConnectionError):
                pass

    async def __aenter__(self) -> "AsyncCrowkisClient":
        await self.aconnect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aconnect(self) -> None:
        self._agive(await self._atake())

    async def execute_async(self, *args: BytesLike) -> Any:
        frame = _encode(args)
        try:
            return await self.execute_async_strict(frame)
        except CrowkisError as exc:
            if not self.fail_soft:
                raise
            self._report(exc)
            return None

    async def execute_async_strict(self, frame: bytes) -> Any:
        attempt = 0
        while True:
            delay: Optional[float] = None
            reply: Any = None
            async with self._slots_async():
                try:
                    conn = await self._atake()
                    try:
                        conn.writer.write(frame)
                        await conn.writer.drain()
                        reply = await asyncio.wait_for(
                            _aread_frame(conn.reader), self.read_timeout
                        )
                    except BaseException:
                        conn.close()
                        raise
                    self._agive(conn)
                except ASYNC_TRANSPORT_FAILURES as exc:
                    if not getattr(exc, "retryable", True) or attempt >= self.max_retries:
                        raise _transport_error(self.host, self.port, attempt + 1, exc) from exc
                    delay = self._backoff(attempt)

            if delay is None:
                if isinstance(reply, CrowkisError):
                    busy = _busy_retry_seconds(reply)
                    if busy is None or attempt >= self.max_retries:
                        raise reply
                    delay = busy
                else:
                    return reply
            await asyncio.sleep(delay)
            attempt += 1

    async def pipeline_async(self, *commands: Iterable[BytesLike]) -> List[Any]:
        batch = list(commands)
        if not batch:
            return []
        frame = b"".join(_encode(command) for command in batch)
        async with self._slots_async():
            try:
                conn = await self._atake()
                try:
                    conn.writer.write(frame)
                    await conn.writer.drain()
                    replies = [
                        await asyncio.wait_for(_aread_frame(conn.reader), self.read_timeout)
                        for _ in batch
                    ]
                except BaseException:
                    conn.close()
                    raise
                self._agive(conn)
                return replies
            except ASYNC_TRANSPORT_FAILURES as exc:
                failure = _transport_error(self.host, self.port, 1, exc)
                if not self.fail_soft:
                    raise failure from exc
                self._report(failure)
                return [None] * len(batch)

    async def cmemset_async(self, agent: str, fact: str, **kwargs: Any) -> Any:
        return await self.execute_async(*self._args_cmemset(agent, fact, **kwargs))

    async def cmemget_async(self, agent: str, query: str, **kwargs: Any) -> Any:
        return await self.execute_async(*self._args_cmemget(agent, query, **kwargs))

    async def cmemextract_async(self, agent: str, conversation: str, **kwargs: Any) -> Any:
        return await self.execute_async(*self._args_cmemextract(agent, conversation, **kwargs))

    async def cmemhistory_async(self, agent: str, query: str, **kwargs: Any) -> Any:
        return await self.execute_async(*self._args_cmemhistory(agent, query, **kwargs))

    async def cmemasof_async(self, agent: str, query: str, unix_ms: int, **kwargs: Any) -> Any:
        return await self.execute_async(*self._args_cmemasof(agent, query, unix_ms, **kwargs))

    async def cmemforget_async(self, agent: str, **kwargs: Any) -> Any:
        return await self.execute_async(*self._args_cmemforget(agent, **kwargs))

    async def cmemlink_async(
        self, agent: str, subject: str, relation: str, obj: str, **kwargs: Any
    ) -> Any:
        return await self.execute_async(
            *self._args_cmemlink(agent, subject, relation, obj, **kwargs)
        )

    async def cmemgraph_async(self, agent: str, entity: str, **kwargs: Any) -> Any:
        return await self.execute_async(*self._args_cmemgraph(agent, entity, **kwargs))

    async def csession_add_async(self, session: str, role: str, text: str, **kwargs: Any) -> Any:
        return await self.execute_async(*self._args_csession_add(session, role, text, **kwargs))

    async def csession_recent_async(self, session: str, **kwargs: Any) -> Any:
        return await self.execute_async(*self._args_csession_recent(session, **kwargs))

    async def csession_search_async(self, session: str, query: str, **kwargs: Any) -> Any:
        return await self.execute_async(*self._args_csession_search(session, query, **kwargs))

    async def creuse_async(self, query: str, **kwargs: Any) -> Any:
        return await self.execute_async(*self._args_creuse(query, **kwargs))

    async def cthink_async(self, query: str, cot_trace: str, **kwargs: Any) -> Any:
        return await self.execute_async(*self._args_cthink(query, cot_trace, **kwargs))

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


    async def ask(
        self,
        prompt: str,
        compute: Callable[[str], Awaitable[Union[str, bytes]]],
        **kwargs: Any,
    ) -> str:
        return await self.get_or_compute_async(prompt, compute, **kwargs)

    def stream(
        self,
        prompt: str,
        compute: Callable[[str], Any],
        **kwargs: Any,
    ) -> AsyncIterator[Union[str, bytes]]:
        return self.stream_get_or_compute(prompt, compute, **kwargs)

    async def store(self, prompt: BytesLike, answer: BytesLike, **kwargs: Any) -> None:
        await self.cset_async(prompt, answer, **kwargs)


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
