# Flow section template (written by the flow agent)

You write **one** important flow's section, once for each guide, as two fragment files. `docs_tool.py assemble` puts them into the guides (single or split mode) and fixes the diagram paths. Write image paths as `diagrams/<file>`, exactly as below.

- `dev.md` and `op.md` each start with the section's anchor line, then the heading with the number from your brief, then the subtitle (conventions §3–4).
- The lists marked `docgen:render` are filled from `facts.json` (`flow_details.<flow-id>`, facts-schema.md). Leave the markers empty.
- Dev Guide: English, every step and every story item with inline permalinks (conventions §5). User Guide: semiformal Bahasa Indonesia (operator template, Language), no code references.

## `dev.md`

```markdown
<!-- docgen:section id="app-flow/create-payment" -->
### 5.1 Create payment (`POST /v1/payments`)
> …

**Flowchart**

![Create payment: flowchart](diagrams/create-payment.flow.drawio.svg)

<one image per sub-flow, captioned "Sub-flow ▶ <name>:">

<steps in the order the flowchart shows them; the flowchart itself has no numbers:>
1. `PaymentHandler.Create` validates the body ([`internal/handler/payment.go:42-60`](…)); 400 on missing `order_id`.
2. `PaymentService.Create` locks the order row ([`internal/service/payment.go:30-55`](…)) …
3. …

<!-- docgen:render id="errors:create-payment" -->
<!-- /docgen:render -->

<!-- docgen:render id="side-effects:create-payment" -->
<!-- /docgen:render -->

**Sequence**

![Create payment: sequence](diagrams/create-payment.seq.drawio.svg)

<The detailed story (diagrams-flow.md §5): a bold capital-letter heading per phase, then a numbered list whose item numbers are the arrow numbers, each item with its code references inline:>
**A. Receive and validate**

1. The client sends `POST /v1/payments` with `{order_id, amount}` and a bearer token ([`internal/router.go:22`](…)).

2. `PaymentHandler.Create` validates the body. If `order_id` is missing it answers `400 {error: "order_id required"}` and nothing is written ([`internal/handler/payment.go:42-60`](…)).

**B. …**
```

## `op.md`

```markdown
<!-- docgen:section id="app-flow/create-payment" -->
### 3.1 Membuat pembayaran (`POST /v1/payments`)
> …

**Flowchart**
<flowchart + sub-flows>

1. Data request diperiksa lebih dulu. Jika `order_id` kosong, response `400`.
2. …

**Sequence**
<sequence diagram>

<Cerita detail (diagrams-flow.md §5): judul tebal berhuruf kapital per fase, lalu daftar bernomor dengan nomor item sama dengan nomor panah, tanpa referensi kode. Tiap item menyebut log yang muncul, tabel atau file yang diperiksa, batas waktu, dan apa yang diterima caller:>
**A. Terima dan validasi**

1. Client mengirim `POST /v1/payments` berisi `{order_id, amount}`.

2. Data diperiksa. Jika `order_id` kosong, client menerima `400` dan log berisi `invalid request` (level WARN). Tidak ada row baru di tabel `payments`.

**B. …**

**Tanda berhasil:** <row baru di tabel `payments` status `PENDING`, log `payment created`>
<!-- docgen:render id="if-failed:create-payment" -->
<!-- /docgen:render -->
```
