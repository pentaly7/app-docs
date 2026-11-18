# app-docs

A Claude Code plugin that writes and maintains two documents for every app in a repository:

- **Dev Guide**: software-engineering English, with `path:line` for every process. Sections: what the app is, structure, setup, startup, app flow, data flow, dev notes, glossary.
- **User Guide** (for operators): titled in English, written in semiformal Bahasa Indonesia (no slang, no "Anda"/"kamu", tech terms in English), humanized with humanizer-indonesia as the last step, no code references. Sections: setup, cara aplikasi bekerja, app flow, data flow, troubleshooting, glossary.

Docs are written to `/docs`, reviewed by a fresh-context "goldfish" agent (the Elephant-Goldfish pattern), checked by a non-LLM validator, and synced one-way to Docmost.

## Commands

| Command | What it does |
|---|---|
| `/app-docs:generate [drawio] [fsm]` | Main command. Fresh docs for new apps, drift update for documented ones, full regeneration after a template change, resume after an interrupted run. |
| `/app-docs:update [drawio] [fsm]` | Drift report, then fixes only the affected sections of already-documented apps. |
| `/app-docs:sync [docmost-url]` | One-way sync to Docmost through your logged-in Chrome. The URL is saved after the first run. |
| `/app-docs:readme` | Rewrites each app's `README.md` (and a monorepo root index) as a condensed copy of its Dev Guide: what it is, tech stack, quick start, configuration, structure diagram, flows, doc links, owners (CODEOWNERS, else recent committers), last-verified commit. Asks first if the Dev Guide is behind `HEAD`; stops if an app has no Dev Guide yet. |

