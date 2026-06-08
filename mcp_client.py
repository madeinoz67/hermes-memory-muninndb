"""MCP JSON-RPC client for MuninnDB over streamable-http transport."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class MCPClient:
    """Minimal MCP client for MuninnDB over streamable-http."""

    def __init__(self, url: str, timeout: float = 15.0, token: str = ""):
        self._url = url.rstrip("/")
        self._timeout = timeout
        self._token = token
        self._request_id = 0
        self._lock = threading.Lock()

    def call(
        self, tool_name: str, arguments: dict | None = None, timeout: float | None = None
    ) -> Any:
        """Call an MCP tool via JSON-RPC."""
        import requests

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

        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        resp = requests.post(
            self._url,
            json=payload,
            headers=headers,
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
