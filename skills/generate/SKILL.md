---
name: generate
description: Generate or refresh the dev guide (English) and operator guide (Bahasa Indonesia) for every app in the current git repository, writing to /docs. Fresh docs for undocumented apps, a drift update for documented ones, a full regeneration when the plugin's template changed, and resume after an interrupted run. Add "drawio" to draw diagrams with the draw.io skill instead of Mermaid.
argument-hint: "[drawio]"
disable-model-invocation: true
---

# Generate app docs

Arguments: `$ARGUMENTS`

This is the main command. It works out what each app needs, so running it again is always safe:

| Situation | What happens |
|---|---|
| No `docs/.docgen/state.json` | Detect apps → fresh docs for all |
| `template_version` in state ≠ current | Full regeneration of every app (update mode, "Template changed: yes") |
| App stage not `done` | Resume from its stage |
| App `done`, but its code changed since its sections' commits | Update the stale sections |
| New app found in the repo | Fresh docs for it |
| Everything up to date | Say so and stop |

## Steps

1. Read `<this skill's base directory>/../../shared/references/pipeline.md` and `.../state-schema.md`. Follow pipeline.md for paths, preflight, diagram mode, stages, agent prompts and the final report.

2. Preflight and diagram mode (pipeline §2–3).

3. **Build the plan.**

   **No state yet:** run `TOOL detect --repo REPO`. Every candidate is an app (backends, frontends, workers, CLIs, libraries), with frontend and backend always separate apps. Drop only:
   - containers that hold no code of their own (a `package.json` with `workspaces` whose packages are listed separately, a Maven `<packaging>pom</packaging>` aggregator), and
   - tooling nested inside another app (for example a `package.json` that only runs linters inside a Go service).

   Guess `kind` from the hints. Write `state.json` with `template_version` from meta, `split_all` from detect, every app at `stage: "pending"`, and `docmost: {}`.

   **State exists:** run `TOOL drift --repo REPO` and apply the table above:
   - `template_changed` → every app gets update mode with "Template changed: yes". Apps without an app-state file get fresh mode. Set `template_version` to current **after** all apps finish, so an interrupted regeneration resumes as a regeneration.
   - `new_app_candidates` → add them as `pending`, filtered as above. Recompute `split_all` (more than 10 apps → true). If it flips to true, every documented app needs regeneration in split mode, so treat them like a template change.
   - `missing_app_state` → reset to `pending`.

4. Show the plan in a few lines (each app with its action, the diagram mode, whether the tree is dirty), then start. The user already asked for the run, so don't wait for approval.

5. Run the per-app pipeline (pipeline §4–5), up to 3 apps in parallel, writing `state.json` after every stage change.

6. Final report (pipeline §6).

## Notes

- Don't commit or push. The user reviews the diff under `docs/` and commits.
- Don't read application source yourself. Agents do that in their own context, which is what lets this scale to large monorepos.
- If the user interrupts and runs `/app-docs:generate` again, the stages in `state.json` pick up where you stopped.
