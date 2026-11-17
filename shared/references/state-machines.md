# State machines (only when the app has `fsm` on)

Some code can only be understood as a state machine. A record (order, payment, item) moves through states, and what the app does depends on the current state. In that code the important question isn't "what does this endpoint do" but "which state can move to which, triggered by what". This file is the method for finding those machines and documenting them.

## Contents
1. What counts
2. Detection method
3. The transition table
4. States without names
5. Several machines
6. Docs sections
7. App state record

---

## 1. What counts

A state machine is documented when **one field** on one entity has **at least 3 states and at least 3 transitions** found in the code. Below that (a boolean flag, an `active/inactive` toggle), it's just a field: mention it in the flow where it's used.

## 2. Detection method

Search in this order. Each step feeds the next.

1. **Libraries.** An explicit state machine library means the machine is declared in one place, so read it there first:
   - Java: Spring Statemachine (`StateMachineConfigurerAdapter`, `withExternal().source().target().event()`)
   - Go: `looplab/fsm` (`fsm.NewFSM`, `fsm.Events`), `qmuntal/stateless` (`.Configure(…).Permit(…)`)
   - PHP: `symfony/workflow` (`framework.workflows` config, `places`, `transitions`), `spatie/laravel-model-states` (`State` classes, `allowTransition`)
   - JS/TS: XState (`createMachine`, `states: {…}`), `javascript-state-machine`. Also Redux/reducer `switch` statements on a status.
2. **Candidate fields.** Grep for fields and columns named `state`, `status`, `stage`, `phase`, `step`, `lifecycle`, `*_status`, `*_state`, and for enums/constants whose values look like states (`PENDING`, `ACTIVE`, `EXPIRED`, `1/2/3` constants grouped together). Check migrations and schema files for enum columns, check constraints and `status_history`-style tables.
3. **Writes, i.e. transitions.** For each candidate field, find **every place that changes it**:
   - assignments: `item.State = 2`, `$order->status = 'paid'`, `order.setStatus(PAID)`
   - updates: `UPDATE orders SET status = … WHERE … status = …`, ORM `update({status: …})`
   - library calls: `fsm.Event("pay")`, `$workflow->apply($order, 'pay')`, `send('PAY')`

   For each write, record the **guard** (the condition on the current state and anything else that must hold), the **trigger** (which endpoint, consumer, cron job, CLI command or UI action reaches this code), and the **side effects** (events published, rows written, external calls). Follow the call graph up from the write to find the trigger.
4. **Reads that branch on state.** `switch (status)`, `if item.state == 1 …`: these show what each state *means* and which actions are allowed in it. They also expose implicit transitions you might have missed.
5. **Writes from outside the request flow.** Cron/scheduled jobs (`expire PENDING after 24h`), consumers reacting to other apps' events, other apps in the repo that write the same table, migration scripts, and admin/manual SQL in runbooks or scripts. Each becomes a dashed transition (diagrams.md §12).
6. **Apply the threshold** (section 1). A field passes when it has at least 3 states and at least 3 transitions.

## 3. The transition table

For each machine, build this table. It drives both the diagram and the text:

| From | To | Trigger | Guard | Side effects | Code |
|---|---|---|---|---|---|
| `PENDING (1)` | `PAID (2)` | `POST /v1/payments/{id}/confirm` | `amount > 0`, gateway returned `settled` | publish `payment.paid` | `internal/payment/confirm.go:44-61` |
| `PENDING (1)` | `EXPIRED (4)` | ⏱ cron `expire-payments` every 5 min | `created_at < now() - 24h` | none | `internal/jobs/expire.go:20-38` |

Then check the machine:
- **Initial state(s)**: the value set when the record is created.
- **Final states**: no transition leaves them. Mark each success or failure.
- **Unreachable states**: no transition enters them, and they aren't the initial state. Note them in dev notes; often dead code or set by hand.
- **Dead ends**: non-final states nothing leaves. These are where records get "stuck". Highlight them for operators.
- **Same transition in several places** (two code paths set `PAID`): one row per path, so drift detection sees every file.

## 4. States without names

When the code uses bare numbers (`item.state == 1`) and nothing names them:
- Infer a name from how the state is used (what's allowed in it, what moves into and out of it, log messages, UI labels, SQL comments, test names).
- Dev doc: show `1 (inferred: ACTIVE)` and add an **Unverified** mark with the original author of the code that sets it (`docs_tool.py author`).
- Operator guide: use the number and a plain description of the behavior only (`status 1: item sudah aktif dan bisa dipakai`), with no "inferred" wording and no mark.
- Diagram: `? (1)` with the inferred name in a Note (diagrams.md §12).

## 5. Several machines

Each machine gets its own diagram and subsection. When a transition in one machine triggers a transition in another (payment `PAID` → order `CONFIRMED`; all items `SHIPPED` → order `COMPLETED`), also draw `state-overview` and describe the chain in the `state-machine` intro.

## 6. Docs sections

Both docs get a `state-machine` section **after `app-flow`**, with one subsection `state-machine/<machine-id>` per machine (`<machine-id>`: kebab-case entity and field, e.g. `payment-status`, `item-state`). Split-mode files: `dev/05b-state-machine/` and `operator/03b-state-machine/` (00-index plus one file per machine), so no existing file is renamed.

**Dev guide** subsection: the diagram, the full transition table (section 3) with `path:line`, initial/final/unreachable/dead-end states, and Unverified marks for inferred names.

**Operator guide** subsection ("Status dan Perubahannya"): the same diagram, then a table per state:

| Status | Artinya | Pindah ke status berikutnya jika | Jika tertahan di status ini, periksa |
|---|---|---|---|
| `PENDING` (1) | Pembayaran dibuat, menunggu konfirmasi gateway | callback gateway diterima, atau cron kedaluwarsa setelah 24 jam | log `gateway callback`, status di dashboard gateway, cron `expire-payments` berjalan |

Then how to find records stuck in a state (a read-only SQL query or admin screen, if the repo shows one), and which transitions happen outside the app (cron, other apps, manual).

## 7. App state record

In `docs/.docgen/apps/<id>.json` (state-schema.md):

```json
"fsm": true,
"state_machines": [
  {
    "id": "payment-status",
    "entity": "payment",
    "field": "payments.status",
    "states": [
      {"value": "1", "name": "PENDING", "inferred": false, "kind": "initial"},
      {"value": "2", "name": "PAID", "inferred": false, "kind": "final-success"},
      {"value": "4", "name": "EXPIRED", "inferred": true, "kind": "final-failure"}
    ],
    "transitions": [
      {"from": "1", "to": "2", "trigger": "POST /v1/payments/{id}/confirm", "guard": "amount > 0",
       "effects": "publish payment.paid", "ref": "internal/payment/confirm.go:44-61", "source": "code"}
    ]
  }
]
```

- `kind`: `initial` | `normal` | `final-success` | `final-failure` | `unreachable`.
- `source`: `code` | `cron` | `other-app` | `manual`.
- `state_machines` is `[]` when `fsm` is on and nothing passes the threshold. Say so in one line in the run summary. The docs then get no section.
