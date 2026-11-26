---
type: llm
focus: trace
weight: 1
---

`.app-docs-workspace.json` in the parent folder lists the repos as `db-service`, `group/wallet`, `shop` in that order, with `calls` showing shop → wallet and wallet → db-service. In the transcript, db-service's app-documenter is launched before shop's.
