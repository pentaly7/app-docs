---
name: generate
description: Generate or refresh the Dev Guide (English) and User Guide (Bahasa Indonesia) for every app in the current git repository, or in every repository of a workspace folder (repos one or two folders below), writing to each repo's /docs. Fresh docs for undocumented apps, a drift update for documented ones, plugin upgrades only when the user accepts them, and resume after an interrupted run. The User Guide is humanized with the humanizer-indonesia skill. Add "drawio" (or run the draw.io skill first) to draw auto-arranged diagrams with draw.io instead of Mermaid, "fsm" to detect and document state machines (remembered for later runs), and "max-apps N" to start at most N apps in this run.
argument-hint: "[drawio] [fsm] [max-apps N]"
disable-model-invocation: true
model: sonnet
---

# Generate app docs

Arguments: `$ARGUMENTS`

This is the main command. It works out what each app needs, so running it again is always safe:

| Situation | What happens |
|---|---|
| No `docs/.docgen/state.json` | Detect apps (you confirm which candidates are apps) → fresh docs for all |
| App left unfinished by an earlier run | Resume at the step it stopped |
| App `done`, but its code changed since its sections' commits | Update the stale sections |
| New app found in the repo | Fresh docs for it |
| The plugin's template, diagram, story or humanizer rules are newer than the repo's | Ask first, with a token estimate. Yes → extend, regenerate, redraw, restory or re-humanize. No → only real drift is fixed |
| Run from a folder of repos (a workspace) | All of the above for every repo, callees first, in one run |
| Everything up to date | Say so and stop |

## Steps

1. Read `<this skill's base directory>/../../shared/references/pipeline.md` §1–3, and nothing else from references.
2. Run `PIPE start --command generate` with the flags the arguments call for (pipeline §1).
3. Act on each action as pipeline §2 says, until `done` or `stop`.

The user already asked for the run, so don't ask for approval before starting.
