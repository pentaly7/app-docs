# Pipeline (shared by `generate` and `update`)

You are the orchestrator. You never read application code yourself. You run the helper script, spawn agents, and own `docs/.docgen/state.json`. That keeps your context small enough for big monorepos.

## Contents
1. Paths
2. Preflight
3. Diagram mode, layout, state machines, humanizer
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
4. Make sure `docs/.docgen/.gitignore` exists and contains `.work/`. Run `TOOL migrate --repo REPO` (cheap, idempotent): it brings docs written by older plugin versions up to current conventions, such as the "User Guide" title.
5. If the arguments contain `fsm`: set `fsm: true` for **every** app in `state.json` (and every app added in this run). It stays on for later runs without the word. An app that was `done` with `fsm` false gets the "FSM newly enabled" update (section 4).

## 3. Diagram mode, layout, state machines, humanizer

### Diagram mode

The draw.io skill has `disable-model-invocation`, so you can't load it with the Skill tool. Use draw.io mode only when the user asked for it in this run:
- the arguments contain `drawio`, or
- the draw.io skill's instructions are already in this conversation (a "Base directory for this skill: …drawio…" header).

Then:
1. Find the skill folder. Use the base directory if it was shown. Otherwise take the first folder with a `SKILL.md` among `~/.claude/skills/*drawio*`, `REPO/.claude/skills/*drawio*`, `~/.agents/skills/*drawio*`, `~/.claude/plugins/**/skills/*drawio*`.
2. Check the CLI: `drawio --version`, `draw.io --version`, or `/Applications/draw.io.app/Contents/MacOS/draw.io --version`.
3. If both checks pass, the mode is `drawio` with `DRAWIO_SKILL=<folder>`. Otherwise the mode is `mermaid`. Tell the user why in one line ("draw.io CLI not found — using Mermaid"), so they don't discover it halfway through the run.
4. **Layout engine (draw.io mode only).** Diagrams are laid out by the plugin's `<SHARED>/scripts/diagram_layout.py`, which needs Graphviz. `command dot -V < /dev/null` must succeed. If it doesn't, **stop before any agent runs** and say what to install: `brew install graphviz` (macOS), `sudo apt install graphviz` (Debian/Ubuntu), `winget install graphviz` (Windows).

Without a draw.io request, the mode is `mermaid`, silently.

### Diagram theme

After an app's last writing step, run `TOOL svg-theme --repo REPO --app <id>`. It applies the light/dark palette to every `.drawio.svg` in the mode stored in `state.json → docmost.diagram_theme` (default `adaptive`, switched to `light` by the first sync if Docmost's toggle doesn't reach images). It's deterministic and costs nothing, so run it every time.

### Humanizer

The operator guide is always humanized with the **humanizer-indonesia** skill (see `humanizer.md`). This doesn't depend on the arguments.

1. Find the skill folder: the first folder with a `SKILL.md` among `~/.claude/skills/humanizer-indonesia`, `REPO/.claude/skills/humanizer-indonesia`, `~/.agents/skills/humanizer-indonesia`, `~/.claude/plugins/**/skills/humanizer-indonesia`. If its instructions are already loaded in this conversation, use that base directory.
2. Found → `HUMANIZER_SKILL=<folder>`.
3. Not found → `HUMANIZER_SKILL=none`, and warn once: "humanizer-indonesia not installed — using the plugin's fallback rules. Install: `git clone https://github.com/adhiprib/humanizer-indonesia ~/.claude/skills/humanizer-indonesia`". Continue.

## 4. Per-app pipeline and resume

Each app moves through stages, recorded in `state.json → apps.<id>.stage`. **Write `state.json` after every stage change**, so an interrupted run resumes from the right stage.

