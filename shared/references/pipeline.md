# Pipeline (shared by `generate` and `update`)

You are the orchestrator. You never read application code yourself. You run the helper script, spawn agents, and own `docs/.docgen/state.json`. That keeps your context small enough for big monorepos.

## Contents
1. Paths
2. Preflight
3. Diagram mode, layout, state machines, humanizer
4. Per-app pipeline and resume
5. Agent prompts
6. Final report
7. After the report

---

## 1. Paths

- `SHARED` = the `shared/` folder of this plugin: `<this skill's base directory>/../../shared`. Resolve it to an absolute path once and pass it to every agent.
- `TOOL` = `python3 <SHARED>/scripts/docs_tool.py`
- `REPO` = `git rev-parse --show-toplevel` from the current directory.

## 2. Preflight

1. Not inside a git repo → stop and say so. Provenance and drift both need git.
2. Run `TOOL meta --repo REPO`. Keep the JSON (`sha`, `short_sha`, `branch`, `dirty`, `date`, `user`, `web_url`, `head_pushed`).
3. One-line warnings, then continue:
   - `dirty` true: "Uncommitted changes: sections will be marked `+ uncommitted changes`."
   - `web_url` null: "No `origin` remote: code references stay plain text, without GitLab links."
   - `head_pushed` false: "HEAD isn't pushed yet: the Dev Guide's code links will 404 until you push it."
4. Make sure `docs/.docgen/.gitignore` exists and contains `.work/`. Run `TOOL migrate --repo REPO` (no LLM, idempotent). It applies the mechanical changes from older plugin versions: the "User Guide" title, the "generated at … run by …" subtitle, GitLab permalinks around code references, and Docmost page keys. These are free, and the new conventions need them, so they aren't part of the opt-in below. Mention the counts it returns in one line if any are non-zero.
5. If `docs/.docgen/bin/` or `docs/.docgen/gitlab-ci.app-docs.yml` exists (the CI check from 2.9–2.10.0, now removed), say once that both can be deleted, together with their `include:` line in `.gitlab-ci.yml`. Don't delete them yourself.
6. **Upgrade plan (opt-in).** If `state.json` exists, run `TOOL upgrade-plan --repo REPO`. When `pending` is empty, go on. Otherwise ask once with AskUserQuestion, showing each item's `what`, `units` and `tokens`, and the total:
   - **Upgrade now**: apply every pending action (section 4).
   - **Not now**: keep the repo's versions in `state.json`. This run fixes real drift and resumes unfinished apps only. The validator doesn't ask for sections from a newer template. The question comes back on the next run.
   When nobody is there to answer (a scheduled run), take "Not now" and say so in the report.
   **Exception: template 3 → 4 (`facts`).** The writers only know template 4: they write rendered blocks and facts entries, never hand-made tables. An app still on template 3 that has drift gets its `facts` stage first, even after "Not now", because updating it otherwise would leave tables half-rendered from a facts file that holds only the changed entries. Say so in the question ("apps with code changes are converted anyway, about 40k tokens each") and in the report. Apps without drift stay on template 3 until the user accepts. The template version is recorded **per app** (`apps/<id>.json → template_version`): the `facts` stage sets the app's to 4, and `state.json → template_version` stays the lowest of all apps.
7. If the arguments contain `fsm`: set `fsm: true` for **every** app in `state.json` (and every app added in this run). It stays on for later runs without the word. An app that was `done` with `fsm` false gets the "FSM newly enabled" update (section 4).

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

The User Guide is always humanized with the **humanizer-indonesia** skill (see `humanizer.md`). This doesn't depend on the arguments.

1. Find the skill folder: the first folder with a `SKILL.md` among `~/.claude/skills/humanizer-indonesia`, `REPO/.claude/skills/humanizer-indonesia`, `~/.agents/skills/humanizer-indonesia`, `~/.claude/plugins/**/skills/humanizer-indonesia`. If its instructions are already loaded in this conversation, use that base directory.
2. Found → `HUMANIZER_SKILL=<folder>`.
3. Not found → `HUMANIZER_SKILL=none`, and warn once: "humanizer-indonesia not installed: using the plugin's fallback rules. Install: `git clone https://github.com/adhiprib/humanizer-indonesia ~/.claude/skills/humanizer-indonesia`". Continue.

