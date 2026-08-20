---
name: coding
description: >
  Safely inspect, propose, and validate workspace code changes under sandbox and confirmation constraints.
version: 1.1.0
---

# Workflow

Read relevant files before proposing a modification. Explain files, risks, and test
commands before requesting `mcp.write_workspace_file`. Never modify .env, .git,
or dependency credentials. Run only `mcp.run_python_in_sandbox` after approval.

## How to use

- Read files with `filesystem.read_text` or `mcp.read_workspace_file`.
- Check a Python file with `mcp.run_skill_script` using
  `{"skill_name":"coding","arguments":{"path":"app/main.py"}}`.
- Write or rename files only after human confirmation.

## Output

The script returns JSON with `status`, `functions`, and `classes`.
