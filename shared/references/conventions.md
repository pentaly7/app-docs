# Conventions (template version 2)

Every agent and script in this plugin follows this file. The validator (`docs_tool.py validate`) checks the parts marked **[checked]**, so breaking them shows up as a failure in the report.

## Contents
1. Two audiences, one truth
2. File layout
3. Section anchors and IDs
4. Section subtitle
5. Code references
6. Marks (dev doc only, with two exceptions)
7. Secrets
8. Unknown deployment facts
9. Flows: important vs. listed
10. When to split a doc

---

## 1. Two audiences, one truth

| | Dev doc | Operator guide |
|---|---|---|
| Reader | A developer who will maintain the app after you | An operator who investigates incidents without asking devs |
| Language | Software-engineering English | Semiformal Bahasa Indonesia: natural, no slang, no "Anda" and no "kamu", no em/en dashes. Tech terms stay English. Business/domain terms stay in their original form. Humanized as the last writing step with humanizer-indonesia (`humanizer.md`). |
| Code refs | `path:line` for every process **[checked]** | Never a file path or line number **[checked]**. Env var names, table/queue/topic names, URLs, log commands and CLI commands are allowed and encouraged. |
| Marks | Unverified, contradiction, security finding, removed, diagram-outdated | Only removed and diagram-outdated. Uncertain behavior is simply left out. |
| Diagrams | Structure, startup, flowchart + sequence per important flow, data-flow, all colored with a legend (`diagrams.md`) | The same files: structure and startup go in `how-it-works` |

Both docs describe the same code at the same commit. If they disagree, one of them is wrong.

## 2. File layout

All paths are relative to the **repository root**. One `docs/` folder per repository.

```
docs/
├── .docgen/
│   ├── state.json            # global index (see state-schema.md)  — committed
│   ├── apps/<app-id>.json    # per-app section map               — committed
│   ├── .gitignore            # contains: .work/
│   └── .work/                # review findings, scratch           — not committed
└── <app-id>/
    ├── dev-guide.md          # single mode
    ├── operator-guide.md     # single mode
    ├── dev/                  # split mode (replaces dev-guide.md)
    ├── operator/             # split mode (replaces operator-guide.md)
    └── diagrams/              # draw.io mode; names in diagrams.md §3
        ├── <flow-id>.flow.drawio.svg
        ├── <flow-id>.seq.drawio.svg
        └── ...
```

`<app-id>`: kebab-case of the app folder name (`services/payment-api` → `payment-api`). On a name collision, use the full path (`services-payment-api`). A repo whose root is the app uses the repo name.

Split mode file names (number prefix keeps Docmost order):

```
dev/01-overview.md  02-structure.md  03-setup.md  04-startup.md
dev/05-app-flow/00-index.md  05-app-flow/<NN>-<flow-id>.md
dev/06-data-flow.md  07-dev-notes.md  08-glossary.md

operator/01-setup.md  02-how-it-works.md
operator/03-app-flow/00-index.md  03-app-flow/<NN>-<flow-id>.md
operator/04-data-flow.md  05-troubleshooting.md  06-glossary.md
```

## 3. Section anchors and IDs

Put an anchor comment on the line directly above every `##` and `###` heading the plugin owns:

```markdown
<!-- docgen:section id="app-flow/create-payment" -->
### Create payment (`POST /v1/payments`)
```

- IDs are stable. Never derive them from the heading text, which can be translated or reworded. Use the flow ID for flows.
- Top-level IDs **[checked]**:
  - dev: `overview`, `structure`, `setup`, `startup`, `app-flow`, `data-flow`, `dev-notes`, `glossary`
  - operator: `setup`, `how-it-works`, `app-flow`, `data-flow`, `troubleshooting`, `glossary`
- A flow has the ID `app-flow/<flow-id>` in **both** docs.
- `<flow-id>` is kebab-case and stable: `create-payment`, `consume-order-created`, `page-checkout`, `cron-daily-settlement`.

## 4. Section subtitle

The line directly under every anchored heading **[checked]**:

```markdown
> `a1b2c3d` · `main` · 2026-11-15 · verified by Rizki Tegar
```

- Short SHA (7 characters), branch, date (YYYY-MM-DD), `git config user.name` of whoever ran the plugin. All four values come from `docs_tool.py meta`.
- Dirty working tree (`meta.dirty` true):
  ```markdown
  > `a1b2c3d` + uncommitted changes · `feature/x` · 2026-11-15 · verified by Rizki Tegar
  ```