### Outside skill versions

humanizer-indonesia and the draw.io skill change on their own schedule, and a new version can change every User Guide's tone or every diagram's look without any change in this plugin. After resolving each one, run `TOOL skill-pin --repo REPO --name humanizer-indonesia --dir <HUMANIZER_SKILL>` (and `--name drawio --dir <DRAWIO_SKILL>` in draw.io mode). When `changed` is true, warn in one line: "humanizer-indonesia changed since the last run (`<old commit>` → `<new commit>`): sections humanized in this run may read differently from older ones. Nothing else is redone." Don't re-humanize on your own; the user decides.

## 4. Per-app pipeline and resume

Each app moves through stages, recorded in `state.json → apps.<id>.stage`. **Write `state.json` after every stage change**, so an interrupted run resumes from the right stage.

### Fresh docs

| Stage now | Next step | Stage after |
|---|---|---|
| `pending` (or `failed` before `app-done`) | app-documenter, mode `app` | `app-done` |
| `app-done` | `TOOL briefs`, then one **flow-documenter** (mode `flow`) per important flow | `flows-done` |
| `flows-done` | `TOOL assemble` (fragments → guides, facts, app state; renders tables) | `drafted` |
| `drafted` | goldfish-reviewer | `reviewed` |
| `reviewed` | doc-fixer, then `TOOL render` | `fixed` |
| `fixed` | humanizer step (below), then svg-theme, validate | `done` |

**Flow agents.** `TOOL briefs --repo REPO --app-state docs/.docgen/apps/<id>.json` writes one brief per important flow. Start one flow-documenter per brief. A flow agent is finished when its `fragment_dir/state.json` exists; record each finished flow in `state.json → apps.<id>.flows_done` right away. On resume in `app-done`, start agents only for flows not in `flows_done`. A flow agent that fails: record it in `stage_error`, still assemble the others, and report the flow as missing (the validator flags its placeholder as `flow-not-assembled`).

**Assemble** stops on nothing: it reports `problems` per flow (a fragment without its anchor, say). Report them; the flow's placeholder stays for the next run.

### Updates, upgrades and redraws

| Situation | Steps | Stage after |
|---|---|---|
| `done` + drift, or FSM newly enabled | app-documenter `update` (app-level stale sections, new and removed flows) → flow-documenter `flow` for each stale or new important flow (`TOOL briefs --flows a,b`) → assemble → goldfish (changed sections) → doc-fixer → render → humanizer step (changed User Guide sections) → svg-theme → validate | `done` |
| `redraw` (diagram rules changed) | app-documenter `redraw` and flow-documenter `redraw` per important flow, in parallel → assemble → humanizer step (the story sections) → svg-theme → validate | `done` |
| `restory` (story rules changed) | flow-documenter `story` per important flow (story-only fragments) → assemble → humanizer step (the story sections) → validate | `done` |
| `fixed` (humanizer rules changed, code unchanged) | humanizer step on the whole User Guide → validate | `done` |
| `extend` (accepted upgrade, `extend`) | app-documenter `extend` → goldfish (the new sections) → doc-fixer → render → humanizer step (the new sections) → validate | `done` |
| `facts` (accepted upgrade, `facts`: template 3 → 4) | app-documenter `facts` → validate. No review: the content doesn't change, and `facts-diff --cells` checks every old table cell and list item made it into the facts | `done` |

Only one agent writes a given file at a time: app-documenter before flow agents, flow agents only into their own fragment folders and specs, the assembler and renderer only between agent steps.

A `redraw` needs the same diagram mode the diagrams were made in. If the app's sections record `diagram: drawio` but this run is in Mermaid mode, skip the redraw for that app, keep `diagram_version` unchanged, and tell the user to rerun with `drawio`.

