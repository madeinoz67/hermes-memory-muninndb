# Changelog

All notable changes to the MuninnDB Hermes plugin are documented here.

## [0.12.0] — 2026-08-21

### Added

- **Kanban workflow vault auto-detection** — Plugin automatically detects kanban task context via `HERMES_KANBAN_TASK` env var and creates a shared workflow vault. Sibling tasks (same parent) share the same vault for cross-task memory.
- **Dual-client architecture** — Separate MCPClient instances for workflow vault (scoped `cap_` token) and main vault (`mk_` key). No token switching, fully concurrency-safe for parallel workflows.
- **Workflow-to-main consolidation** — At session end, all workflow vault memories are consolidated into the main (profile) vault. Workflow vault auto-evaporates via TTL.
- **Cross-vault recall** — Prefetch and recall search both workflow vault and main vault, merging results.
- **`workflow_vault_ttl_hours` config option** — TTL for auto-created workflow vaults (default: 72h).
- **`MCPClient.set_token()` method** — For programmatic token switching (utility, not used in main flow).

### Changed

- Cross-vault recall now routes through workflow-aware vault list when in kanban mode.
- `LifecycleHooks` gains `set_workflow_vault()`, `get_recall_vaults()`, and `_consolidate_workflow_to_main()`.
- Plugin docstring updated to reflect v0.11.0 sync and 44 tools.

## [0.9.0] — 2026-07-21

### Added

- **`muninn_create_workflow_vault`** — New tool for creating shared workflow vaults with scoped capability tokens (RFC #597). Creates `wf-*` prefixed vaults with the `working` preset (7-day auto-evaporation, multi-user enabled). Requires `MUNINN_AGENT_VAULT_CREATE=1` on the MuninnDB server and a full-mode `mk_` key.
- **9 new params on `muninn_search`** — `threshold`, `profile` (traversal profiles: causal/confirmatory/adversarial/structural), `since`, `before`, `tags_all`, `tags_any`, `tag_filter` (key:value prefix range filtering), `embedding` (pre-computed query vector), `annotate` (staleness/conflict metadata).
- `vault` param on `muninn_trust` — allows targeting a specific vault when setting trust levels.

### Changed

- Tool count: 42 → 43 (matches MuninnDB MCP server v0.9.0).
- `muninn_search` mode descriptions expanded with per-mode threshold defaults.
- `muninn_trust` description updated to mention `ExcludeUntrusted` vault config.
- README updated with authentication section, workflow vault docs, and v0.9.0 tool count.
- Auth config now documented in `config.yaml` headers (preferred) alongside env var fallback.

### Fixed

- `SEARCH_SCHEMA` was missing 9 of 14 server params — `threshold`, `profile`, `since`, `before`, `tags_all`, `tags_any`, `tag_filter`, `embedding`, `annotate` were not exposed to the LLM.
- `TRUST_SCHEMA` was missing `vault` param — could not target non-default vaults.

## [0.8.0] — 2026-07-13

### Added

- **Work-queue lease tools** — `muninn_claim`, `muninn_compare_and_set`, `muninn_release` for multi-agent coordination with advisory ownership leases.
- `caller` and `include_leased` params on `muninn_search` for lease-aware recall filtering.
- `muninn_entity_state` param rename: `name` → `entity_name`, added `merged_into` for state=merged.
- `muninn_entity_state_batch` for batch entity state updates (max 50).
- `muninn_export_graph` `include_engrams` param for enriched entity types.
- `muninn_replay_enrichment` `dry_run` and `limit` params.
- `muninn_get_enrichment_candidates` `cursor` and `limit` params for pagination.
- `muninn_apply_enrichment` full schema: `entities`, `memory_type`, `relationships`, `source`, `stages_completed`, `summary`, `type_label`.
- `muninn_evolve` `embedding` param for pre-computed vectors.
- `muninn_explain` `embedding` param for accurate semantic scores.
- `muninn_traverse` `follow_entities` param for entity-hop BFS traversal.
- `muninn_state` `reason` param for state change justification.
- `muninn_claim` `ttl_secs` param for lease duration.
- `muninn_consolidate` `merged_content` param (renamed from generic items).

### Changed

- Tool count: 39 → 42.
- `muninn_find_by_entity` now supports fuzzy entity resolution (token overlap matching).

## [0.7.0] — 2026-06-15

### Added

- Initial plugin release with 39 MCP tools.
- Cross-vault semantic search (profile vault + base vault merge).
- Automatic turn storage and session-end consolidation.
- Entity extraction and relationship tracking.
- Hierarchical memory (tree storage + recall).
- Enrichment pipeline integration.
- Circuit breaker resilience.
- Tool priority filtering (core/p0/p0-p1/all).
