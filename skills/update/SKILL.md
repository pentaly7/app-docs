---
name: update
description: Report drift between the existing app docs in /docs and the current code, then fix only the affected sections (new flows added, removed flows marked, renamed files followed). Only touches apps that are already documented; use generate to document new apps. The User Guide is humanized with the humanizer-indonesia skill. Add "drawio" (or run the draw.io skill first) to redraw changed diagrams with draw.io, and "fsm" to add state machine sections to every documented app (remembered for later runs).
argument-hint: "[drawio] [fsm]"
disable-model-invocation: true
---

# Update app docs

Arguments: `$ARGUMENTS`

The narrow version of `generate`: it never creates docs for apps that aren't documented yet. Use it after a batch of code changes, when you want to see and fix drift without bootstrapping anything new.

## Steps

1. Read `<this skill's base directory>/../../shared/references/pipeline.md` and `.../state-schema.md`.

2. No `docs/.docgen/state.json` → tell the user to run `/app-docs:generate` first, and stop.

3. Preflight, diagram mode, layout engine, `fsm` and humanizer (pipeline §2–3). In draw.io mode without a layout engine, stop here with the install instructions.

4. Run `TOOL drift --repo REPO` and show the **drift report** first, compact:

   ```
   payment-api   4 stale sections   (internal/service/payment.go modified, internal/handler/refund.go deleted)
   order-worker  up to date
   New apps not documented: web/admin → run /app-docs:generate
   ```

   - Plugin upgrades (template, diagrams, stories, humanizer) run only if the user accepted the upgrade plan in preflight (pipeline §2 step 7, §4).
   - `missing_app_state` → mention them and suggest generate. Don't bootstrap them here.
   - Apps whose stage isn't `done` → resume them per the pipeline table.
   - Apps with `fsm` newly turned on by this run → update with "FSM newly enabled: yes".

5. For each app with stale sections, run the update row of pipeline §4: app-documenter `update` for app-level sections and new or removed flows, a flow-documenter per stale or new important flow, assemble, goldfish on the changed sections, doc-fixer, the humanizer step on the changed User Guide sections, validate. At most 5 agents at a time, `state.json` written after every stage change.

6. Final report (pipeline §6), plus the list of apps that were already up to date.

Then the line about syncing in a new conversation (pipeline §7). Don't commit.
