---
name: error-diagnosis
description: >
  Diagnose learner mistakes from recorded evidence and propose focused review without changing records automatically.
version: 1.1.0
---

# Workflow

Diagnose incorrect answers from the question, learner response, standard answer,
and recorded evidence. Explain the likely misconception and propose a focused
review task without changing mastery or review records without confirmation.

## How to use

Run the objective comparison script with `mcp.run_skill_script`:

`{"skill_name":"error-diagnosis","arguments":{"expected":"A","response":"B"}}`

It returns `correct`, `expected`, and `response`. Use the result together with
the question explanation before suggesting a review task.
