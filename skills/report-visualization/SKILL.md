---
name: report-visualization
description: Generate local, evidence-based charts for learning reports. Use when a learning report needs charts for practice accuracy, task completion, study time, or knowledge-point mastery, and when visual report evidence must remain on the user's device.
---

# Report Visualization

Create charts only from program-calculated `LearningStats`; never invent, smooth,
or overwrite values. Render locally to SVG in the app data directory.

## Workflow

1. Render an overview chart for practice accuracy, task completion, and study minutes.
2. Render a knowledge-point mastery chart, emphasizing lower mastery values.
3. Embed the local chart paths in the Markdown report and retain the numeric report text.
4. State when a metric has no data instead of drawing a misleading chart.

## Constraints

- Do not send learning data to a third-party chart service.
- Do not use charts as a replacement for evidence, citations, or numeric values.
- Use `app.services.report_visualization.ReportVisualizationService` for report charts.
