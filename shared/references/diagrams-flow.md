# Diagrams: flows (diagram version 8)

Flowcharts and sequence diagrams for one important flow, and the story under the sequence diagram. Read `diagrams.md` first.

## 4. Flowcharts: every branch

A flowchart shows **what decides what** inside the flow. Trace the code path and draw **every condition that changes the outcome**:

- validation failures, each distinct error or status code as its own exit
- auth/permission failures, not-found, conflict/duplicate/idempotency hits
- feature flags and config-driven switches (name the key)
- retries (count and backoff), timeouts (value and config key), circuit breakers, fallbacks
- caught exceptions and what happens next (rollback, compensate, log and continue)
- early returns, loops over items (show the loop with its exit condition)
- async hand-offs (publish and return, enqueue job), and what the caller gets at that point

Every path ends at a **success terminal** or an **error terminal**, or visibly rejoins another path. A decision diamond has every outgoing edge labelled with its condition (`valid`, `invalid → 400`, `order not found → 404`, `retry < 3`).

**Decision labels are short**, at most about 5 words (`issuer allowed?`, `state == 1 and not today?`). When the real condition is longer (several `and`/`or` parts, a list of values), put the **full condition in a Note** beside the diamond, connected with a dashed line without an arrow, and keep the short label in the diamond. Long text inside a diamond overflows its shape. **No step numbers in flowcharts.** Shapes say what happens. The steps in the text follow the flowchart top to bottom, without referring to numbers.

**Keep it readable:**
- **Down, and right for branches that go on.** A branch ending in a success/error end goes to the row below. A branch that continues with more steps (another decision, a fallback) goes right on the same row and runs down as its own column. The script works this out from the edges. Nothing goes up, except `rejoin` lines, which run down the shared channel and enter their target from above.
- **At most 3 lines of text per shape.** Keep the short part in the shape (`2. INSERT row`, with a timeout key or function name if it matters) and move the rest into a note. The script lists shapes over the limit in `long_labels`. Fix those and run it again.
- **Identical logic drawn twice is drawn once.** When parallel or repeated branches run the same steps (writing two log tables, with the same validation and fallback), draw the shared steps **once** as a `shared.<sub-id>` sub-flow. Point each branch at it with a sub-flow node that says which instance it is (`▶ Write row with SAF fallback: TXN_LOG via InsertTxnLog`).

## 5. Sequence diagrams

A sequence diagram shows **who calls whom, in order**, for the same flow. One per important flow. It should read like a story in pictures, so the script makes it rich. You decide what's in it:

- **Participants** left to right in call order: caller, this app (split into its main layers when it helps: handler, service, repository), other internal apps, datastores, queues, external systems. Give each its real `kind`: the header is drawn as a person (`client`), a cylinder (`db`), a folder (`file`), a bucket (`object`), a hexagon (`cache`), a cloud (`external`), or a box (`step`, `internal`).
- **Phases:** group the messages into 3–6 phases that name what is happening (`Receive & validate`, `Call partner`, `Map response`, `Write logs`, `Respond`). Each phase is a colored band with its name on the left.
- **Early exits are `break`, never nested `alt`.** "If the api_key is wrong, reply 401 and stop" is one small `break` box at that spot, and the happy path continues below it, unnested. Use `alt` only for two outcomes that both continue (Partner API error vs. 2xx reply), and give each block a `tone` (`ok` green, `error` red).
- **Message kinds:** `sync` (call), `async` (publish, enqueue), `reply`, `error`. Colors follow automatically: green for the happy path, red for errors, storage colors for storage access, grey for external systems.
- **Short arrow labels**, with the key detail in a **note** beside the lifeline: `{"note": "timeout CLIENT.PARTNER.TIMEOUT", "over": "svc"}`.
- Activation bars and arrow numbers are automatic.

**The story under the diagram.** The arrow numbers belong to the diagram, and the text walks through them in detail, in plain markdown that renders the same everywhere:

- One **bold heading per phase band**, with a **capital letter**: `**A. Receive and validate**`, `**B. Call the partner**`, …
- Under it, a normal markdown **numbered list**, one item per arrow, and **the item number is the arrow number**. Phases cover consecutive arrows, so phase B's list simply starts where A's ended (`5.`, `6.`, …), and every number matches its circle in the diagram.
- Leave a blank line between items, so each arrow reads as its own short paragraph.
- Every arrow in the diagram gets its item, in order.

Each item says, where it applies:
- **what moves:** the call or message and the data passed (fields, headers, body shape)
- **what decides:** the condition that picks this branch, and what happens on the other branch
- **what is written or logged:** the table and columns, file and path, log message text and level
- **limits:** timeouts and retries, with their values and config keys
- **the result:** response code and body
- **errors:** what the caller gets on each error path, and whether anything else still happens (rows still written, nothing written)
- **what outlives the request:** queued for replay, picked up by a cron job, an event others consume

Errors (`break`, `alt`) are described **inside** their phase, in the item of the arrow that carries them.

**Dev guide:** each item carries its code references **inline**, in parentheses right after the part of the sentence they back up: repo-relative file and lines (`path:line` or `path:start-end`), validated like every code reference. A sentence that touches two places gets both:

```markdown
**A. Receive and validate**

1. The caller sends `POST /inquiry` with an `InquiryRequest` JSON body and the `api_key` header (`internal/server/router.go:41`).

2. The logger middleware starts a transaction and logs the request as step 1 `IN` at INFO, before any check runs (`internal/server/middleware/logger.go:18-37`).

3. If `api_key` doesn't equal `SERVER.API_KEY`, the handler answers `401 {message: "invalid api key"}` (`internal/server/auth.go:22-35`). No transaction-log or ledger row is written, and the flow stops here.

**B. Take the file**

5. `drain` renames `SAF` to `SAF.loaded-<YYYY-MM-DD HH:MM:SS>` under the queue mutex (`internal/repository/saf.go:60`, `internal/repository/saf.go:162-167`). Producers that push after the rename create a fresh `SAF` file, and entries pushed during the drain wait for the next tick (`internal/repository/saf.go:131-159`).
```

**User Guide:** the same headings and numbered items in Bahasa Indonesia, with no code references. Instead, each item adds what an operator sees and checks: the **log message** at that point (text and level), the **table or file** to look in, **how long** the step may take (timeout and its key), and **what the caller sees**:

```markdown
**A. Terima dan validasi**

1. Caller mengirim `POST /inquiry` berisi `InquiryRequest` dengan header `api_key`.

2. Request dicatat di log sebagai step 1 `IN` (level INFO) sebelum pemeriksaan apa pun.

3. Jika `api_key` tidak sama dengan `SERVER.API_KEY`, caller menerima `401 {message: "invalid api key"}`. Tidak ada row di `TXN_LOG` maupun `LEDGER_TRANS`, dan proses berhenti di sini.
```

The story can be long. Detail is the point here. The steps under the flowchart stay detailed too: they explain the **logic** (each decision and rule) top to bottom, and the story explains the **interaction** (who calls whom, with what, in what order).

