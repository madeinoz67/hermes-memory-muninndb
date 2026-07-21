# Post-Install Setup

The MuninnDB plugin files are installed. Complete these steps to activate it:

## 1. Set as memory provider

```bash
hermes memory setup
```

Select **muninndb** from the provider list.

## 2. Configure MuninnDB connection

Create the config file with your MuninnDB server URL:

```bash
cat > ~/.hermes/muninndb.json << 'EOF'
{
  "mcp_url": "http://YOUR_MUNINNDB_HOST:8750/mcp"
}
EOF
```

Replace `YOUR_MUNINNDB_HOST` with your MuninnDB server address.

## 3. Restart gateway

```bash
hermes gateway restart
```

## 4. Verify

```bash
hermes memory status
```

Should show `muninndb` as active and available.

## Optional: Authentication (for workflow vaults)

If you need workflow vaults, add your MuninnDB API key:

```yaml
# In config.yaml under mcp_servers:
mcp_servers:
  muninndb:
    type: streamable-http
    url: http://YOUR_MUNINNDB_HOST:8750/mcp
    headers:
      Authorization: Bearer mk_<your_key>
```

See the full README for all configuration options.
