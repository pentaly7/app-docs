# README template

A README is the front door: someone lands on the repo or app folder in GitLab and needs to know what this is, how to run it, and where the full docs are. It's a **condensed copy of the Dev Guide**, **rendered by `docs_tool.py readme`** (no model) and rewritten in full on every `/app-docs:readme` run. This file describes what the script produces; change the script to change the README.

Where each part comes from: the title and intro (the overview's first paragraph), Tech stack (the overview's table, without the entry point), Quick start (the setup section's "Run" subsection), Configuration (facts `config`), Structure (the structure diagram and the structure section's folder tree), Flows (facts `flows`), Owners (CODEOWNERS or git), footer (the oldest Dev Guide section). Old README claims are dropped, because nothing is copied from the old README; the ones the Dev Guide marked as contradictions are listed in the run's report.

## What the script guarantees

- Only what the Dev Guide and facts say; English; no code references and no marks; secrets as keys and placeholders, exactly as in the facts.
- Links relative to the README's folder. Docmost only when a page URL is known.

## Per-app README (`<app root>/README.md`, or the repo root for a single-app repo)

~~~markdown
# <App name>

<2–3 sentences: what it does, who calls it, what it calls. From Dev Guide §1.>

## Tech stack
| | |
|---|---|
| Language & framework | Go 1.22, Gin |
| Runs as | HTTP API on port 8080 |
| Talks to | SQL database (TXN_LOG, LEDGER_TRANS), Partner billing API |

## Quick start
<from Dev Guide §3: requirements in one line, then the exact commands>
```bash
cp .env.example .env    # fill in the keys below
make run
make test
```

## Configuration
| Key | Required | Meaning | Example / default |
|---|---|---|---|
<every key from the Dev Guide's configuration table, same placeholders>

## Structure
![<App name> structure](<structure_diagram>)

<the Dev Guide's folder tree, top two levels only>

## Flows
| Flow | Purpose |
|---|---|
<every flow from the Dev Guide's app-flow index, without code refs>

## Documentation
- [Dev Guide](<dev_guide>): how it works, with code references (English)
- [User Guide](<user_guide>): running and troubleshooting, for operators (Bahasa Indonesia)
- [Docmost](<docmost_url>)          ← only if docmost_url is set

## Owners
<from the plan's owners: CODEOWNERS entries as written, or "Most active in the last 6 months: Name <email>, …">

---
<sub>Docs generated from `<short verified_sha>` on `<verified_branch>`, <verified_date> (the oldest section of the Dev Guide).</sub>
~~~

## Root README in a monorepo (`README.md`)

~~~markdown
# <Repository name>

<1–2 sentences: what this repository holds, from the apps' overviews.>

## Apps
| App | Type | Stack | Path | What it does |
|---|---|---|---|---|
| [payment-api](services/payment-api/README.md) | backend | Go, Gin | `services/payment-api` | Creates and confirms payments |

## Running everything
<only what the Dev Guides say about running apps together (docker-compose, Makefile targets, shared infrastructure); otherwise one line pointing to each app's Quick start>

## Shared tooling
<only repo-wide tools the Dev Guides mention (linters, CI, code generation); omit the section if none>

## Documentation
<one line per app: Dev Guide · User Guide · Docmost (when set)>

## Owners
<root owners from the plan>

---
<sub>Docs generated from: <app>: `<short sha>` (<date>), …</sub>
~~~
