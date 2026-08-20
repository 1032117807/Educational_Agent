---
name: resource-analysis
description: >
  Analyze locally imported resources with source references and create knowledge drafts rather than final records.
version: 1.1.0
---

# Workflow

Analyze only locally imported course resources. Summarize evidence with source
references, distinguish facts from inference, and create knowledge-point drafts
instead of writing final learning data directly.

## How to use

Run the inspection script with `mcp.run_skill_script`:

`{"skill_name":"resource-analysis","arguments":{"path":"workspace-file.txt"}}`

`path` is a relative project-workspace text file. The script returns character
count, non-empty line count, and a short evidence preview.
