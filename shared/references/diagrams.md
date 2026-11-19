# Diagrams (diagram version 8)

Diagrams are the first thing readers look at, so they carry the detail. They are **colorful, complete and exact**: every branch the code can take, real names, real values. The validator checks the parts marked **[checked]**.

## Contents
1. Which diagrams, where
2. Mode and layout: never place shapes by hand
3. Files and embedding
4. Flowcharts: every branch
5. Sequence diagrams
6. Structure, startup, data-flow
7. Detail inside the diagram
8. Colors, shapes, legend
9. Sub-flows instead of size limits
10. Mixed docs on update
11. Mermaid version
12. State diagrams (only with `fsm`)
13. Diagram spec format (input of `diagram_layout.py`)

---

## 1. Which diagrams, where

| Diagram | Dev guide section | Operator guide section |
|---|---|---|
| Structure (components and how they connect) | `structure` | `how-it-works` |
| Startup flowchart | `startup` | `how-it-works` |
| Flowchart per important flow, with sub-flows | `app-flow/<flow-id>` | `app-flow/<flow-id>` |
| Sequence diagram per important flow | `app-flow/<flow-id>` | `app-flow/<flow-id>` |
| Data-flow diagram | `data-flow` | `data-flow` |
| State diagram per state machine, plus an overview when 2+ machines drive each other (only when the app has `fsm` on; see `state-machines.md`) | `state-machine/<machine-id>` | `state-machine/<machine-id>` |

Every cell above is required **[checked]**. Both docs use the **same files**, with English labels, so they never disagree. Flows that are only listed in the index table get no diagram.

## 2. Mode and layout: never place shapes by hand

The orchestrator gives you the mode and, in draw.io mode, the layout engine. Don't guess.

**You never place shapes or route lines.** You write a small JSON **spec** of what is in the diagram (section 13): nodes, edges, which nodes form the happy path, notes, zones, sequence messages. The plugin's layout script places and routes everything with Graphviz and writes a styled, editable draw.io file:

```
python3 <Shared>/scripts/diagram_layout.py docs/.docgen/.work/<diagram-id>.json -o docs/.docgen/.work/<diagram-id>.drawio --preview docs/.docgen/.work/<diagram-id>.preview.svg < /dev/null
```

