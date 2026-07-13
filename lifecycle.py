"""Lifecycle hooks for MuninnDB plugin.

Implements: prefetch, queue_prefetch, sync_turn, on_memory_write,
on_session_switch, on_pre_compress, on_delegation, system_prompt_block,
on_session_end.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from .circuit_breaker import CircuitBreaker
from .config import load_config
from .formatter import format_recall_result
from .mcp_client import MCPClient

logger = logging.getLogger(__name__)

# Default skip patterns — used when not overridden by config.
# Only generic patterns that apply to all users. User-specific
# patterns should go in skip_patterns_extra in muninndb.json.
DEFAULT_SKIP_PATTERNS = [
    "[System note:",
    "[hermes]",
    "MEDIA:",
    "/test ",
    "/debug ",
]


def _merge_skip_patterns(
    config_skip: list[str] | None = None,
    config_extra: list[str] | None = None,
) -> list[str]:
    """Build the skip patterns list from defaults + config overrides.

    If config provides skip_patterns, those replace the defaults.
    skip_patterns_extra is always appended.
    """
    if config_skip is not None and len(config_skip) > 0:
        base = list(config_skip)
    else:
        base = list(DEFAULT_SKIP_PATTERNS)
    if config_extra:
        base.extend(config_extra)
    return base


def is_valuable_turn(
    user_content: str,
    assistant_content: str,
    skip_patterns: list[str],
    trivial_min_words: int = 5,
) -> bool:
    """Filter out noise — only store turns with clear knowledge signal."""
    user_lower = user_content.strip().lower()
    words = len(user_content.split())

    # Too short — not enough signal
    if words < trivial_min_words:
        return False

    # Skip system notes, platform prefixes, test messages
    for pat in skip_patterns:
        if user_lower.startswith(pat.lower()):
            return False

    # Skip if assistant response is very long (likely tool-heavy)
    if assistant_content and len(assistant_content) > 2000:
        return False

    # Skip pure questions (no new information contributed)
    if user_content.strip().endswith("?") and words < 20:
        return False

    return True


def _summarize_session(messages: List[Dict[str, Any]]) -> str:
    """Extract key themes from session messages for end-of-session summary."""
    user_msgs = [
        m.get("content", "")[:200]
        for m in messages
        if m.get("role") == "user" and m.get("content")
    ]
    if not user_msgs:
        return "Empty session"

    # Take first + last few user messages as theme indicators
    themes = []
    if len(user_msgs) <= 5:
        themes = user_msgs
    else:
        themes = user_msgs[:3] + user_msgs[-2:]

    summary = "Session themes: " + " | ".join(themes)
    return summary[:500]


class LifecycleHooks:
    """Manages all lifecycle state and hook execution.

    This class is instantiated by MuninnDBMemoryProvider and holds the
    mutable state (threads, caches, config) that lifecycle hooks need.
    """

    def __init__(
        self,
        client: MCPClient | None,
        circuit: CircuitBreaker | None,
        vault: str,
        activate_limit: int = 10,
        activate_min_score: float = 0.3,
        prefetch_tokens: int = 800,
        trivial_min_words: int = 5,
        skip_patterns: list[str] | None = None,
    ):
        self._client = client
        self._circuit = circuit
        self._vault = vault
        self._activate_limit = activate_limit
        self._activate_min_score = activate_min_score
        self._prefetch_tokens = prefetch_tokens
        self._trivial_min_words = trivial_min_words
        self._skip_patterns = skip_patterns or list(DEFAULT_SKIP_PATTERNS)

        # Threading state
        self._prefetch_cache: dict[tuple[str, int], str] = {}
        self._prefetch_lock = threading.Lock()
        self._turn_index = 0
        self._prefetch_thread: threading.Thread | None = None
        self._sync_thread: threading.Thread | None = None
        self._stored_obs_count = 0  # track observations stored this session

        # Will be set by provider
        self._session_id = ""
        self._cross_vault_recall_fn = None

        # Guide cache (lazy-fetched from muninn_guide on first use)
        self._guide_cache: str = ""
        self._guide_fetched: bool = False

    # ── Cross-vault recall wiring ────────────────────────────────────────

    def set_cross_vault_recall(self, fn):
        """Set the cross-vault recall function (from the provider)."""
        self._cross_vault_recall_fn = fn

    # ── System prompt ────────────────────────────────────────────────────

    @staticmethod
    def _extract_guide_text(result: Any) -> str:
        """Extract guide text from muninn_guide response.

        Handles the three possible return shapes from MCPClient.call():
        - dict with "text" key -> return result["text"]
        - dict with "content" key (string) -> return result["content"]
        - str -> return as-is
        - anything else -> return ""
        """
        if isinstance(result, dict):
            text = result.get("text", "") or result.get("content", "")
            if isinstance(text, str):
                return text
        elif isinstance(result, str):
            return result
        return ""

    def system_prompt_block(self) -> str:
        if not self._client:
            return ""

        # Return cached guide if already fetched successfully
        if self._guide_fetched and self._guide_cache:
            return self._guide_cache

        # Attempt to fetch from muninn_guide (once per session)
        if not self._guide_fetched:
            self._guide_fetched = True  # Set BEFORE call — prevent retry storms
            # Check circuit breaker before attempting
            if self._circuit is None or not self._circuit.is_open:
                try:
                    result = self._client.call("muninn_guide", {})
                    text = self._extract_guide_text(result)
                    if text and text.strip():
                        self._guide_cache = text.strip()
                        if self._circuit is not None:
                            self._circuit.record_success()
                        return self._guide_cache
                except Exception as exc:
                    if self._circuit is not None:
                        self._circuit.record_failure()
                    logger.debug("MuninnDB muninn_guide fetch failed, using fallback: %s", exc)

        # Fallback: return cached guide or static text
        if self._guide_cache:
            return self._guide_cache

        return (
            "[MuninnDB Memory]\n"
            "Long-term semantic memory is available via MuninnDB. "
            "Use muninn_recall to search, muninn_remember to store, "
            "muninn_forget to remove, muninn_evolve to update, "
            "muninn_status to check vault health. "
            "Memories are automatically synced after each turn."
        )

    # ── Prefetch (recall before each turn) ───────────────────────────────

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
        if self._cross_vault_recall_fn:
            try:
                result = self._cross_vault_recall_fn(query)
                return format_recall_result(result, self._prefetch_tokens)
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
        if not self._cross_vault_recall_fn:
            return
        try:
            result = self._cross_vault_recall_fn(query)
            formatted = format_recall_result(result, self._prefetch_tokens)
            if formatted:
                with self._prefetch_lock:
                    self._prefetch_cache[(sid, turn)] = formatted
        except Exception as exc:
            self._circuit.record_failure()
            logger.debug("MuninnDB queue_prefetch failed: %s", exc)

    # ── Sync turn (store after each turn) ────────────────────────────────

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        tool_calls: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if not self._client or self._circuit.is_open:
            return

        # Smart filtering — only store valuable turns
        if not is_valuable_turn(
            user_content, assistant_content,
            self._skip_patterns, self._trivial_min_words,
        ):
            self._turn_index += 1
            return

        self._turn_index += 1

        # Wait for previous sync thread
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)

        self._sync_thread = threading.Thread(
            target=self._do_sync_turn,
            args=(user_content, assistant_content, session_id or self._session_id),
            kwargs={"tool_calls": tool_calls},
            daemon=True,
        )
        self._sync_thread.start()

    def _do_sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        sid: str,
        *,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        try:
            # Extract key facts from assistant response (first 500 chars)
            asst_excerpt = assistant_content[:500] if assistant_content else ""

            # Store as observation with the assistant's answer as the valuable content
            content = f"User asked: {user_content[:200]}"
            if asst_excerpt:
                content += f"\nKey info: {asst_excerpt}"

            # Append tool call summaries if provided
            if tool_calls:
                summaries = []
                for tc in tool_calls[:5]:  # cap at 5 tool calls
                    name = tc.get("name", "")
                    result_preview = str(tc.get("result", ""))[:100]
                    summaries.append(f"{name}: {result_preview}")
                if summaries:
                    content += "\nTools used: " + "; ".join(summaries)

            self._client.call("muninn_remember", {
                "content": content,
                "type": "observation",
                "summary": user_content[:200],
                "vault": self._vault,
            })
            self._circuit.record_success()
            self._stored_obs_count += 1
        except Exception as exc:
            self._circuit.record_failure()
            logger.debug("MuninnDB sync_turn failed: %s", exc)

    # ── Session switch ───────────────────────────────────────────────────

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
            self._stored_obs_count = 0
            self._guide_fetched = False
            self._guide_cache = ""
            with self._prefetch_lock:
                self._prefetch_cache.clear()

    # ── Session end (NEW) ────────────────────────────────────────────────

    def _consolidate_observations(self) -> None:
        """Merge similar observations stored this session to prevent noise accumulation.

        Runs at session boundary when enough observations were stored.
        Uses muninn_consolidate to combine related observations into a single
        consolidated memory, reducing vault noise over time.
        """
        if self._stored_obs_count < 3:
            return
        try:
            # Find recent observations in this vault
            result = self._client.call("muninn_recall", {
                "context": ["recent session observations"],
                "limit": 5,
                "threshold": 0.2,
                "vault": self._vault,
            })
            self._circuit.record_success()

            memories = (
                result.get("memories")
                or result.get("engrams")
                or result.get("results")
                or []
            )
            obs_ids = [m["id"] for m in memories if m.get("id")]

            if len(obs_ids) >= 3:
                # Build a consolidated summary from the observations
                summaries = []
                for m in memories[:5]:
                    s = m.get("summary") or m.get("content", "")
                    if s:
                        summaries.append(s[:150])
                consolidated = "Session synthesis: " + " | ".join(summaries)

                self._client.call("muninn_consolidate", {
                    "ids": obs_ids,
                    "merged_content": consolidated[:1000],
                    "vault": self._vault,
                })
                self._circuit.record_success()
                logger.debug(
                    "MuninnDB consolidated %d observations into session synthesis",
                    len(obs_ids),
                )
        except Exception as exc:
            # Consolidation is best-effort — don't fail session end
            logger.debug("MuninnDB consolidation skipped: %s", exc)

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """Called at session boundary (/new, /reset, session expiry).

        Flushes remaining insights as a session summary memory.
        """
        if not self._client or self._circuit.is_open:
            return

        # Wait for any in-flight sync
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)

        # Extract key topics/themes from the session
        summary = _summarize_session(messages)
        if summary == "Empty session":
            return

        try:
            self._client.call("muninn_remember", {
                "content": summary,
                "type": "observation",
                "vault": self._vault,
            })
            self._circuit.record_success()
        except Exception:
            pass

        # Consolidate observations stored this session to reduce noise
        self._consolidate_observations()
        self._stored_obs_count = 0

    # ── Memory write mirror ──────────────────────────────────────────────

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

    # ── Pre-compress hook ────────────────────────────────────────────────

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

    # ── Delegation hook ──────────────────────────────────────────────────

    def on_delegation(
        self, task: str, result: str, *, child_session_id: str = "", **kwargs
    ) -> None:
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

    # ── Shutdown ─────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Join background threads."""
        for t in [self._prefetch_thread, self._sync_thread]:
            if t and t.is_alive():
                t.join(timeout=5.0)
