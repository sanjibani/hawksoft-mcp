# hawksoft-mcp

**Model Context Protocol (MCP) server for [HawkSoft](https://www.hawksoft.com/) Insurance Agency Management.**

Talk to your HawkSoft data from Claude, Cursor, or any MCP client — read clients, policies, and claims, and write back log notes, attachments, and receipts in plain English.

Built against the [HawkSoft Partner API v3.0](https://partner.hawksoft.app/v3/api.html). No existing MCP for HawkSoft — this is the first.

---

## What you can do with it

```
You:  "Show me every HawkSoft client modified since Monday and group them by carrier."

Claude:  *calls list_changed_clients, then get_client for each, then summarises*

You:  "Find the policy POR83741 and log a phone call with the insured about their renewal."

Claude:  *searches by policy → opens client → calls create_log_note with channel=5*
```

Other things agents do well with this server:

- Pre-call briefs — pull the client's full history (policies, claims, prior conversations) before a phone call
- Auto-document carrier touchpoints — every email/phone with a carrier becomes a structured log note
- Batch activity reporting — "give me a weekly summary of every client I called"
- Certificate of insurance / declaration page intake — attach PDFs straight into the right client record
- Reconciliation help — surface clients with outstanding invoices, draft follow-ups

---

## Install

```bash
pip install -e .
```

Or just use `uv` / `pipx` if you prefer.

---

## Configure

You need HawkSoft Partner API credentials — username + password issued by HawkSoft after your app is approved through their [Partner Program](https://www.hawksoft.com/about/partners/).

```bash
export HAWKSOFT_USERNAME="your-vendor-username"
export HAWKSOFT_PASSWORD="your-vendor-password"
```

You can also drop these in a `.env` file (see `.env.example`).

### Who uses this server?

Two audiences:

1. **Approved HawkSoft API Partners** building tools for independent agencies. Your vendor credentials work directly.
2. **Independent agencies** doing their own custom integration work. HawkSoft has explicitly opened this path — see the [V3.0 launch post](https://blog.hawksoft.com/partner-api-3.0):

   > "any agencies who build their own custom API integrations" can use the V3.0 Partner API directly.

   If you're an agency and don't have vendor credentials yet, email `opportunities@hawksoft.com` to get set up.

---

## Use with Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "hawksoft": {
      "command": "hawksoft-mcp",
      "env": {
        "HAWKSOFT_USERNAME": "your-vendor-username",
        "HAWKSOFT_PASSWORD": "your-vendor-password"
      }
    }
  }
}
```

Restart Claude Desktop. You should see 9 new tools + 1 resource (`hawksoft://channels`).

## Use with Claude Code

```bash
claude mcp add hawksoft -- hawksoft-mcp \
  --env HAWKSOFT_USERNAME=your-user --env HAWKSOFT_PASSWORD=your-pass
```

## Use with Cursor

Add a new MCP server in Cursor settings pointing at the `hawksoft-mcp` command with the same env vars.

---

## Tools

| Tool | Type | What it does |
| --- | --- | --- |
| `list_agencies` | Read | List agency IDs that have subscribed to your vendor app |
| `list_offices` | Read | List offices for a given agency |
| `list_changed_clients` | Read | Incremental sync — clients changed since a timestamp |
| `get_client` | Read | Full client record (details, people, contacts, claims, policies) |
| `get_clients_bulk` | Read | Fetch up to 200 clients in one call |
| `search_client_by_policy` | Read | Find a client by exact policy number |
| `create_log_note` | Write | Add a log note + optional follow-up task |
| `create_attachment` | Write | Attach a base64 file (PDF / image / doc) to a client |
| `create_receipts` | Write | Record one or more payments against invoices |
| `list_channels_tool` | Reference | All 56 HawkSoft LogAction codes |

Plus one resource:

| URI | Description |
| --- | --- |
| `hawksoft://channels` | Full channel catalog (value / label / category) |

---

## Common patterns

### Pre-call brief

```
User:  I'm about to call client 4231. Give me the full picture.
Agent: list_changed_clients(agency_id=1, as_of="2020-01-01")
       → [4231, ...]
       get_client(agency_id=1, client_id=4231)
       → returns details, policies, people, prior claims
       summarise: 2 personal auto policies, 1 umbrella, no recent claims, last contact 2 weeks ago about a billing question...
```

### Document a phone call after it happens

```
User:  I just got off a call with the Johnsons about their renewal. Auto policy. Renewal looks good, they want to add a teenage driver next month.
Agent: search_client_by_policy(agency_id=1, policy_number="AUTO-7741")
       → finds client
       create_log_note(
           agency_id=1,
           client_id=client_id,
           channel="Phone From Insured",
           description="Renewal discussion; wants to add teen driver next month",
           body="Discussed upcoming renewal. Customer satisfied with current rate. Mentioned adding a teenage driver in ~30 days. Set follow-up task for CSR to send driver addition intake form.",
           task_title="Send teen driver intake form",
           task_description="Customer mentioned adding teenage driver to auto policy next month. Send standard intake form.",
           task_due_date="2026-07-15",
           task_assigned_to_role="CSR",
       )
```

### End-of-day activity digest

```
User:  What did I do with clients today?
Agent: create_log_note(...) for each touchpoint during the day,
       then for the digest: get_clients_bulk(client_numbers=[recent_ids])
       and summarise.
```

---

## Channel catalog

Channels use friendly names everywhere in the API — never the integer. `Phone From Insured`, `Email To Carrier`, etc. The full 56-entry catalog is exposed via the `list_channels_tool` tool and the `hawksoft://channels` resource.

---

## API coverage

| HawkSoft endpoint | MCP tool |
| --- | --- |
| `GET /vendor/agencies` | `list_agencies` |
| `GET /vendor/agency/{id}/offices` | `list_offices` |
| `GET /vendor/agency/{id}/clients` | `list_changed_clients` |
| `GET /vendor/agency/{id}/client/{id}` | `get_client` |
| `POST /vendor/agency/{id}/clients` | `get_clients_bulk` |
| `GET /vendor/agency/{id}/clients/search` | `search_client_by_policy` |
| `POST /vendor/agency/{id}/client/{id}/log` | `create_log_note` |
| `POST /vendor/agency/{id}/client/{id}/attachment` | `create_attachment` |
| `POST /vendor/agency/{id}/client/{id}/receipts` | `create_receipts` |

Full HawkSoft Partner API v3.0 docs: <https://partner.hawksoft.app/v3/api.html>

---

## Development

```bash
# install with dev deps
pip install -e ".[dev]"

# run tests
pytest

# run server locally (stdio)
hawksoft-mcp
```

## Security & audit logging

Every tool call emits a structured JSONL audit record (one JSON object per
line) to stderr by default. Each record has:

```
ts, tool, request_id, args, result_size, is_error, error_type, duration_ms
```

Sensitive fields are redacted before logging: `password`, `api_key`, `token`,
`access_token`, `refresh_token`, `authorization`, `client_secret`. Long string
values are truncated to 256 characters.

To redirect to a file (e.g. for shipping to your log aggregator), set:

```bash
export HAWKSOFT_MCP_AUDIT_LOG=/var/log/hawksoft-mcp/audit.jsonl
hawksoft-mcp
```

The audit log is fail-open: if the configured file cannot be opened (missing
directory, permission denied), records fall back to stderr and the tool still
returns its result.

If you don't have HawkSoft credentials yet, the client will raise a clear error on first call — the server doesn't try to connect at import time.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Contributing

Issues + PRs welcome. Two things that always help:

1. **More tools.** If you spot a HawkSoft endpoint we missed (or one that needs a friendlier wrapper), open an issue.
2. **Better prompts.** The most useful thing you can share is a real example of an insurance workflow this helped you with — we collect these in `/examples`.

---

## See also

- [HawkSoft Partner API V3.0 docs](https://partner.hawksoft.app/v3/api.html)
- [HawkSoft partner program](https://www.hawksoft.com/about/partners/)
- [Model Context Protocol spec](https://modelcontextprotocol.io)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)