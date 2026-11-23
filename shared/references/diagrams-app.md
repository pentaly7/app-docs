# Diagrams: app level (diagram version 8)

Structure, startup, data-flow and state diagrams. Read `diagrams.md` first.

## 6. Structure, startup, data-flow

- **Structure**: the app's components (handlers, services, workers, schedulers, repositories, caches, clients) and how they connect, plus everything outside the app it talks to. Group the app's components inside one container labelled with the app name. Arrows labelled with protocol and purpose (`HTTP JSON`, `gRPC`, `SQL`, `publishes order.created`).
- **Startup**: flowchart from process start to "ready", in code order: config load and validation, logger, DI/wiring, connections (with retry/timeouts), migrations, workers/schedulers, server listen, readiness. Every fail-fast condition is an error terminal (`missing DB_DSN → exit 1`).
- **Data-flow**: the app's components with the data on the arrows, grouped into zones: `Callers` (first), the app, `External systems`, then **one zone per storage type** so the reader sees where data lands: `Database (<engine>)`, `File storage (<where>)`, `Object storage (<provider>)`, `Cache (<engine>)`, `Other storage`. Only zones that have something in them. Each storage node uses its storage kind (section 8) and its label names the actual thing: the table (`TXN_LOG (table)`), the path (`logs/app.YYYY-MM-DD.log`), the bucket and prefix (`s3://docs/uploads/`), the key pattern (`session:{id}`). The same storage zones are used in the structure diagram. Keep arrow labels **short** (a few words: `INSERT TXN_LOG row`, `POST inquiry / reply`) and give the full field lists in the table under the diagram. Long labels on arrows collide with each other. A two-way exchange is one edge with `"both": true`. Include retention/cleanup jobs if they exist.

## 12. State diagrams (only with `fsm`)

Drawn from the transition table in `state-machines.md`. One per state machine, plus `state-overview` when 2 or more machines drive each other.

- **Initial pseudo-state**: small filled circle (`ellipse;fillColor=#333333;strokeColor=#333333;` 20×20), arrow to the initial state.
- **State**: rounded box with the state's name and, when the code stores a number, the value (`PENDING (1)`). Step colors (`#E1D5E7` / `#9673A6`). Success end states use the success terminal style; failure end states (cancelled, failed, expired) use the error terminal style. A final state also gets an arrow to a **final pseudo-state** (`ellipse;shape=doubleEllipse;fillColor=#333333;` 20×20).
- **Transition**: arrow labelled `trigger [guard] / action`, for example `POST /pay [amount > 0] / publish payment.paid`. Keep labels short. A long guard goes into a Note, as in section 4.
- **Transitions from outside the app's request flow** are dashed, with the source in the label: `⏱ cron expire-orders (24h)`, `↪ order-service`, `✋ manual DB update`.
- A value marked Unverified in the dev doc is drawn as `? (3)` with the inferred name in the Note: `probably REFUNDED, see dev notes`.
- **Overview** (`state-overview`): one container per machine, with only the transitions where a change in one machine triggers a change in another, labelled with the trigger.
- Layout as in section 2 (spec `"type": "state"`). Mermaid mode: `stateDiagram-v2` with `classDef` colors, `[*]` for initial and final pseudo-states.

