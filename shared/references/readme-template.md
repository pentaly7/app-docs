# README template

A README is the front door: someone lands on the repo or app folder in GitLab and needs to know what this is, how to run it, and where the full docs are. It's a **condensed copy of the Dev Guide**, written so it works on its own, and it's **rewritten in full** on every `/app-docs:readme` run.

## Rules

- **Source: the Dev Guide only.** Don't read application code. If the Dev Guide doesn't say it, the README doesn't either. The orchestrator has already confirmed with the user that the Dev Guide is recent enough.
- **English**, the same style as the Dev Guide: concise, one fact per sentence, no filler, no marketing.
- **No `path:line` references and no Unverified/Contradiction/Security marks.** A README is a summary, and the Dev Guide link covers detail. Short code names (`billing.Service`) are fine.
- **Secrets:** keys and placeholders only, exactly as in the Dev Guide's configuration table.
- **Diagrams:** embed the structure diagram (`structure_diagram` from the plan, a relative path). In Mermaid mode, copy the Dev Guide's structure Mermaid block.
- **Links are relative** to the README's own folder, from the plan (`dev_guide`, `user_guide`, `structure_diagram`). Docmost only when `docmost_url` is set. Leave it out otherwise, without a placeholder.
- **The old README:** read it before rewriting. Statements in it that the Dev Guide contradicts are dropped or corrected in the new text. List each one in your summary ("old README said X; Dev Guide says Y").

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
<sub>Docs last verified at `<short verified_sha>` on `<verified_branch>`, <verified_date>.</sub>
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
<sub>Docs last verified: <app>: `<short sha>` (<date>), …</sub>
~~~