The upgrade plan's actions map to stages: `regenerate` → update mode with "Template changed: yes" for every app, `extend` → `extend`, `facts` → `facts` (after `extend` when both are pending), `redraw` → `redraw`, `restory` → `restory`, `rehumanize` → `fixed`. Set `template_version` to current after the last app finishes its template steps, so an interrupted upgrade resumes as an upgrade. If the user said "Not now", don't set any of these stages and don't touch the versions. Several can be pending at once: template steps first, then `redraw`, then `restory`, then the humanizer step. After every app finishes, set `diagram_version` / `story_version` / `humanizer_version` to the current values from `TOOL meta`.

### Every app, every run

- **Before the first agent** touches an app: `TOOL keep-snapshot --repo REPO --app-state <state> --out docs/.docgen/.work/keep-<id>.json`. People write `<!-- app-docs:keep -->` blocks into the guides (conventions §8).
- **After every writing step** (each agent, and assemble): `TOOL keep-restore --repo REPO --app-state <state> --before docs/.docgen/.work/keep-<id>.json`. It puts back any keep block an agent dropped. Report restored blocks: an agent that drops them needs its prompt checked.
- **After assemble**, render once with `--refresh-owners`: `TOOL render --repo REPO --app-state <state> --refresh-owners`. That takes this run's owners snapshot; every other render reuses it, so the owners table doesn't change between runs on its own.
- **Before validate**: `TOOL stamp --repo REPO --app-state <state>`. It records each section's file contents, so drift still works after a squash merge or rebase.

### Humanizer step

1. `TOOL humanize-plan --repo REPO --app-state <state> --skill <HUMANIZER_SKILL> [--scope <op: keys>]`. It returns how many paragraphs need work. **0 → skip the agent.**
2. `TOOL facts-snapshot … --out docs/.docgen/.work/facts-<id>-prehuman.json`.
3. operator-humanizer with the plan.
4. `TOOL facts-diff … --before …-prehuman.json --only op --strict`. Any change is a failure: run operator-humanizer **once more** with the `changes` list ("put back exactly these facts"), and diff again. Still failing → record a validator failure `humanizer-fact-changed` and keep the text. Never loop.

### Fact checks around the fixer

After `assemble` (or the first writing step of an update), `TOOL facts-snapshot … --out …-draft.json`. After `doc-fixer` and render, `TOOL facts-diff … --before …-draft.json`. Fixes may change facts, so this is **report only**: list lost or added facts under "Fix changed facts". The validator also compares the two guides' facts and warns on mismatches; report them, don't fix them.

### Waiting, concurrency, failures

Waiting: an agent that takes a long time is normal. **Wait for every agent to finish.** Never stop or cancel one, and never start a second agent on the same files. If you run a shell command yourself, use `command <tool> … < /dev/null` with explicit paths.

Concurrency: at most **5 agents running at once**, across all apps (several Agent calls in one message). Fill free slots with the next flow agents of any app, then with the next app's stage. Stages within one app run in order. If an agent fails, record `stage: "failed"` and `stage_error` (for a flow agent: as above), move on, and report it. Never let one broken app block the rest.

Validation (no LLM) after svg-theme: `TOOL validate --repo REPO --app-state docs/.docgen/apps/<id>.json`. Failures **don't block writing**. Collect them for the report.

**Token recording.** At the start of the run, set `RUN` to the current time (`date -u +%Y-%m-%dT%H:%M:%SZ`), the same value for the whole run. Every time an agent finishes, its completion carries `total_tokens` and `duration_ms`. Record them right away, because they aren't stored anywhere else:
`TOOL usage-record --repo REPO --run RUN --app <id> --stage <stage it ran> --agent <agent name> --tokens <total_tokens> --ms <duration_ms>`
For flow agents, use `--stage flow:<flow-id>`. If the completion doesn't show a token count, leave `--tokens` out. Your own (orchestrator) tokens aren't in it.

