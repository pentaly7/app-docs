# Pipeline (shared by `generate` and `update`)

You are the orchestrator. You never read application code yourself. You run the helper script, spawn agents, and own `docs/.docgen/state.json`. That keeps your context small enough for big monorepos.

## Contents
1. Paths
2. Preflight
3. Diagram mode and humanizer
4. Per-app pipeline and resume
5. Agent prompts
6. Final report

---

## 1. Paths

- `SHARED` = the `shared/` folder of this plugin: `<this skill's base directory>/../../shared`. Resolve it to an absolute path once and pass it to every agent.
- `TOOL` = `python3 <SHARED>/scripts/docs_tool.py`
- `REPO` = `git rev-parse --show-toplevel` from the current directory.

## 2. Preflight

1. Not inside a git repo → stop and say so. Provenance and drift both need git.
2. Run `TOOL meta --repo REPO`. Keep the JSON (`sha`, `short_sha`, `branch`, `dirty`, `date`, `user`).
3. If `dirty` is true, warn in one line ("Uncommitted changes: sections will be marked `+ uncommitted changes`") and continue.
4. Make sure `docs/.docgen/.gitignore` exists and contains `.work/`.

## 3. Diagram mode and humanizer

### Diagram mode

The draw.io skill has `disable-model-invocation`, so you can't load it with the Skill tool. Use draw.io mode only when the user asked for it in this run:
- the arguments contain `drawio`, or
- the draw.io skill's instructions are already in this conversation (a "Base directory for this skill: …drawio…" header).

Then:
1. Find the skill folder. Use the base directory if it was shown. Otherwise take the first folder with a `SKILL.md` among `~/.claude/skills/*drawio*`, `REPO/.claude/skills/*drawio*`, `~/.agents/skills/*drawio*`, `~/.claude/plugins/**/skills/*drawio*`.
2. Check the CLI: `drawio --version`, `draw.io --version`, or `/Applications/draw.io.app/Contents/MacOS/draw.io --version`.
3. If both checks pass, the mode is `drawio` with `DRAWIO_SKILL=<folder>`. Otherwise the mode is `mermaid`. Tell the user why in one line ("draw.io CLI not found — using Mermaid"), so they don't discover it halfway through the run.

Without a draw.io request, the mode is `mermaid`, silently.

### Humanizer

The built-in Indonesian humanizer (`humanizer-id.md`, the humanizer-id agent) **always** runs on the operator guide. An installed humanizer skill is added on top **only when the user asked for it in this run**, using the same two triggers as draw.io:
- the arguments contain `humanizer`, or
- a humanizer skill's instructions are already in this conversation (a "Base directory for this skill: …humaniz…" header).

Find the folder the same way as for draw.io (`*humaniz*` instead of `*drawio*`, also `~/.claude/plugins/**/skills/*humaniz*`). If it was asked for but not found, say so in one line and continue with the built-in rules only. Pass `HUMANIZER_SKILL=<folder or "none">` to the humanizer-id agent.

## 4. Per-app pipeline and resume

Each app moves through stages, recorded in `state.json → apps.<id>.stage`. **Write `state.json` after every stage change**, so an interrupted run resumes from the right stage.

| Stage now | Next step | Stage after |
|---|---|---|
| `pending` (or `failed` before drafting) | app-documenter, mode `fresh` | `drafted` |
| `drafted` | goldfish-reviewer | `reviewed` |
| `reviewed` | app-documenter, mode `fix` | `fixed` |
| `fixed` | humanizer-id on the operator guide; then validate | `done` |
| `done` + drift found | app-documenter `update` → goldfish-reviewer (changed sections only) → app-documenter `fix` → humanizer-id (changed operator sections only) → validate | `done` |

Concurrency: run up to **3 apps at a time** (several Agent calls in one message), then the next batch. Stages within one app run in order. If an agent fails, record `stage: "failed"` and `stage_error`, move on to the other apps, and report the failure at the end. Never let one broken app block the rest.

Validation (no LLM) after the humanizer step: `TOOL validate --repo REPO --app-state docs/.docgen/apps/<id>.json`. Failures **don't block writing**. Collect them for the report.

Cost control: app-documenter and humanizer-id run on Sonnet and goldfish-reviewer on Opus, as set in their agent files. Goldfish runs once per app per run. Fixes are applied without a second review. The validator is the safety net.

## 5. Agent prompts

Fill in the `<…>` values. Agents start with no context, so everything they need goes in the prompt.

**app-documenter, mode fresh**
```
Mode: fresh
Repo root: <REPO>
App: id=<id> root=<root> language=<lang> kind=<kind-guess>
Shared folder: <SHARED>
Meta: <meta JSON>
Diagram mode: <drawio|mermaid>   Draw.io skill: <path or "none">
Split: <"forced (repo has >10 apps)" | "decide by conventions §10">
Other apps in this repo (for cross-app links): <id → docs path, or "not documented yet">
Write: docs per conventions, docs/.docgen/apps/<id>.json. Return a summary of 10 lines or fewer.
```

**app-documenter, mode update**
```
Mode: update
(same header as fresh)
Drift for this app: <JSON from TOOL drift for this app: stale sections + changed/renamed/deleted files>
Template changed: <yes|no>   (yes → redo every section as in fresh mode, keep flow IDs)
```

**goldfish-reviewer**
```
Repo root: <REPO>
Shared folder: <SHARED>
App state: docs/.docgen/apps/<id>.json
Review scope: <"all sections" | list of section keys changed in this run>
Write findings to: docs/.docgen/.work/review-<id>.json
```
Don't pass the documenter's summary or reasoning to the goldfish. Its value is that it starts fresh.

**app-documenter, mode fix**
```
Mode: fix
(same header as fresh)
Findings: docs/.docgen/.work/review-<id>.json
```

**humanizer-id**
```
Repo root: <REPO>
Shared folder: <SHARED>
App state: docs/.docgen/apps/<id>.json
Scope: <"all sections" | list of op: section keys changed in this run>
Humanizer skill: <HUMANIZER_SKILL path or "none">
```
The humanizer runs last, after goldfish, so nothing undoes its tone. The validator is the only check after it.

## 6. Final report

Keep it short. One block per app, failures first:

```
payment-api  ✅ done   docs/payment-api/  (single, 23 flows, 9 full)
  Validator: 2 failures
    - dev:app-flow/refund: code ref services/payment-api/x.go:300 beyond end of file (210 lines)
  Goldfish: 11 findings → 10 fixed, 1 rejected (reason)
  Diagrams: 9 flows × (flowchart + sequence), 6 sub-flows, structure, startup, data-flow
  Marks: 3 unverified · 1 contradiction · 2 security findings
  Fill manually: deployment, log location
order-web    ❌ failed at drafted: <stage_error>
```

Then one line on what's next (for example "Run `/app-docs:sync` to push to Docmost"). Remind the user that nothing was committed. They review the diff and commit.
