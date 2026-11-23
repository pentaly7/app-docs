---
type: llm
focus: trace
weight: 1
---

The Dev Guide marks a Contradiction for the README's claim that vouchers live in a Postgres table, and describes the real storage: one JSON file, vouchers.json in DATA_DIR, rewritten through a temp file and a rename.
