"""Tool schemas and unified dispatch for MuninnDB plugin.

Synced against MuninnDB MCP server (muninndb/internal/mcp/tools.go)
as of 2026-07-13 — 39 registered MCP tools.

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
    # Core (wrapper: muninn_search → muninn_recall with cross-vault)
    "muninn_search": "muninn_recall",
    # P0 — lifecycle
    "muninn_remember": "muninn_remember",
    "muninn_remember_batch": "muninn_remember_batch",
    "muninn_recall": "muninn_recall",
    "muninn_read": "muninn_read",
    "muninn_forget": "muninn_forget",
    "muninn_evolve": "muninn_evolve",
    "muninn_consolidate": "muninn_consolidate",
    "muninn_restore": "muninn_restore",
    "muninn_list_deleted": "muninn_list_deleted",
    "muninn_state": "muninn_state",
    "muninn_session": "muninn_session",
    "muninn_status": "muninn_status",
    "muninn_where_left_off": "muninn_where_left_off",
    "muninn_contradictions": "muninn_contradictions",
    # P1 — knowledge graph
    "muninn_link": "muninn_link",
    "muninn_traverse": "muninn_traverse",
    "muninn_decide": "muninn_decide",
    "muninn_explain": "muninn_explain",
    # P1 — entity management
    "muninn_entities": "muninn_entities",
    "muninn_entity": "muninn_entity",
    "muninn_find_by_entity": "muninn_find_by_entity",
    "muninn_entity_state": "muninn_entity_state",
    "muninn_entity_state_batch": "muninn_entity_state_batch",
    "muninn_entity_clusters": "muninn_entity_clusters",
    "muninn_entity_timeline": "muninn_entity_timeline",
    "muninn_similar_entities": "muninn_similar_entities",
    "muninn_merge_entity": "muninn_merge_entity",
    # P1 — quality / trust / feedback
    "muninn_trust": "muninn_trust",
    "muninn_feedback": "muninn_feedback",
    # P1 — enrichment
    "muninn_get_enrichment_candidates": "muninn_get_enrichment_candidates",
    "muninn_apply_enrichment": "muninn_apply_enrichment",
    "muninn_retry_enrich": "muninn_retry_enrich",
    "muninn_replay_enrichment": "muninn_replay_enrichment",
    # P2 — audit / debug / export
    "muninn_provenance": "muninn_provenance",
    "muninn_export_graph": "muninn_export_graph",
    "muninn_guide": "muninn_guide",
    # P2 — Hierarchical memory
    "muninn_remember_tree": "muninn_remember_tree",
    "muninn_recall_tree": "muninn_recall_tree",
    "muninn_add_child": "muninn_add_child",
    # P1 — Work-queue / lease (v0.8.0)
    "muninn_compare_and_set": "muninn_compare_and_set",
    "muninn_claim": "muninn_claim",
    "muninn_release": "muninn_release",
}

# ---------------------------------------------------------------------------
# Entity type enum (single source of truth: muninndb validEntityTypes)
# ---------------------------------------------------------------------------

_ENTITY_TYPE_ENUM = [
    "person", "organization", "location", "concept", "technology",
    "project", "tool", "database", "service", "framework",
    "language", "product", "event", "other",
]

# ---------------------------------------------------------------------------
# Tool schemas — synced with muninndb/internal/mcp/tools.go
# ---------------------------------------------------------------------------

# ── Core (3) ──────────────────────────────────────────────────────────────

SEARCH_SCHEMA = {
    "name": "muninn_search",
    "description": (
        "Semantic search across MuninnDB long-term memory. "
        "Returns ranked memories with relevance scores. "
        "Wraps muninn_recall with cross-vault search."
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
            "caller": {
                "type": "string",
                "description": "Your ownership-lease identity ('{host}:{session}'). Leased memories owned by others are hidden; your own are returned normally.",
            },
            "include_leased": {
                "type": "boolean",
                "description": "When true, disables lease filtering so memories checked out by other owners are also returned (admin/debug). Default: false.",
            },
        },
        "required": ["query"],
    },
}

REMEMBER_SCHEMA = {
    "name": "muninn_remember",
    "description": (
        "Store a new piece of information (engram) in long-term memory. "
        "IMPORTANT: Keep each memory atomic — one concept, decision, or fact per memory. "
        "If a conversation covers multiple topics, use muninn_remember_batch. "
        "TIP: Provide 'entities' and 'entity_relationships' whenever you can identify them — "
        "this builds the knowledge graph immediately without requiring background enrichment. "
        "NOTE: If the exact same content already exists, the existing memory ID is returned."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The information to remember."},
            "concept": {"type": "string", "description": "Short label for this memory."},
            "type": {
                "type": "string",
                "description": (
                    "Memory type — built-in name (fact, decision, observation, preference, "
                    "issue, task, procedure, event, goal, constraint, identity, reference) "
                    "or free-form label (e.g. 'architectural_decision')."
                ),
            },
            "type_label": {"type": "string", "description": "Explicit free-form type label."},
            "summary": {"type": "string", "description": "One-line summary. Skips background summarization."},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional topic tags.",
            },
            "confidence": {"type": "number", "description": "Confidence score 0.0-1.0 (default 1.0)."},
            "created_at": {"type": "string", "description": "ISO 8601 timestamp. Defaults to now."},
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Entity name."},
                        "type": {"type": "string", "enum": _ENTITY_TYPE_ENUM, "description": "Entity type."},
                    },
                    "required": ["name", "type"],
                },
                "description": "Entities mentioned. Skips background entity extraction.",
            },
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "target_id": {"type": "string", "description": "ID of the target memory (ULID)."},
                        "relation": {"type": "string", "description": "Relationship type."},
                        "weight": {"type": "number", "description": "Association weight 0.0-1.0 (default 0.9)."},
                    },
                    "required": ["target_id", "relation"],
                },
                "description": "Relationships to existing memories.",
            },
            "entity_relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from_entity": {"type": "string", "description": "Source entity name."},
                        "to_entity": {"type": "string", "description": "Target entity name."},
                        "rel_type": {"type": "string", "description": "Relationship type (uses, depends_on, caches_with, manages, contradicts, supports, extends, implements, belongs_to)."},
                        "weight": {"type": "number", "description": "Confidence 0.0-1.0 (default 0.9)."},
                    },
                    "required": ["from_entity", "to_entity", "rel_type"],
                },
                "description": "Typed entity-to-entity relationships for the knowledge graph.",
            },
            "op_id": {"type": "string", "description": "Idempotency key. Returns cached ID if receipt exists."},
            "embedding": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Optional pre-computed embedding vector. Must match vault dimension.",
            },
        },
        "required": ["content"],
    },
}

ENTITIES_SCHEMA = {
    "name": "muninn_entities",
    "description": "List known entities in the vault, sorted by mention count. Optionally filter by state.",
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max results (default: 50)."},
            "state": {
                "type": "string",
                "description": "Filter by state: active, deprecated, merged, resolved.",
            },
        },
        "required": [],
    },
}

# ── P0 — Lifecycle tools ─────────────────────────────────────────────────

WHERE_LEFT_OFF_SCHEMA = {
    "name": "muninn_where_left_off",
    "description": (
        "Surface what was being worked on at the end of the last session. "
        "Returns the most recently accessed active memories, sorted by recency. "
        "Call at session start to orient yourself before any user queries."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max memories (default: 10, max: 50)."},
        },
        "required": [],
    },
}

FORGET_SCHEMA = {
    "name": "muninn_forget",
    "description": "Soft-delete a memory. It remains recoverable but is excluded from recall.",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Memory ID to forget."},
        },
        "required": ["id"],
    },
}

EVOLVE_SCHEMA = {
    "name": "muninn_evolve",
    "description": "Update a memory with new information. Creates a new version and archives the old one.",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "ID of the memory to evolve."},
            "new_content": {"type": "string", "description": "Updated information."},
            "reason": {"type": "string", "description": "Why this memory is being updated."},
            "concept": {
                "type": "string",
                "description": "Optional new label. Correct concepts encoding mutable state.",
            },
            "embedding": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Optional pre-computed embedding vector for the new version.",
            },
        },
        "required": ["id", "new_content", "reason"],
    },
}

REMEMBER_BATCH_SCHEMA = {
    "name": "muninn_remember_batch",
    "description": (
        "Store multiple memories at once (max 50). More efficient than repeated muninn_remember. "
        "Best practice: break complex topics into individual atomic memories."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "memories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "The information to remember."},
                        "concept": {"type": "string", "description": "Short label."},
                        "type": {"type": "string", "description": "Memory type."},
                        "type_label": {"type": "string", "description": "Free-form type label."},
                        "summary": {"type": "string", "description": "One-line summary."},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number"},
                        "created_at": {"type": "string"},
                        "entities": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "type": {"type": "string"},
                                },
                                "required": ["name", "type"],
                            },
                        },
                        "relationships": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "target_id": {"type": "string"},
                                    "relation": {"type": "string"},
                                    "weight": {"type": "number"},
                                },
                                "required": ["target_id", "relation"],
                            },
                        },
                        "entity_relationships": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "from_entity": {"type": "string"},
                                    "to_entity": {"type": "string"},
                                    "rel_type": {"type": "string"},
                                    "weight": {"type": "number"},
                                },
                                "required": ["from_entity", "to_entity", "rel_type"],
                            },
                        },
                        "embedding": {
                            "type": "array",
                            "items": {"type": "number"},
                        },
                    },
                    "required": ["content"],
                },
                "description": "Array of memories to store (max 50).",
            },
        },
        "required": ["memories"],
    },
}

CONTRADICTIONS_SCHEMA = {
    "name": "muninn_contradictions",
    "description": "Check for known contradictions in this vault.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

STATUS_SCHEMA = {
    "name": "muninn_status",
    "description": "Get health and capacity statistics for the vault.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

READ_SCHEMA = {
    "name": "muninn_read",
    "description": (
        "Fetch a single memory by its ID. Returns full content plus any caller-provided "
        "entities and entity relationships stored with the memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Memory ID (ULID)."},
        },
        "required": ["id"],
    },
}

CONSOLIDATE_SCHEMA = {
    "name": "muninn_consolidate",
    "description": "Merge multiple related memories into one. Archives the originals. Maximum 50 IDs.",
    "parameters": {
        "type": "object",
        "properties": {
            "ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "IDs of memories to merge (max 50).",
            },
            "merged_content": {"type": "string", "description": "Content for the consolidated memory."},
        },
        "required": ["ids", "merged_content"],
    },
}

RESTORE_SCHEMA = {
    "name": "muninn_restore",
    "description": "Recover a soft-deleted memory within the 7-day recovery window.",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "ID of the deleted memory to restore."},
        },
        "required": ["id"],
    },
}

LIST_DELETED_SCHEMA = {
    "name": "muninn_list_deleted",
    "description": "List soft-deleted memories still within the 7-day recovery window.",
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max results (default: 20, max: 100)."},
        },
        "required": [],
    },
}

STATE_SCHEMA = {
    "name": "muninn_state",
    "description": (
        "Transition a memory's lifecycle state. Valid states: "
        "planning, active, paused, blocked, completed, cancelled, archived."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "ID of the memory to update."},
            "state": {
                "type": "string",
                "enum": ["planning", "active", "paused", "blocked", "completed", "cancelled", "archived"],
                "description": "The new lifecycle state.",
            },
            "reason": {"type": "string", "description": "Optional: why the state is being changed."},
        },
        "required": ["id", "state"],
    },
}

SESSION_SCHEMA = {
    "name": "muninn_session",
    "description": "Get a summary of recent memory activity since a timestamp.",
    "parameters": {
        "type": "object",
        "properties": {
            "since": {"type": "string", "description": "ISO 8601 timestamp. Return activity after this time."},
        },
        "required": ["since"],
    },
}

# ── P1 — Knowledge graph tools ───────────────────────────────────────────

LINK_SCHEMA = {
    "name": "muninn_link",
    "description": (
        "Create or strengthen an association between two memories. "
        "Choose the most specific relation type: supports, contradicts, depends_on, "
        "supersedes, relates_to, is_part_of, causes, preceded_by, followed_by, "
        "created_by_person, belongs_to_project, references, implements, blocks, "
        "resolves, refines."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "source_id": {"type": "string", "description": "Source memory ID."},
            "target_id": {"type": "string", "description": "Target memory ID."},
            "relation": {"type": "string", "description": "Relationship type."},
            "weight": {"type": "number", "description": "Association weight 0.0-1.0 (default 0.8)."},
        },
        "required": ["source_id", "target_id", "relation"],
    },
}

TRAVERSE_SCHEMA = {
    "name": "muninn_traverse",
    "description": (
        "Explore the memory graph by following associations from a starting memory. "
        "Returns nodes and edges within the specified hop distance."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "start_id": {"type": "string", "description": "ID of the memory to start from."},
            "max_hops": {"type": "integer", "description": "Maximum BFS depth (default: 2, max: 5)."},
            "max_nodes": {"type": "integer", "description": "Max memories to return (default: 20, max: 100)."},
            "rel_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Filter to specific relation types.",
            },
            "follow_entities": {
                "type": "boolean",
                "description": "When true, BFS also traverses shared entity links (default: false).",
            },
        },
        "required": ["start_id"],
    },
}

DECIDE_SCHEMA = {
    "name": "muninn_decide",
    "description": "Record a decision with rationale and link it to supporting evidence.",
    "parameters": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "description": "The decision made."},
            "rationale": {"type": "string", "description": "Reasoning behind the decision."},
            "alternatives": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Other options that were considered.",
            },
            "evidence_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Memory IDs that support this decision.",
            },
        },
        "required": ["decision", "rationale"],
    },
}

EXPLAIN_SCHEMA = {
    "name": "muninn_explain",
    "description": (
        "Show the full score breakdown for why a specific memory would be returned "
        "for a given query. Use for debugging recall quality."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "engram_id": {"type": "string", "description": "ID of the memory to score-explain."},
            "query": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Context phrases to evaluate against.",
            },
            "embedding": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Optional pre-computed query embedding vector.",
            },
        },
        "required": ["engram_id", "query"],
    },
}

# ── P1 — Entity management tools ─────────────────────────────────────────

ENTITY_SCHEMA = {
    "name": "muninn_entity",
    "description": (
        "Returns the full aggregate view for a named entity: metadata, "
        "engrams mentioning it, relationships, and co-occurring entities."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Entity name (case-insensitive)."},
            "limit": {"type": "integer", "description": "Max engrams to include (default: 20)."},
        },
        "required": ["name"],
    },
}

FIND_BY_ENTITY_SCHEMA = {
    "name": "muninn_find_by_entity",
    "description": (
        "Return all memories that mention a given named entity. "
        "Uses the entity reverse index for fast lookup."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "entity_name": {"type": "string", "description": "Entity name to look up."},
            "limit": {"type": "integer", "description": "Max results (1-50, default: 20)."},
        },
        "required": ["entity_name"],
    },
}

ENTITY_STATE_SCHEMA = {
    "name": "muninn_entity_state",
    "description": (
        "Set the lifecycle state of a named entity (active, deprecated, merged, resolved) "
        "and optionally correct its type. For state=merged, provide merged_into."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "entity_name": {"type": "string", "description": "Entity name to update."},
            "state": {
                "type": "string",
                "description": "New state: active, deprecated, merged, or resolved.",
            },
            "merged_into": {
                "type": "string",
                "description": "Canonical entity name (required when state=merged).",
            },
            "type": {
                "type": "string",
                "enum": _ENTITY_TYPE_ENUM,
                "description": "Correct the entity type. Omit to preserve existing.",
            },
        },
        "required": ["entity_name", "state"],
    },
}

ENTITY_STATE_BATCH_SCHEMA = {
    "name": "muninn_entity_state_batch",
    "description": (
        "Update lifecycle state for multiple entities in one call (max 50). "
        "Partial success supported — check per-item status."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "entity_name": {"type": "string", "description": "Entity name to update."},
                        "state": {"type": "string", "description": "New state."},
                        "merged_into": {"type": "string", "description": "Canonical entity (state=merged)."},
                        "type": {"type": "string", "enum": _ENTITY_TYPE_ENUM},
                    },
                    "required": ["entity_name", "state"],
                },
                "description": "Array of entity state operations (max 50).",
            },
        },
        "required": ["operations"],
    },
}

ENTITY_CLUSTERS_SCHEMA = {
    "name": "muninn_entity_clusters",
    "description": (
        "Return entity pairs that frequently co-occur in the same memories. "
        "Useful for discovering implicit relationships."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "min_count": {"type": "integer", "description": "Minimum co-occurrence count (default: 2)."},
            "top_n": {"type": "integer", "description": "Max pairs to return (default: 20)."},
        },
        "required": [],
    },
}

ENTITY_TIMELINE_SCHEMA = {
    "name": "muninn_entity_timeline",
    "description": (
        "Chronological view of when an entity first appeared and how it evolved. "
        "Shows all engrams mentioning the entity, sorted by creation time."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "entity_name": {"type": "string", "description": "Entity name to look up."},
            "limit": {"type": "integer", "description": "Max timeline entries (1-50, default: 10)."},
        },
        "required": ["entity_name"],
    },
}

SIMILAR_ENTITIES_SCHEMA = {
    "name": "muninn_similar_entities",
    "description": (
        "Find entity names that are likely duplicates based on trigram similarity. "
        "Use muninn_merge_entity to merge confirmed duplicates."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "threshold": {"type": "number", "description": "Min similarity 0.0-1.0 (default: 0.85)."},
            "top_n": {"type": "integer", "description": "Max pairs to return (default: 20)."},
        },
        "required": [],
    },
}

MERGE_ENTITY_SCHEMA = {
    "name": "muninn_merge_entity",
    "description": (
        "Merge entity_a into entity_b (canonical). Sets entity_a to merged state, "
        "relinks all engrams. Use dry_run=true to preview."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "entity_a": {"type": "string", "description": "Entity to merge away."},
            "entity_b": {"type": "string", "description": "Canonical entity to keep."},
            "dry_run": {"type": "boolean", "description": "Preview without writing (default: false)."},
        },
        "required": ["entity_a", "entity_b"],
    },
}

# ── P1 — Quality / Trust / Feedback ──────────────────────────────────────

TRUST_SCHEMA = {
    "name": "muninn_trust",
    "description": (
        "Set the trust level of an engram. Levels: verified (human-confirmed), "
        "inferred (AI-generated, default), external (imported), untrusted (unreliable)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "ULID of the engram to update."},
            "trust": {
                "type": "string",
                "enum": ["verified", "inferred", "external", "untrusted"],
                "description": "Trust level to assign.",
            },
        },
        "required": ["id", "trust"],
    },
}

FEEDBACK_SCHEMA = {
    "name": "muninn_feedback",
    "description": "Record explicit feedback on an engram. Updates learned scoring weights via SGD.",
    "parameters": {
        "type": "object",
        "properties": {
            "engram_id": {"type": "string", "description": "Engram ID that was retrieved."},
            "useful": {"type": "boolean", "description": "Whether the engram was helpful (default: false)."},
        },
        "required": ["engram_id"],
    },
}

# ── P1 — Enrichment pipeline ─────────────────────────────────────────────

GET_ENRICHMENT_CANDIDATES_SCHEMA = {
    "name": "muninn_get_enrichment_candidates",
    "description": (
        "Return active memories missing one or more enrichment stages so an external "
        "MCP agent can enrich them."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "stages": {
                "type": "array",
                "items": {"type": "string", "enum": ["entities", "relationships", "classification", "summary"]},
                "description": "Which stages to look for. Defaults to all four.",
            },
            "limit": {"type": "integer", "description": "Max candidates (default: 50, max: 200)."},
            "cursor": {"type": "string", "description": "Pagination cursor from previous call."},
        },
        "required": [],
    },
}

APPLY_ENRICHMENT_SCHEMA = {
    "name": "muninn_apply_enrichment",
    "description": (
        "Persist externally generated enrichment output for a single memory. "
        "Use after an MCP agent reads candidates and generates results."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "ID of the memory to update."},
            "expected_updated_at": {
                "type": "string",
                "description": "RFC3339Nano timestamp from candidate response. Prevents stale overwrites.",
            },
            "summary": {"type": "string", "description": "Generated summary."},
            "memory_type": {"type": "string", "description": "Generated memory type."},
            "type_label": {"type": "string", "description": "Generated free-form type label."},
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string", "enum": _ENTITY_TYPE_ENUM},
                        "confidence": {"type": "number"},
                    },
                    "required": ["name", "type"],
                },
                "description": "Extracted entities to persist.",
            },
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from_entity": {"type": "string"},
                        "to_entity": {"type": "string"},
                        "rel_type": {"type": "string"},
                        "weight": {"type": "number"},
                    },
                    "required": ["from_entity", "to_entity", "rel_type"],
                },
                "description": "Extracted entity relationships.",
            },
            "stages_completed": {
                "type": "array",
                "items": {"type": "string", "enum": ["entities", "relationships", "classification", "summary"]},
                "description": "Explicit stage list to mark complete even when output is empty.",
            },
            "source": {"type": "string", "description": "Provenance label (default: mcp_agent)."},
        },
        "required": ["id", "expected_updated_at"],
    },
}

RETRY_ENRICH_SCHEMA = {
    "name": "muninn_retry_enrich",
    "description": "Re-queue a memory for enrichment processing by active plugins.",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "ID of the memory to re-enrich."},
        },
        "required": ["id"],
    },
}

REPLAY_ENRICHMENT_SCHEMA = {
    "name": "muninn_replay_enrichment",
    "description": (
        "Re-run the enrichment pipeline for memories missing specific stages. "
        "Supports dry_run=true to preview. Returns processed/skipped/failed/remaining counts."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "stages": {
                "type": "array",
                "items": {"type": "string", "enum": ["entities", "relationships", "classification", "summary"]},
                "description": "Which stages to re-run. Defaults to all four.",
            },
            "limit": {"type": "integer", "description": "Max memories to process (default: 50, max: 200)."},
            "dry_run": {"type": "boolean", "description": "Scan only, don't enrich (default: false)."},
        },
        "required": [],
    },
}

# ── P2 — Audit / Debug / Export ──────────────────────────────────────────

PROVENANCE_SCHEMA = {
    "name": "muninn_provenance",
    "description": "Returns the ordered audit trail for an engram — who wrote it, what changed, and why.",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Engram ID (ULID)."},
        },
        "required": ["id"],
    },
}

EXPORT_GRAPH_SCHEMA = {
    "name": "muninn_export_graph",
    "description": (
        "Export the entity relationship graph as JSON-LD or GraphML. "
        "Nodes are named entities; edges are typed entity-to-entity relationships."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "enum": ["json-ld", "graphml"],
                "description": "Output format: 'json-ld' (default) or 'graphml'.",
            },
            "include_engrams": {
                "type": "boolean",
                "description": "Enrich entity types from entity record table (default: false).",
            },
        },
        "required": [],
    },
}

GUIDE_SCHEMA = {
    "name": "muninn_guide",
    "description": "Get instructions on how to use MuninnDB effectively. Call on first connect.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

# ── P2 — Hierarchical memory tools ───────────────────────────────────────

REMEMBER_TREE_SCHEMA = {
    "name": "muninn_remember_tree",
    "description": (
        "Store a nested hierarchy (project plan, task tree, outline) as linked engrams. "
        "Each node becomes a full engram. Returns root_id and node_map."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "root": {
                "type": "object",
                "properties": {
                    "concept": {"type": "string", "description": "Short label."},
                    "content": {"type": "string", "description": "Content."},
                    "type": {"type": "string", "description": "Memory type."},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "children": {
                        "type": "array",
                        "description": "Child nodes (recursive).",
                        "items": {"type": "object"},
                    },
                },
                "required": ["concept", "content"],
                "description": "Root node of the tree. Children are recursive.",
            },
        },
        "required": ["root"],
    },
}

RECALL_TREE_SCHEMA = {
    "name": "muninn_recall_tree",
    "description": (
        "Retrieve the complete ordered hierarchy rooted at root_id. "
        "Use after muninn_recall finds the root engram's ID."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "root_id": {"type": "string", "description": "ULID of the root engram."},
            "max_depth": {"type": "integer", "description": "Max recursion depth. 0=unlimited (default: 10)."},
            "limit": {"type": "integer", "description": "Max children per node. 0=no limit (default: 0)."},
            "include_completed": {"type": "boolean", "description": "Include completed nodes (default: true)."},
        },
        "required": ["root_id"],
    },
}

ADD_CHILD_SCHEMA = {
    "name": "muninn_add_child",
    "description": (
        "Add a single child node to an existing parent in a tree. "
        "Use for incremental tree updates without resending the whole tree."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "parent_id": {"type": "string", "description": "ULID of the parent engram."},
            "concept": {"type": "string", "description": "Short label for the new child."},
            "content": {"type": "string", "description": "Content for the new child."},
            "type": {"type": "string", "description": "Memory type."},
            "tags": {"type": "array", "items": {"type": "string"}},
            "ordinal": {"type": "integer", "description": "Explicit ordinal position. Omit to append."},
            "embedding": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Optional pre-computed embedding vector.",
            },
        },
        "required": ["parent_id", "concept", "content"],
    },
}

# ── P1 — Work-queue / lease (v0.8.0) ────────────────────────────────────

COMPARE_AND_SET_SCHEMA = {
    "name": "muninn_compare_and_set",
    "description": (
        "Atomically transition a memory's lifecycle state only if it currently matches "
        "an expected state (compare-and-set). Use to avoid clobbering concurrent transitions. "
        "Returns whether it applied and the current state/owner on conflict."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "ID of the memory to update."},
            "expect_state": {
                "type": "string",
                "enum": ["planning", "active", "paused", "blocked", "completed", "cancelled", "archived"],
                "description": "Only apply if the current state equals this. Omit to skip the guard.",
            },
            "set_state": {
                "type": "string",
                "enum": ["planning", "active", "paused", "blocked", "completed", "cancelled", "archived"],
                "description": "The new lifecycle state to set when the guard holds.",
            },
        },
        "required": ["id", "set_state"],
    },
}

CLAIM_SCHEMA = {
    "name": "muninn_claim",
    "description": (
        "Atomically claim an advisory ownership lease on a memory so a fleet of agents "
        "can treat vault memories as a work queue and avoid double-processing. "
        "Returns status: acquired, refreshed, reclaimed, or conflict."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "ID of the memory to claim."},
            "owner": {
                "type": "string",
                "description": "Stable holder identity, conventionally '{host}:{session}'.",
            },
            "ttl_secs": {
                "type": "integer",
                "description": "Lease duration in seconds. Goes stale after this without a refresh.",
            },
        },
        "required": ["id", "owner", "ttl_secs"],
    },
}

RELEASE_SCHEMA = {
    "name": "muninn_release",
    "description": (
        "Release an ownership lease held by owner, making the memory immediately "
        "visible to recall again. Idempotent: releasing an unleased memory is a no-op."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "ID of the memory to release."},
            "owner": {"type": "string", "description": "The holder identity used when claimed."},
        },
        "required": ["id", "owner"],
    },
}

# ---------------------------------------------------------------------------
# All schemas — 42 tools matching MuninnDB MCP server v0.8.0
# ---------------------------------------------------------------------------

ALL_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    # Core (3)
    SEARCH_SCHEMA,
    REMEMBER_SCHEMA,
    ENTITIES_SCHEMA,
    # P0 — Lifecycle (12)
    WHERE_LEFT_OFF_SCHEMA,
    FORGET_SCHEMA,
    EVOLVE_SCHEMA,
    REMEMBER_BATCH_SCHEMA,
    CONTRADICTIONS_SCHEMA,
    STATUS_SCHEMA,
    READ_SCHEMA,
    CONSOLIDATE_SCHEMA,
    RESTORE_SCHEMA,
    LIST_DELETED_SCHEMA,
    STATE_SCHEMA,
    SESSION_SCHEMA,
    # P1 — Knowledge graph (4)
    LINK_SCHEMA,
    TRAVERSE_SCHEMA,
    DECIDE_SCHEMA,
    EXPLAIN_SCHEMA,
    # P1 — Entity management (8)
    ENTITY_SCHEMA,
    FIND_BY_ENTITY_SCHEMA,
    ENTITY_STATE_SCHEMA,
    ENTITY_STATE_BATCH_SCHEMA,
    ENTITY_CLUSTERS_SCHEMA,
    ENTITY_TIMELINE_SCHEMA,
    SIMILAR_ENTITIES_SCHEMA,
    MERGE_ENTITY_SCHEMA,
    # P1 — Quality / Trust / Feedback (2)
    TRUST_SCHEMA,
    FEEDBACK_SCHEMA,
    # P1 — Enrichment (4)
    GET_ENRICHMENT_CANDIDATES_SCHEMA,
    APPLY_ENRICHMENT_SCHEMA,
    RETRY_ENRICH_SCHEMA,
    REPLAY_ENRICHMENT_SCHEMA,
    # P2 — Audit / Export / Guide (3)
    PROVENANCE_SCHEMA,
    EXPORT_GRAPH_SCHEMA,
    GUIDE_SCHEMA,
    # P2 — Hierarchical memory (3)
    REMEMBER_TREE_SCHEMA,
    RECALL_TREE_SCHEMA,
    ADD_CHILD_SCHEMA,
    # P1 — Work-queue / lease (3, v0.8.0)
    COMPARE_AND_SET_SCHEMA,
    CLAIM_SCHEMA,
    RELEASE_SCHEMA,
]


def get_tool_schemas(priority_filter: str = "all") -> List[Dict[str, Any]]:
    """Return tool schemas filtered by priority tier.

    Args:
        priority_filter: One of 'core', 'p0', 'p0-p1', 'p0-p2', 'all'.
            - 'core': 3 essential tools (search, remember, entities)
            - 'p0': core + 12 P0 lifecycle tools = 15 tools
            - 'p0-p1': core + P0 + 21 P1 tools = 36 tools
            - 'all' or 'p0-p2': all 42 tools (default)
    """
    _CORE = {id(SEARCH_SCHEMA), id(REMEMBER_SCHEMA), id(ENTITIES_SCHEMA)}
    _P0 = {
        id(WHERE_LEFT_OFF_SCHEMA), id(FORGET_SCHEMA), id(EVOLVE_SCHEMA),
        id(REMEMBER_BATCH_SCHEMA), id(CONTRADICTIONS_SCHEMA), id(STATUS_SCHEMA),
        id(READ_SCHEMA), id(CONSOLIDATE_SCHEMA), id(RESTORE_SCHEMA),
        id(LIST_DELETED_SCHEMA), id(STATE_SCHEMA), id(SESSION_SCHEMA),
    }
    _P1 = {
        id(LINK_SCHEMA), id(TRAVERSE_SCHEMA), id(DECIDE_SCHEMA), id(EXPLAIN_SCHEMA),
        id(ENTITY_SCHEMA), id(FIND_BY_ENTITY_SCHEMA), id(ENTITY_STATE_SCHEMA),
        id(ENTITY_STATE_BATCH_SCHEMA), id(ENTITY_CLUSTERS_SCHEMA),
        id(ENTITY_TIMELINE_SCHEMA), id(SIMILAR_ENTITIES_SCHEMA), id(MERGE_ENTITY_SCHEMA),
        id(TRUST_SCHEMA), id(FEEDBACK_SCHEMA),
        id(GET_ENRICHMENT_CANDIDATES_SCHEMA), id(APPLY_ENRICHMENT_SCHEMA),
        id(RETRY_ENRICH_SCHEMA), id(REPLAY_ENRICHMENT_SCHEMA),
        id(COMPARE_AND_SET_SCHEMA), id(CLAIM_SCHEMA), id(RELEASE_SCHEMA),
    }
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
            # Pass through new fields if provided
            for key in ("concept", "type_label", "tags", "confidence", "created_at",
                        "entities", "relationships", "entity_relationships", "op_id", "embedding"):
                if key in args:
                    mcp_args[key] = args[key]
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
