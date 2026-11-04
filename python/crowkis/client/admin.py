from __future__ import annotations

import json
import warnings
from http.client import HTTPConnection
from typing import Any, Dict, Optional
from urllib.parse import urlencode, urlparse

from . import config as _config
from .connection import CrowkisError


_API_KEY_WARNED = False


class CrowkisAdmin:
    """The management HTTP API. Reading needs no key; writes need the server's
    CROWKIS_AUTH_TOKEN as `token`. `api_key` is a deprecated name for it."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:6384",
        *,
        token: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 5.0,
    ) -> None:
        global _API_KEY_WARNED
        if api_key and not _API_KEY_WARNED:
            _API_KEY_WARNED = True
            warnings.warn(
                "CrowkisAdmin(api_key=...) is deprecated: users and API keys were removed in "
                "Crowkis 0.5.2. Pass the server's CROWKIS_AUTH_TOKEN as token=... instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        parsed = urlparse(base_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 6384  # the management port (the RESP port + 1)
        self.token = token
        self.api_key = api_key
        self.timeout = timeout

    def _request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        payload = None if body is None else json.dumps(body).encode()
        headers = {"content-type": "application/json"}
        token = self.token or self.api_key
        if token:
            # http.client's own error for a bad header value quotes the value.
            if "\r" in token or "\n" in token:
                raise CrowkisError("token must be a single line")
            if self.token:
                headers["authorization"] = f"Bearer {token}"
            else:
                headers["x-crowkis-api-key"] = token
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
