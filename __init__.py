"""MuninnDB memory plugin — MemoryProvider interface.

Cross-session semantic memory via MuninnDB knowledge graph.
Connects to a MuninnDB MCP server over streamable-http transport.

Features:
- Semantic recall (prefetch) before each turn
- Automatic turn storage (sync_turn) after each turn
- Mirrors built-in memory writes to MuninnDB knowledge graph
- Entity extraction and relationship tracking
- Session-aware with vault scoping

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
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

SEARCH_SCHEMA = {
    "name": "muninn_search",
    "description": (
        "Semantic search across MuninnDB long-term memory. "
        "Returns ranked memories with relevance scores."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "limit": {"type": "integer", "description": "Max results (default: 10)."},
            "mode": {
                "type": "string",
                "enum": ["semantic", "recent", "balanced", "deep"],
                "description": "Recall mode (default: balanced).",
            },
        },
        "required": ["query"],
    },
}

REMEMBER_SCHEMA = {
    "name": "muninn_remember",
    "description": "Persist a fact, preference, decision, or observation to MuninnDB long-term memory.",
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The information to remember."},
            "memory_type": {
                "type": "string",
                "enum": ["fact", "decision", "observation", "preference", "issue", "task", "procedure", "event", "goal", "constraint"],
                "description": "Memory type (default: fact).",
            },
            "summary": {"type": "string", "description": "One-line summary."},
        },
        "required": ["content"],
    },
}

ENTITIES_SCHEMA = {
    "name": "muninn_entities",
    "description": "List known entities in the MuninnDB knowledge graph, sorted by mention count.",
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max results (default: 20)."},
        },
        "required": [],
    },
}


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class _CircuitBreaker:
    """Simple circuit breaker for network calls."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, threshold: int = 5, timeout_s: float = 60.0):
        self._threshold = threshold
        self._timeout_s = timeout_s
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure = 0.0
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._state == self.OPEN:
                if time.time() - self._last_failure > self._timeout_s:
                    self._state = self.HALF_OPEN
                    return False
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._state = self.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure = time.time()
            if self._failure_count >= self._threshold:
                self._state = self.OPEN
                logger.warning("MuninnDB circuit breaker OPEN after %d failures", self._failure_count)


# ---------------------------------------------------------------------------
# MCP JSON-RPC client
# ---------------------------------------------------------------------------

class _MCPClient:
    """Minimal MCP client for MuninnDB over streamable-http."""

    def __init__(self, url: str, timeout: float = 15.0, token: str = ""):
        self._url = url.rstrip("/")
        self._timeout = timeout
        self._token = token
        self._request_id = 0
        self._lock = threading.Lock()

    def call(self, tool_name: str, arguments: dict | None = None, timeout: float | None = None) -> Any:
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


# ---------------------------------------------------------------------------
# Overlay formatter
# ---------------------------------------------------------------------------

def _format_recall_result(result: dict, max_tokens: int = 800) -> str:
    """Format MuninnDB recall result into a compact context block."""
    memories = result.get("memories") or result.get("engrams") or result.get("results") or []
    if not memories:
        return ""

    lines = ["[MuninnDB Context]"]
    char_budget = max_tokens * 4  # rough token-to-char estimate
    total = 0

    for m in memories[:10]:
        concept = m.get("concept", "")
        summary = m.get("summary") or m.get("content", "")
        if not summary:
            continue
        # Compact
        summary = summary.replace("\n", " ").strip()[:300]
        line = f"- {concept}: {summary}" if concept else f"- {summary}"
        if total + len(line) > char_budget:
            break
        lines.append(line)
        total += len(line)

    return "\n".join(lines) if len(lines) > 1 else ""


# ---------------------------------------------------------------------------
# Main plugin class
# ---------------------------------------------------------------------------

