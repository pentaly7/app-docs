---
type: llm
focus: trace
weight: 1
---

Every draw.io diagram was produced from a JSON spec run through shared/scripts/diagram_layout.py (specs kept in docs/.docgen/.work/), never with hand-written coordinates; in each flowchart the happy path is one straight vertical column, error exits leave decisions sideways, and error paths that continue to a later step share one channel on the right.
