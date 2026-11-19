# Dev guide template

Audience: a developer who has never seen this app and must change it safely next week. Software-engineering English. Concise but complete: one fact per sentence, no filler ("This section describes…", "It is important to note…"), no marketing. Prefer tables and numbered steps over paragraphs. Every process gets a `path:line` reference (conventions §5).

Structure below. Keep the anchors and subtitles exactly as conventions §3–4 say; the example values are illustrative.

---

```markdown
# <App name> — Dev Guide

<!-- docgen:section id="overview" -->
## 1. What is this app
> `a1b2c3d` · `main` · 2026-11-15 · verified by Jane Doe

<2–4 sentences: what business problem it solves, who/what calls it, what it calls.>

| | |
|---|---|
| Type | backend API / frontend / worker / CLI / library |
| Language & framework | Go 1.22, Gin |
| Entry point | `cmd/server/main.go:14` |
| Talks to | PostgreSQL `payments`, Kafka `order.created`, PayGate API |
| Called by | `checkout-web`, `order-service` |

<!-- docgen:section id="structure" -->
## 2. How the app is structured
> …

<structure diagram (diagrams.md §6)>

<Folder tree, two or three levels, only folders that matter, one comment per line.>
<Then: layering rules a dev must respect (e.g. handlers never touch the DB directly), each with path:line evidence.>

<!-- docgen:section id="setup" -->
## 3. Setup
> …

### Requirements
<runtimes, services (DB, broker, cache) and versions, from build files / docker-compose>

### Configuration
| Key | Required | Meaning | Example / default |
|---|---|---|---|
| `DB_DSN` | yes | Postgres connection string | `<postgres://user:password@host:5432/db>` |
Where config is loaded: `internal/config/config.go:20-61`.

### Run
<exact commands: install, migrate, run, test — copied from Makefile/package.json/README when they still work>

### Deployment
<what the repo shows (Dockerfile, CI, Helm), or the Unknown placeholder from conventions §8>

<!-- docgen:section id="startup" -->
## 4. Startup
> …

<startup diagram (diagrams.md §6)>

<Numbered sequence from process start to "ready to serve": config load, DI/wiring, connections, migrations, background workers, server listen. Each step with path:line. State what makes startup fail fast.>

<!-- docgen:section id="app-flow" -->
## 5. App flow
> …

<Index table of ALL flows, grouped by module/domain:>
| Flow | Purpose | Code |
|---|---|---|
| `POST /v1/payments` | Create a payment | `internal/handler/payment.go:42-88` |

<!-- docgen:section id="app-flow/create-payment" -->
### 5.1 Create payment (`POST /v1/payments`)
> …

**Flowchart**

![Create payment: flowchart](diagrams/create-payment.flow.drawio.svg)

<one image per sub-flow, captioned "Sub-flow ▶ <name>:">

<steps in the order the flowchart shows them; the flowchart itself has no numbers:>
1. `PaymentHandler.Create` validates the body (`internal/handler/payment.go:42-60`); 400 on missing `order_id`.
2. `PaymentService.Create` locks the order row (`internal/service/payment.go:30-55`) …
3. …

**Errors:** <every error branch in the flowchart: where it's produced (path:line), what the caller gets>
**Side effects:** <rows written, events published, external calls>

**Sequence**

![Create payment: sequence](diagrams/create-payment.seq.drawio.svg)

<The detailed story (diagrams.md §5): a bold capital-letter heading per phase, then a numbered list whose item numbers are the arrow numbers, each item with its code references inline:>
**A. Receive and validate**

1. The client sends `POST /v1/payments` with `{order_id, amount}` and a bearer token (`internal/router.go:22`).

2. `PaymentHandler.Create` validates the body. If `order_id` is missing it answers `400 {error: "order_id required"}` and nothing is written (`internal/handler/payment.go:42-60`).

**B. …**

<!-- docgen:section id="state-machine" -->
## State machines          ← only when the app has fsm on and a machine was found (state-machines.md §6)
> …

<which machines exist, and how they drive each other: state-overview diagram when 2+>

<!-- docgen:section id="state-machine/payment-status" -->
### Payment status (`payments.status`)
> …

<state diagram, transition table with path:line, initial / final / unreachable / dead-end states, Unverified marks for inferred names>

<!-- docgen:section id="data-flow" -->
## 6. Data flow
> …

<Diagram of where data comes from, where it's stored and where it goes (DFD). Then a table of every place data lives: name, **storage type** (database / file storage / object storage / cache / queue / other) and where exactly (engine, path, bucket), owner (this app or other), what is read/written (full field lists go here), by which flows. Include data lifecycle: retention, soft delete, archival jobs if any.>

<!-- docgen:section id="dev-notes" -->
## 7. Dev notes
> …

### Gotchas
<non-obvious behavior, ordering rules, hidden coupling, each with path:line>

### Unverified
<one line per Unverified mark in this doc, linking the section>

### Contradictions
<one line per Contradiction mark>

### Security findings
<one line per Security finding mark, value redacted>

### Tech debt
<only what you saw in code: dead code, TODO/FIXME clusters, deprecated libs, with path:line>

<!-- docgen:section id="glossary" -->
## 8. Glossary
| Term | Meaning in this app |
|---|---|
| Settlement | Daily batch that marks captured payments as paid out (`cron-daily-settlement`) |
```

---

## A good flow step vs. a weak one

Weak: "The service handles the payment and saves it to the database."
Good: "`PaymentService.Create` (`internal/service/payment.go:30-55`) inserts a `payments` row with status `PENDING` inside the same transaction that locks `orders.id`, so a retry with the same `order_id` returns the existing payment instead of creating a second one."

The good version names the code, says where it runs, what it writes, and the behavior a maintainer would otherwise trip over.