Cost control: every writer runs on Sonnet and goldfish-reviewer on Opus, as set in their agent files. Goldfish runs once per app per run; fixes are applied without a second review; the validator is the safety net.

## 5. Agent prompts

Fill in the `<…>` values. Agents start with no context, so everything they need goes in the prompt. Every prompt starts with this header:

```
Repo root: <REPO>
Shared folder: <SHARED>
Meta: <meta JSON>
Diagram mode: <drawio|mermaid>   Draw.io skill: <path or "none">
```

**app-documenter**
```
Mode: <app | update | extend | facts | redraw>
App: id=<id> root=<root> language=<lang> kind=<kind-guess>
FSM: <on|off>
Split: <"forced (repo has >10 apps)" | "decide by conventions §10">
Other apps in this repo (for cross-app links): <id → docs path, or "not documented yet">
Repo template version: <state.template_version>
update only:  Drift: <TOOL drift JSON for this app>   Template changed: <yes|no>   FSM newly enabled: <yes|no>
extend only:  Add these sections and nothing else: <upgrade-plan sections>
Write: per your mode. Return a summary of 10 lines or fewer.
```

**flow-documenter**
```
Mode: <flow | story | redraw>
Brief: docs/.docgen/.work/briefs/<id>/<flow-id>.json
```

**goldfish-reviewer**
```
App state: docs/.docgen/apps/<id>.json
Review scope: <"all sections" | list of section keys changed in this run>
Write findings to: docs/.docgen/.work/review-<id>.json
```
Don't pass any writer's summary or reasoning to the goldfish. Its value is that it starts fresh.

**doc-fixer**
```
App state: docs/.docgen/apps/<id>.json
Findings: docs/.docgen/.work/review-<id>.json
```

**operator-humanizer**
```
App state: docs/.docgen/apps/<id>.json
Plan: docs/.docgen/.work/humanize-<id>-plan.json
humanizer-indonesia skill: <HUMANIZER_SKILL path or "none">
Facts to restore: <only on the second pass: the facts-diff changes list>
```
The humanizer runs last, after the goldfish and the fixer, so nothing undoes its tone. The validator is the only check after it.

## 6. Final report

Keep it short. Run `TOOL usage-report --repo REPO --run RUN` first. One block per app, failures first:

```
payment-api  ✅ done   docs/payment-api/  (single, 23 flows, 9 full)
  Validator: 2 failures
    - dev:app-flow/refund: code ref services/payment-api/x.go:300 beyond end of file (210 lines)
  Goldfish: 11 findings → 10 fixed, 1 rejected (reason)
  Fix changed facts: dev:app-flow/refund lost `30s`, added `60s`
  Guides disagree: app-flow/create-payment: User Guide says `PAYMENT_TIMEOUT_MS`, Dev Guide doesn't
  Code links: commit a1b2c3d not pushed (links 404 until pushed)
  Tokens: 412k (app 95k · flows 9 × 18k · review 70k · fix 20k · humanize 25k)
  Diagrams: 9 flows × (flowchart + sequence), 6 sub-flows, structure, startup, data-flow · layout graphviz · theme adaptive
  State machines: payment-status (5 states, 9 transitions, 1 inferred name), item-state
  Marks: 3 unverified · 1 contradiction · 2 security findings
  Fill manually: deployment, log location
order-web    ❌ failed at drafted: <stage_error>
```

After the app blocks, one line with the run's total tokens and, when `usage-report` has a `previous` run, the total of that run and its plugin version ("Tokens this run: 1.2M; previous run (2.9.1): 1.9M"). These are only the subagents' tokens.

Remind the user that nothing was committed. They review the diff and commit.

## 7. After the report

If at least one app changed in this run, ask with AskUserQuestion:

**Sync to Docmost now?** "Yes, sync now" / "No, I'll sync later". The user decides when to sync, never the plugin. On yes, read `<SHARED>/../skills/sync/SKILL.md` and follow it, with the root URL from `state.json` (it asks for one when there's none).

In a scheduled run, ask nothing: write the report and stop.
