"""Where a client finds its server: code, then the environment, then the defaults.

A value passed in code always wins. When one is not passed, the client looks at
CROWKIS_HOST, CROWKIS_PORT, CROWKIS_AUTH_TOKEN (or CROWKIS_TOKEN) and CROWKIS_TENANT,
then at the parts of CROWKIS_URL (``crowkis://:token@host:port/tenant``), and only
then uses the built-in default. An empty variable counts as not set.

The environment is read when a client is created, not when crowkis is imported, so
a ``.env`` file loaded after the import still applies. The SDK never loads a
``.env`` file itself. Error messages name the variable and never repeat its value,
since a URL can carry the token.
"""

from __future__ import annotations

import os
import re
from typing import NamedTuple, Optional
from urllib.parse import unquote, urlsplit

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6383


class Settings(NamedTuple):
    host: str
    port: int
    auth_token: Optional[str]
    tenant: Optional[str]


def _var(name: str) -> Optional[str]:
    value = os.environ.get(name, "").strip()
    return value or None


def _port(text: str, name: str) -> int:
    # ASCII digits only, as in Node: int() would also take "6_383", "+80" or "٦٣٨٣".
    port = int(text) if text.isascii() and text.isdigit() else 0
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} must be a port number from 1 to 65535")
    return port


def _unquote(text: str) -> str:
    """Percent-decoding that keeps an escape it cannot decode as it is, never as
    U+FFFD, so a token is never silently changed. Same as node/config.js."""
    try:
        return unquote(text, errors="strict")
    except UnicodeDecodeError:
        def run(match: "re.Match[str]") -> str:
            try:
                return unquote(match.group(0), errors="strict")
            except UnicodeDecodeError:
                return match.group(0)

        return re.sub(r"(?:%[0-9a-fA-F]{2})+", run, text)


def _from_url() -> Settings:
    """The parts CROWKIS_URL gives; a part it leaves out is None."""
    url = _var("CROWKIS_URL")
    if url is None:
        return Settings(None, None, None, None)  # type: ignore[arg-type]
    problem = "CROWKIS_URL must look like crowkis://:token@host:port/tenant"
    unreadable = False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        unreadable = True
    if unreadable:
        # Raised outside the except block and with the URL dropped from this frame:
        # the parser's own error quotes the URL (token and all), and chaining or an
        # error tracker that records local variables would otherwise carry it on.
        url = parts = None  # type: ignore[assignment]
        raise ValueError(f"{problem} (it could not be read; check its port is from 1 to 65535)")
    if port == 0:
        raise ValueError(f"{problem} (its port is not a number from 1 to 65535)")
    if parts.scheme != "crowkis":
        raise ValueError(f"{problem} (it must start with crowkis://)")
    if not parts.hostname:
        raise ValueError(f"{problem} (it has no host)")
    token = parts.password or parts.username
    tenant = parts.path.strip("/")
    return Settings(
        parts.hostname,
        port,  # type: ignore[arg-type]
        _unquote(token) if token else None,
        _unquote(tenant) if tenant else None,
    )


def resolve(
    host: Optional[str] = None,
    port: Optional[int] = None,
    auth_token: Optional[str] = None,
    tenant: Optional[str] = None,
) -> Settings:
    """Fill in each setting not passed in code from the environment or the default.

    A variable is only read for a setting the code left out, so a bad CROWKIS_PORT
    does not stop a client that was given its port.
    """
    # An empty token or tenant counts as not passed, as an empty variable does.
    auth_token = auth_token or None
    url = None if all(v is not None for v in (host, port, auth_token, tenant or None)) else _from_url()
    if host is None:
        host = _var("CROWKIS_HOST") or url.host or DEFAULT_HOST
    if port is None:
        text = _var("CROWKIS_PORT")
        port = _port(text, "CROWKIS_PORT") if text else (url.port or DEFAULT_PORT)
    if auth_token is None:
        auth_token = _var("CROWKIS_AUTH_TOKEN") or _var("CROWKIS_TOKEN") or url.auth_token
    if not tenant:
        tenant = _var("CROWKIS_TENANT") or url.tenant or tenant
    return Settings(host, port, auth_token, tenant)
