# Conventions (template version 4)

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
11. Owners and escalation
12. Links to other apps

---

## 1. Two audiences, one truth

| | Dev doc | Operator guide |
|---|---|---|
| Reader | A developer who will maintain the app after you | An operator who investigates incidents without asking devs |
| Language | Software-engineering English | Semiformal Bahasa Indonesia: natural, no slang, no "Anda" and no "kamu", no em/en dashes. Tech terms stay English. Business/domain terms stay in their original form. Humanized as the last writing step with humanizer-indonesia (`humanizer.md`). |
| Code refs | `path:line` for every process **[checked]** | Never a file path or line number **[checked]**. Env var names, table/queue/topic names, URLs, log commands and CLI commands are allowed and encouraged. |
| Marks | Unverified, contradiction, security finding, removed, diagram-outdated | Only removed and diagram-outdated. Uncertain behavior is simply left out. |
| Diagrams | Structure, startup, flowchart + sequence per important flow, data-flow, all colored with a legend (`diagrams.md`) | The same files: structure and startup go in `how-it-works` |

Both docs describe the same code at the same commit. If they disagree, one of them is wrong. The validator compares the facts in each section that exists in both guides (numbers with units such as `30s` or `5 menit`, `ALL_CAPS` keys such as `PAYMENT_TIMEOUT_MS`, HTTP status codes) and warns on any fact the User Guide has and the Dev Guide doesn't **[checked, warning]**. It doesn't fix them: the final report lists each mismatch for a person to decide.

## 2. File layout

All paths are relative to the **repository root**. One `docs/` folder per repository.

