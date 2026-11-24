# Facts file (template version 4)

Every table and list in both guides is **rendered by script** from one JSON file per app, `docs/.docgen/facts/<app-id>.json` (committed). You write each fact once, as data, in both languages; `docs_tool.py render` writes the tables and lists into both guides. Prose stays yours: overview, steps under the flowchart, sequence stories, how-it-works, "Tanda berhasil", troubleshooting text.

Why: a table written twice by hand (once per guide) costs twice the output and drifts. Rendered, both guides agree by construction, and an update changes only the entries that changed.

## Rules

- **Bilingual fields** are objects: `{"en": "…", "id": "…"}`. `en` is software-engineering English, `id` is semiformal Bahasa Indonesia (operator template voice: no slang, no Anda/kamu, no dashes). Fields marked *id only* are for the User Guide alone.
- **Code references** are plain `"path:start-end"` strings. The renderer turns them into permalinks pinned to the section's commit. Never write URLs here.
- **Names** (keys, tables, log messages, metrics) are written exactly as in the code, without backticks; the renderer adds them.
- **On update, change only entries whose facts changed.** An unchanged entry keeps its `id` text, so nothing is translated twice.
- The `id` text is polished by the humanizer at the end of the run, through `docs_tool.py facts-set`, like the User Guide's prose. Write it plainly; don't try to sound polished.
- Empty list = "none found". The renderer prints `_None._` / `_Tidak ada._`, or the unknown placeholder where conventions §8 asks for one (alerts).
- Never edit a rendered block in the markdown. The validator compares every block with the facts file (`render-stale`).

## Shape

```json
{
  "config": [
    {"key": "PAYMENT_TIMEOUT_MS", "required": false, "default": "5000", "example": null,
     "meaning": {"en": "Timeout for the gateway call", "id": "Batas waktu memanggil payment gateway"},
     "if_changed": {"id": "Request ke gateway diputus lebih cepat atau lebih lambat"},
     "if_wrong": {"id": "Banyak response 502 dan log `gateway timeout`"}}
  ],
  "config_loaded_at": "internal/config/config.go:20-61",
  "flows": {
    "create-payment": {"purpose": {"en": "Create a payment", "id": "Membuat pembayaran"},
                       "check": {"id": "log `payment create failed`, tabel `payments`"}}
  },
  "storage": [
    {"name": "payments", "kind": "database", "where": "PostgreSQL, schema public", "flows": ["create-payment"],
     "data": {"en": "One row per payment: id, order_id, amount, status", "id": "Satu row per pembayaran: id, order_id, amount, status"},
     "retention": {"en": "Kept forever", "id": "Disimpan selamanya"}}
  ],
  "logs": [
    {"message": "gateway timeout after <ms>ms", "level": "ERROR", "ref": "internal/gateway/client.go:77",
     "when": {"id": "Payment gateway tidak menjawab dalam `PAYMENT_TIMEOUT_MS`"},
     "meaning": {"id": "Periksa status gateway. Pembayaran tetap `PENDING`."}}
  ],
  "metrics": [{"name": "payment_requests_total", "type": "counter", "meaning": {"id": "Jumlah request pembayaran, label `status`"}}],
  "alerts": [{"name": "PaymentGatewayDown", "severity": "page", "source": "deploy/prometheus/payment.rules.yml",
              "when": {"id": "Lebih dari 10% request gagal selama 5 menit"}, "first_step": {"id": "Periksa status gateway"}}],
  "common_errors": [{"symptom": "gateway timeout", "meaning": {"id": "Gateway lambat"}, "check": {"id": "Status gateway, `PAYMENT_TIMEOUT_MS`"}}],
  "glossary": [{"term": "Settlement", "en": "Daily batch that marks captured payments as paid out", "id": "Proses harian yang menandai pembayaran sudah dibayarkan ke merchant"}],
  "notes": {
    "gotchas": [{"text": {"en": "A retry with the same order_id returns the existing payment"}, "ref": "internal/service/payment.go:30-55"}],
    "tech_debt": [{"text": {"en": "TODO cluster in the refund client"}, "ref": "internal/refund/client.go:12-40"}]
  },
  "flow_details": {
    "create-payment": {
      "errors": [
        {"when": {"en": "order_id missing", "id": "`order_id` kosong"}, "caller_gets": "`400 {error: \"order_id required\"}`",
         "ref": "internal/handler/payment.go:42-60",
         "cause": {"id": "Caller mengirim body tanpa `order_id`."}, "check": {"id": "Periksa payload dari caller."}}
      ],
      "side_effects": [{"text": {"en": "INSERT into `payments` with status `PENDING`"}, "ref": "internal/repo/payment.go:18-30"}]
    }
  }
}
```

- `storage[].kind`: `database` | `file` | `object` | `cache` | `queue` | `other` (the same kinds as the data-flow diagram).
- `common_errors[].symptom`: a log text or a symptom. Plain text that isn't a log message goes in as a bilingual object instead.
- `logs`: every WARN-or-higher message on the documented flows, plus the INFO lines that mark success. `message` is the fixed text in the code; the changing parts are written `<name>`. The validator searches the code for it.
- `metrics`, `alerts`: only what the code registers and the repo's rule files hold (operator template §7).
- Owners aren't written by agents: the renderer takes them from CODEOWNERS or git once per run and stores the result as `owners_snapshot`.
- `manual` is **written by people, never by agents**: values the repo can't provide. The renderer adds `manual.alerts` to the alerts table, and `manual.owners` / `manual.escalation` override the computed ones. Rendered placeholders point here.

```json
"manual": {
  "escalation": ["@oncall-payments"],
  "alerts": [{"name": "PaymentErrorsHigh", "severity": "page", "when": {"id": "Error rate di atas 5% selama 10 menit"}, "first_step": {"id": "Periksa dashboard Payments"}}]
}
```

- Entries that flow agents add to the shared lists (`logs`, `glossary`, `metrics`, `config`, `storage`) carry `_by`: the flows that mention them. The assembler drops an entry when no flow claims it anymore, so a log message removed from the code leaves the log index. Don't write `_by` or `_app` yourself.
- The Dev Guide's Unverified, Contradiction and Security finding lists are collected from the marks in the doc, so they aren't in the facts either.

## Blocks

Put each marker pair where the template shows it, with nothing between them; `render` fills it.

```markdown
<!-- docgen:render id="config" -->
<!-- /docgen:render -->
```

| Block id | Dev Guide | User Guide | From |
|---|---|---|---|
| `config` | setup | setup | `config`, `config_loaded_at` |
| `config-effects` | | troubleshooting | `config[].if_changed`, `if_wrong` |
| `flow-index` | app-flow | app-flow | app state `flows`, `facts.flows` |
| `storage` | data-flow | data-flow | `storage` |
| `common-errors` | | troubleshooting | `common_errors` |
| `log-index` | | log-index | `logs` |
| `metrics`, `alerts` | | alerts | `metrics`, `alerts` |
| `owners` | | owners | CODEOWNERS / git |
| `glossary` | glossary | glossary | `glossary` |
| `notes:gotchas`, `notes:tech-debt` | dev-notes | | `notes` |
| `notes:unverified`, `notes:contradictions`, `notes:security` | dev-notes | | marks in the Dev Guide |
| `errors:<flow-id>`, `side-effects:<flow-id>` | each important flow | | `flow_details` |
| `if-failed:<flow-id>` | | each important flow | `flow_details[].errors` |
