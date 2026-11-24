# Diagrams (diagram version 8)

Diagrams are the first thing readers look at, so they carry the detail. They are **colorful, complete and exact**: every branch the code can take, real names, real values. The validator checks the parts marked **[checked]**.

## Files

The diagram rules are split so each agent reads only what it draws:

| File | Sections | Read by |
|---|---|---|
| `diagrams.md` (this file) | 1 Which diagrams · 2 Mode and layout · 3 Files · 7 Detail · 9 Sub-flows · 10 Mixed docs | every agent that draws |
| `diagrams-flow.md` | 4 Flowcharts · 5 Sequence diagrams and their story | flow agent |
| `diagrams-app.md` | 6 Structure, startup, data-flow · 12 State diagrams | app agent |
| `diagrams-spec.md` | 13 Spec format | both, draw.io mode |
| `diagrams-style.md` | 8 Colors, shapes, legend · 11 Mermaid version | Mermaid mode only (in draw.io mode the layout script applies the colors) |

Section numbers are the same in every file, so "diagrams §5" means section 5 wherever it lives.

---

## 1. Which diagrams, where

| Diagram | Dev guide section | Operator guide section |
|---|---|---|
| Structure (components and how they connect) | `structure` | `how-it-works` |
| Startup flowchart | `startup` | `how-it-works` |
| Flowchart per important flow, with sub-flows | `app-flow/<flow-id>` | `app-flow/<flow-id>` |
| Sequence diagram per important flow **that calls another system** (`external: true`) | `app-flow/<flow-id>` | `app-flow/<flow-id>` |
| Data-flow diagram | `data-flow` | `data-flow` |
| State diagram per state machine, plus an overview when 2+ machines drive each other (only when the app has `fsm` on; see `state-machines.md`) | `state-machine/<machine-id>` | `state-machine/<machine-id>` |

Every cell above is required **[checked]**. "Another system" means anything outside this app's own process and database: another service or app (also one in this repo), a third-party API, a message broker, a mainframe or gateway. A flow that only reads and writes its own database gets a flowchart and no sequence diagram or story: there is no conversation to draw. Both docs use the **same files**, with English labels, so they never disagree. Flows that are only listed in the index table get no diagram.

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

Write each spec to `docs/.docgen/.work/specs/<app-id>/<diagram-id>.json` (`<diagram-id>` = the file name without `.drawio.svg`, section 3). Then, in draw.io mode, run **one** command for all of yours:

```
python3 <Shared>/scripts/docs_tool.py diagrams --repo <repo> --app <app-id> --only <your prefixes> < /dev/null
```

It lays out every spec, exports the editable `docs/<app-id>/diagrams/<diagram-id>.drawio.svg`, and returns only the **flagged** ones: label overlaps, shapes over 3 lines (`long_labels`), layout errors, failed exports. Each flagged diagram comes with a PNG. **Look at those PNGs and nothing else**: an image stays in your context for the rest of your run, so viewing clean diagrams costs tokens on every later turn. Fix a flagged diagram by changing its **spec** (shorter labels, a sub-flow, `rejoin` instead of `error`, a note instead of a long diamond label) and run the command again with `--only <that diagram-id>`. Never edit coordinates in a `.drawio` file. The light/dark theme is applied afterwards by the orchestrator (`svg-theme`); don't add your own dark-mode styling.

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

