# MuninnDB — Knowledge Graph Memory Plugin for Hermes Agent

Persistent semantic memory via MuninnDB knowledge graph with entity tracking,
hierarchical organization, enrichment pipeline, work-queue leases, and
automatic turn syncing via MCP streamable-http transport.

**42 tools** synced with MuninnDB v0.8.0.

## Quick Install (for Hermes Agent)

If you are a Hermes agent reading this, follow these steps to install or update:

### 1. Verify MuninnDB MCP server is reachable

```bash
curl -s -m 5 -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  http://MUNINNDB_HOST:8750/mcp | python3 -c "
import json, sys
d = json.load(sys.stdin)
tools = d.get('result', {}).get('tools', [])
print(f'MCP server returned {len(tools)} tools')
"
```

Expected: 42 tools. If 0 or connection refused, MuninnDB server needs starting.

### 2. Check plugin is in place

```bash
ls -la /opt/data/plugins/memory/muninndb/__init__.py
```

If missing, copy from the repo (see Development section).

### 3. Verify MCP config in config.yaml

```bash
grep -A2 'muninndb:' /opt/data/config.yaml
```

Must include `type: streamable-http`:
```yaml
mcp_servers:
  muninndb:
    type: streamable-http            # ← REQUIRED — without this, 0 tools load
    url: http://MUNINNDB_HOST:8750/mcp
```

### 4. Verify memory provider config

```bash
grep -A4 'memory:' /opt/data/config.yaml
```

Must include:
```yaml
memory:
  provider: muninndb
  memory_enabled: true
```

### 5. Verify muninndb is in platform toolsets

```bash
grep 'muninndb' /opt/data/config.yaml
```

Should appear under `platform_toolsets.cli` and `platform_toolsets.discord`.

### 6. Restart gateway to reload

```bash
hermes restart
```

### 7. Verify tools are loaded

After restart, search for muninn tools:
- Use `tool_search(query="muninn")` — should return 40+ matches
- Use `mcp_muninndb_muninn_status()` — should return vault health

### 8. If something is wrong

Check logs:
```bash
hermes logs | grep -i muninndb
```

Common issues:
- **0 tools loaded**: Missing `type: streamable-http` in mcp_servers config
- **Circuit breaker open**: MuninnDB server is down or unreachable
- **Tools stale**: Gateway not restarted after config change

## Features

- Semantic search with cross-vault recall (profile vault + base vault)
- Automatic turn storage (sync_turn) after each agent turn
- Entity extraction and relationship tracking
- Knowledge graph navigation and traversal
- Hierarchical memory organization (tree storage + recall)
- Enrichment pipeline for memory quality (entities, relationships, classification, summary)
- Work-queue leases for multi-agent coordination (claim/compare-and-set/release)
- Circuit breaker resilience for MCP failures
- Session-aware with per-profile vault scoping
- 42 tools synced with MuninnDB v0.8.0

## Manual Installation (for Humans)

### 1. Copy plugin files

```bash
mkdir -p /opt/data/plugins/memory/muninndb
cp __init__.py plugin.yaml config.py tools.py circuit_breaker.py mcp_client.py formatter.py lifecycle.py \
   /opt/data/plugins/memory/muninndb/
```

### 2. Configure connection

Option A — `muninndb.json` in Hermes home:
```bash
cat > ~/.hermes/muninndb.json << 'EOF'
{
  "mcp_url": "http://MUNINNDB_HOST:8750/mcp"
}
EOF
```

Option B — `config.yaml` mcp_servers section (preferred):
```yaml
mcp_servers:
  muninndb:
    type: streamable-http
    url: http://MUNINNDB_HOST:8750/mcp
```

Option C — environment variable:
```bash
export MUNINNDB_MCP_URL=http://MUNINNDB_HOST:8750/mcp
```

Priority: `muninndb.json` > `config.yaml` mcp_servers > env var.

### 3. Set memory provider

In `config.yaml`:
```yaml
memory:
  provider: muninndb
  memory_enabled: true
```

### 4. Add to platform toolsets

In `config.yaml` under `platform_toolsets`:
```yaml
platform_toolsets:
  cli:
    - muninndb
  discord:
    - muninndb
```

### 5. Restart

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
| `skip_patterns` | Base skip patterns for turn filtering | (built-in) |
| `skip_patterns_extra` | Additional user-extensible skip patterns | `[]` |
| `tool_priority_filter` | Tool families: core/p0/p0-p1/all | `all` |
| `enable_audit_tools` | Enable P2 audit/debug tools | `false` |

### Optional Authentication

```bash
export MUNINNDB_MCP_TOKEN=your_token_here
```

## Tool Reference (42 tools)

### Core Memory (3)

| Tool | Purpose |
|------|---------|
| `muninn_search` | Semantic search (cross-vault wrapper around muninn_recall) |
| `muninn_remember` | Store a memory — supports entities, relationships, entity_relationships, tags, confidence, embedding |
| `muninn_entities` | List entities, filterable by state |