class MuninnDBMemoryProvider(MemoryProvider):
    """MuninnDB knowledge graph memory — semantic recall, entity graph, auto-sync."""

    def __init__(self):
        self._client: _MCPClient | None = None
        self._circuit: _CircuitBreaker | None = None
        self._vault = "default"
        self._session_id = ""
        self._user_id = "default"
        self._activate_limit = 10
        self._activate_min_score = 0.3
        self._prefetch_tokens = 800
        self._trivial_min_words = 5
        self._request_timeout = 15.0

        # Prefetch cache (turn-indexed)
        self._prefetch_cache: dict[tuple[str, int], str] = {}
        self._prefetch_lock = threading.Lock()
        self._turn_index = 0
        self._prefetch_thread: threading.Thread | None = None
        self._sync_thread: threading.Thread | None = None

    # ── Core identity ──────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "muninndb"

    def is_available(self) -> bool:
        """Check if MuninnDB is configured — no network calls."""
        # 1. Check muninndb.json
        for candidate in self._config_paths():
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
        return [
            {"key": "mcp_url", "description": "MuninnDB MCP server URL (e.g. http://10.0.0.150:8750/mcp)", "required": True},
            {"key": "vault_prefix", "description": "Vault name prefix (default: 'hermes')", "default": "hermes"},
            {"key": "activate_limit", "description": "Max memories per prefetch (default: 10)", "default": 10},
            {"key": "activate_min_score", "description": "Min relevance score 0-1 (default: 0.3)", "default": 0.3},
        ]

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        config_path = Path(hermes_home) / "muninndb.json"
        existing = {}
        if config_path.exists():
            try:
                existing = json.loads(config_path.read_text())
            except Exception:
                pass
        existing.update(values)
        config_path.write_text(json.dumps(existing, indent=2))

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id
        self._turn_index = 0

        hermes_home = str(kwargs.get("hermes_home", ""))
        self._user_id = kwargs.get("user_id", "default")
        agent_identity = kwargs.get("agent_identity", "")

        # Load config from muninndb.json
        config = self._load_config(hermes_home)

        # Resolve MCP URL: config > mcp_servers auto-detect > env var
        mcp_url = config.get("mcp_url", "").strip()
        if not mcp_url:
            mcp_url = self._detect_mcp_url(hermes_home)
        if not mcp_url:
            mcp_url = os.environ.get("MUNINNDB_MCP_URL", "")

        if not mcp_url:
            logger.error("MuninnDB: no MCP URL found in muninndb.json, config.yaml, or MUNINNDB_MCP_URL env")
            return

        # Resolve token (optional — MuninnDB may not require auth)
        token = os.environ.get("MUNINNDB_MCP_TOKEN", "").strip()

        # Apply config
        self._activate_limit = int(config.get("activate_limit", 10))
        self._activate_min_score = float(config.get("activate_min_score", 0.3))
        self._prefetch_tokens = int(config.get("prefetch_context_tokens", 800))
        self._trivial_min_words = int(config.get("trivial_message_min_words", 5))
        self._request_timeout = float(config.get("request_timeout_s", 15.0))

        # Vault: prefix + agent identity (profile-scoped)
        # "default" profile → base vault (no suffix)
        vault_prefix = config.get("vault_prefix", "hermes")
        if agent_identity and agent_identity != "default":
            self._vault = f"{vault_prefix}_{agent_identity}"
        else:
            self._vault = vault_prefix

        # Create client
        self._client = _MCPClient(mcp_url, timeout=self._request_timeout, token=token)

        # Circuit breaker
        threshold = int(config.get("circuit_breaker_threshold", 5))
        timeout_s = float(config.get("circuit_breaker_timeout_s", 60.0))
        self._circuit = _CircuitBreaker(threshold=threshold, timeout_s=timeout_s)

        logger.info("MuninnDB initialized: url=%s vault=%s limit=%d", mcp_url, self._vault, self._activate_limit)

    def system_prompt_block(self) -> str:
        if not self._client:
            return ""
        return (
            "[MuninnDB Memory]\n"
            "Long-term semantic memory is available via MuninnDB. "
            "Use muninn_search to recall relevant context, muninn_remember to persist important facts. "
            "Memories are automatically synced after each turn."
        )

    def shutdown(self) -> None:
        # Join background threads
        for t in [self._prefetch_thread, self._sync_thread]:
            if t and t.is_alive():
                t.join(timeout=5.0)
        self._client = None

    # ── Cross-vault helpers ────────────────────────────────────────────────

    def _get_cross_vaults(self) -> list[str]:
        """Return vaults to search: profile vault + base vault if different."""
        vaults = [self._vault]
        base = self._vault.split("_")[0] if "_" in self._vault else ""
        if base and base != self._vault:
            vaults.append(base)
        return vaults

    def _cross_vault_recall(self, query: str, limit: int = 0, threshold: float = 0.0) -> dict:
        """Search across profile vault + base vault, merge and deduplicate results."""
        limit = limit or self._activate_limit
        threshold = threshold or self._activate_min_score
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
                memories = result.get("memories") or result.get("engrams") or result.get("results") or []
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

    # ── Prefetch (recall before each turn) ─────────────────────────────────

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not self._client or self._circuit.is_open:
            return ""

        sid = session_id or self._session_id

        # Check turn-indexed cache first
        with self._prefetch_lock:
            cached = self._prefetch_cache.pop((sid, self._turn_index), "")
        if cached:
            return cached

        # Cache miss — cross-vault recall
        try:
            result = self._cross_vault_recall(query)
            return _format_recall_result(result, self._prefetch_tokens)
        except Exception as exc:
            self._circuit.record_failure()
            logger.debug("MuninnDB prefetch failed: %s", exc)
            return ""

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        if not self._client or self._circuit.is_open:
            return

        # Wait for previous prefetch thread
        if self._prefetch_thread and self._prefetch_thread.is_alive():
            self._prefetch_thread.join(timeout=3.0)

        sid = session_id or self._session_id
        self._prefetch_thread = threading.Thread(
            target=self._do_prefetch,
            args=(query, sid, self._turn_index + 1),
            daemon=True,
        )
        self._prefetch_thread.start()

    def _do_prefetch(self, query: str, sid: str, turn: int) -> None:
        try:
            result = self._cross_vault_recall(query)
            formatted = _format_recall_result(result, self._prefetch_tokens)
            if formatted:
                with self._prefetch_lock:
                    self._prefetch_cache[(sid, turn)] = formatted
        except Exception as exc:
            self._circuit.record_failure()
            logger.debug("MuninnDB queue_prefetch failed: %s", exc)

    # ── Sync turn (store after each turn) ──────────────────────────────────

    # Patterns to skip — system noise, not knowledge
    _SKIP_PATTERNS = [
        "[System note:", "[madeinoz]", "[hermes]", "MEDIA:",
        "test search", "test muninndb", "ive restarted",
        "ok now we", "ok ", "yes ", "done", "perfect",
        "how are vaults", "what about underlying",
    ]

    def _is_valuable_turn(self, user_content: str, assistant_content: str) -> bool:
        """Filter out noise — only store turns with clear knowledge signal."""
        user_lower = user_content.strip().lower()
        words = len(user_content.split())

        # Too short — not enough signal
        if words < 12:
            return False

        # Skip system notes, platform prefixes, test messages
        for pat in self._SKIP_PATTERNS:
            if user_lower.startswith(pat.lower()):
                return False

        # Skip if assistant response is mostly tool output
        if assistant_content and len(assistant_content) > 200:
            # If response is very long, it's likely tool-heavy — skip
            if len(assistant_content) > 2000:
                return False

        # Skip pure questions (no new information contributed)
        if user_content.strip().endswith("?") and words < 20:
            return False

        return True

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        if not self._client or self._circuit.is_open:
            return

        # Smart filtering — only store valuable turns
        if not self._is_valuable_turn(user_content, assistant_content):
            self._turn_index += 1
            return

        self._turn_index += 1

        # Wait for previous sync thread
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)

        self._sync_thread = threading.Thread(
            target=self._do_sync_turn,
            args=(user_content, assistant_content, session_id or self._session_id),
            daemon=True,
        )
        self._sync_thread.start()

    def _do_sync_turn(self, user_content: str, assistant_content: str, sid: str) -> None:
        try:
            # Extract key facts from assistant response (first 500 chars)
            asst_excerpt = assistant_content[:500] if assistant_content else ""

            # Store as observation with the assistant's answer as the valuable content
            content = f"User asked: {user_content[:200]}"
            if asst_excerpt:
                content += f"\nKey info: {asst_excerpt}"

            self._client.call("muninn_remember", {
                "content": content,
                "type": "observation",
                "summary": user_content[:200],
                "vault": self._vault,
            })
            self._circuit.record_success()
        except Exception as exc:
            self._circuit.record_failure()
            logger.debug("MuninnDB sync_turn failed: %s", exc)

    # ── Session switch ─────────────────────────────────────────────────────

    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        **kwargs,
    ) -> None:
        self._session_id = new_session_id
        if reset:
            self._turn_index = 0
            with self._prefetch_lock:
                self._prefetch_cache.clear()

    # ── Memory write mirror ────────────────────────────────────────────────

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Mirror built-in memory writes to MuninnDB."""
        if not self._client or self._circuit.is_open:
            return
        if action == "remove":
            return  # Don't mirror removes

        # Map action+target to memory type
        memory_type = "preference" if target == "user" else "fact"

        try:
            self._client.call("muninn_remember", {
                "content": content,
                "type": memory_type,
                "vault": self._vault,
            })
            self._circuit.record_success()
        except Exception as exc:
            self._circuit.record_failure()
            logger.debug("MuninnDB on_memory_write mirror failed: %s", exc)

    # ── Pre-compress hook ──────────────────────────────────────────────────

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        """Extract key facts from messages about to be compressed."""
        if not self._client or self._circuit.is_open:
            return ""

        # Store a compression summary as a memory
        user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
        if not user_msgs:
            return ""

        summary = " | ".join(user_msgs[:5])[:500]
        try:
            self._client.call("muninn_remember", {
                "content": f"Session context (compressed): {summary}",
                "type": "observation",
                "vault": self._vault,
            })
            self._circuit.record_success()
        except Exception:
            pass

        return ""

    # ── Delegation hook ────────────────────────────────────────────────────

    def on_delegation(self, task: str, result: str, *, child_session_id: str = "", **kwargs) -> None:
        """Record subagent delegation as a memory."""
        if not self._client or self._circuit.is_open:
            return

        try:
            self._client.call("muninn_remember", {
                "content": f"Delegated task: {task[:300]}\nResult: {result[:300]}",
                "type": "task",
                "vault": self._vault,
            })
            self._circuit.record_success()
        except Exception:
            self._circuit.record_failure()

    # ── Tools ──────────────────────────────────────────────────────────────

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [SEARCH_SCHEMA, REMEMBER_SCHEMA, ENTITIES_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if not self._client:
            return json.dumps({"error": "MuninnDB not initialized"})

        if self._circuit.is_open:
            return json.dumps({"error": "MuninnDB circuit breaker open — try again later"})

        try:
            if tool_name == "muninn_search":
                result = self._cross_vault_recall(
                    args.get("query", ""),
                    limit=args.get("limit", 10),
                    threshold=max(args.get("threshold", 0.3), 0.3),  # floor at 0.3
                )
            elif tool_name == "muninn_remember":
                result = self._client.call("muninn_remember", {
                    "content": args.get("content", ""),
                    "type": args.get("memory_type", "fact"),
                    "summary": args.get("summary", ""),
                    "vault": self._vault,
                })
            elif tool_name == "muninn_entities":
                result = self._client.call("muninn_entities", {
                    "limit": args.get("limit", 20),
                    "vault": self._vault,
                })
            else:
                return json.dumps({"error": f"Unknown tool: {tool_name}"})

            self._circuit.record_success()
            return json.dumps(result, default=str)
        except Exception as exc:
            self._circuit.record_failure()
            return json.dumps({"error": str(exc)})

    # ── Config helpers ─────────────────────────────────────────────────────

    def _config_paths(self) -> list[Path]:
        """Candidate paths for muninndb.json."""
        paths = []
        # HERMES_HOME
        hermes_home = os.environ.get("HERMES_HOME", "")
        if hermes_home:
            paths.append(Path(hermes_home) / "muninndb.json")
        # Default locations
        paths.append(Path.home() / ".hermes" / "muninndb.json")
        paths.append(Path("/opt/data/muninndb.json"))
        return paths

    def _load_config(self, hermes_home: str = "") -> dict:
        """Load muninndb.json from the first location found."""
        candidates = []
        if hermes_home:
            candidates.append(Path(hermes_home) / "muninndb.json")
        candidates.extend(self._config_paths())

        for p in candidates:
            if p.exists():
                try:
                    return json.loads(p.read_text())
                except Exception as exc:
                    logger.warning("MuninnDB: failed to parse %s: %s", p, exc)
        return {}

    def _detect_mcp_url(self, hermes_home: str = "") -> str:
        """Auto-detect MCP URL from config.yaml mcp_servers section."""
        config_candidates = []
        if hermes_home:
            config_candidates.append(Path(hermes_home) / "config.yaml")
        config_candidates.append(Path.home() / ".hermes" / "config.yaml")
        config_candidates.append(Path("/opt/data/config.yaml"))

        for p in config_candidates:
            if p.exists():
                try:
                    import yaml
                    with open(p) as f:
                        config = yaml.safe_load(f) or {}
                    servers = config.get("mcp_servers", {})
                    muninn = servers.get("muninndb", {})
                    if muninn.get("url"):
                        return muninn["url"]
                except Exception:
                    pass
        return ""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    ctx.register_memory_provider(MuninnDBMemoryProvider())
