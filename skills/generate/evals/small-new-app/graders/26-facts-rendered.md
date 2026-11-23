---
type: llm
focus: trace
weight: 1
---

docs/.docgen/facts/<app-id>.json exists, every table and list in both guides that facts-schema.md lists (configuration, flow index, storage, log index, metrics, alerts, owners, glossary, per-flow errors, side effects and "Jika gagal") sits between docgen:render markers, and `docs_tool.py render --check` reports nothing stale.