What the script guarantees, so you don't have to:
- **Flowcharts:** **top-down**, with **rounded** line corners and **no step numbers**. The happy path (`"spine": true`) is one dead-straight vertical column. A decision's branch that simply **ends** (success/error end, storage, external system) goes to the row **below**. A branch that **goes on** to more steps goes **right** on the same row and becomes its own column, which runs down in turn, with its notes on its right. Lines end on the diamond's edge. Notes sit **left** of the shape they explain, joined by a dashed line without an arrow. The script reports shapes with more than 3 lines of text (`long_labels`). Error paths that continue to a later step (`"kind": "rejoin"`) run down **one shared channel** on the right instead of crossing the diagram.
- **Data-flow / structure:** zones (Callers, the app, External systems, Storage) as labelled containers, top to bottom in the direction the data moves. Data going back to an earlier zone doesn't reorder them.
- **Sequence:** one row per message and a **numbered dark circle** at the start of every arrow (like Mermaid's `autonumber`). Participants drawn as what they are (a person for callers, a cylinder for databases, a cloud for external systems). **Arrows colored by meaning**: green happy path, red errors and early exits, the storage color for database/file/bucket/cache access, grey for external systems; replies dashed in the same color. **Phase bands** behind groups of messages, **activation bars** while a participant is busy, `alt`/`opt`/`break` boxes **tinted** green or red, and yellow **notes** beside a lifeline. Self-call labels sit right of their loop, and boxes widen to fit their labels.
- **Labels:** every line label is moved along its own line to a spot that doesn't touch a shape, another label or another line. Sideways lines get room for their label.
- **All:** the colors in section 8 and a legend of exactly the kinds used.

Then, in draw.io mode:
1. Export the editable SVG with the draw.io CLI: `drawio -x -f svg -e -o docs/<app-id>/diagrams/<diagram-id>.drawio.svg docs/.docgen/.work/<diagram-id>.drawio < /dev/null` (the draw.io skill describes the CLI per platform). Keep the spec, `.drawio` and previews in `.work/`.
2. Read the script's output: `label_overlaps` must be `0`. If it isn't, shorten the labels it points to (full detail goes in the table or steps under the diagram) and run it again. Then look at the rendered result (a PNG export, or the `--preview` SVG). If it's hard to read, change the **spec** (shorter labels, a sub-flow, `rejoin` instead of `error`, a note instead of a long diamond label) and run the script again. Never edit coordinates in the `.drawio` file.
3. The orchestrator applies the light/dark theme to every `.drawio.svg` after you finish (section 8). Don't add your own dark-mode styling.

**mermaid** mode: fenced ` ```mermaid ` blocks in the markdown, identical in both docs. Mermaid lays itself out. Section 11 shows the colors. The spec rules (spine, side exits, rejoin) still guide what you write, even though Mermaid can't enforce them.

## 3. Files and embedding

```
docs/<app-id>/diagrams/
  structure.drawio.svg
  startup.drawio.svg
  data-flow.drawio.svg
  <flow-id>.flow.drawio.svg            # main flowchart          [checked: ".flow." in name]
  <flow-id>.flow.<sub-id>.drawio.svg   # sub-flow of that flow
  shared.<sub-id>.drawio.svg           # sub-flow reused by 2+ flows
  <flow-id>.seq.drawio.svg             # sequence diagram        [checked: ".seq." in name]
  <machine-id>.state.drawio.svg        # state diagram (fsm)     [checked: ".state." in name]
  (specs, .drawio sources, previews)   → docs/.docgen/.work/
  state-overview.drawio.svg            # how machines drive each other (fsm, 2+ machines)
```

Embed each with a caption line, without em/en dashes because the operator guide uses the same lines (paths relative to the markdown file; split-mode files sit deeper, so adjust `../`):

```markdown
**Flowchart**

![Create payment: flowchart](diagrams/create-payment.flow.drawio.svg)

Sub-flow ▶ Validate request:

![Create payment, sub-flow validate request](diagrams/create-payment.flow.validate-request.drawio.svg)

**Sequence**

![Create payment: sequence](diagrams/create-payment.seq.drawio.svg)
```

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

## 6. Structure, startup, data-flow

- **Structure**: the app's components (handlers, services, workers, schedulers, repositories, caches, clients) and how they connect, plus everything outside the app it talks to. Group the app's components inside one container labelled with the app name. Arrows labelled with protocol and purpose (`HTTP JSON`, `gRPC`, `SQL`, `publishes order.created`).
- **Startup**: flowchart from process start to "ready", in code order: config load and validation, logger, DI/wiring, connections (with retry/timeouts), migrations, workers/schedulers, server listen, readiness. Every fail-fast condition is an error terminal (`missing DB_DSN → exit 1`).
- **Data-flow**: the app's components with the data on the arrows, grouped into zones: `Callers` (first), the app, `External systems`, then **one zone per storage type** so the reader sees where data lands: `Database (<engine>)`, `File storage (<where>)`, `Object storage (<provider>)`, `Cache (<engine>)`, `Other storage`. Only zones that have something in them. Each storage node uses its storage kind (section 8) and its label names the actual thing: the table (`TXN_LOG (table)`), the path (`logs/app.YYYY-MM-DD.log`), the bucket and prefix (`s3://docs/uploads/`), the key pattern (`session:{id}`). The same storage zones are used in the structure diagram. Keep arrow labels **short** (a few words: `INSERT TXN_LOG row`, `POST inquiry / reply`) and give the full field lists in the table under the diagram. Long labels on arrows collide with each other. A two-way exchange is one edge with `"both": true`. Include retention/cleanup jobs if they exist.

## 7. Detail inside the diagram

Put the facts a reader would otherwise have to dig out of code **in the diagram**:

| Element | Show |
|---|---|
| Entry | HTTP method + path, or topic/queue name, or cron schedule, or CLI command |
| Process step | what it does, and the function/class (`Lock order: OrderRepo.LockForUpdate`) |
| Decision | the actual condition (`amount <= 0?`, `status == PAID?`) |
| Datastore | table and the operation with columns (`payments: INSERT id, order_id, amount, status=PENDING`) |
| Queue/topic | name and payload fields (`order.created {order_id, total, items[]}`) |
| External call | system, endpoint, timeout and its config key (`PayGate POST /v2/charge · timeout 5s (PAYMENT_TIMEOUT_MS)`) |
| Retry | count, backoff, config key (`retry ×3, backoff 2s (CHARGE_RETRY)`) |
| Error terminal | status code / outcome and message (`502 gateway_timeout`, `payment stays PENDING`) |
| Success terminal | response code and body summary (`201 {payment_id, status}`) |

No file paths in diagrams (they're shared with the operator guide). Function and class names are fine.

## 8. Colors, shapes, legend

Every diagram is colored by **component kind** and by **outcome**, and has a legend **[checked]**. You draw with the **light** palette below. All text is dark (`#1A1A1A`) except on the start node.

**Dark mode** is added afterwards by the orchestrator (`docs_tool.py svg-theme`). It removes draw.io's own automatic dark colors (the muddy browns), then adds the dark palette in the right-hand column, which the SVG switches to when the viewer is in dark mode. If the first Docmost sync shows that images don't follow Docmost's theme toggle, the theme is switched to **always light** for every diagram. The editable diagram inside the SVG always keeps the light palette.

| Kind | Shape | draw.io style |
|---|---|---|
| Start, step-number circles | pill / circle | `fillColor=#2F2F2F;strokeColor=#2F2F2F;fontColor=#FFFFFF;` |
| Client / user | rounded pill | `rounded=1;arcSize=50;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;fontColor=#1A1A1A;` |
| Step in this app | rounded box | `rounded=1;whiteSpace=wrap;html=1;fillColor=#E1D5E7;strokeColor=#9673A6;fontColor=#1A1A1A;` |
| Sub-flow reference | predefined process | `shape=process;whiteSpace=wrap;html=1;backgroundOutline=1;fillColor=#E1D5E7;strokeColor=#9673A6;fontColor=#1A1A1A;fontStyle=1;` |
| Decision | diamond | `rhombus;whiteSpace=wrap;html=1;fillColor=#FFF2CC;strokeColor=#D6B656;fontColor=#1A1A1A;` |
| Database (table, collection) — spec kind `db` | cylinder | `shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=10;fillColor=#D5E8D4;strokeColor=#82B366;fontColor=#1A1A1A;` |
| File storage (local disk, NFS, SFTP) — `file` | folder | `shape=folder;tabWidth=46;tabHeight=12;tabPosition=left;fillColor=#F0E2C8;strokeColor=#A0844F;fontColor=#1A1A1A;` |
| Object storage (S3, GCS, MinIO bucket) — `object` | bucket (trapezoid) | `shape=trapezoid;flipV=1;size=0.1;fillColor=#F2D7E9;strokeColor=#A65C8C;fontColor=#1A1A1A;` |
| Cache / in-memory store (Redis, Memcached) — `cache` | hexagon | `shape=hexagon;size=0.08;fillColor=#E2EFDA;strokeColor=#548235;fontColor=#1A1A1A;` |
| Other storage (search index, etc.) — `store` | dashed cylinder | `shape=cylinder3;dashed=1;fillColor=#EEF3EE;strokeColor=#7A8C7A;fontColor=#1A1A1A;` |
| Queue / topic | parallelogram | `shape=parallelogram;perimeter=parallelogramPerimeter;whiteSpace=wrap;html=1;fixedSize=1;fillColor=#FFE6CC;strokeColor=#D79B00;fontColor=#1A1A1A;` |
| Other internal app | rounded box | `rounded=1;whiteSpace=wrap;html=1;fillColor=#B0E3E6;strokeColor=#0E8088;fontColor=#1A1A1A;` |
| External system | dashed box | `rounded=0;dashed=1;whiteSpace=wrap;html=1;fillColor=#F5F5F5;strokeColor=#666666;fontColor=#1A1A1A;` |
| Success terminal | pill, bold | `rounded=1;arcSize=50;whiteSpace=wrap;html=1;fillColor=#A9DFBF;strokeColor=#1E8449;fontColor=#1A1A1A;fontStyle=1;` |
| Error terminal | pill, bold | `rounded=1;arcSize=50;whiteSpace=wrap;html=1;fillColor=#F8CECC;strokeColor=#B85450;fontColor=#1A1A1A;fontStyle=1;` |
| Note (full condition) | note | `shape=note;size=12;whiteSpace=wrap;html=1;align=left;spacingLeft=6;fillColor=#FFF9DB;strokeColor=#D6B656;fontColor=#1A1A1A;` + connector `endArrow=none;dashed=1;strokeColor=#D6B656;` |

Dark palette applied by `svg-theme` (for reference; never draw with it):

| Kind | Light fill / stroke | Dark fill / stroke |
|---|---|---|
| Background | `#FFFFFF` | `#1E1E1E` |
| Text | `#1A1A1A` | `#E8E8E8` |
| Normal edges and arrowheads | `#333333` | `#B0B0B0` |
| Start, initial/final, step-number circles | `#2F2F2F` (white text) | `#5A5A5A` / `#8A8A8A` (light text) |
| Client / user | `#DAE8FC` / `#6C8EBF` | `#1F3A5F` / `#6C9BD2` |
| Step in this app, sub-flow, state | `#E1D5E7` / `#9673A6` | `#3B2A4F` / `#B39DDB` |
| Decision | `#FFF2CC` / `#D6B656` | `#4A3F12` / `#E0C35A` |
| Database | `#D5E8D4` / `#82B366` | `#1E4024` / `#7BC47F` |
| File storage | `#F0E2C8` / `#A0844F` | `#3D3220` / `#C9A86A` |
| Object storage | `#F2D7E9` / `#A65C8C` | `#4A2440` / `#D58BBF` |
| Cache | `#E2EFDA` / `#548235` | `#263A1C` / `#8FC26A` |
| Other storage | `#EEF3EE` / `#7A8C7A` | `#2B332B` / `#A3B5A3` |
| Queue / topic | `#FFE6CC` / `#D79B00` | `#4A3215` / `#F0A040` |
| Other internal app | `#B0E3E6` / `#0E8088` | `#0F3D40` / `#4FC3C9` |
| External system, frames | `#F5F5F5` / `#666666` | `#2B2B2B` / `#9E9E9E` |
| Success terminal, success edges | `#A9DFBF` / `#1E8449` | `#1B4D2E` / `#4CAF6E` |
| Error terminal, error edges | `#F8CECC` / `#B85450` | `#5C2323` / `#E57373` |
| Note | `#FFF9DB` / `#D6B656` | `#3D3820` / `#E0C35A` |

Use **only** the colors in these tables. Any other color won't get a dark version.

| Edge | draw.io style |
|---|---|
| Normal | `edgeStyle=none;rounded=1;arcSize=16;endArrow=block;endFill=1;html=1;strokeColor=#333333;fontColor=#1A1A1A;` (lines have **rounded corners**; every label has an explicit `fontColor` so dark mode can recolor it) |
| Main success path | add `strokeColor=#1E8449;strokeWidth=2;` |
| Error path | add `strokeColor=#B85450;` |
| Async | add `dashed=1;endArrow=open;` |

Sequence participants use the fill and stroke of their kind (`shape=umlLifeline;perimeter=lifelinePerimeter;…`). Frames (`shape=umlFrame`) are light grey `#F5F5F5`. Use `#E8F5E9` for a success branch frame and `#FDECEA` for an error branch frame.

**Legend**: `diagram_layout.py` adds it below the diagram, with one swatch per node kind and edge kind **used in that diagram** (and the step-number circle in sequence diagrams). Don't draw your own.

## 9. Sub-flows instead of size limits

There is no node limit. Completeness beats compactness. Readability comes from splitting, not from leaving branches out:

- A `.drawio.svg` shows only its **first page**, so never use multiple pages. Split into files instead.
- The main flowchart shows the whole flow end to end. Move a sub-process into its own sub-flow file when it has more than about 8 nodes of its own, or when 2 or more flows use it (then it's `shared.<sub-id>`).
- In the main flowchart, a sub-flow is one "sub-flow reference" node labelled `▶ <Sub-flow name>`, with the same name as its caption in the doc. Its outgoing edges still show every outcome the sub-flow can return (`valid`, `invalid → 400`).
- A sub-flow diagram starts with a Start node named after the parent step and ends with terminals that match those outcomes.

## 10. Mixed docs on update

- Mode mermaid, a stale section has `.drawio.svg` diagrams: keep them and add the "Diagram possibly outdated" mark (conventions §6). Don't replace them with Mermaid.
- Mode drawio, a stale section has Mermaid: redraw in draw.io.
- New sections use the current mode. A doc with both kinds is fine.

## 11. Mermaid version

Same rules, same colors. Each flowchart starts with the class definitions, and colors every node **[checked: `classDef` present]**:

```mermaid
flowchart TD
    classDef start fill:#333333,stroke:#333333,color:#FFFFFF
    classDef client fill:#DAE8FC,stroke:#6C8EBF,color:#1A1A1A
    classDef step fill:#E1D5E7,stroke:#9673A6,color:#1A1A1A
    classDef decision fill:#FFF2CC,stroke:#D6B656,color:#1A1A1A
    classDef store fill:#D5E8D4,stroke:#82B366,color:#1A1A1A
    classDef queue fill:#FFE6CC,stroke:#D79B00,color:#1A1A1A
    classDef internal fill:#B0E3E6,stroke:#0E8088,color:#1A1A1A
    classDef external fill:#F5F5F5,stroke:#666666,color:#1A1A1A,stroke-dasharray:4 3
    classDef ok fill:#A9DFBF,stroke:#1E8449,color:#1A1A1A,font-weight:bold
    classDef err fill:#F8CECC,stroke:#B85450,color:#1A1A1A,font-weight:bold

    S(["POST /v1/payments"]):::start --> V{"1. body valid?"}:::decision
    V -- "no" --> E400(["400 invalid_request"]):::err
    V -- "yes" --> L["2. Lock order: OrderRepo.LockForUpdate"]:::step
    L --> DB[("orders: SELECT … FOR UPDATE")]:::store
    DB --> F{"order found?"}:::decision
    F -- "no" --> E404(["404 order_not_found"]):::err
    F -- "yes" --> OK(["201 {payment_id, status}"]):::ok
    linkStyle 1,5 stroke:#B85450
```

- `linkStyle <indexes> stroke:#B85450` colors error edges (indexes count links in order, starting at 0). `-.->` marks async edges.
- Sequence diagrams: start with `autonumber` (numbered circles, same as draw.io mode); `participant` order as in section 5, `->>` sync, `-)` async, `-->>` reply. Wrap success/error alternatives in `rect rgb(232,245,233)` / `rect rgb(253,236,234)` inside `alt` blocks.
- Mermaid has no real legend. Add one line under the diagram: `Legend: purple = this app · green cylinder = datastore · orange = queue · grey dashed = external · red = error path`.
- Pitfalls: quote labels with spaces or symbols; don't use `end` as a node id; `DB[("label")]` for cylinders.

## 12. State diagrams (only with `fsm`)

Drawn from the transition table in `state-machines.md`. One per state machine, plus `state-overview` when 2 or more machines drive each other.

- **Initial pseudo-state**: small filled circle (`ellipse;fillColor=#333333;strokeColor=#333333;` 20×20), arrow to the initial state.
- **State**: rounded box with the state's name and, when the code stores a number, the value (`PENDING (1)`). Step colors (`#E1D5E7` / `#9673A6`). Success end states use the success terminal style; failure end states (cancelled, failed, expired) use the error terminal style. A final state also gets an arrow to a **final pseudo-state** (`ellipse;shape=doubleEllipse;fillColor=#333333;` 20×20).
- **Transition**: arrow labelled `trigger [guard] / action`, for example `POST /pay [amount > 0] / publish payment.paid`. Keep labels short. A long guard goes into a Note, as in section 4.
- **Transitions from outside the app's request flow** are dashed, with the source in the label: `⏱ cron expire-orders (24h)`, `↪ order-service`, `✋ manual DB update`.
- A value marked Unverified in the dev doc is drawn as `? (3)` with the inferred name in the Note: `probably REFUNDED, see dev notes`.
- **Overview** (`state-overview`): one container per machine, with only the transitions where a change in one machine triggers a change in another, labelled with the trigger.
- Layout as in section 2 (spec `"type": "state"`). Mermaid mode: `stateDiagram-v2` with `classDef` colors, `[*]` for initial and final pseudo-states.

## 13. Diagram spec format (input of `diagram_layout.py`)

One JSON file per diagram. Full worked examples (a real flowchart with notes and rejoins, a zoned data-flow, a sequence with frames, a state machine) are in `references/spec-examples/`. Labels may contain `\n` for line breaks; the script also wraps long lines.

**Flowchart / state / data-flow / structure**

```json
{
  "type": "flowchart",
  "title": "Inquiry: flowchart",
  "nodes": [
    {"id": "start", "kind": "start", "spine": true, "label": "POST /inquiry\nInquiryRequest JSON"},
    {"id": "auth", "kind": "decision", "spine": true, "label": "2. api_key valid?"},
    {"id": "auth-note", "kind": "note", "note_for": "auth", "label": "header api_key must equal SERVER.API_KEY ..."},
    {"id": "e401", "kind": "err", "label": "401 invalid api key"},
    {"id": "rc89", "kind": "step", "label": "respCode = 89 (link down)"},
    {"id": "log", "kind": "subflow", "spine": true, "label": "13. ▶ Write transaction log + ledger"}
  ],
  "edges": [
    {"from": "start", "to": "auth", "kind": "success"},
    {"from": "auth", "to": "e401", "kind": "error", "label": "no"},
    {"from": "rc89", "to": "log", "kind": "rejoin"}
  ]
}
```

- `type`: `flowchart` (top-down, spine) · `state` (left-to-right) · `dataflow` / `structure` (zones, top-down).
- Node `kind`: `start` `client` `step` `subflow` `decision` `db` `file` `object` `cache` `store` `queue` `internal` `external` `ok` `err` `note` `state` `initial` `final`. Colors and shapes come from the kind (section 8). Storage always uses the specific kind (`db`, `file`, `object`, `cache`); `store` is only for storage that is none of those.
- `"spine": true` on every node of the happy path, in order. Exactly one straight column.
- `"note_for": "<id>"` on notes. The script draws the dashed connector itself.
- Edge `kind`: `success` (happy path) · `normal` · `error` (ends at an error end point) · `rejoin` (an error path that continues to a later spine step, sharing the right-hand channel) · `async` · `external` (state diagrams: cron, other app, manual). `"both": true` draws arrows on both ends.
- Data-flow / structure: add `"zones": [{"id": "callers", "label": "Callers"}, {"id": "app", "label": "<app name>"}, {"id": "external", "label": "External systems"}, {"id": "db", "label": "Database (SQL)"}, {"id": "files", "label": "File storage (local disk)"}]` (one zone per storage type that exists) and a `"zone"` on every node. The first zone is the top row.
- `"direction"` overrides the default (`TB` or `LR`), rarely needed.

**Sequence**

```json
{
  "type": "sequence",
  "title": "Inquiry: sequence",
  "participants": [
    {"id": "caller", "kind": "client", "label": "Upstream caller"},
    {"id": "svc", "kind": "step", "label": "billing.Service"},
    {"id": "partner", "kind": "external", "label": "Partner billing API"}
  ],
  "steps": [
    {"from": "caller", "to": "svc", "label": "POST /inquiry {rrn, billData}"},
    {"frame": "alt", "label": "[Partner API unreachable]",
     "steps": [{"from": "partner", "to": "svc", "kind": "error", "label": "dial error → respCode 89"}],
     "else": [{"label": "[reply ok]", "steps": [{"from": "partner", "to": "svc", "kind": "reply", "label": "200 {status}"}]}]},
    {"from": "svc", "to": "caller", "kind": "reply", "label": "200 {respCode, billData}"}
  ]
}
```

- Participant `kind`: `client` `step` `internal` `external` `db` `file` `object` `cache` `store` `queue`.
- Message `kind`: `sync` (default) · `async` · `reply` · `error`. A message to the same participant draws a self-loop.
- Phases: `{"phase": "Call partner", "steps": [...]}` at the top level, wrapping the steps of that phase.
- Frames: `"frame": "break" | "alt" | "opt" | "loop"` with a condition `label`, nested `steps`, and for `alt` any `else` blocks. Optional `"tone": "ok" | "error" | "neutral"` on a frame or an `else` block (`break` is red by default).
- Notes: `{"note": "timeout CLIENT.PARTNER.TIMEOUT", "over": "<participant id>"}`, drawn beside that lifeline at that point.
- Arrows are numbered automatically in order. The story under the diagram is a numbered list whose item numbers are the arrow numbers, under capital-letter phase headings (section 5).

