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
It also exposes the same durable Agent actions used by the desktop client:
creating goals, generating plan/report jobs, creating resumable workflows and
saving confirmed memories. They share the `TOOL_CATALOG` action names,
confirmation requirement and `AgentToolCall` audit trail. The cloud executor
uses tenant-scoped data and a per-session workspace; the desktop executor uses
the local database/workspace under the same capability contract.

`desktop.*` tools are shown to both clients but remain linked-client
capabilities. In Web they are queued for the requested `companion_id`; a
browser cannot access a local disk or run local code unless the signed-in
desktop companion polls, executes and returns that call.
