from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterator, Optional, Union

BytesLike = Union[str, bytes, bytearray, memoryview]


@dataclass(frozen=True)
class GrpcCacheHit:
    hit: bool
    response: bytes
    similarity: float
    ttl_remaining: int
    matched_key: bytes
    confidence: float
    hit_type: str

    @property
    def text(self) -> str:
        return self.response.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class GrpcStreamChunk:
    delta: bytes
    is_final: bool
    format: str

    @property
    def text(self) -> str:
        return self.delta.decode("utf-8", errors="replace")


class CrowkisGrpcStub:
    """Small gRPC client stub for the bundled Crowkis proto.

    Install `grpcio` in the application environment to use this class. The SDK
    keeps it optional so RESP users do not need gRPC dependencies.
    """

    def __init__(self, target: str = "127.0.0.1:6381", *, auth_token: Optional[str] = None) -> None:
        try:
            import grpc  # type: ignore
        except ImportError as exc:
            raise RuntimeError("CrowkisGrpcStub requires `pip install grpcio`") from exc

        self._grpc = grpc
        self._channel = grpc.insecure_channel(target)
        metadata = ()
        if auth_token:
            metadata = (("x-crowkis-auth-token", auth_token),)
        self._metadata = metadata

        self._get = self._channel.unary_unary(
            "/crowkis.v1.CrowkisCache/Get",
            request_serializer=_encode_get_request,
            response_deserializer=_decode_get_response,
        )
        self._set = self._channel.unary_unary(
            "/crowkis.v1.CrowkisCache/Set",
            request_serializer=_encode_set_request,
            response_deserializer=_decode_set_response,
        )
        self._stream = self._channel.unary_stream(
            "/crowkis.v1.CrowkisCache/GetStream",
            request_serializer=_encode_get_request,
            response_deserializer=_decode_stream_chunk,
        )
        self._stats = self._channel.unary_unary(
            "/crowkis.v1.CrowkisCache/Stats",
            request_serializer=lambda _: b"",
            response_deserializer=_decode_stats_response,
        )
        self._invalidate = self._channel.unary_unary(
            "/crowkis.v1.CrowkisCache/Invalidate",
            request_serializer=_encode_invalidate_request,
            response_deserializer=_decode_invalidate_response,
        )

    def get(self, query: BytesLike, **kwargs):
        return self._get({"query": _b(query), **kwargs}, metadata=self._metadata)

    def set(self, query: BytesLike, response: BytesLike, **kwargs):
        return self._set(
            {"query": _b(query), "response": _b(response), **kwargs},
            metadata=self._metadata,
        )

    def get_stream(self, query: BytesLike, **kwargs) -> Iterator[GrpcStreamChunk]:
        return self._stream({"query": _b(query), **kwargs}, metadata=self._metadata)

    def stats(self):
        return self._stats({}, metadata=self._metadata)

    def invalidate(self, tenant: str = ""):
        return self._invalidate({"tenant": tenant}, metadata=self._metadata)

    def close(self) -> None:
        self._channel.close()


def _b(value: BytesLike) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return bytes(value)


def _encode_get_request(value: dict) -> bytes:
    out = bytearray()
    _write_bytes(out, 1, value.get("query") or b"")
    _write_string(out, 2, value.get("tenant") or "")
    _write_string(out, 3, value.get("model") or "")
    if value.get("threshold") is not None:
        _write_float(out, 4, float(value["threshold"]))
    _write_varint(out, 5, int(value.get("chunk_tokens") or value.get("chunkTokens") or 0))
    _write_varint(out, 6, int(value.get("delay_ms") or value.get("delayMs") or 0))
    _write_string(out, 7, value.get("format") or "")
    if value.get("image") is not None:
        _write_bytes(out, 8, _b(value["image"]))
    return bytes(out)


def _encode_set_request(value: dict) -> bytes:
    out = bytearray()
    _write_bytes(out, 1, value.get("query") or b"")
    _write_bytes(out, 2, value.get("response") or b"")
    _write_varint(out, 3, int(value.get("ttl_secs") or value.get("ttl") or 0))
    _write_string(out, 4, value.get("tenant") or "")
    _write_string(out, 5, value.get("model") or "")
    if value.get("image") is not None:
        _write_bytes(out, 6, _b(value["image"]))
    return bytes(out)


