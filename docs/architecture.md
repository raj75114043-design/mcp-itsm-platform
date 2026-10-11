# Architecture

## Components
| Component | Module | Notes |
|---|---|---|
| Systems of record | `store.py` | Tables standing in for ITSM, CMDB, KB, on-call and monitoring APIs |
| Tool specs | `gateway/tools.py` | 15 tools with argument models, scope, risk class, `untrusted_output` |
| Policy pipeline | `gateway/registry.py`, `gateway/policy.py` | See ADR-0001 |
| MCP servers | `servers/build.py` | Generated FastMCP tools with full JSON Schemas and tool annotations (`readOnlyHint`, `destructiveHint`) |
| Agent | `agent/commander.py` | MCP client; deterministic reasoning; optional tool-less LLM summary |
| Console | `streamlit_app.py` | Commander, approvals, catalogue, playground, audit, evaluation |

## Transports and identity
* **Streamable HTTP** at `/mcp`: `Authorization: Bearer <token>` per request.
* **stdio**: token from `MCP_TOKEN` (one identity per process, as with desktop clients).
* **In-process** (agent, tests): token bound when the server is built.

## Data flow for one alert
`get_alert` → `get_ci` → `get_dependencies` → `search_incidents` (duplicate) → `list_changes` → (`get_ci` root) →
`search_kb` → `get_article` → `who_is_on_call` → `create_incident` | `add_work_note` → `page_engineer` (pending approval).
