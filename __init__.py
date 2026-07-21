"""MuninnDB memory plugin — MemoryProvider interface.

Cross-session semantic memory via MuninnDB knowledge graph.
Connects to a MuninnDB MCP server over streamable-http transport.

Features:
- Semantic recall (prefetch) before each turn
- Automatic turn storage (sync_turn) after each turn
- Mirrors built-in memory writes to MuninnDB knowledge graph
- Entity extraction and relationship tracking
- Hierarchical memory organization
- Enrichment pipeline for memory quality
- Session-aware with vault scoping
- 43 tools synced with MuninnDB MCP server v0.9.0 (2026-07-21):
  3 core + 12 P0 lifecycle + 4 knowledge graph + 8 entity management
  + 2 quality/trust + 4 enrichment + 3 audit/export/guide + 3 hierarchical
  + 3 work-queue/lease + 1 workflow vaults

Config (muninndb.json in HERMES_HOME):
  mcp_url                   — MuninnDB MCP endpoint (required)
  vault_prefix              — Vault name prefix (default: "hermes")
  activate_limit            — Max memories per prefetch (default: 10)
  activate_min_score        — Min relevance score (default: 0.3)
  prefetch_context_tokens   — Token budget for prefetch (default: 800)
  trivial_message_min_words — Skip sync for short messages (default: 5)
  circuit_breaker_threshold — Failures before opening (default: 5)
  circuit_breaker_timeout_s — Seconds before half-open (default: 60)
  request_timeout_s         — HTTP request timeout (default: 15.0)
  skip_patterns             — Base skip patterns (default: built-in list)
  skip_patterns_extra       — Additional user-extensible skip patterns
  tool_priority_filter      — Tool families to expose: all/p0/p0-p1/p0-p2 (default: all)
  enable_audit_tools        — Enable P2 audit/debug tools (default: false)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider

# Re-export from submodules for backward compatibility
from .circuit_breaker import CircuitBreaker as _CircuitBreaker
from .config import config_paths as _config_paths
from .config import detect_mcp_url as _detect_mcp_url
from .config import get_config_schema as _get_config_schema
from .config import load_config as _load_config
from .config import save_config as _save_config_values
from .formatter import format_recall_result as _format_recall_result
from .lifecycle import LifecycleHooks
from .mcp_client import MCPClient as _MCPClient
from .tools import get_tool_schemas as _get_tool_schemas
from .tools import handle_tool_call as _handle_tool_call

logger = logging.getLogger(__name__)


class MuninnDBMemoryProvider(MemoryProvider):
    """MuninnDB knowledge graph memory — semantic recall, entity graph, auto-sync."""

    def __init__(self):
        self._client: _MCPClient | None = None
        self._circuit: _CircuitBreaker | None = None
        self._vault = "default"
        self._session_id = ""
        self._user_id = "default"
        self._hooks: LifecycleHooks | None = None
        self._config: dict = {}

    # ── Core identity ──────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "muninndb"

    def is_available(self) -> bool:
        """Check if MuninnDB is configured — no network calls."""
        # 1. Check muninndb.json
        for candidate in _config_paths():
            if candidate.exists():
                return True
        # 2. Check mcp_servers in config.yaml
        try:
            from hermes_cli.config import load_config
            config = load_config()
            servers = config.get("mcp_servers", {})
            if servers.get("muninndb", {}).get("url"):
                return True
        except Exception:
            pass
        # 3. Env var
        return bool(os.environ.get("MUNINNDB_MCP_URL"))

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return _get_config_schema()

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        _save_config_values(values, hermes_home)

    # ── Lifecycle ──────────────────────────────────────────────────────

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id

        hermes_home = str(kwargs.get("hermes_home", ""))
        self._user_id = kwargs.get("user_id", "default")
        agent_identity = kwargs.get("agent_identity", "")

        # Load config from muninndb.json
        self._config = _load_config(hermes_home)

        # Resolve MCP URL: config > mcp_servers auto-detect > env var
        mcp_url = self._config.get("mcp_url", "").strip()
        if not mcp_url:
            mcp_url = _detect_mcp_url(hermes_home)
        if not mcp_url:
            mcp_url = os.environ.get("MUNINNDB_MCP_URL", "")

        if not mcp_url:
            logger.error(
                "MuninnDB: no MCP URL found in muninndb.json, config.yaml, or MUNINNDB_MCP_URL env"
            )
            return

        # Resolve token (optional — MuninnDB may not require auth)
        token = os.environ.get("MUNINNDB_MCP_TOKEN", "").strip()

        # Apply config
        activate_limit = int(self._config.get("activate_limit", 10))
        activate_min_score = float(self._config.get("activate_min_score", 0.3))
        prefetch_tokens = int(self._config.get("prefetch_context_tokens", 800))
        trivial_min_words = int(self._config.get("trivial_message_min_words", 5))
        request_timeout = float(self._config.get("request_timeout_s", 15.0))

        # Vault: prefix + agent identity (profile-scoped)
        vault_prefix = self._config.get("vault_prefix", "hermes")
        if agent_identity and agent_identity != "default":
            self._vault = f"{vault_prefix}_{agent_identity}"
        else:
            self._vault = vault_prefix

        # Create client
        self._client = _MCPClient(mcp_url, timeout=request_timeout, token=token)

        # Circuit breaker
        threshold = int(self._config.get("circuit_breaker_threshold", 5))
        timeout_s = float(self._config.get("circuit_breaker_timeout_s", 60.0))
        self._circuit = _CircuitBreaker(threshold=threshold, timeout_s=timeout_s)

        # Build skip patterns from config
        from .lifecycle import _merge_skip_patterns

        skip_patterns = _merge_skip_patterns(
            self._config.get("skip_patterns"),
            self._config.get("skip_patterns_extra"),
        )

        # Create lifecycle hooks manager
        self._hooks = LifecycleHooks(
            client=self._client,
            circuit=self._circuit,
            vault=self._vault,
            activate_limit=activate_limit,
            activate_min_score=activate_min_score,
            prefetch_tokens=prefetch_tokens,
            trivial_min_words=trivial_min_words,
            skip_patterns=skip_patterns,
        )
        self._hooks._session_id = session_id
        self._hooks.set_cross_vault_recall(self._cross_vault_recall)

        logger.info(
            "MuninnDB initialized: url=%s vault=%s limit=%d",
            mcp_url, self._vault, activate_limit,
        )

    def system_prompt_block(self) -> str:
        if not self._hooks:
            return ""
        return self._hooks.system_prompt_block()

    def shutdown(self) -> None:
        if self._hooks:
            self._hooks.shutdown()
        if self._client:
            self._client.close()
        self._client = None

    # ── Cross-vault helpers ────────────────────────────────────────────

    def _get_cross_vaults(self) -> list[str]:
        """Return vaults to search: profile vault + base vault if different."""
        vaults = [self._vault]
        base = self._vault.split("_")[0] if "_" in self._vault else ""
        if base and base != self._vault:
            vaults.append(base)
        return vaults

    def _cross_vault_recall(self, query: str, limit: int = 0, threshold: float = 0.0) -> dict:
        """Search across profile vault + base vault, merge and deduplicate results."""
        if not self._client or not self._circuit:
            return {"memories": [], "total": 0}

        limit = limit or self._hooks._activate_limit
        threshold = threshold or self._hooks._activate_min_score
        all_memories = []
        seen_ids = set()

        for vault in self._get_cross_vaults():
            try:
                result = self._client.call("muninn_recall", {
                    "context": [query],
                    "limit": limit,
                    "threshold": threshold,
                    "vault": vault,
                })
                self._circuit.record_success()
                memories = (
                    result.get("memories")
                    or result.get("engrams")
                    or result.get("results")
                    or []
                )
                for m in memories:
                    mid = m.get("id", "")
                    if mid and mid not in seen_ids:
                        seen_ids.add(mid)
                        m["_vault"] = vault  # tag source vault
                        all_memories.append(m)
            except Exception as exc:
                self._circuit.record_failure()
                logger.debug("MuninnDB cross-vault recall failed for %s: %s", vault, exc)

        # Sort by score descending
        all_memories.sort(key=lambda m: m.get("score", 0), reverse=True)
        return {"memories": all_memories[:limit], "total": len(all_memories)}

    # ── Prefetch ───────────────────────────────────────────────────────

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not self._hooks:
            return ""
        return self._hooks.prefetch(query, session_id=session_id)

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        if not self._hooks:
            return
        self._hooks.queue_prefetch(query, session_id=session_id)

    # ── Sync turn ──────────────────────────────────────────────────────

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ) -> None:
        if not self._hooks:
            return
        self._hooks.sync_turn(
            user_content, assistant_content,
            session_id=session_id,
            tool_calls=tool_calls,
        )

    # ── Session switch ─────────────────────────────────────────────────

    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        **kwargs,
    ) -> None:
        if not self._hooks:
            return
        self._hooks.on_session_switch(
            new_session_id,
            parent_session_id=parent_session_id,
            reset=reset,
        )

    # ── Session end (NEW) ──────────────────────────────────────────────

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        if not self._hooks:
            return
        self._hooks.on_session_end(messages)

    # ── Memory write mirror ────────────────────────────────────────────

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._hooks:
            return
        self._hooks.on_memory_write(action, target, content, metadata)

    # ── Pre-compress hook ──────────────────────────────────────────────

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        if not self._hooks:
            return ""
        return self._hooks.on_pre_compress(messages)

    # ── Delegation hook ────────────────────────────────────────────────

    def on_delegation(
        self, task: str, result: str, *, child_session_id: str = "", **kwargs
    ) -> None:
        if not self._hooks:
            return
        self._hooks.on_delegation(task, result, child_session_id=child_session_id)

    # ── Tools ──────────────────────────────────────────────────────────

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        priority_filter = self._config.get("tool_priority_filter", "all")
        return _get_tool_schemas(priority_filter=priority_filter)

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        return _handle_tool_call(
            tool_name,
            args,
            client=self._client,
            circuit=self._circuit,
            vault=self._vault,
            cross_vault_recall_fn=self._cross_vault_recall,
        )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    ctx.register_memory_provider(MuninnDBMemoryProvider())
