---
type: llm
focus: trace
weight: 1
---

For one state machine, every place in the code that writes its state field (assignments, UPDATE statements, library calls, cron jobs) appears as a transition in its table, with trigger, guard and path:line.
