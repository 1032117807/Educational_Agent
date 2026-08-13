# Cross-Client Agent Runtime

`app/agent_runtime/catalog.py` is the single capability manifest shared by the
desktop client and the SaaS/Web client. Tool definitions and Skill names are
shared. Execution is not.

| Target | Used by | Execution boundary |
| --- | --- | --- |
| `cloud_sandbox` | Web and desktop | Per-tenant sandbox workspace and restricted container |
| `desktop_companion` | Desktop, or a Web session explicitly linked to a running desktop companion | User's local workspace and local MCP server |

The Web API must never use `desktop_companion` against the SaaS host. To make a
web conversation operate on a user's computer, the desktop app needs an
authenticated companion connection that claims only that user's tool calls and
returns streamed tool events. This preserves the same Agent/Skill/MCP protocol
without giving a shared server host-file permissions.

The current SaaS implementation automatically exposes tenant learning data.
The next implementation step is a `cloud_sandbox` service that provisions a
per-session writable workspace, invokes the existing `learning_agent_mcp.py`
tools inside that sandbox, and publishes tool events into the existing SSE
conversation stream.
