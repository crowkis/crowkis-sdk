from __future__ import annotations

import asyncio
import socket
from typing import Any, Dict, Iterable, List, Optional, Union

BytesLike = Union[str, bytes, bytearray, memoryview]


class CrowkisError(Exception):

    retryable = True


MAX_LINE_BYTES = 512 * 1024
BUSY_DEFAULT_RETRY_SECONDS = 0.05
BUSY_MAX_RETRY_SECONDS = 2.0


def _b(value: BytesLike) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return bytes(value)



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


def _auth_refused(denied: CrowkisError) -> CrowkisError:
    if "without any password configured" in str(denied):
        denied = CrowkisError(
            "the server has no CROWKIS_AUTH_TOKEN set; remove auth_token "
            "or set the same token on the server"
        )
    denied.retryable = False
    return denied


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