def _encode_invalidate_request(value: dict) -> bytes:
    out = bytearray()
    _write_string(out, 1, value.get("tenant") or "")
    return bytes(out)


def _decode_get_response(data: bytes) -> GrpcCacheHit:
    fields = dict(_fields(data))
    return GrpcCacheHit(
        hit=bool(_varint_value(fields.get(1, b""))),
        response=fields.get(2, b""),
        similarity=_float_value(fields.get(3, b"")),
        ttl_remaining=int(_varint_value(fields.get(4, b""))),
        matched_key=fields.get(5, b""),
        confidence=_float_value(fields.get(6, b"")),
        hit_type=(fields.get(7, b"") or b"unknown").decode(errors="replace"),
    )


def _decode_set_response(data: bytes) -> dict:
    fields = dict(_fields(data))
    return {
        "ok": bool(_varint_value(fields.get(1, b""))),
        "error": (fields.get(2, b"") or b"").decode(errors="replace"),
    }


def _decode_stream_chunk(data: bytes) -> GrpcStreamChunk:
    fields = dict(_fields(data))
    return GrpcStreamChunk(
        delta=fields.get(1, b""),
        is_final=bool(_varint_value(fields.get(2, b""))),
        format=(fields.get(3, b"") or b"text").decode(errors="replace"),
    )


def _decode_stats_response(data: bytes) -> dict:
    fields = dict(_fields(data))
    return {
        "total_requests": _varint_value(fields.get(1, b"")),
        "total_hits": _varint_value(fields.get(2, b"")),
        "total_misses": _varint_value(fields.get(3, b"")),
        "hit_rate_pct": _double_value(fields.get(4, b"")),
        "tokens_saved": _varint_value(fields.get(5, b"")),
        "avg_confidence": _double_value(fields.get(6, b"")),
        "avg_latency_ms": _double_value(fields.get(7, b"")),
        "vector_index_entries": _varint_value(fields.get(8, b"")),
        "memtable_bytes": _varint_value(fields.get(9, b"")),
        "memtable_keys": _varint_value(fields.get(10, b"")),
    }


def _decode_invalidate_response(data: bytes) -> dict:
    fields = dict(_fields(data))
    return {
        "ok": bool(_varint_value(fields.get(1, b""))),
        "removed": _varint_value(fields.get(2, b"")),
    }


def _fields(data: bytes):
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        number, wire = tag >> 3, tag & 7
        if wire == 0:
            start = pos
            _, pos = _read_varint(data, pos)
            yield number, data[start:pos]
        elif wire == 1:
            yield number, data[pos : pos + 8]
            pos += 8
        elif wire == 2:
            size, pos = _read_varint(data, pos)
            yield number, data[pos : pos + size]
            pos += size
        elif wire == 5:
            yield number, data[pos : pos + 4]
            pos += 4
        else:
            raise ValueError(f"unsupported wire type {wire}")


def _write_bytes(out: bytearray, field: int, value: bytes) -> None:
    if not value:
        return
    _write_key(out, field, 2)
    _write_varint_raw(out, len(value))
    out.extend(value)


def _write_string(out: bytearray, field: int, value: str) -> None:
    _write_bytes(out, field, value.encode("utf-8"))


def _write_float(out: bytearray, field: int, value: float) -> None:
    if value == 0:
        return
    _write_key(out, field, 5)
    out.extend(struct.pack("<f", value))


def _write_varint(out: bytearray, field: int, value: int) -> None:
    if value == 0:
        return
    _write_key(out, field, 0)
    _write_varint_raw(out, value)


def _write_key(out: bytearray, field: int, wire: int) -> None:
    _write_varint_raw(out, (field << 3) | wire)


def _write_varint_raw(out: bytearray, value: int) -> None:
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)


def _read_varint(data: bytes, pos: int):
    value = 0
    shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, pos
        shift += 7
    raise ValueError("truncated varint")


def _varint_value(data: bytes) -> int:
    return _read_varint(data, 0)[0] if data else 0


def _float_value(data: bytes) -> float:
    return struct.unpack("<f", data)[0] if len(data) == 4 else 0.0


def _double_value(data: bytes) -> float:
    return struct.unpack("<d", data)[0] if len(data) == 8 else 0.0