### P0 — Lifecycle (12)

| Tool | Purpose |
|------|---------|
| `muninn_where_left_off` | Session resumption — recently accessed memories |
| `muninn_forget` | Soft-delete a memory |
| `muninn_evolve` | Update memory (new version, archive old) |
| `muninn_remember_batch` | Atomic batch store (max 50) |
| `muninn_contradictions` | Find conflicting knowledge |
| `muninn_status` | Vault health summary |
| `muninn_read` | Fetch single memory by ID |
| `muninn_consolidate` | Merge multiple memories into one |
| `muninn_restore` | Recover soft-deleted memory (7-day window) |
| `muninn_list_deleted` | List recoverable deleted memories |
| `muninn_state` | Lifecycle state transitions (planning→active→completed→archived) |
| `muninn_session` | Activity summary since timestamp |

### P1 — Knowledge Graph (4)

| Tool | Purpose |
|------|---------|
| `muninn_link` | Create typed relationship (16 relation types, weight) |
| `muninn_traverse` | Graph BFS from a starting memory |
| `muninn_decide` | Record decision with rationale + evidence IDs |
| `muninn_explain` | Score breakdown for debugging recall quality |

### P1 — Entity Management (8)

| Tool | Purpose |
|------|---------|
| `muninn_entity` | Full aggregate view (entity + memories + relationships) |
| `muninn_find_by_entity` | Find all memories mentioning an entity |
| `muninn_entity_state` | Entity lifecycle state (active/deprecated/merged/resolved) |
| `muninn_entity_state_batch` | Batch entity state updates (max 50) |
| `muninn_entity_clusters` | Co-occurring entity pairs |
| `muninn_entity_timeline` | Entity chronological evolution |
| `muninn_similar_entities` | Find duplicate entities (trigram similarity) |
| `muninn_merge_entity` | Merge duplicate entities (dry_run supported) |

### P1 — Quality / Trust / Feedback (2)

| Tool | Purpose |
|------|---------|
| `muninn_trust` | Set trust level (verified/inferred/external/untrusted) |
| `muninn_feedback` | SGD feedback on recall quality |

### P1 — Enrichment (4)

| Tool | Purpose |
|------|---------|
| `muninn_get_enrichment_candidates` | Find memories missing enrichment stages |
| `muninn_apply_enrichment` | Persist externally-generated enrichment |
| `muninn_retry_enrich` | Re-queue memory for enrichment |
| `muninn_replay_enrichment` | Re-run enrichment pipeline (dry_run supported) |

### P1 — Work-Queue / Lease (3) — v0.8.0

| Tool | Purpose |
|------|---------|
| `muninn_compare_and_set` | Atomic state transition with guard (CAS) |
| `muninn_claim` | Claim ownership lease (acquired/refreshed/reclaimed/conflict) |
| `muninn_release` | Release ownership lease (idempotent) |

### P2 — Audit / Export / Guide (3)

| Tool | Purpose |
|------|---------|
| `muninn_provenance` | Audit trail for an engram |
| `muninn_export_graph` | Export entity graph (json-ld/graphml) |
| `muninn_guide` | Agent usage instructions |

### P2 — Hierarchical Memory (3)

| Tool | Purpose |
|------|---------|
| `muninn_remember_tree` | Store nested hierarchy as linked engrams |
| `muninn_recall_tree` | Retrieve complete ordered hierarchy |
| `muninn_add_child` | Add single child to existing tree node |

## How It Works

### Automatic Behaviors

1. **Prefetch** — Before each turn, semantic search surfaces relevant memories
2. **Turn Sync** — After each turn, key facts stored as observations
3. **Memory Mirror** — Built-in `memory()` writes mirrored to MuninnDB
4. **Session End** — Flushes insights + consolidates ≥3 observations via `muninn_consolidate`
5. **Delegation Tracking** — Subagent task+result recorded for continuity

### Vault Scoping

- Default profile: `hermes`
- Named profile: `hermes_<profile_name>`
- Cross-vault search: profile vault + base vault merged, deduplicated by score

### Tool Priority Filtering

Use `tool_priority_filter` to control token overhead:
- `core` — 3 essential tools
- `p0` — Core + P0 lifecycle (15 tools)
- `p0-p1` — Core + P0 + P1 (36 tools)
- `all` — All 42 tools (default)

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| 0 tools loaded | Missing `type: streamable-http` | Add to mcp_servers config |
| Circuit breaker open | MuninnDB server down | Start/restart MuninnDB |
| Tools stale | Gateway not restarted | `hermes restart` |
| No memories returned | Wrong vault or empty | Check `muninn_status()` |

## Development

```bash
git clone https://github.com/madeinoz67/hermes-memory-muninndb
cd hermes-memory-muninndb
ln -sf $(pwd) /opt/data/plugins/memory/muninndb
hermes restart
```

## License

MIT
