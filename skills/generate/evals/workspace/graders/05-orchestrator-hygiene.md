---
type: llm
focus: trace
weight: 1
---

The orchestrator ran `pipeline.py` (start, answer/apps, done, next) and nothing else from the plugin's scripts: it never ran `docs_tool.py` itself, never read the services' Go code, and never edited `docs/`, a `state.json` or the run file. It printed the report from the final `done` action, which has a block per service and a spend line.
