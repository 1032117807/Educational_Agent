# Learning Plan

Version: 1.0.0

Build plans from objective course progress, remaining time, recent study time,
knowledge mastery, and task completion. Produce drafts first and require human
confirmation before writing learning tasks.

## How to use

Estimate a daily load with `mcp.run_skill_script`:

`{"skill_name":"learning-plan","arguments":{"remaining_minutes":600,"remaining_days":10,"minimum_minutes":20}}`

The script returns `daily_minutes`; use it only for a plan draft and request
confirmation before creating tasks.
