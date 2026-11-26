# app-docs

A Claude Code plugin that writes and maintains two documents for every app in a repository, or in every repository of a workspace folder:

- **Dev Guide**: software-engineering English, with a GitLab permalink (`path:line`, pinned to the commit the text was written from) for every process. Sections: what the app is, structure, setup, startup, app flow, data flow, dev notes, glossary.
- **User Guide** (for operators): titled in English, written in semiformal Bahasa Indonesia (no slang, no "Anda"/"kamu", tech terms in English), humanized with humanizer-indonesia as the last step, no code references. Sections: setup, cara aplikasi bekerja, app flow, data flow, troubleshooting, log message index, alerts and monitoring, owners and escalation, glossary.

Docs are written to `/docs`, with every table and list rendered by script from one facts file per app, reviewed by a fresh-context "goldfish" agent (the Elephant-Goldfish pattern), and checked by a non-LLM validator. The User Guide is synced one-way to Docmost for operators; developers read the Dev Guide in GitLab.

## Commands

| Command | What it does |
|---|---|
| `/app-docs:generate [drawio] [fsm] [max-apps N]` | Main command. Fresh docs for new apps, drift update for documented ones, plugin upgrades only when you accept them (with a token estimate), resume after an interrupted run. Run it in a repo, or in a folder of repos (workspace). |
| `/app-docs:update [drawio] [fsm] [max-apps N]` | Drift report, then fixes only the affected sections of already-documented apps. |
| `/app-docs:sync [docmost-url]` | One-way sync of one repo's User Guides to Docmost through your logged-in Chrome. In a workspace folder it syncs the next repo that needs it; each repo gets a new conversation. The URL is saved after the first run. |
| `/app-docs:readme` | Rewrites each app's `README.md` (and a monorepo root index) by script, with no model, as a condensed copy of its Dev Guide: what it is, tech stack, quick start, configuration, structure diagram, flows, doc links, owners (CODEOWNERS, else recent committers), the commit of its oldest section. Asks first if the Dev Guide is behind `HEAD`; stops if an app has no Dev Guide yet. |