| Stage now | Next step | Stage after |
|---|---|---|
| `pending` (or `failed` before drafting) | app-documenter, mode `fresh` | `drafted` |
| `drafted` | goldfish-reviewer | `reviewed` |
| `reviewed` | app-documenter, mode `fix` | `fixed` |
| `fixed` | operator-humanizer on the operator guide; then svg-theme, validate | `done` |
| `done` + drift found, or FSM newly enabled | app-documenter `update` → goldfish-reviewer (changed sections only) → app-documenter `fix` → operator-humanizer (changed operator sections only) → svg-theme → validate | `done` |
| `redraw` (set when only `diagram_changed`) | app-documenter `redraw` → operator-humanizer (the User Guide sections it rewrote) → svg-theme → validate | `done` |
| `restory` (set when `story_changed`) | app-documenter `story` → operator-humanizer (the story sections) → validate | `done` |
| `done` + humanizer version changed, code unchanged | operator-humanizer on the whole operator guide → validate | `done` |

A `redraw` needs the same diagram mode the diagrams were made in. If the app's sections record `diagram: drawio` but this run is in Mermaid mode, skip the redraw for that app, keep `diagram_version` unchanged, and tell the user to rerun with `drawio`, instead of turning draw.io diagrams into Mermaid or marking them all outdated.

Several of `diagram_changed`, `story_changed` and `humanizer_changed` can be true at once. Run `redraw` first, then `restory`, then the humanizer step. After every app finishes, set `diagram_version` / `story_version` / `humanizer_version` in `state.json` to the current values from `TOOL meta`.

Waiting: an agent that takes a long time is normal, because tracing every branch and drawing diagrams is slow. **Wait for every agent to finish.** Never stop or cancel one, and never start a second agent for an app whose agent is still running, since both would write the same files. If you run any shell command yourself, use `command <tool> … < /dev/null` with explicit paths, so the user's shell aliases can't make it hang.

Concurrency: run up to **3 apps at a time** (several Agent calls in one message), then the next batch. Stages within one app run in order. If an agent fails, record `stage: "failed"` and `stage_error`, move on to the other apps, and report the failure at the end. Never let one broken app block the rest.

Validation (no LLM) after svg-theme: `TOOL validate --repo REPO --app-state docs/.docgen/apps/<id>.json`. Failures **don't block writing**. Collect them for the report.

Cost control: app-documenter and operator-humanizer run on Sonnet and goldfish-reviewer on Opus, as set in their agent files. Goldfish runs once per app per run. Fixes are applied without a second review. The validator is the safety net.

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
FSM: <on|off>
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
FSM newly enabled: <yes|no>   (yes → detect state machines and add their sections, state-machines.md)
```

**app-documenter, mode story**
```
Mode: story
(same header as fresh)
Rewrite every sequence story of this app under the current diagrams.md §5, re-reading the code.
```

**app-documenter, mode redraw**
```
Mode: redraw
(same header as fresh)
Redraw every diagram of this app under the current diagrams.md. Keep all text.
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

**operator-humanizer**
```
Repo root: <REPO>
Shared folder: <SHARED>
App state: docs/.docgen/apps/<id>.json
Scope: <"all sections" | list of op: section keys changed in this run>
humanizer-indonesia skill: <HUMANIZER_SKILL path or "none">
```
The humanizer runs last, after goldfish, so nothing undoes its tone. The validator is the only check after it.

## 6. Final report

Keep it short. One block per app, failures first:

```
payment-api  ✅ done   docs/payment-api/  (single, 23 flows, 9 full)
  Validator: 2 failures
    - dev:app-flow/refund: code ref services/payment-api/x.go:300 beyond end of file (210 lines)
  Goldfish: 11 findings → 10 fixed, 1 rejected (reason)
  Diagrams: 9 flows × (flowchart + sequence), 6 sub-flows, structure, startup, data-flow · layout graphviz · theme adaptive
  State machines: payment-status (5 states, 9 transitions, 1 inferred name), item-state
  Marks: 3 unverified · 1 contradiction · 2 security findings
  Fill manually: deployment, log location
order-web    ❌ failed at drafted: <stage_error>
```

Then one line on what's next (for example "Run `/app-docs:sync` to push to Docmost"). Remind the user that nothing was committed. They review the diff and commit.
