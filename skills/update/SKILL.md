---
name: update
description: Report drift between the existing app docs in /docs and the current code, then fix only the affected sections (new flows added, removed flows marked, renamed files followed). Only touches apps that are already documented, in the current repository or in every repository of a workspace folder; use generate to document new apps. The User Guide is humanized with the humanizer-indonesia skill. Add "drawio" (or run the draw.io skill first) to redraw changed diagrams with draw.io, "fsm" to add state machine sections to every documented app (remembered for later runs), and "max-apps N" to start at most N apps.
argument-hint: "[drawio] [fsm] [max-apps N]"
disable-model-invocation: true
model: sonnet
---

# Update app docs

Arguments: `$ARGUMENTS`

The narrow version of `generate`: it never creates docs for apps or repos that aren't documented yet (it lists them, so you can run generate). Use it after a batch of code changes.

## Steps

1. Read `<this skill's base directory>/../../shared/references/pipeline.md` §1–3, and nothing else from references.
2. Run `PIPE start --command update` with the flags the arguments call for (pipeline §1).
3. Act on each action as pipeline §2 says, until `done` or `stop`. The report lists stale sections fixed, apps already up to date stay out of it.
