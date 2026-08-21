"""Config loading, auto-detection, and schema for MuninnDB plugin."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def config_paths() -> list[Path]:
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


def load_config(hermes_home: str = "") -> dict:
    """Load muninndb.json from the first location found."""
    candidates = []
    if hermes_home:
        candidates.append(Path(hermes_home) / "muninndb.json")
    candidates.extend(config_paths())

    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception as exc:
                logger.warning("MuninnDB: failed to parse %s: %s", p, exc)
    return {}


def detect_mcp_url(hermes_home: str = "") -> str:
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


def save_config(values: Dict[str, Any], hermes_home: str) -> None:
    """Save config values to muninndb.json."""
    config_path = Path(hermes_home) / "muninndb.json"
    existing = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text())
        except Exception:
            pass
    existing.update(values)
    config_path.write_text(json.dumps(existing, indent=2))


def get_config_schema() -> List[Dict[str, Any]]:
    """Return config schema entries for hermes memory setup."""
    return [
        {
            "key": "mcp_url",
            "description": "MuninnDB MCP server URL (e.g. http://10.0.0.150:8750/mcp)",
            "required": True,
        },
        {
            "key": "vault_prefix",
            "description": "Vault name prefix (default: 'hermes')",
            "default": "hermes",
        },
        {
            "key": "activate_limit",
            "description": "Max memories per prefetch (default: 10)",
            "default": 10,
        },
        {
            "key": "activate_min_score",
            "description": "Min relevance score 0-1 (default: 0.3)",
            "default": 0.3,
        },
        {
            "key": "skip_patterns",
            "description": "Base list of skip patterns for turn filtering",
            "default": [],
        },
        {
            "key": "skip_patterns_extra",
            "description": "Additional user-extensible skip patterns",
            "default": [],
        },
        {
            "key": "tool_priority_filter",
            "description": "Tool families to expose: all, p0, p0-p1, or p0-p2",
            "default": "all",
        },
        {
            "key": "enable_audit_tools",
            "description": "Enable audit/debug tools (P2: audit_trail, debug_recall, vault_health, export_graph)",
            "default": False,
        },
        {
            "key": "workflow_vault_ttl_hours",
            "description": "TTL in hours for auto-created workflow vaults (default: 72 = 3 days)",
            "default": 72,
        },
    ]
