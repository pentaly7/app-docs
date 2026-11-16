# app-docs

A Claude Code plugin that writes and maintains two documents for every app in a repository:

- **Dev Guide**: software-engineering English, with `path:line` for every process. Sections: what the app is, structure, setup, startup, app flow, data flow, dev notes, glossary.
- **Panduan Operator**: Bahasa Indonesia ("Anda", no slang, tech terms in English), no code references. Sections: setup, app flow, data flow, troubleshooting, glossary.

Docs are written to `/docs`, reviewed by a fresh-context "goldfish" agent (the Elephant-Goldfish pattern), checked by a non-LLM validator, and synced one-way to Docmost.

## Commands

| Command | What it does |
|---|---|
| `/app-docs:generate [drawio]` | Main command. Fresh docs for new apps, drift update for documented ones, full regeneration after a template change, resume after an interrupted run. |
| `/app-docs:update [drawio]` | Drift report, then fixes only the affected sections of already-documented apps. |
| `/app-docs:sync [docmost-url]` | One-way sync to Docmost through your logged-in Chrome. The URL is saved after the first run. |

Add `drawio` to draw diagrams with the [draw.io skill](https://github.com/Agents365-ai/drawio-skill) as editable `.drawio.svg` files. Without it, diagrams are Mermaid blocks. The draw.io skill uses `disable-model-invocation`, so this plugin only uses it when you ask.

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

All writing rules live in `shared/references/`: `conventions.md` (the hard rules), the two templates, `diagrams.md`, and `pipeline.md`. If you change them in a way that should regenerate existing docs, bump `TEMPLATE_VERSION` in `shared/scripts/docs_tool.py` (and the version in the title of `conventions.md`). The next `generate` regenerates everything.

## Known limits

- **Docmost sync is UI automation.** The first sync runs a calibration (Markdown paste and SVG upload) and stops if your Docmost version doesn't support them. A Docmost UI upgrade can break it.
- Diagrams in Docmost are images. Edit them through the `.drawio.svg` in GitLab, then sync.
- Importance ranking and flow detection come from static reading of the code. Reflection-heavy or config-driven routing may be under-detected. The goldfish review is the check for that.
