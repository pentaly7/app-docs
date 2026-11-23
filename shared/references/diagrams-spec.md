# Diagrams: spec format (diagram version 8)

The JSON input of `diagram_layout.py`, for draw.io mode.

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