Skills this plugin uses:
- **[humanizer-indonesia](https://github.com/adhiprib/humanizer-indonesia)** (dependency, always used): polishes the operator guide's prose in `semiformal` register, with the plugin's own voice preset (`shared/references/voice-operator-docs.md`). If it isn't installed, the plugin warns and uses its fallback rules. Install it with `git clone https://github.com/adhiprib/humanizer-indonesia ~/.claude/skills/humanizer-indonesia`.
- **[draw.io skill](https://github.com/Agents365-ai/drawio-skill)** (optional): add `drawio` to the command, or run the skill first in the same session, to get editable `.drawio.svg` diagrams. Shapes are never placed by hand: agents write a small spec per diagram and the plugin's `shared/scripts/diagram_layout.py` lays it out with **Graphviz**: a straight happy path, side exits for errors, one shared channel for errors that continue, notes on the left, zones for data-flow, numbered circles in sequence diagrams. Without Graphviz the run stops and tells you how to install it. Without it, diagrams are colored Mermaid blocks. It uses `disable-model-invocation`, so when you ask for it the plugin reads its `SKILL.md` directly, because subagents can't inherit skills loaded in your session.

## Diagrams

| Diagram | Where |
|---|---|
| Structure | dev `structure`, operator `how-it-works` |
| Startup flowchart | dev `startup`, operator `how-it-works` |
| Flowchart (every branch, sub-flow files instead of size limits) + sequence diagram | every important flow, both docs |
| Data-flow diagram, with one group per storage type (database, file storage, object storage, cache) | `data-flow`, both docs |
| State diagram per state machine, plus an overview (with `fsm`) | `state-machine`, both docs |

Colored by component kind and outcome, with a legend. Long decision conditions go into a Note beside a short diamond label. Every `.drawio.svg` carries a light and a dark palette and follows the viewer's dark mode. The first Docmost sync checks that it follows Docmost's own toggle, and switches every diagram to always-light if it doesn't. The validator checks that each one exists, is editable, is a single page, is colored and has a legend. Full rules: `shared/references/diagrams.md`.

## Install

```bash
# from the folder that contains app-docs-marketplace/
claude plugin marketplace add pentaly7/app-docs
claude plugin install app-docs@app-docs
```

## Requirements

- git, Python 3.8+ (the helper script is stdlib-only)
- draw.io mode: the draw.io skill installed, plus the draw.io desktop CLI
- sync: Claude Code running locally (CLI with `--chrome`, or the desktop app), with Chrome and the Claude in Chrome extension, logged in to Docmost

## How a run works

```
generate/update (orchestrator, your session)
  └─ per app, up to 3 in parallel, stage saved in docs/.docgen/state.json
       app-documenter (Sonnet)  → writes docs + docs/.docgen/apps/<app>.json
       goldfish-reviewer (Opus) → fresh context, reviews docs vs. code → findings
       app-documenter (Sonnet)  → applies findings it can verify (no re-review)
       operator-humanizer (Sonnet) → humanizer-indonesia on the operator guide's prose only
       docs_tool.py validate    → non-LLM checks; failures reported, not blocking
```

## What gets written

```
docs/
├── .docgen/state.json            # apps, stages, Docmost page map — commit it
├── .docgen/apps/<app>.json       # flows + per-section commit/files map — commit it
└── <app>/dev-guide.md, operator-guide.md, diagrams/
    (or dev/ and operator/ folders when split: >50 endpoints, >10 FE pages, or >10 apps in the repo)
```

Every section carries `` > `sha` · `branch` · date · verified by <name> ``, and gets `+ uncommitted changes` when generated from a dirty tree.

## Customizing

All writing rules live in `shared/references/`: `conventions.md` (the hard rules), the two templates, `diagrams.md`, `humanizer.md`, `voice-operator-docs.md`, and `pipeline.md`. If you change them in a way that should regenerate existing docs, bump `TEMPLATE_VERSION` in `shared/scripts/docs_tool.py` (and the version in the title of `conventions.md`). The next `generate` regenerates everything. If you only change the humanizer rules or the voice preset, bump `HUMANIZER_VERSION` instead: the next run re-humanizes the operator guides and touches nothing else. If you only change diagram rules, bump `DIAGRAM_VERSION`: the next run redraws diagrams only. The dark palette lives in `DARK_FILL` / `DARK_STROKE` / `DARK_TEXT` in `docs_tool.py`; keep it in step with diagrams.md §8.

## State machines (`fsm`)

Add `fsm` once (`/app-docs:generate fsm`) and every app in the repo gets state machine detection, remembered in `state.json` for later runs. A state field with at least 3 states and 3 transitions becomes a documented machine: transition table with `path:line` (dev), a state diagram (both), what each status means and what to check when a record is stuck (operator). Numeric states without names get an inferred name marked Unverified in the dev guide. The detection method is in `shared/references/state-machines.md`.

## Upgrading

From 2.5: "Panduan Operator" is now titled "User Guide" (content stays Indonesian). The next generate or sync renames existing titles automatically, in the files and in Docmost.

From 2.4: the next `/app-docs:generate drawio` redraws diagrams with separate storage types (text untouched).

From 2.3: the next `/app-docs:generate drawio` redraws every diagram with the new layout script (text untouched). Install Graphviz first.

From 2.2: the next `/app-docs:generate drawio` redraws every diagram with auto-layout and the new palette (text untouched), then themes them. Install Graphviz first, or draw.io desktop v30+.

From 2.0: the next `/app-docs:generate` re-humanizes every operator guide (semiformal, no slang) and redraws the diagrams.

### From 1.x

Template version 2 changes diagrams, the operator guide's voice and its sections, so the next `/app-docs:generate` regenerates every documented app. Commit or stash first so you can compare.

## Known limits

- **Docmost page titles:** only the app's page carries the app name. Sub-pages drop it ("User Guide", "Dev Guide"). The markdown files in GitLab keep their full H1.
- **Docmost sync is UI automation.** The first sync runs a calibration (Markdown paste and SVG upload) and stops if your Docmost version doesn't support them. A Docmost UI upgrade can break it.
- Mermaid mode doesn't get the dark palette: Docmost renders Mermaid itself.
- Diagrams in Docmost are images, scaled to the page width. Large flowcharts are split into sub-flow files so each stays readable. Edit them through the `.drawio.svg` in GitLab, then sync.
- Importance ranking and flow detection come from static reading of the code. Reflection-heavy or config-driven routing may be under-detected. The goldfish review is the check for that.