```
docs/
├── .docgen/
│   ├── state.json            # global index (see state-schema.md)  — committed
│   ├── apps/<app-id>.json    # per-app section map               — committed
│   ├── facts/<app-id>.json   # every table and list, as data      — committed (facts-schema.md)
│   ├── .gitignore            # contains: .work/
│   └── .work/                # briefs, fragments, specs, reviews  — not committed
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
operator/04-data-flow.md  05-troubleshooting.md  05a-log-index.md  05b-alerts.md  05c-owners.md  06-glossary.md

dev/05b-state-machine/00-index.md  05b-state-machine/<NN>-<machine-id>.md        # only with fsm
operator/03b-state-machine/00-index.md  03b-state-machine/<NN>-<machine-id>.md   # only with fsm
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
  - operator: `setup`, `how-it-works`, `app-flow`, `data-flow`, `troubleshooting`, `log-index`, `alerts`, `owners`, `glossary`
  - both, only when the app has `fsm` on and a state machine was found: `state-machine` plus `state-machine/<machine-id>` per machine (`state-machines.md`)
- A flow has the ID `app-flow/<flow-id>` in **both** docs.
- `<flow-id>` is kebab-case and stable: `create-payment`, `consume-order-created`, `page-checkout`, `cron-daily-settlement`.

## 4. Section subtitle

The line directly under every anchored heading **[checked]**:

```markdown
> generated at `a1b2c3d` on `main`, 2026-11-15, run by Jane Doe
```

- Short SHA (7 characters), branch, date (YYYY-MM-DD), `git config user.name` of whoever ran the plugin. All four values come from `docs_tool.py meta`.
- It says **generated**, not verified: it records which commit the text was written from and who ran the plugin. Nobody signed off on it.
- Write the subtitle **without** a dirty mark. `docs_tool.py stamp` adds ` + uncommitted changes` afterwards, only to sections whose own files have uncommitted changes (and removes it once they're committed):
  ```markdown
  > generated at `a1b2c3d` + uncommitted changes on `feature/x`, 2026-11-15, run by Jane Doe
  ```
- Same format in the User Guide. It isn't a mark, it's provenance.
- Only update the subtitle of a section you actually re-checked.
- Docs from template version 2 (`· verified by`) are converted by `docs_tool.py migrate`; don't rewrite them by hand.

## 5. Code references

Dev Guide only. Every reference is a GitLab permalink pinned to the **section's** commit, so it opens the exact lines the text was written from, even after the code moves on **[checked]**:

```markdown
[`services/payment/internal/handler/payment.go:42-88`](https://gitlab.example.com/team/shop/-/blob/a1b2c3d4e5f6/services/payment/internal/handler/payment.go#L42-88)
[`app/Http/Controllers/OrderController.php:120`](https://gitlab.example.com/team/shop/-/blob/a1b2c3d4e5f6/app/Http/Controllers/OrderController.php#L120)
```

- The link base is `meta.web_url`; the commit is the full SHA from `meta.sha` for the section you're writing. Link text stays the plain `path:line` span, so the doc still reads well as plain text.
- Marks (§6) use the same linked form.
- `meta.web_url` is null (no `origin` remote): write the plain span without a link. The validator only asks for links when a remote exists.
- `meta.head_pushed` is false: write the links anyway. They 404 until the commit is pushed; the final report says so.
- The validator checks that the file exists at the section's commit, that the lines are within the file, that the link points at the section's commit, and warns when none of the functions named in the same sentence appear in the cited lines.
- No code snippets. Name the function or class in prose next to the reference: "`CreatePayment` handler ([`.../payment.go:42-88`](…)) validates the amount, then …".
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

**Filling them in.** A person replaces a prose placeholder with a **keep block**, which no rewrite removes:

```markdown
<!-- app-docs:keep -->
Deploy lewat ArgoCD, app `payment-prod`, namespace `payments`.
<!-- /app-docs:keep -->
```

Agents copy keep blocks unchanged; a script puts back any that a rewrite dropped, at the end of the same section. Rendered tables (alerts, owners and escalation) can't hold a keep block; their placeholder names the field to fill in the facts file instead (`manual.alerts`, `manual.owners`, `manual.escalation`, facts-schema.md).

Don't guess a team or a channel for alerts or escalation: the rendered tables print their own placeholder until someone fills `manual` in the facts file.

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

## 11. Owners and escalation

The User Guide's `owners` section tells an operator who to contact. Take it from `docs_tool.py owners --root <app root>`, never from memory or from names seen in commit messages **[checked: section exists]**:

- **CODEOWNERS covers the app:** its owners are both the owners and the escalation target. The script reads the first file GitLab would use (`CODEOWNERS`, then `docs/CODEOWNERS`, then `.gitlab/CODEOWNERS`) and applies GitLab's rules: last match wins inside a `[section]`, sections add up.
- **No rule covers it:** owners are the top 3 committers to the app's folder over the last 6 months, and escalation is the unknown placeholder (§8). Committers know the code; that doesn't make them on call.
- **Manual override:** `manual.owners` and `manual.escalation` in the facts file win over both. Use them when the escalation target isn't in CODEOWNERS.
- The table is rendered from a snapshot taken once per run, so it doesn't change between runs just because time passed.
- Write names and GitLab handles exactly as returned. Say where they came from ("dari CODEOWNERS", "dari riwayat commit 6 bulan terakhir"), so a reader knows how much to trust it.

## 12. Links to other apps

When a flow calls another app, link to that app's guide of the same kind: Dev Guide to Dev Guide, User Guide to User Guide. Take the targets from the prompt's "Other apps" list; never guess a path.

- **Same repo:** a relative link from this file to the other app's guide file (`../order-worker/operator-guide.md`), so it works in GitLab and in a local checkout.
- **Another repo in the workspace:** the GitLab link the prompt gives (`https://gitlab…/team/wallet/-/blob/main/docs/wallet/operator-guide.md`). Never a relative path that leaves the repo: it breaks in GitLab.
- **Not documented yet:** the app's name in backticks, no link.

Write the link in the markdown and nothing else. Sync turns a User Guide link into the target's Docmost page, or into plain text until that page exists; the markdown keeps its GitLab link.
