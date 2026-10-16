# AI agents over MCP

OpenNexus is also an [MCP](https://modelcontextprotocol.io) server. Claude Code,
Cursor, Codex or any MCP client can connect to your workspace and do what you
do in the dashboard: read clients and agents, create and tune agents, load
knowledge, connect tools and test replies.

## Connect an agent

1. Open **Settings → AI agents** and click **Create token**. Name it after the
   machine that will use it. Tick **Read only** for a token that can list and
   read but never change anything or spend credit.
2. Copy the token: it is shown once and stored only as a SHA-256 hash.
3. Add the server to your client. The tab shows the snippet for each one:

```bash
claude mcp add --transport http opennexus https://app.your-agency.com/api/mcp --header "Authorization: Bearer onx_…"
```

Cursor (`.cursor/mcp.json`):

```json
{ "mcpServers": { "opennexus": { "url": "https://app.your-agency.com/api/mcp", "headers": { "Authorization": "Bearer onx_…" } } } }
```

## Tools

| Tool | Changes data | What it does |
|---|---|---|
| `list_clients`, `list_agents`, `get_agent` | no | Read the workspace; `get_agent` can include the system prompt. |
| `list_knowledge`, `list_agent_tools`, `list_models` | no | Knowledge documents and Q&A, connected tools, available models. |
| `create_client`, `create_agent`, `update_agent` | yes | The same validation as the dashboard. |
| `add_knowledge_text`, `add_qa` | yes | Text or Markdown knowledge (indexed for retrieval), exact answers. |
| `connect_tool` | yes | An HTTP endpoint or an MCP server the agent calls while answering. |
| `test_agent` | yes | A message as a customer; pass `conversation_id` to continue. Billed like any reply. |

Every tool calls the dashboard's own route as the token's owner, so ownership
checks and side effects are identical.

## Activity log and revocation

Every call is listed under **Activity log**: when, which token, which tool, its
arguments (long text shortened) and the outcome. **Revoke** a token the moment
you stop trusting the machine that holds it; it stops working immediately.

## Protocol

Streamable HTTP, stateless, JSON responses: `POST /api/mcp` with a JSON-RPC
message or batch. `initialize`, `ping`, `tools/list` and `tools/call` are
supported; notifications get `202`. A missing or revoked token gets `401`.
