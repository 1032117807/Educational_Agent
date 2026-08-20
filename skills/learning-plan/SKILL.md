---
name: learning-plan
description: >
  Create evidence-based learning-plan drafts from goals, available time, mastery, and task progress.
version: 1.1.0
---

# Workflow

Build plans from objective course progress, remaining time, recent study time,
knowledge mastery, and task completion. Produce drafts first and require human
confirmation before writing learning tasks.

## How to use

Estimate a daily load with `mcp.run_skill_script`:

`{"skill_name":"learning-plan","arguments":{"remaining_minutes":600,"remaining_days":10,"minimum_minutes":20}}`

The script returns `daily_minutes`; use it only for a plan draft and request
confirmation before creating tasks.