Skills this plugin uses:
- **[humanizer-indonesia](https://github.com/adhiprib/humanizer-indonesia)** (dependency, always used): polishes every changed User Guide section, prose and table text in `semiformal` register, with the plugin's own voice preset (`shared/references/voice-operator-docs.md`). If it isn't installed, the plugin warns and uses its fallback rules. Install it with `git clone https://github.com/adhiprib/humanizer-indonesia ~/.claude/skills/humanizer-indonesia`.
- **[draw.io skill](https://github.com/Agents365-ai/drawio-skill)** (optional): add `drawio` to the command, or run the skill first in the same session, to get editable `.drawio.svg` diagrams. Shapes are never placed by hand: agents write a small spec per diagram and the plugin's `shared/scripts/diagram_layout.py` lays it out with **Graphviz**: a straight happy path, side exits for errors, one shared channel for errors that continue, notes on the left, zones for data-flow, numbered circles in sequence diagrams. Without Graphviz the run stops and tells you how to install it. Without it, diagrams are colored Mermaid blocks. It uses `disable-model-invocation`, so when you ask for it the plugin reads its `SKILL.md` directly, because subagents can't inherit skills loaded in your session.

## Diagrams

| Diagram | Where |
|---|---|
| Structure | dev `structure`, operator `how-it-works` |
| Startup flowchart | dev `startup`, operator `how-it-works` |
| Flowchart (every branch, sub-flow files instead of size limits) + sequence diagram | every important flow, both docs |
| Data-flow diagram, with one group per storage type (database, file storage, object storage, cache) | `data-flow`, both docs |
| State diagram per state machine, plus an overview (with `fsm`) | `state-machine`, both docs |

Colored by component kind and outcome, with a legend. Long decision conditions go into a Note beside a short diamond label. Every `.drawio.svg` carries a light and a dark palette and follows the viewer's dark mode. The first Docmost sync checks that it follows Docmost's own toggle; if it doesn't, sync uploads always-light copies and the files in `docs/` stay adaptive for GitLab. The validator checks that each one exists, is editable, is a single page, is colored and has a legend. Full rules: `shared/references/diagrams.md`.

## Install

```bash
claude plugin marketplace add pentaly7/app-docs
claude plugin install app-docs@app-docs
```

## Requirements

- git, Python 3.8+ (the scripts are stdlib-only)
- draw.io mode: the draw.io skill installed, plus the draw.io desktop CLI and Graphviz
- sync: Claude Code running locally (CLI with `--chrome`, or the desktop app), with Chrome and the Claude in Chrome extension, logged in to Docmost

## Models

| Who | Model | Why |
|---|---|---|
| Your session (the orchestrator) for generate, update and sync | **Sonnet**, set by the skills (`model: sonnet`) | It runs `pipeline.py`, launches agents and prints the report. Opus adds cost and nothing else here. |
| app-documenter, flow-documenter, doc-fixer, operator-humanizer | Sonnet | The writing. |
| goldfish-reviewer | **Opus** | The quality check: a fresh reader comparing the docs with the code. Keep it on Opus. |

The skill setting switches the model for the run's turn. If the final report's "Main session model" line says Opus anyway, run `/model sonnet` before the next run.

## Running on Claude Pro

Pro has a usage limit per 5-hour window, and a big run (16 services in one workspace) can reach it.
- Runs use **3 agents at a time**. More at once wouldn't use fewer tokens; it would only reach the limit sooner, with more half-done work cut off when it does.
- `max-apps N` starts at most N apps in a run (`/app-docs:generate max-apps 4`). The rest are listed as not started; the next run continues with them. The default is every app.
- Hitting the limit mid-run is safe. Run the same command again (in a new conversation is fine): finished agents' work is found on disk, and the run resumes at the step each app was at.
- Check where tokens went: the report ends with spend per model since the run started (`docs_tool.py usage-spend`), and the main session's model.

## Workspaces

Run generate, update or sync from a folder that isn't a repo, and every git repo one or two folders below it is part of the run: `parent/svc-a/`, `parent/group/svc-b/`. A repo's own nested clones and submodules aren't separate repos, and `vendor/`, `node_modules/` and similar folders are skipped. Each repo keeps its own `docs/`.

- **Callees first:** the plugin guesses which service calls which from config files (base URL hosts, keys like `WALLET_URL`) and documents and syncs callees before their callers, so cross-service links work on the first pass. The guess is in `.app-docs-workspace.json` in the parent folder; if it's wrong, edit `calls` and set `"calls_source": "manual"`.
- **Links between services:** in the markdown, a GitLab link to the other repo's guide (it works in GitLab). Sync turns a User Guide link into the other service's Docmost page once that page exists, and plain text until then.
- **Questions once:** uncommitted changes, upgrades and the like are asked once for the whole run, not per repo.
- **Sync one repo per conversation:** every browser call re-sends the whole conversation, so each repo gets a new one. Run `/app-docs:sync` from the parent folder and it picks the next repo (callees first); at the end it tells you which repo is next. A link that waits for a later repo resolves when its repo is synced again.
- **One calibration:** the first sync calibrates Docmost and the workspace file keeps it for every repo. The workspace file and the run file beside it (`.app-docs-run.json`) aren't committed anywhere.
- A colleague who runs the plugin in their single repo gets a normal single-repo run; links already written stay as they are.

## How a run works

```
generate/update (your session, on Sonnet) → pipeline.py start / done / next → one action at a time
  pipeline.py: meta, migrate, drift, upgrade plan, questions (once per run), jobs per app, 3 agents at a time,
               every script step between agents, checks on each agent's output, resume, the report
  └─ per app, per job (fresh, update, extend, facts, redraw, restory, rehumanize)
       app-documenter (Sonnet)        → app-level sections, facts file, flow inventory, app diagrams
       flow-documenter (Sonnet) × N   → one per group of flows sharing code: sections, diagrams, story, flow facts
       assemble / render              → fragments into the guides; every table and list rendered from the facts
       goldfish-reviewer (Opus)       → fresh context: Dev Guide, facts and the User Guide-only sections vs. code
       doc-fixer (Sonnet)             → applies findings, reading only the code lines each one cites
       operator-humanizer (Sonnet)    → humanizer-indonesia on the User Guide sections changed in this run
       facts-diff                     → the humanizer may not change a number, name or status code
       stamp / validate               → per-section provenance; non-LLM checks, reported not blocking
  └─ report: per app, then spend per model since the run started
  └─ "run /app-docs:sync in a new conversation"
```

Each agent gets a reading list made for its mode (story and redraw agents skip the writing templates, Mermaid runs skip the draw.io spec rules). Diagrams are laid out and exported in one script call per agent (`docs_tool.py diagrams`); agents look only at the PNGs of diagrams it flags.

Fact checks (no LLM): numbers with units, backtick names and status codes are compared before and after the humanizer (any change fails, and the humanizer gets one retry), before and after the fix step (reported), and between the two guides (mismatches reported for you to decide). Log messages and metric names in the User Guide must exist in the code.

## What gets written

```
docs/
├── .docgen/state.json            # apps, stages, Docmost page map — commit it
├── .docgen/apps/<app>.json       # flows + per-section commit/files map — commit it
├── .docgen/facts/<app>.json      # every table and list, as data — commit it
└── <app>/dev-guide.md, operator-guide.md, diagrams/
    (or dev/ and operator/ folders when split: >50 endpoints, >10 FE pages, or >10 apps in the repo)
```

Every section carries `` > generated at `sha` on `branch`, date, run by <name> ``, and gets `+ uncommitted changes` when generated from a dirty tree. "Generated", not "verified": it records which commit the text came from and who ran the plugin, not that anyone checked it.

## Filling in what the code can't say

Some facts aren't in the repository: how production is deployed, who is on call, which alerts exist outside the repo. The guides mark them "Belum diketahui … Mohon diisi manual". Fill them in so that no later run overwrites them:
- **In prose**, replace the placeholder with a keep block. Agents copy it unchanged, and a script puts it back if a rewrite drops it:
  ```markdown
  <!-- app-docs:keep -->
  Deploy lewat ArgoCD, app `payment-prod`.
  <!-- /app-docs:keep -->
  ```
- **In tables** (alerts, owners, escalation), fill `manual` in `docs/.docgen/facts/<app>.json`; the placeholder in the table says which field. See `shared/references/facts-schema.md`.
- **In a README**, wrap anything of your own (licence, badges, contribution rules) in a keep block; `/app-docs:readme` copies it into every rewrite.

## Customizing

All writing rules live in `shared/references/`: `conventions.md` (the hard rules), the two guide templates and `flow-template.md`, `facts-schema.md`, `diagrams*.md` (split by who reads them), `humanizer.md` and `voice-operator-docs.md`. The run itself is `shared/scripts/pipeline.py`, described in `pipeline.md`. If you change them in a way that should regenerate existing docs, bump `TEMPLATE_VERSION` in `shared/scripts/docs_tool.py` (and the version in the title of `conventions.md`). The next `generate` regenerates everything. If you only change the humanizer rules or the voice preset, bump `HUMANIZER_VERSION` instead: the next run re-humanizes the operator guides and touches nothing else. If you only change diagram rules, bump `DIAGRAM_VERSION`: the next run redraws diagrams only. The dark palette lives in `DARK_FILL` / `DARK_STROKE` / `DARK_TEXT` in `docs_tool.py`; keep it in step with diagrams-style.md §8. Each agent's reading list per mode is `reading_list` in `pipeline.py` (app-documenter and flow-documenter); the other agents name theirs in their own files under `agents/`.

## State machines (`fsm`)

Add `fsm` once (`/app-docs:generate fsm`) and every app in the repo gets state machine detection, remembered in `state.json` for later runs. A state field with at least 3 states and 3 transitions becomes a documented machine: transition table with `path:line` (dev), a state diagram (both), what each status means and what to check when a record is stuck (operator). Numeric states without names get an inferred name marked Unverified in the dev guide. The detection method is in `shared/references/state-machines.md`.

## Upgrading

Upgrades are opt-in. When the plugin's rules are newer than the ones a repo's docs were written with, `generate`/`update` show what would be redone and a rough token estimate, and ask. "Not now" keeps the repo's versions: only real drift is fixed, the validator doesn't ask for newer sections, and you're asked again next run. Mechanical changes (titles, subtitles, links, page keys) are applied by `docs_tool.py migrate` without asking, because they cost nothing and the new conventions depend on them.

### From 2.10.3 (to 3.0.0)

Nothing in your docs is redone. What changes:
- **Finish 2.x runs first.** 3.0 doesn't continue 2.x stages: an app left mid-run (stage `app-done`, `drafted`, …) makes the next run ask whether to start it fresh or stop so you can finish it with 2.10.3.
- **The orchestrator runs on Sonnet** and only follows `pipeline.py`. The script does every non-model step, so none can be skipped.
- **Docmost gets the User Guide only**, as the app's own page (no "User Guide" sub-page, no "Dev Guide" page). `migrate` drops Dev Guide page keys from `state.json` without touching Docmost. If you had synced 2.x pages, the old User Guide sub-page shows up as an orphan on the next sync, to archive or delete.
- **Diagrams in `docs/` stay adaptive** (light and dark), because GitLab shows them. When Docmost's theme toggle doesn't reach images, sync uploads light copies instead of changing your files.
- **Workspaces**, `max-apps N`, 3 agents at a time, questions once per run. Sync covers one repo per conversation: from the parent folder it picks the next repo, callees first, and tells you when to start a new conversation for the one after.
- **Removed:** `usage-record` and `usage-report` (the local token log). The report shows real spend from `usage-spend`.

From 2.10.2 (to 2.10.3): nothing to redo. The humanizer now polishes every paragraph and the table text of each User Guide section a run writes or changes (before: only flagged paragraphs, never tables). Sections that don't change aren't re-polished; to polish a whole existing guide once, bump `HUMANIZER_VERSION` and accept the upgrade.

From 2.10.1: nothing to redo. Before the next run, commit (or answer "Commit first" when asked): docs written by 2.10.1 from a dirty tree marked every section dirty, and the first 2.10.2 run re-marks each section by its own files. If the repo lives on a Windows drive under WSL (`/mnt/d/...`), clone it into the Linux home folder; it removes false "modified" files and speeds up every step. New: flows that share code are documented by one agent (groups), sequence diagrams only for flows that call another system, each diagram uploaded to Docmost once and linked from other pages, and real token spend in the report (`usage-spend`, from Claude Code's session transcripts).

From 2.10.0: nothing to redo. The GitLab CI check is gone (it could let a failing merge request merge in repos that use branch pipelines); delete `docs/.docgen/bin/`, `docs/.docgen/gitlab-ci.app-docs.yml` and their `include:` line if you added them. The next run stamps each section's file contents (squash merges no longer mark everything stale) and takes an owners snapshot. Keep blocks and `manual` facts are new; see "Filling in what the code can't say".

From 2.9.x: if you accept the upgrade, each app's tables and lists move into `docs/.docgen/facts/<app>.json` (one agent run per app, no new research; `facts-diff` proves nothing was lost), and are rendered by script from then on. Without it, the docs stay as they are and updates keep working. Upgrade from 2.9.1 if you can: its token report is the baseline that shows what 2.10 saves.

From 2.9.0: nothing to redo. Runs now record each agent's tokens in `docs/.docgen/.work/usage.jsonl` (local, not committed), and the final report shows them per app and stage, with the previous run's total for comparison.

From 2.8.x: the next run converts every subtitle to "generated at … run by …", wraps every Dev Guide code reference in a GitLab permalink, and re-keys Docmost pages by section ID (no LLM). If you accept the upgrade, it then adds three User Guide sections to every app (log message index, alerts and monitoring, owners and escalation) without touching the rest. Existing Docmost pages are found again under the new keys; inline comments on synced pages are still replaced by each sync (see Known limits).

From 2.8.1: sequence stories use a bold capital-letter heading per phase and a plain numbered list whose numbers are the arrow numbers; the next `/app-docs:generate` rewrites them into this format.

From 2.8.0: Dev Guide stories carry their code references inline in each arrow line; the next `/app-docs:generate` rewrites the stories once more.

From 2.7.1: the next `/app-docs:generate` re-reads the code and rewrites every sequence story in detail: a line per arrow, with inline file and line references in the Dev Guide, and log messages, tables and timeouts in the User Guide. Diagrams and the rest of the text are untouched. The plugin's examples no longer contain real product or company names.

From 2.7.0: the next `/app-docs:generate drawio` redraws flowcharts without step numbers, with branches that continue in their own column to the right (text untouched).

From 2.6.1: the next `/app-docs:generate drawio` redraws every diagram top-down, with richer sequence diagrams (phases, `break` boxes, colored arrows, activation bars, participant shapes, notes), and rewrites each sequence story as lettered paragraphs. The rest of the text is untouched.

From 2.6.0: the next `/app-docs:generate drawio` redraws diagrams with rounded lines, readable labels in dark mode, and fixed sequence label placement (text untouched).

From 2.5: "Panduan Operator" is now titled "User Guide" (content stays Indonesian). The next generate or sync renames existing titles automatically, in the files and in Docmost.

From 2.4: the next `/app-docs:generate drawio` redraws diagrams with separate storage types (text untouched).

From 2.3: the next `/app-docs:generate drawio` redraws every diagram with the new layout script (text untouched). Install Graphviz first.

From 2.2: the next `/app-docs:generate drawio` redraws every diagram with auto-layout and the new palette (text untouched), then themes them. Install Graphviz first, or draw.io desktop v30+.

From 2.0: the next `/app-docs:generate` re-humanizes every operator guide (semiformal, no slang) and redraws the diagrams.

### From 1.x

Template version 2 changes diagrams, the operator guide's voice and its sections, so the next `/app-docs:generate` regenerates every documented app. Commit or stash first so you can compare.

## Known limits

- **Docmost page titles:** each app's page is titled with the app's name; split sub-pages drop it. The markdown files in GitLab keep their full H1.
- **Docmost sync is UI automation.** Page text goes through the OS clipboard and a real paste, diagrams through Docmost's image upload. The first sync calibrates both and stops if your Docmost version doesn't support them; a page that fails later triggers one recalibration. A Docmost UI upgrade can still break it.
- **Docmost inline comments don't survive a sync.** Each sync replaces the page body, so comments attached to text in it are lost or detached. URLs, page history and the page tree are kept. Keep notes in separate pages, or propose changes as a merge request on the markdown.
- **Call order is a guess** from config files. A wrong guess only delays some cross-service links to the next sync; fix it in the workspace file.
