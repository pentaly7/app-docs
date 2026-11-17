# Diagrams (diagram version 3)

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

**Overlapping lines and shapes come from hand-placed coordinates.** So in draw.io mode you never write `x`/`y` positions or edge waypoints for flowcharts, structure, startup, data-flow or state diagrams. You describe **nodes, edges, labels and styles**, and a layout engine places and routes them:

| Layout engine (from the orchestrator) | How |
|---|---|
| `graphviz` | Write the graph JSON that the draw.io skill's `scripts/autolayout.py` takes (see its SKILL.md for the format), then run it, e.g. `python3 <drawio-skill>/scripts/autolayout.py graph.json -o out.drawio < /dev/null`. It does placement and orthogonal routing. Use its `--tune` to pick the direction and `--group` for containers (the app container in structure diagrams). |
| `elk` | Write the diagram as Mermaid (`flowchart` / `stateDiagram-v2`) and let the draw.io CLI (v30+) convert it into an arranged, editable `.drawio` file, as the draw.io skill describes. |
| Sequence diagrams (either engine) | The draw.io skill's `scripts/seqlayout.py`. Never hand-place lifelines or messages. |

After layout, you may change **styles and labels only** (apply section 8). Never move shapes or reroute edges by hand. If the result is hard to read, change the **structure** instead (shorter labels, a sub-flow file, a different direction via `--tune`) and run the layout again.

- Export every diagram as an **editable** `.drawio.svg`: draw.io CLI `-x -f svg -e`, so the diagram XML stays inside the SVG **[checked]**. Keep `.drawio`, graph JSON and PNG previews in `docs/.docgen/.work/`.
- Look at each rendered PNG before moving on. Look for duplicate edges (two edges between the same pair of nodes with the same label: keep one), cut-off labels, and branches that don't reach a terminal.
- The orchestrator applies the light/dark theme to every `.drawio.svg` after you finish (section 8). Don't add your own dark-mode styling.
- **mermaid** mode: fenced ` ```mermaid ` blocks in the markdown, identical in both docs. Mermaid lays itself out. Section 11 shows the colors.

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

**Decision labels are short**, at most about 5 words (`issuer allowed?`, `state == 1 and not today?`). When the real condition is longer (several `and`/`or` parts, a list of values), put the **full condition in a Note** beside the diamond, connected with a dashed line without an arrow, and keep the short label in the diamond. Long text inside a diamond overflows its shape. Number the main-path steps so they match the numbered steps in the text (`1.`, `2.`…).

## 5. Sequence diagrams

A sequence diagram shows **who calls whom, in order**, for the same flow. One per important flow.

- Participants left to right in call order: caller, this app (split into its main layers when it helps: handler, service, repository), other internal apps, datastores, queues, external systems. Each participant head is colored by kind (section 8).
- Messages: **synchronous call** = solid line, filled arrowhead. **Async message** (publish, enqueue, fire-and-forget) = solid line, open arrowhead. **Reply** = dashed line, open arrowhead. Error replies are red.
- Label each message with its number and content: `3. INSERT payments (order_id, amount, status=PENDING)`, `5. POST /v2/charge {order_id, gross_amount}`, `6. 201 {transaction_id}`.
- Use `alt` / `opt` / `loop` frames for the branches from the flowchart that involve other participants (timeout, retry loop, not found), each frame labelled with its condition.
- Layout comes from the draw.io skill's `scripts/seqlayout.py` (section 2): every message gets its own row, so labels never sit on top of each other.

## 6. Structure, startup, data-flow

- **Structure**: the app's components (handlers, services, workers, schedulers, repositories, caches, clients) and how they connect, plus everything outside the app it talks to. Group the app's components inside one container labelled with the app name. Arrows labelled with protocol and purpose (`HTTP JSON`, `gRPC`, `SQL`, `publishes order.created`).
- **Startup**: flowchart from process start to "ready", in code order: config load and validation, logger, DI/wiring, connections (with retry/timeouts), migrations, workers/schedulers, server listen, readiness. Every fail-fast condition is an error terminal (`missing DB_DSN → exit 1`).
- **Data-flow**: external entities (who sends/receives data), processes (this app's flows), stores (tables, caches, buckets) and queues. Each arrow is labelled with the data that moves (`payment {id, status}`) and the direction. Include retention/cleanup jobs if they exist.

## 7. Detail inside the diagram

Put the facts a reader would otherwise have to dig out of code **in the diagram**:

| Element | Show |
|---|---|
| Entry | HTTP method + path, or topic/queue name, or cron schedule, or CLI command |
| Process step | step number, what it does, and the function/class (`2. Lock order: OrderRepo.LockForUpdate`) |
| Decision | the actual condition (`amount <= 0?`, `status == PAID?`) |
| Datastore | table and the operation with columns (`payments: INSERT id, order_id, amount, status=PENDING`) |
| Queue/topic | name and payload fields (`order.created {order_id, total, items[]}`) |
| External call | system, endpoint, timeout and its config key (`Midtrans POST /v2/charge · timeout 5s (PAYMENT_TIMEOUT_MS)`) |
| Retry | count, backoff, config key (`retry ×3, backoff 2s (CHARGE_RETRY)`) |
| Error terminal | status code / outcome and message (`502 gateway_timeout`, `payment stays PENDING`) |
| Success terminal | response code and body summary (`201 {payment_id, status}`) |

No file paths in diagrams (they're shared with the operator guide). Function and class names are fine.

## 8. Colors, shapes, legend

Every diagram is colored by **component kind** and by **outcome**, and has a legend **[checked]**. You draw with the **light** palette below. All text is dark (`#1A1A1A`) except on the start node.

