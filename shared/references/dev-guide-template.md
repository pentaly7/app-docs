# Dev guide template

Audience: a developer who has never seen this app and must change it safely next week. Software-engineering English. Concise but complete: one fact per sentence, no filler ("This section describes…", "It is important to note…"), no marketing. Prefer tables and numbered steps over paragraphs. Every process gets a `path:line` reference (conventions §5).

Structure below. Keep the anchors and subtitles exactly as conventions §3–4 say; the example values are illustrative.

---

```markdown
# <App name> — Dev Guide

<!-- docgen:section id="overview" -->
## 1. What is this app
> `a1b2c3d` · `main` · 2026-11-15 · verified by Rizki Tegar

<2–4 sentences: what business problem it solves, who/what calls it, what it calls.>

| | |
|---|---|
| Type | backend API / frontend / worker / CLI / library |
| Language & framework | Go 1.22, Gin |
| Entry point | `cmd/server/main.go:14` |
| Talks to | PostgreSQL `payments`, Kafka `order.created`, Midtrans API |
| Called by | `checkout-web`, `order-service` |

<!-- docgen:section id="structure" -->
## 2. How the app is structured
> …

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

<diagram (see diagrams.md)>

1. `PaymentHandler.Create` validates the body (`internal/handler/payment.go:42-60`); 400 on missing `order_id`.
2. `PaymentService.Create` locks the order row (`internal/service/payment.go:30-55`) …
3. …

**Errors:** <which errors, where produced, what the caller gets>
**Side effects:** <rows written, events published, external calls>

<!-- docgen:section id="data-flow" -->
## 6. Data flow
> …

<Diagram of where data comes from, where it's stored and where it goes (DFD). Then a table of datastores/queues: name, owner (this app or other), what is read/written, by which flows. Include data lifecycle: retention, soft delete, archival jobs if any.>

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
