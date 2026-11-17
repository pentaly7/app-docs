---
name: update
description: Report drift between the existing app docs in /docs and the current code, then fix only the affected sections (new flows added, removed flows marked, renamed files followed). Only touches apps that are already documented; use generate to document new apps. Add "drawio" to redraw changed diagrams with the draw.io skill, and "humanizer" to apply your installed humanizer skill on top of the built-in Indonesian one (or run those skills first in the same session).
argument-hint: "[drawio] [humanizer]"
disable-model-invocation: true
---

# Update app docs

Arguments: `$ARGUMENTS`

The narrow version of `generate`: it never creates docs for apps that aren't documented yet. Use it after a batch of code changes, when you want to see and fix drift without bootstrapping anything new.

## Steps

1. Read `<this skill's base directory>/../../shared/references/pipeline.md` and `.../state-schema.md`.

2. No `docs/.docgen/state.json` → tell the user to run `/app-docs:generate` first, and stop.

3. Preflight, diagram mode and humanizer (pipeline §2–3).

4. Run `TOOL drift --repo REPO` and show the **drift report** first, compact:

   ```
   payment-api   4 stale sections   (internal/service/payment.go modified, internal/handler/refund.go deleted)
   order-worker  up to date
   New apps not documented: web/admin → run /app-docs:generate
   ```

   - `template_changed` → say so. Every documented app gets regenerated (update mode, "Template changed: yes"), and `template_version` is set to current at the end.
   - `missing_app_state` → mention them and suggest generate. Don't bootstrap them here.
   - Apps whose stage isn't `done` → resume them per the pipeline table.

5. For each app with stale sections, run the update branch of the pipeline: app-documenter `update` → goldfish-reviewer limited to the changed sections → app-documenter `fix` → humanizer-id on the changed operator sections → validate. Up to 3 apps in parallel, `state.json` written after every stage change.

6. Final report (pipeline §6), plus the list of apps that were already up to date.

Don't commit. Mention `/app-docs:sync` if any app changed.