**Dark mode** is added afterwards by the orchestrator (`docs_tool.py svg-theme`). It removes draw.io's own automatic dark colors (the muddy browns), then adds the dark palette in the right-hand column, which the SVG switches to when the viewer is in dark mode. If the first Docmost sync shows that images don't follow Docmost's theme toggle, the theme is switched to **always light** for every diagram. The editable diagram inside the SVG always keeps the light palette.

| Kind | Shape | draw.io style |
|---|---|---|
| Start | ellipse | `ellipse;whiteSpace=wrap;html=1;fillColor=#333333;strokeColor=#333333;fontColor=#FFFFFF;` |
| Client / user | rounded pill | `rounded=1;arcSize=50;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;fontColor=#1A1A1A;` |
| Step in this app | rounded box | `rounded=1;whiteSpace=wrap;html=1;fillColor=#E1D5E7;strokeColor=#9673A6;fontColor=#1A1A1A;` |
| Sub-flow reference | predefined process | `shape=process;whiteSpace=wrap;html=1;backgroundOutline=1;fillColor=#E1D5E7;strokeColor=#9673A6;fontColor=#1A1A1A;fontStyle=1;` |
| Decision | diamond | `rhombus;whiteSpace=wrap;html=1;fillColor=#FFF2CC;strokeColor=#D6B656;fontColor=#1A1A1A;` |
| Datastore / cache | cylinder | `shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=12;fillColor=#D5E8D4;strokeColor=#82B366;fontColor=#1A1A1A;` |
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
| Start, normal edges | `#333333` | `#B0B0B0` |
| Client / user | `#DAE8FC` / `#6C8EBF` | `#1F3A5F` / `#6C9BD2` |
| Step in this app, sub-flow, state | `#E1D5E7` / `#9673A6` | `#3B2A4F` / `#B39DDB` |
| Decision | `#FFF2CC` / `#D6B656` | `#4A3F12` / `#E0C35A` |
| Datastore | `#D5E8D4` / `#82B366` | `#1E4024` / `#7BC47F` |
| Queue / topic | `#FFE6CC` / `#D79B00` | `#4A3215` / `#F0A040` |
| Other internal app | `#B0E3E6` / `#0E8088` | `#0F3D40` / `#4FC3C9` |
| External system, frames | `#F5F5F5` / `#666666` | `#2B2B2B` / `#9E9E9E` |
| Success terminal, success edges | `#A9DFBF` / `#1E8449` | `#1B4D2E` / `#4CAF6E` |
| Error terminal, error edges | `#F8CECC` / `#B85450` | `#5C2323` / `#E57373` |
| Note | `#FFF9DB` / `#D6B656` | `#3D3820` / `#E0C35A` |

Use **only** the colors in these tables. Any other color won't get a dark version.

| Edge | draw.io style |
|---|---|
| Normal | `endArrow=block;endFill=1;html=1;strokeColor=#333333;fontColor=#1A1A1A;` |
| Main success path | add `strokeColor=#1E8449;strokeWidth=2;` |
| Error path | add `strokeColor=#B85450;` |
| Async | add `dashed=1;endArrow=open;` |

Sequence participants use the fill and stroke of their kind (`shape=umlLifeline;perimeter=lifelinePerimeter;…`). Frames (`shape=umlFrame`) are light grey `#F5F5F5`. Use `#E8F5E9` for a success branch frame and `#FDECEA` for an error branch frame.

**Legend**: a bordered box (`fillColor=#FFFFFF;strokeColor=#666666;`) titled "Legend", with one small swatch and label for each kind and edge style **used in that diagram**, and nothing else. Add it **after** the layout run, placed outside the laid-out graph's bounding box (below it, aligned right), so the layout engine never routes edges through it.

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
- Sequence diagrams: `participant` order as in section 5, `->>` sync, `-)` async, `-->>` reply. Wrap success/error alternatives in `rect rgb(232,245,233)` / `rect rgb(253,236,234)` inside `alt` blocks.
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
- Layout as in section 2 (`stateDiagram-v2` for ELK, graph JSON for Graphviz). Mermaid mode: `stateDiagram-v2` with `classDef` colors, `[*]` for initial and final pseudo-states.

