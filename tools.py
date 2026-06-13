"""Tool schemas and unified dispatch for MuninnDB plugin.

All tool calls flow through handle_tool_call() which:
1. Checks circuit breaker
2. Injects vault automatically
3. Routes via TOOL_NAME_MAP to the MCP server
4. Returns structured JSON
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool name mapping (plugin tool name → MCP tool name)
# ---------------------------------------------------------------------------

TOOL_NAME_MAP: Dict[str, str] = {
    # Original tools
    "muninn_search": "muninn_recall",
    "muninn_remember": "muninn_remember",
    "muninn_entities": "muninn_entities",
    # P0 tools
    "muninn_where_left_off": "muninn_where_left_off",
    "muninn_forget": "muninn_forget",
    "muninn_evolve": "muninn_evolve",
    "muninn_remember_batch": "muninn_remember_batch",
    "muninn_contradictions": "muninn_contradictions",
    "muninn_status": "muninn_status",
    # P1 — Knowledge graph
    "muninn_link": "muninn_link",
    "muninn_merge": "muninn_merge",
    "muninn_traverse": "muninn_traverse",
    "muninn_decide": "muninn_decide",
    # P1 — Entity management
    "muninn_find_entity": "muninn_find_entity",
    "muninn_entity_snapshot": "muninn_entity_snapshot",
    "muninn_entity_versions": "muninn_entity_versions",
    "muninn_entity_clusters": "muninn_entity_clusters",
    "muninn_similar_entities": "muninn_similar_entities",
    "muninn_merge_entity": "muninn_merge_entity",
    "muninn_entity_state": "muninn_entity_state",
    "muninn_forget_entity": "muninn_forget_entity",
    # P1 — Quality assurance
    "muninn_classify": "muninn_classify",
    "muninn_trust": "muninn_trust",
    "muninn_feedback": "muninn_feedback",
    # P2 — Audit & debug
    "muninn_audit_trail": "muninn_audit_trail",
    "muninn_debug_recall": "muninn_debug_recall",
    "muninn_vault_health": "muninn_vault_health",
    "muninn_export_graph": "muninn_export_graph",
    # P2 — Hierarchical memory
    "muninn_parent": "muninn_parent",
    "muninn_child": "muninn_child",
    "muninn_level": "muninn_level",
    # P2 — Enrichment pipeline
    "muninn_get_enrichment_candidates": "muninn_get_enrichment_candidates",
    "muninn_replay_enrichment": "muninn_replay_enrichment",
}

# ---------------------------------------------------------------------------
# Tool schemas (existing 3 + P0 6)
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
                "enum": [
                    "fact", "decision", "observation", "preference", "issue",
                    "task", "procedure", "event", "goal", "constraint",
                    "ephemeral", "milestone",
                ],
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

# P0 tools

WHERE_LEFT_OFF_SCHEMA = {
    "name": "muninn_where_left_off",
    "description": (
        "Session resumption tool. Returns recently accessed memories with timestamps. "
        "Use at the start of a new session to pick up where you left off."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max recent memories to return (default: 10).",
            },
        },
        "required": [],
    },
}

FORGET_SCHEMA = {
    "name": "muninn_forget",
    "description": (
        "Soft-delete a memory by ID. The memory is marked as deleted rather than "
        "permanently removed, allowing potential recovery."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "The memory ID to forget.",
            },
            "reason": {
                "type": "string",
                "description": "Optional reason for deletion.",
            },
        },
        "required": ["id"],
    },
}

EVOLVE_SCHEMA = {
    "name": "muninn_evolve",
    "description": (
        "Update a memory's content without creating a duplicate. "
        "Use this to refine or correct existing memories rather than storing a new version."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "The memory ID to update.",
            },
            "content": {
                "type": "string",
                "description": "The new content for the memory.",
            },
            "reason": {
                "type": "string",
                "description": "Optional reason for the update.",
            },
        },
        "required": ["id", "content"],
    },
}

REMEMBER_BATCH_SCHEMA = {
    "name": "muninn_remember_batch",
    "description": (
        "Store multiple memories atomically. All memories are stored in a single "
        "transaction — if any fails, none are persisted."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "memories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "type": {"type": "string"},
                        "summary": {"type": "string"},
                        "entities": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["content"],
                },
                "description": "Array of memories to store atomically.",
            },
        },
        "required": ["memories"],
    },
}

CONTRADICTIONS_SCHEMA = {
    "name": "muninn_contradictions",
    "description": (
        "Find conflicting memories in the vault. Returns pairs of memories with "
        "contradictory content for review and resolution."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max contradiction pairs to return (default: 10).",
            },
        },
        "required": [],
    },
}

STATUS_SCHEMA = {
    "name": "muninn_status",
    "description": (
        "Vault health summary. Returns memory count, health status, enrichment mode, "
        "and config summary. Useful for debugging vault issues."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

# ---------------------------------------------------------------------------
# P1 — Knowledge graph tools
# ---------------------------------------------------------------------------

LINK_SCHEMA = {
    "name": "muninn_link",
    "description": (
        "Create a typed relationship between two memories. "
        "Use to connect related memories in the knowledge graph."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "source_id": {
                "type": "string",
                "description": "Source memory ID.",
            },
            "target_id": {
                "type": "string",
                "description": "Target memory ID.",
            },
            "relation": {
                "type": "string",
                "description": "Relationship type (e.g. 'supports', 'contradicts', 'derived_from').",
            },
        },
        "required": ["source_id", "target_id", "relation"],
    },
}

MERGE_SCHEMA = {
    "name": "muninn_merge",
    "description": (
        "Consolidate fragmented observations into a single unified memory. "
        "Source memories are marked as merged; a new memory is created."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "source_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "IDs of memories to merge.",
            },
            "target_content": {
                "type": "string",
                "description": "Consolidated content for the merged memory.",
            },
        },
        "required": ["source_ids", "target_content"],
    },
}

TRAVERSE_SCHEMA = {
    "name": "muninn_traverse",
    "description": (
        "Explore the memory graph starting from a specific memory. "
        "Returns connected memories along relationship edges."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "start_id": {
                "type": "string",
                "description": "Starting memory ID.",
            },
            "direction": {
                "type": "string",
                "enum": ["forward", "backward", "both"],
                "description": "Traversal direction (default: both).",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum traversal depth (default: 3).",
            },
        },
        "required": ["start_id"],
    },
}

DECIDE_SCHEMA = {
    "name": "muninn_decide",
    "description": (
        "Record a decision with its rationale and considered alternatives. "
        "Creates a structured decision memory for future reference."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "description": "The decision that was made.",
            },
            "rationale": {
                "type": "string",
                "description": "Why this decision was made.",
            },
            "alternatives": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Alternatives that were considered but not chosen.",
            },
        },
        "required": ["decision", "rationale"],
    },
}

# ---------------------------------------------------------------------------
# P1 — Entity management tools
# ---------------------------------------------------------------------------

FIND_ENTITY_SCHEMA = {
    "name": "muninn_find_entity",
    "description": (
        "Fast entity lookup by name. Returns entity details including "
        "type, mention count, and associated memory count."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Entity name to look up.",
            },
        },
        "required": ["name"],
    },
}

ENTITY_SNAPSHOT_SCHEMA = {
    "name": "muninn_entity_snapshot",
    "description": (
        "Full aggregate view of an entity — the entity itself plus all "
        "associated memories and relationships."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Entity name to snapshot.",
            },
        },
        "required": ["name"],
    },
}

ENTITY_VERSIONS_SCHEMA = {
    "name": "muninn_entity_versions",
    "description": (
        "Track how an entity has evolved over time. Returns the version "
        "history including changes to type, state, and metadata."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Entity name to get versions for.",
            },
        },
        "required": ["name"],
    },
}

ENTITY_CLUSTERS_SCHEMA = {
    "name": "muninn_entity_clusters",
    "description": (
        "Discover implicit entity relationships via co-occurrence analysis. "
        "Returns pairs of entities that frequently appear together."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "top_n": {
                "type": "integer",
                "description": "Number of top clusters to return (default: 20).",
            },
        },
        "required": [],
    },
}

SIMILAR_ENTITIES_SCHEMA = {
    "name": "muninn_similar_entities",
    "description": (
        "Find potential duplicate entities — case variants, fuzzy matches, "
        "and near-duplicate names. Useful for entity deduplication."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

MERGE_ENTITY_SCHEMA = {
    "name": "muninn_merge_entity",
    "description": (
        "Deduplicate entity names by merging a source entity into a target. "
        "All memories and relationships from source are transferred to target."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Source entity name (will be merged into target).",
            },
            "target": {
                "type": "string",
                "description": "Target entity name (will absorb the source).",
            },
        },
        "required": ["source", "target"],
    },
}

ENTITY_STATE_SCHEMA = {
    "name": "muninn_entity_state",
    "description": (
        "Manage entity lifecycle state transitions. Set an entity to "
        "active, archived, or merged state."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Entity name.",
            },
            "state": {
                "type": "string",
                "enum": ["active", "archived", "merged"],
                "description": "New state for the entity.",
            },
            "type": {
                "type": "string",
                "description": "Optional entity type to set.",
            },
        },
        "required": ["name", "state"],
    },
}

FORGET_ENTITY_SCHEMA = {
    "name": "muninn_forget_entity",
    "description": (
        "Remove an entity from the knowledge graph. Optionally cascade "
        "to delete all associated memories."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Entity name to remove.",
            },
            "cascade": {
                "type": "boolean",
                "description": "If true, also delete all associated memories (default: false).",
            },
        },
        "required": ["name"],
    },
}

# ---------------------------------------------------------------------------
# P1 — Quality assurance tools
# ---------------------------------------------------------------------------

CLASSIFY_SCHEMA = {
    "name": "muninn_classify",
    "description": (
        "Classify a memory's confidence level. Used by the classify pipeline "
        "to mark memories as verified, inferred, or untrusted."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "Memory ID to classify.",
            },
            "classification": {
                "type": "string",
                "enum": ["verified", "inferred", "untrusted"],
                "description": "Confidence classification.",
            },
        },
        "required": ["id", "classification"],
    },
}

TRUST_SCHEMA = {
    "name": "muninn_trust",
    "description": (
        "Set the trust level on a memory. Marks whether the memory is "
        "verified, inferred from context, or untrusted."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "Memory ID.",
            },
            "level": {
                "type": "string",
                "enum": ["verified", "inferred", "untrusted"],
                "description": "Trust level to set.",
            },
        },
        "required": ["id", "level"],
    },
}

FEEDBACK_SCHEMA = {
    "name": "muninn_feedback",
    "description": (
        "Signal whether a recall was useful for relevance tuning. "
        "Helps improve future search quality."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The original search query.",
            },
            "memory_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "IDs of recalled memories being rated.",
            },
            "useful": {
                "type": "boolean",
                "description": "Whether the recall results were useful.",
            },
        },
        "required": ["query", "memory_ids", "useful"],
    },
}

# ---------------------------------------------------------------------------
# P2 — Audit & debug tools
# ---------------------------------------------------------------------------

AUDIT_TRAIL_SCHEMA = {
    "name": "muninn_audit_trail",
    "description": (
        "Change history for a memory. Returns a chronological list of all "
        "modifications with timestamps, change types, and diff metadata."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "Memory ID to get audit trail for.",
            },
        },
        "required": ["id"],
    },
}

DEBUG_RECALL_SCHEMA = {
    "name": "muninn_debug_recall",
    "description": (
        "Explain why a recall returned specific results. Returns scored results "
        "with detailed explanation metadata including matching factors and "
        "relevance breakdown."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The query to debug (same query used in recall).",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to analyze (default: 5).",
            },
        },
        "required": ["query"],
    },
}

VAULT_HEALTH_SCHEMA = {
    "name": "muninn_vault_health",
    "description": (
        "Detailed health diagnostics for the vault. Returns memory count, "
        "storage size, index health, and enrichment statistics."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

EXPORT_GRAPH_SCHEMA = {
    "name": "muninn_export_graph",
    "description": (
        "Export the entity graph in structured format. Supports JSON and DOT "
        "(Graphviz) output formats for visualization and analysis."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "enum": ["json", "dot"],
                "description": "Output format (default: json).",
            },
        },
        "required": [],
    },
}

# ---------------------------------------------------------------------------
# P2 — Hierarchical memory tools
# ---------------------------------------------------------------------------

PARENT_SCHEMA = {
    "name": "muninn_parent",
    "description": (
        "Set a parent memory for hierarchical organization. Creates a "
        "parent-child relationship in the memory graph."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "child_id": {
                "type": "string",
                "description": "ID of the child memory.",
            },
            "parent_id": {
                "type": "string",
                "description": "ID of the parent memory.",
            },
        },
        "required": ["child_id", "parent_id"],
    },
}

CHILD_SCHEMA = {
    "name": "muninn_child",
    "description": (
        "Set a child memory for hierarchical organization. Creates a "
        "parent-child relationship in the memory graph."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "parent_id": {
                "type": "string",
                "description": "ID of the parent memory.",
            },
            "child_id": {
                "type": "string",
                "description": "ID of the child memory.",
            },
        },
        "required": ["parent_id", "child_id"],
    },
}

LEVEL_SCHEMA = {
    "name": "muninn_level",
    "description": (
        "Navigate hierarchical memory levels. Returns the parent (up) or "
        "children (down) of a memory in the hierarchy."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "Memory ID to navigate from.",
            },
            "direction": {
                "type": "string",
                "enum": ["up", "down"],
                "description": "Navigation direction: up (parent) or down (children).",
            },
        },
        "required": ["id", "direction"],
    },
}

# ---------------------------------------------------------------------------
# P2 — Enrichment pipeline tools
# ---------------------------------------------------------------------------

GET_ENRICHMENT_CANDIDATES_SCHEMA = {
    "name": "muninn_get_enrichment_candidates",
    "description": (
        "Find memories that are missing enrichment stages. Returns a list of "
        "memory IDs along with which enrichment stages are incomplete."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

REPLAY_ENRICHMENT_SCHEMA = {
    "name": "muninn_replay_enrichment",
    "description": (
        "Run the enrichment pipeline on specified memories. If no IDs are "
        "provided, runs on all memories with missing enrichment stages."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Memory IDs to enrich. If omitted, enriches all "
                    "memories with missing enrichment stages."
                ),
            },
        },
        "required": [],
    },
}

# ---------------------------------------------------------------------------
# All schemas in order (original 3 + P0 6 + P1 15 + P2 9 = 33 tools)
# ---------------------------------------------------------------------------

ALL_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    SEARCH_SCHEMA,
    REMEMBER_SCHEMA,
    ENTITIES_SCHEMA,
    # P0
    WHERE_LEFT_OFF_SCHEMA,
    FORGET_SCHEMA,
    EVOLVE_SCHEMA,
    REMEMBER_BATCH_SCHEMA,
    CONTRADICTIONS_SCHEMA,
    STATUS_SCHEMA,
    # P1 — Knowledge graph
    LINK_SCHEMA,
    MERGE_SCHEMA,
    TRAVERSE_SCHEMA,
    DECIDE_SCHEMA,
    # P1 — Entity management
    FIND_ENTITY_SCHEMA,
    ENTITY_SNAPSHOT_SCHEMA,
    ENTITY_VERSIONS_SCHEMA,
    ENTITY_CLUSTERS_SCHEMA,
    SIMILAR_ENTITIES_SCHEMA,
    MERGE_ENTITY_SCHEMA,
    ENTITY_STATE_SCHEMA,
    FORGET_ENTITY_SCHEMA,
    # P1 — Quality assurance
    CLASSIFY_SCHEMA,
    TRUST_SCHEMA,
    FEEDBACK_SCHEMA,
    # P2 — Audit & debug
    AUDIT_TRAIL_SCHEMA,
    DEBUG_RECALL_SCHEMA,
    VAULT_HEALTH_SCHEMA,
    EXPORT_GRAPH_SCHEMA,
    # P2 — Hierarchical memory
    PARENT_SCHEMA,
    CHILD_SCHEMA,
    LEVEL_SCHEMA,
    # P2 — Enrichment pipeline
    GET_ENRICHMENT_CANDIDATES_SCHEMA,
    REPLAY_ENRICHMENT_SCHEMA,
]


def get_tool_schemas(priority_filter: str = "all") -> List[Dict[str, Any]]:
    """Return tool schemas filtered by priority tier.

    Args:
        priority_filter: One of 'core', 'p0', 'p0-p1', 'p0-p2', 'all'.
            - 'core': 3 essential tools (search, remember, entities)
            - 'p0': core + 6 P0 lifecycle tools = 9 tools
            - 'p0-p1': core + P0 + 14 P1 tools = 23 tools
            - 'all' or 'p0-p2': all 33 tools (default)
    """
    # Tier membership defined by schema objects — ordering-independent
    _CORE = {id(SEARCH_SCHEMA), id(REMEMBER_SCHEMA), id(ENTITIES_SCHEMA)}
    _P0 = {id(WHERE_LEFT_OFF_SCHEMA), id(FORGET_SCHEMA), id(EVOLVE_SCHEMA),
            id(REMEMBER_BATCH_SCHEMA), id(CONTRADICTIONS_SCHEMA), id(STATUS_SCHEMA)}
    _P1 = {id(LINK_SCHEMA), id(MERGE_SCHEMA), id(TRAVERSE_SCHEMA), id(DECIDE_SCHEMA),
            id(FIND_ENTITY_SCHEMA), id(ENTITY_SNAPSHOT_SCHEMA), id(ENTITY_VERSIONS_SCHEMA),
            id(ENTITY_CLUSTERS_SCHEMA), id(SIMILAR_ENTITIES_SCHEMA), id(MERGE_ENTITY_SCHEMA),
            id(ENTITY_STATE_SCHEMA), id(FORGET_ENTITY_SCHEMA),
            id(CLASSIFY_SCHEMA), id(TRUST_SCHEMA), id(FEEDBACK_SCHEMA)}
    # P2 = everything else in ALL_TOOL_SCHEMAS not in CORE/P0/P1

    filter_sets = {
        "core": _CORE,
        "p0": _CORE | _P0,
        "p0-p1": _CORE | _P0 | _P1,
    }
    allowed = filter_sets.get(priority_filter.lower().strip())
    if allowed is None:
        # 'all', 'p0-p2', or unknown → return everything
        return list(ALL_TOOL_SCHEMAS)
    return [s for s in ALL_TOOL_SCHEMAS if id(s) in allowed]


def handle_tool_call(
    tool_name: str,
    args: Dict[str, Any],
    *,
    client: Any,
    circuit: Any,
    vault: str,
    cross_vault_recall_fn: Any = None,
) -> str:
    """Unified tool dispatch with vault injection and circuit breaker.

    Args:
        tool_name: The plugin tool name (e.g. "muninn_search").
        args: Tool call arguments from the agent.
        client: MCPClient instance.
        circuit: CircuitBreaker instance.
        vault: Vault name to inject.
        cross_vault_recall_fn: Optional callable for cross-vault recall
            (muninn_search uses this for multi-vault search).

    Returns:
        JSON string result.
    """
    if not client:
        return json.dumps({"error": "MuninnDB not initialized"})

    if circuit.is_open:
        return json.dumps({"error": "MuninnDB circuit breaker open — try again later"})

    try:
        # muninn_search uses cross-vault recall (special handler)
        if tool_name == "muninn_search" and cross_vault_recall_fn is not None:
            result = cross_vault_recall_fn(
                args.get("query", ""),
                limit=args.get("limit", 10),
                threshold=max(args.get("threshold", 0.3), 0.3),
            )
            circuit.record_success()
            return json.dumps(result, default=str)

        # muninn_remember maps "memory_type" arg → "type" MCP param
        if tool_name == "muninn_remember":
            mcp_args = {
                "content": args.get("content", ""),
                "type": args.get("memory_type", "fact"),
                "summary": args.get("summary", ""),
                "vault": vault,
            }
            result = client.call("muninn_remember", mcp_args)
            circuit.record_success()
            return json.dumps(result, default=str)

        # Generic passthrough for all other tools
        mcp_name = TOOL_NAME_MAP.get(tool_name, tool_name)
        mcp_args = dict(args)
        mcp_args.setdefault("vault", vault)

        result = client.call(mcp_name, mcp_args)
        circuit.record_success()
        return json.dumps(result, default=str)

    except Exception as exc:
        circuit.record_failure()
        return json.dumps({"error": str(exc)})
