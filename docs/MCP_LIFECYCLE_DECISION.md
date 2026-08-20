# MCP Connection Lifecycle Decision

## Decision

Keep the local stdio MCP gateway isolated per tool call. This is a deliberate
lifecycle policy, not an omitted optimization.

Each call receives a new process, one-time approval token, workspace boundary,
and cancellation scope. Reusing a client session would require a process-wide
approval-token model and lifecycle cleanup for cancellation, which would weaken
the existing per-action confirmation boundary unless a more complex server-side
session protocol is introduced and independently reviewed.

## Measurement

Run the read-only benchmark from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_mcp_gateway.py --runs 5
```

It reports median, mean and maximum latency for the actual gateway startup,
MCP initialization and a workspace read. It does not invoke write, code or
network tools.

Reference run on 2026-08-14 (Windows development environment, 3 runs):
`median_ms=852.8`, `mean_ms=1001.4`, `max_ms=1328.2`. These values are a
baseline for this machine, not a production SLA.

## Revisit Gate

Reconsider a pooled connection only when the measured per-call latency becomes
a user-visible bottleneck and the replacement preserves all of these invariants:

- fresh, server-verified approval for every mutating action;
- per-call cancellation that cannot cancel another tenant or Agent run;
- no workspace/environment data leakage across calls;
- deterministic shutdown on UI cancellation and application exit;
- benchmark and security regression coverage before enabling it behind a flag.
