# Hermes Memory Plugin — MuninnDB

A [Hermes Agent](https://github.com/nousresearch/hermes-agent) memory plugin that provides cross-session semantic memory via [MuninnDB](https://github.com/scrypster/muninndb) knowledge graph.

## Features

- **Semantic Recall** — prefetches relevant memories before each turn using vector similarity search
- **Automatic Turn Syncing** — stores valuable conversation turns to the knowledge graph after each turn
- **Memory Write Mirroring** — mirrors Hermes built-in `memory` tool writes to MuninnDB
- **Entity Extraction** — tracks named entities and relationships across conversations
- **Cross-Vault Search** — searches both profile-scoped and base vaults with deduplication
- **Circuit Breaker** — gracefully handles MuninnDB server outages without blocking conversations
- **Profile-Scoped Vaults** — separate memory spaces per Hermes profile (e.g., `hermes_coder`, `hermes_researcher`)

## Prerequisites

1. **Hermes Agent** installed and working
2. **MuninnDB** server running and accessible (see [MuninnDB docs](https://github.com/scrypster/muninndb))
3. Python `requests` library (usually already available in Hermes venv)

## Installation

### 1. Copy the plugin to Hermes plugins directory

```bash
# Create the plugin directory if it doesn't exist
mkdir -p ~/.hermes/plugins/memory/muninndb

# Copy plugin files
cp __init__.py ~/.hermes/plugins/memory/muninndb/
cp plugin.yaml ~/.hermes/plugins/memory/muninndb/
```

Or if Hermes is installed at a custom location (e.g., `/opt/data`):

```bash
mkdir -p /opt/data/plugins/memory/muninndb
cp __init__.py /opt/data/plugins/memory/muninndb/
cp plugin.yaml /opt/data/plugins/memory/muninndb/
```

### 2. Configure the MCP connection

Create a `muninndb.json` in your Hermes home directory:

```bash
cat > ~/.hermes/muninndb.json << 'EOF'
{
  "mcp_url": "http://YOUR_MUNINNDB_HOST:8750/mcp",
  "vault_prefix": "hermes"
}
EOF
```

Or if using `/opt/data` as Hermes home:

```bash
cat > /opt/data/muninndb.json << 'EOF'
{
  "mcp_url": "http://10.0.0.150:8750/mcp",
  "vault_prefix": "hermes"
}
EOF
```

### 3. Restart Hermes

```bash
hermes restart
# or restart the gateway if running as a service
```

## Configuration

The plugin reads configuration from `muninndb.json` in the Hermes home directory. All fields are optional except `mcp_url`.

| Key | Description | Default |
|-----|-------------|---------|
| `mcp_url` | MuninnDB MCP server URL (e.g. `http://10.0.0.150:8750/mcp`) | **required** |
| `vault_prefix` | Vault name prefix for memory scoping | `hermes` |
| `activate_limit` | Max memories returned per prefetch | `10` |
| `activate_min_score` | Minimum relevance score (0.0–1.0) for recall | `0.3` |
| `prefetch_context_tokens` | Token budget for prefetch context block | `800` |
| `trivial_message_min_words` | Skip sync for messages shorter than this | `5` |
| `circuit_breaker_threshold` | Consecutive failures before circuit opens | `5` |
| `circuit_breaker_timeout_s` | Seconds before circuit half-opens for retry | `60` |
| `request_timeout_s` | HTTP request timeout in seconds | `15.0` |

### Alternative Configuration Methods

**Via `config.yaml` (mcp_servers section):**

```yaml
mcp_servers:
  muninndb:
    url: http://10.0.0.150:8750/mcp
```

**Via environment variable:**

```bash
export MUNINNDB_MCP_URL=http://10.0.0.150:8750/mcp
```

Priority order: `muninndb.json` > `config.yaml` mcp_servers > `MUNINNDB_MCP_URL` env var.

### Optional Authentication

If your MuninnDB server requires a Bearer token:

```bash
export MUNINNDB_MCP_TOKEN=your_token_here
```

## Usage

Once installed and configured, the plugin registers three tools automatically:

### `muninn_search` — Semantic Memory Search

```
muninn_search(query="email triage configuration")
```

Searches across long-term memory using semantic similarity. Returns ranked memories with relevance scores.

**Parameters:**
- `query` (required) — What to search for
- `limit` — Max results (default: 10)
- `mode` — Recall mode: `semantic`, `recent`, `balanced` (default), `deep`

### `muninn_remember` — Store Memory

```
muninn_remember(content="User prefers concise responses", memory_type="preference")
```

Persists a fact, preference, decision, or observation to long-term memory.

**Parameters:**
- `content` (required) — The information to remember
- `memory_type` — One of: `fact`, `decision`, `observation`, `preference`, `issue`, `task`, `procedure`, `event`, `goal`, `constraint` (default: `fact`)
- `summary` — One-line summary

### `muninn_entities` — List Knowledge Graph Entities

```
muninn_entities(limit=20)
```

Lists known entities in the knowledge graph, sorted by mention count.

**Parameters:**
- `limit` — Max results (default: 20)

## How It Works

### Automatic Behaviors

The plugin operates transparently alongside Hermes' built-in memory:

1. **Prefetch** — Before each user message, the plugin searches MuninnDB for relevant memories and injects them as context into the system prompt.

2. **Turn Sync** — After each conversation turn, valuable exchanges are automatically stored as observations. Short messages, system notes, and test messages are filtered out.

3. **Memory Mirror** — When the agent uses the built-in `memory` tool (add/replace/remove), the write is mirrored to MuninnDB as a `fact` or `preference`.

4. **Pre-Compress** — Before context window compression, key facts from messages about to be dropped are stored as compressed observations.

5. **Delegation** — Subagent task delegation results are recorded as `task` type memories.

### Vault Scoping

Memories are scoped by vault name:
- Default profile: `hermes`
- Named profile: `hermes_<profile_name>` (e.g., `hermes_coder`)

Cross-vault search automatically includes the base vault when querying a profile vault.

### Circuit Breaker

If MuninnDB becomes unreachable, the circuit breaker opens after 5 consecutive failures and retries after 60 seconds. This prevents the plugin from blocking conversations during outages.

## Troubleshooting

### Plugin not loading

Check Hermes logs for errors:
```bash
hermes logs | grep -i muninn
```

### No memories being recalled

1. Verify MuninnDB is running: `curl http://YOUR_HOST:8750/mcp`
2. Check the MCP URL in `muninndb.json`
3. Ensure MuninnDB has stored memories (use `muninn_entities` to check)

### Circuit breaker stuck open

The circuit breaker auto-recovers after `circuit_breaker_timeout_s` seconds (default: 60). To force a restart, restart Hermes.

## Development

```bash
# Clone the repo
git clone https://github.com/madeinoz67/hermes-memory-muninndb.git
cd hermes-memory-muninndb

# Link into Hermes for live development
ln -sf $(pwd) /opt/data/plugins/memory/muninndb

# Restart Hermes to pick up changes
hermes restart
```

## License

MIT
