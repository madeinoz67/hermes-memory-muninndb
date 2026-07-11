# MuninnDB — Knowledge Graph Memory Plugin for Hermes Agent

Persistent semantic memory via MuninnDB knowledge graph with entity tracking,
hierarchical organization, enrichment pipeline, and automatic turn syncing.
Connects to a MuninnDB MCP server over streamable-http transport.

## Features

- Semantic search with cross-vault recall
- Automatic turn storage (sync_turn) after each agent turn
- Entity extraction and relationship tracking
- Knowledge graph navigation and traversal
- Hierarchical memory organization (parent/child)
- Enrichment pipeline for memory quality
- Circuit breaker resilience for MCP failures
- Session-aware with per-profile vault scoping
- 33 tools covering lifecycle, knowledge graph, entity management, quality, audit, and enrichment

## Prerequisites

1. **Hermes Agent** installed and working
2. **MuninnDB MCP server** running and accessible (https://github.com/scrypster/muninndb)
3. Python `requests` library (usually already available in Hermes venv)

## Installation

### 1. Copy the plugin to Hermes plugins directory

```bash
mkdir -p ~/.hermes/plugins/memory/muninndb
cp __init__.py plugin.yaml config.py tools.py circuit_breaker.py mcp_client.py formatter.py lifecycle.py ~/.hermes/plugins/memory/muninndb/
```

Or if Hermes is installed at a custom location:

```bash
mkdir -p /opt/data/plugins/memory/muninndb
cp __init__.py plugin.yaml config.py tools.py circuit_breaker.py mcp_client.py formatter.py lifecycle.py /opt/data/plugins/memory/muninndb/
```

### 2. Configure the connection

Create a `muninndb.json` in your Hermes home directory:

```bash
cat > ~/.hermes/muninndb.json << 'EOF'
{
  "mcp_url": "http://YOUR_HOST:8750/mcp"
}
EOF
```

### 3. Restart Hermes

```bash
hermes restart
```

## Configuration

| Key | Description | Default |
|-----|-------------|---------|
| `mcp_url` | MuninnDB MCP server URL | **required** |
| `vault_prefix` | Vault name prefix | `hermes` |
| `activate_limit` | Max memories per prefetch | `10` |
| `activate_min_score` | Min relevance score 0-1 | `0.3` |
| `prefetch_context_tokens` | Token budget for prefetch output | `800` |
| `trivial_message_min_words` | Skip sync for short messages | `5` |
| `circuit_breaker_threshold` | Failures before opening circuit | `5` |
| `circuit_breaker_timeout_s` | Seconds before half-open | `60` |
| `request_timeout_s` | HTTP request timeout | `15.0` |
| `skip_patterns` | Base skip patterns for turn filtering | `[]` |
| `skip_patterns_extra` | Additional user-extensible skip patterns | `[]` |
| `tool_priority_filter` | Tool families to expose: all/p0/p0-p1/p0-p2 | `all` |
| `enable_audit_tools` | Enable P2 audit/debug tools | `false` |

### Alternative Configuration Methods

**Via `config.yaml` (mcp_servers section):**

```yaml
mcp_servers:
  muninndb:
    url: http://YOUR_HOST:8750/mcp
```

**Via environment variable:**

```bash
export MUNINNDB_MCP_URL=http://YOUR_HOST:8750/mcp
```

Priority order: `muninndb.json` > `config.yaml` mcp_servers > env var.

### Optional Authentication

```bash
export MUNINNDB_MCP_TOKEN=your_token_here
```

## Tool Reference (33 tools)

### Core Memory (3)

#### `muninn_search` — Semantic search across MuninnDB long-term memory

```
muninn_search(query="project architecture")
```

**Parameters:**
- `query` (required) — What to search for
- `limit` — Max results (default: 10)
- `mode` — Recall mode: semantic, recent, balanced, deep (default: balanced)

#### `muninn_remember` — Persist a fact, preference, decision, or observation

```
muninn_remember(content="Project uses pytest for testing", memory_type="fact")
```

**Parameters:**
- `content` (required) — The information to remember
- `memory_type` — Type: fact, decision, observation, preference, issue, task, procedure, event, goal, constraint, ephemeral, milestone (default: fact)
- `summary` — One-line summary

#### `muninn_entities` — List known entities sorted by mention count

```
muninn_entities(limit=20)
```

**Parameters:**
- `limit` — Max results (default: 20)

### P0 — Lifecycle (6)

#### `muninn_where_left_off` — Session resumption with recent memories

```
muninn_where_left_off()
```

**Parameters:**
- `limit` — Max recent memories (default: 10)

#### `muninn_forget` — Soft-delete a memory by ID

```
muninn_forget(id="mem_abc123")
```

**Parameters:**
- `id` (required) — Memory ID to forget
- `reason` — Optional reason for deletion

#### `muninn_evolve` — Update memory content without creating duplicates

```
muninn_evolve(id="mem_abc123", content="Updated content")
```

**Parameters:**
- `id` (required) — Memory ID to update
- `content` (required) — New content
- `reason` — Optional reason for update

#### `muninn_remember_batch` — Atomic multi-memory storage

```
muninn_remember_batch(memories=[{"content": "fact 1"}, {"content": "fact 2"}])
```

**Parameters:**
- `memories` (required) — Array of memory objects, each with `content` and optional `type`, `summary`, `entities`

#### `muninn_contradictions` — Find conflicting memories

```
muninn_contradictions()
```

**Parameters:**
- `limit` — Max pairs to return (default: 10)

#### `muninn_status` — Vault health summary

```
muninn_status()
```

### P1 — Knowledge Graph (4)

#### `muninn_link` — Create typed relationship between memories

```
muninn_link(source_id="mem_a", target_id="mem_b", relation="supports")
```

**Parameters:**
- `source_id` (required) — Source memory ID
- `target_id` (required) — Target memory ID
- `relation` (required) — Relationship type (e.g. supports, contradicts, derived_from)

#### `muninn_merge` — Consolidate fragmented observations

```
muninn_merge(source_ids=["mem_a", "mem_b"], target_content="Unified content")
```

**Parameters:**
- `source_ids` (required) — IDs of memories to merge
- `target_content` (required) — Consolidated content

#### `muninn_traverse` — Explore memory graph from a starting point

```
muninn_traverse(start_id="mem_abc123", direction="both", max_depth=3)
```

**Parameters:**
- `start_id` (required) — Starting memory ID
- `direction` — forward, backward, both (default: both)
- `max_depth` — Maximum traversal depth (default: 3)

#### `muninn_decide` — Record a decision with rationale

```
muninn_decide(decision="Use SQLite", rationale="Simpler for self-hosted")
```

**Parameters:**
- `decision` (required) — The decision made
- `rationale` (required) — Why it was made
- `alternatives` — Alternatives considered but not chosen

### P1 — Entity Management (8)

#### `muninn_find_entity` — Fast entity lookup by name

**Parameters:** `name` (required) — Entity name

#### `muninn_entity_snapshot` — Full aggregate entity view

**Parameters:** `name` (required) — Entity name

#### `muninn_entity_versions` — Entity evolution over time

**Parameters:** `name` (required) — Entity name

#### `muninn_entity_clusters` — Discover implicit entity relationships

**Parameters:** `top_n` — Number of top clusters (default: 20)

#### `muninn_similar_entities` — Find potential duplicate entities

No required parameters.

#### `muninn_merge_entity` — Deduplicate entity names

**Parameters:** `source` (required), `target` (required) — Source merges into target

#### `muninn_entity_state` — Entity lifecycle state transitions

**Parameters:** `name` (required), `state` (required: active/archived/merged), `type` (optional)

#### `muninn_forget_entity` — Remove entity from knowledge graph

**Parameters:** `name` (required), `cascade` — Also delete associated memories (default: false)

### P1 — Quality Assurance (3)

#### `muninn_classify` — Classify memory confidence level

**Parameters:** `id` (required), `classification` (required: verified/inferred/untrusted)

#### `muninn_trust` — Set trust level on a memory

**Parameters:** `id` (required), `level` (required: verified/inferred/untrusted)

#### `muninn_feedback` — Signal recall usefulness for relevance tuning

**Parameters:** `query` (required), `memory_ids` (required), `useful` (required)

### P2 — Audit & Debug (4)

#### `muninn_audit_trail` — Change history for a memory

```
muninn_audit_trail(id="mem_abc123")
```

**Parameters:** `id` (required) — Memory ID to get audit trail for

#### `muninn_debug_recall` — Explain why recall returned specific results

```
muninn_debug_recall(query="project architecture")
```

**Parameters:** `query` (required), `limit` — Max results to analyze (default: 5)

#### `muninn_vault_health` — Detailed vault health diagnostics

```
muninn_vault_health()
```

No required parameters. Returns memory count, storage size, index health, enrichment stats.

#### `muninn_export_graph` — Export entity graph

```
muninn_export_graph(format="json")
```

**Parameters:** `format` — Output format: json or dot (default: json)

### P2 — Hierarchical Memory (3)

#### `muninn_parent` — Set parent memory for hierarchy

```
muninn_parent(child_id="mem_child", parent_id="mem_parent")
```

**Parameters:** `child_id` (required), `parent_id` (required)

#### `muninn_child` — Set child memory for hierarchy

```
muninn_child(parent_id="mem_parent", child_id="mem_child")
```

**Parameters:** `parent_id` (required), `child_id` (required)

#### `muninn_level` — Navigate memory hierarchy

```
muninn_level(id="mem_abc123", direction="up")
```

**Parameters:** `id` (required), `direction` (required: up/down)

### P2 — Enrichment Pipeline (2)

#### `muninn_get_enrichment_candidates` — Find memories missing enrichment stages

```
muninn_get_enrichment_candidates()
```

No required parameters. Returns list of memory IDs with missing enrichment stages.

#### `muninn_replay_enrichment` — Run enrichment pipeline on memories

```
muninn_replay_enrichment(ids=["mem_a", "mem_b"])
```

**Parameters:** `ids` — Memory IDs to enrich. If omitted, enriches all candidates.

## How It Works

### Automatic Behaviors

1. **Prefetch** — Before each turn, performs semantic search to surface relevant memories from the vault
2. **Turn Sync** — After each turn, stores key facts as observations automatically
3. **Memory Mirror** — Built-in `memory()` tool writes are mirrored to MuninnDB
4. **Session End** — On `/new`, `/reset`, or session expiry, flushes remaining insights
5. **Delegation Tracking** — Subagent task+result pairs are recorded for continuity

### Vault Scoping

- Default profile: `hermes`
- Named profile: `hermes_<profile_name>`
- Cross-vault search: profile vault + base vault merged, deduplicated by score

### Circuit Breaker

The plugin uses a circuit breaker to prevent cascading failures when the MCP server is unavailable:
- **Closed** (normal): All requests pass through
- **Open** (tripped): After N consecutive failures, all requests return error immediately
- **Half-open**: After timeout, allows one probe request to test recovery

### Tool Priority Filtering

Use `tool_priority_filter` in config to control which tool families are exposed:
- `all` — All 33 tools (default)
- `p0` — Only core + P0 lifecycle (9 tools)
- `p0-p1` — Core + P0 + P1 (24 tools)
- `p0-p2` — Same as `all` (33 tools)

Audit tools (audit_trail, debug_recall, vault_health, export_graph) are additionally gated by `enable_audit_tools` and default to off.

## Troubleshooting

### Plugin not loading

```bash
hermes logs | grep -i muninndb
```

### Not working as expected

1. Verify MuninnDB MCP server is running: `curl http://YOUR_HOST:8750/mcp`
2. Check the MCP URL in muninndb.json or config.yaml
3. Ensure `type: streamable-http` is set in mcp_servers config
4. Restart Hermes after config changes

### Tools not appearing

1. Check `tool_priority_filter` setting
2. Verify `enable_audit_tools` is `true` if audit tools are missing
3. Gateway restart required — tool list is frozen at session start

## Development

```bash
git clone https://github.com/madeinoz67/hermes-memory-muninndb
cd hermes-memory-muninndb
ln -sf $(pwd) ~/.hermes/plugins/memory/muninndb
hermes restart
```

## License

MIT
