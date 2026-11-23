---
name: generate
description: Generate or refresh the Dev Guide (English) and User Guide (Bahasa Indonesia) for every app in the current git repository, writing to /docs. Fresh docs for undocumented apps, a drift update for documented ones, plugin upgrades only when the user accepts them, and resume after an interrupted run. The User Guide is humanized with the humanizer-indonesia skill. Add "drawio" (or run the draw.io skill first) to draw auto-arranged diagrams with draw.io instead of Mermaid, and "fsm" to detect and document state machines in every app (remembered for later runs).
argument-hint: "[drawio] [fsm]"
disable-model-invocation: true
---

# Generate app docs

Arguments: `$ARGUMENTS`

This is the main command. It works out what each app needs, so running it again is always safe:

| Situation | What happens |
|---|---|
| No `docs/.docgen/state.json` | Detect apps → fresh docs for all |
| App stage not `done` | Resume from its stage |
| App `done`, but its code changed since its sections' commits | Update the stale sections |
| New app found in the repo | Fresh docs for it |
| The plugin's template, diagram, story or humanizer rules are newer than the repo's | Ask first, with a token estimate (pipeline §2 step 6). Yes → extend, regenerate, redraw, restory or re-humanize as the plan says. No → only real drift is fixed |
| Everything up to date | Say so and stop |

## Steps

1. Read `<this skill's base directory>/../../shared/references/pipeline.md` and `.../state-schema.md`. Follow pipeline.md for paths, preflight, diagram mode, stages, agent prompts and the final report.

2. Preflight, diagram mode, layout engine, `fsm` and humanizer (pipeline §2–3). In draw.io mode without a layout engine, stop here with the install instructions.

3. **Build the plan.**

   **No state yet:** run `TOOL detect --repo REPO`. Every candidate is an app (backends, frontends, workers, CLIs, libraries), with frontend and backend always separate apps. Drop only:
   - containers that hold no code of their own (a `package.json` with `workspaces` whose packages are listed separately, a Maven `<packaging>pom</packaging>` aggregator), and
   - tooling nested inside another app (for example a `package.json` that only runs linters inside a Go service).

   Guess `kind` from the hints. Write `state.json` with `template_version`, `humanizer_version`, `diagram_version` and `story_version` from meta, `fsm` per app (true when the arguments contain `fsm`), `split_all` from detect, every app at `stage: "pending"`, and `docmost: {}`.

   **State exists:** run `TOOL drift --repo REPO`:
   - Stale sections → the app gets the update branch.
   - `new_app_candidates` → add them as `pending`, filtered as above. Recompute `split_all` (more than 10 apps → true). If it flips to true, every documented app needs regeneration in split mode: ask as for an upgrade, with the same token estimate per app.
   - `missing_app_state` → reset to `pending`.
   - Version changes are handled only through the upgrade plan the user accepted in preflight (pipeline §4 maps its actions to stages). If they declined, ignore `template_changed`, `diagram_changed`, `story_changed` and `humanizer_changed` for this run.

4. Show the plan in a few lines (each app with its action, the diagram mode, the humanizer used, whether the tree is dirty), then start. The user already asked for the run, so don't wait for approval.

5. Run the per-app pipeline (pipeline §4–5): the app-level agent, then one flow agent per important flow, assembled by script. At most 5 agents at a time across all apps, `state.json` written after every stage change.

6. Final report (pipeline §6), then the sync and CI questions (pipeline §7).

## Notes

- Don't commit or push. The user reviews the diff under `docs/` and commits.
- Don't read application source yourself. Agents do that in their own context, which is what lets this scale to large monorepos.
- If the user interrupts and runs `/app-docs:generate` again, the stages in `state.json` pick up where you stopped.