- Same format in the operator guide. It isn't a mark, it's provenance.
- Only update the subtitle of a section you actually re-checked.

## 5. Code references

Dev doc only. Format: a backtick span holding a repo-root-relative path, a colon, and a line or line range **[checked]**:

```
`services/payment/internal/handler/payment.go:42-88`
`app/Http/Controllers/OrderController.php:120`
```

- The validator checks that the file exists at the section's commit and that the lines are within the file.
- No code snippets. Name the function or class in prose next to the reference: "`CreatePayment` handler (`.../payment.go:42-88`) validates the amount, then …".
- Reference where the process **runs**, not only where it's declared.

## 6. Marks

Each mark is a blockquote line that starts with the marker exactly as shown, so it can be found by grep.

Dev doc only:

```markdown
> ⚠️ **Unverified:** <what is unclear, one sentence>. Original author: <name> (`<short-sha>`, <YYYY-MM-DD>).
> ⚠️ **Contradiction:** <source, e.g. README.md> says <X>; code does <Y> (`path:line`).
> 🔒 **Security finding:** <what, e.g. hardcoded DB password> at `path:line` (value redacted).
```

- Get the original author with `docs_tool.py author <file> <start> <end>`. Write whatever it returns, even an "initial import" commit or a bot account. Don't look for a better name.
- Every security finding also goes into the **Security findings** list in `dev-notes`.
- Contradictions come from READMEs, old docs, wiki exports or code comments that disagree with the code. The code is the truth. Describe what the code does, and mark the contradiction.

Both docs:

```markdown
> 🗑️ **Removed in `<short-sha>`** (<YYYY-MM-DD>): <one line on what replaced it, or "no replacement">.
> 🖼️ **Diagram possibly outdated:** code changed in `<short-sha>`; rerun with draw.io to redraw.
```

- Removed sections stay in the doc, marked. Never delete them.
- "Diagram possibly outdated" appears only when a section has a `.drawio.svg` diagram, its code changed, and the current run has no draw.io. Leave the old diagram in place.

## 7. Secrets

- Config sections list **keys only**, with a placeholder that shows the expected shape: `DB_PASSWORD=<database password>`, `PAYMENT_GATEWAY_URL=<https://gateway.example.com>`, `JWT_TTL=<seconds, e.g. 3600>`.
- Never copy a real value from `.env*`, config files, CI variables or source code, in either doc **[checked]**. Non-secret defaults (ports, timeouts, feature flags) may be shown as "default: 8080".
- Hardcoded secrets found in source → security-finding mark plus a dev-notes entry, value redacted.

## 8. Unknown deployment facts

Operators need production facts (where logs go, health check URL, per-environment config, how it's deployed) that often live outside the repo. Look in Dockerfile, docker-compose, Helm/k8s manifests, `.gitlab-ci.yml`, Procfile, systemd units and Makefile first. When nothing in the repo says, write the placeholder (it isn't an uncertainty mark, so it appears in both docs):

- Dev: `_Unknown — not in this repository. Fill in manually._`
- Operator: `_Belum diketahui: tidak ada di repository ini. Mohon diisi manual._`

## 9. Flows: important vs. listed

A **flow** is one entry point into the app: HTTP endpoint, gRPC method, queue/topic consumer, scheduled job, CLI command, or (frontend) a page/route.

- Every detected flow appears in **both** docs and in `apps/<app-id>.json` **[checked]**.
- **Important** flows get a full subsection with steps, a flowchart and a sequence diagram **[checked]**. The rest go in a table in the `app-flow` index (dev: flow, purpose, `path:line`; operator: flow, purpose, what to check when it fails).
- Choose importance from the code alone. Rank higher when a flow:
  - moves money or changes balances
  - does auth or permissions
  - writes to a datastore or publishes events
  - calls external systems
  - fans out to many internal calls
  - is a scheduled/batch job (failures are silent)
  - is on the main user journey (frontend)

  Lower: health/metrics endpoints, static pages, thin CRUD reads. As a rule of thumb, an app with 10 or fewer flows documents all of them fully. Larger apps fully document roughly the top third, at least 10, and list the rest. Grouping in the index follows the code's own modules/domains.

## 10. When to split a doc

Split mode (one file per section, one Docmost page per file) when **any** is true:
- The repo has more than 10 apps. Then **all** apps in it split.
- A backend app has more than 50 HTTP/gRPC endpoints.
- A frontend app has more than 10 pages/routes.

Workers, consumers, CLIs, cron apps and libraries otherwise always use single mode.
