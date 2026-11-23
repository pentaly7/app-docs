# Dev guide template

Audience: a developer who has never seen this app and must change it safely next week. Software-engineering English. Concise but complete: one fact per sentence, no filler ("This section describes…", "It is important to note…"), no marketing. Prefer tables and numbered steps over paragraphs. Every process gets a `path:line` reference, written as a GitLab permalink pinned to the section's commit (conventions §5). In this template `(…)` stands for that permalink: `<meta.web_url>/-/blob/<meta.sha>/<path>#L42-60`. Never leave `(…)` in a real doc.

Structure below. Keep the anchors and subtitles exactly as conventions §3–4 say; the example values are illustrative. Tables and lists marked `docgen:render` are filled by `docs_tool.py render` from the facts file (`facts-schema.md`): write the facts, leave the markers empty.

---

```markdown
# <App name> — Dev Guide

<!-- docgen:section id="overview" -->
## 1. What is this app
> generated at `a1b2c3d` on `main`, 2026-11-15, run by Jane Doe

<2–4 sentences: what business problem it solves, who/what calls it, what it calls.>

| | |
|---|---|
| Type | backend API / frontend / worker / CLI / library |
| Language & framework | Go 1.22, Gin |
| Entry point | [`cmd/server/main.go:14`](…) |
| Talks to | PostgreSQL `payments`, Kafka `order.created`, PayGate API |
| Called by | `checkout-web`, `order-service` |

<!-- docgen:section id="structure" -->
## 2. How the app is structured
> …

<structure diagram (diagrams-app.md §6)>

<Folder tree, two or three levels, only folders that matter, one comment per line.>
<Then: layering rules a dev must respect (e.g. handlers never touch the DB directly), each with path:line evidence.>

<!-- docgen:section id="setup" -->
## 3. Setup
> …

### Requirements
<runtimes, services (DB, broker, cache) and versions, from build files / docker-compose>

### Configuration
<!-- docgen:render id="config" -->
<!-- /docgen:render -->

### Run
<exact commands: install, migrate, run, test — copied from Makefile/package.json/README when they still work>

### Deployment
<what the repo shows (Dockerfile, CI, Helm), or the Unknown placeholder from conventions §8>

<!-- docgen:section id="startup" -->
## 4. Startup
> …

<startup diagram (diagrams-app.md §6)>

<Numbered sequence from process start to "ready to serve": config load, DI/wiring, connections, migrations, background workers, server listen. Each step with path:line. State what makes startup fail fast.>

<!-- docgen:section id="app-flow" -->
## 5. App flow
> …

<One or two sentences on how the flows group (modules/domains). The index of ALL flows is rendered:>
<!-- docgen:render id="flow-index" -->
<!-- /docgen:render -->

<One placeholder line per important flow, in index order. The flow agent writes the section (flow-template.md), and `docs_tool.py assemble` puts it here.>
<!-- docgen:flow id="create-payment" -->

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

<Diagram of where data comes from, where it's stored and where it goes (DFD). Then the rendered table of every place data lives (facts `storage`: full field lists, flows, retention):>

<!-- docgen:render id="storage" -->
<!-- /docgen:render -->

<Prose only for lifecycle the table can't carry: archival jobs, soft delete rules.>

<!-- docgen:section id="dev-notes" -->
## 7. Dev notes
> …

### Gotchas
<!-- docgen:render id="notes:gotchas" -->
<!-- /docgen:render -->

### Unverified
<!-- docgen:render id="notes:unverified" -->
<!-- /docgen:render -->

### Contradictions
<!-- docgen:render id="notes:contradictions" -->
<!-- /docgen:render -->

### Security findings
<!-- docgen:render id="notes:security" -->
<!-- /docgen:render -->

### Tech debt
<!-- docgen:render id="notes:tech-debt" -->
<!-- /docgen:render -->

<!-- docgen:section id="glossary" -->
## 8. Glossary
<!-- docgen:render id="glossary" -->
<!-- /docgen:render -->
```

---

## A good flow step vs. a weak one

Weak: "The service handles the payment and saves it to the database."
Good: "`PaymentService.Create` ([`internal/service/payment.go:30-55`](…)) inserts a `payments` row with status `PENDING` inside the same transaction that locks `orders.id`, so a retry with the same `order_id` returns the existing payment instead of creating a second one."

The good version names the code, says where it runs, what it writes, and the behavior a maintainer would otherwise trip over.
