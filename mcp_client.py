"""MCP JSON-RPC client for MuninnDB over streamable-http transport."""
from __future__ import annotations
import json
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class MCPClient:
    """Minimal MCP client for MuninnDB over streamable-http.

    Uses requests.Session with connection pooling and automatic retry
    on transient failures (502/503/504, connection errors, timeouts).
    """

    def __init__(self, url: str, timeout: float = 15.0, token: str = ""):
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        self._url = url.rstrip("/")
        self._timeout = timeout
        self._token = token
        self._request_id = 0
        self._lock = threading.Lock()

        # Connection pool with automatic retry on transient failures
        self._session = requests.Session()
        retry = Retry(
            total=2,
            backoff_factor=0.3,
            status_forcelist=[502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(
            pool_connections=4,
            pool_maxsize=8,
            max_retries=retry,
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        # Pre-set static headers and auth
        self._session.headers.update({"Content-Type": "application/json"})
        if self._token:
            self._session.headers["Authorization"] = f"Bearer {self._token}"

    def call(
        self, tool_name: str, arguments: dict | None = None, timeout: float | None = None
    ) -> Any:
        """Call an MCP tool via JSON-RPC."""
        with self._lock:
            self._request_id += 1
            req_id = self._request_id

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
            },
        }

        resp = self._session.post(
            self._url,
            json=payload,
            timeout=timeout or self._timeout,
        )
        resp.raise_for_status()

        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"MuninnDB error: {body['error']}")

        # Unpack MCP content wrapper
        result = body.get("result", {})
        content = result.get("content", [])
        if isinstance(content, list) and len(content) >= 1:
            item = content[0]
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                try:
                    return json.loads(text)
                except (ValueError, TypeError):
                    return {"text": text}
        return result

    def close(self) -> None:
        """Close the underlying HTTP session and release connections."""
        self._session.close()
