# Operator guide template (template version 2, humanizer version 2)

Audience: an operator who runs and monitors the app and wants to investigate an incident without asking a developer. They know servers, logs and databases, but they don't read the source code.

## Language

- Bahasa Indonesia, **semiformal**: natural, clear work language, the way a careful senior operator writes an internal wiki. Not stiff officialese, and **no slang** (`nggak`, `gak`, `udah`, `aja`, `banget`, `bikin`, `kalo`, `gimana` are out).
- **No "Anda" and no "kamu".** Write sentences that don't address anyone: imperatives (`Periksa log …`, `Jalankan ulang service …`) or plain statements (`Jika timeout, request dicoba ulang 3 kali`).
- **No em dash or en dash** (— –) in prose, titles, captions or placeholders. Use a colon, a comma, or two sentences. The humanizer's metrics count every dash.
- Tech terms stay in English, without italics and without an Indonesian translation in parentheses: endpoint, request, response, queue, topic, consumer, retry, timeout, log, config, deploy, health check, cache, cron job, payload, status code. The glossary explains them.
- Business/domain terms stay as the code and the business write them: "settlement", "top-up", "refund", "Faktur".
- No file paths or line numbers. Env var names, table/queue names, URLs, log and CLI commands are fine, in backticks.
- No Unverified/Contradiction/Security marks. Leave out anything uncertain, without hinting that something is missing.
- The final text goes through humanizer-indonesia (`humanizer.md`). Write naturally from the start anyway, since the humanizer polishes, it doesn't rescue.

| Kaku / terasa AI | Semiformal yang natural |
|---|---|
| "Apabila permintaan mengalami kegagalan, Anda dapat melakukan pengecekan terhadap log aplikasi." | "Jika request gagal, periksa log di `/var/log/payment/app.log`." |
| "Proses settlement memainkan peran penting dalam memastikan…" | "Settlement berjalan setiap hari pukul 01.00 dan menandai pembayaran yang sudah dibayarkan ke merchant." |
| "Kalo request-nya gagal, cek aja log-nya." (slang) | "Jika request gagal, periksa log aplikasi." |

## Structure

The document title is the English "User Guide" (that's how it appears in GitLab and Docmost). Everything under it, headings included, stays in Bahasa Indonesia.

Anchors and subtitles exactly as in conventions §3–4. Diagrams as in `diagrams.md`: the same files as the dev guide.

```markdown
# <App name>: User Guide

<!-- docgen:section id="setup" -->
## 1. Setup
> `a1b2c3d` · `main` · 2026-11-16 · verified by Jane Doe

<1 sampai 2 kalimat: fungsi aplikasi dan penggunanya.>

### Yang dibutuhkan
<database, broker, cache, service lain, beserta versinya>

### Konfigurasi
| Key | Wajib | Fungsi | Contoh / default |
|---|---|---|---|
| `DB_DSN` | ya | Koneksi ke database Postgres | `<postgres://user:password@host:5432/db>` |
| `PAYMENT_TIMEOUT_MS` | tidak | Batas waktu memanggil payment gateway | default `5000` |

### Cara menjalankan
<perintah start/stop/restart, port, cara memastikan aplikasi sudah siap>

### Deployment
<apa yang ada di repo, atau placeholder "Belum diketahui" dari conventions §8>

<!-- docgen:section id="how-it-works" -->
## 2. Cara Aplikasi Bekerja
> …

### Komponen
<structure diagram>
<Penjelasan singkat tiap komponen: tugasnya dan dengan apa komponen itu terhubung (DB, queue, service lain, sistem eksternal).>

### Dari start sampai siap
<startup diagram>
<Urutan langkah dari aplikasi dinyalakan sampai siap menerima request. Sebutkan kondisi yang membuat aplikasi langsung berhenti (config kosong, DB tidak bisa dihubungi) dan pesan yang muncul di log.>

<!-- docgen:section id="app-flow" -->
## 3. Alur Aplikasi
> …

| Flow | Fungsi | Jika gagal, periksa |
|---|---|---|
| `POST /v1/payments` | Membuat pembayaran | log `payment create failed`, tabel `payments` |

<!-- docgen:section id="app-flow/create-payment" -->
### 3.1 Membuat pembayaran (`POST /v1/payments`)
> …

**Flowchart**
<flowchart + sub-flows>

1. Data request diperiksa lebih dulu. Jika `order_id` kosong, response `400`.
2. …

**Sequence**
<sequence diagram>

<Cerita detail (diagrams.md §5): judul berhuruf per fase, satu baris per panah (① ②…), tanpa referensi kode. Tiap baris menyebut log yang muncul, tabel atau file yang diperiksa, batas waktu, dan apa yang diterima caller:>
**a. Terima dan validasi**
① Client mengirim `POST /v1/payments` berisi `{order_id, amount}`.
② Data diperiksa. Jika `order_id` kosong, client menerima `400` dan log berisi `invalid request` (level WARN). Tidak ada row baru di tabel `payments`.

**b. …**

**Tanda berhasil:** <row baru di tabel `payments` status `PENDING`, log `payment created`>
**Jika gagal:** <gejala, penyebab yang paling mungkin, lalu apa yang diperiksa, untuk setiap cabang error di flowchart>

<!-- docgen:section id="state-machine" -->
## Status dan Perubahannya          ← hanya jika app memakai fsm dan state machine ditemukan (state-machines.md §6)
> …

<status apa saja yang ada dan bagaimana satu status memicu status lain>

<!-- docgen:section id="state-machine/payment-status" -->
### Status pembayaran (`payments.status`)
> …

<state diagram, tabel per status: artinya, pindah jika, jika tertahan periksa apa; cara mencari record yang tertahan>

<!-- docgen:section id="data-flow" -->
## 4. Alur Data
> …

<data-flow diagram, lalu tabel: jenis data, **jenis penyimpanan** (database / file storage / object storage / cache / queue) dan lokasi persisnya (tabel, path, bucket), siapa yang menulis dan membaca, lama penyimpanan>

<!-- docgen:section id="troubleshooting" -->
## 5. Troubleshooting
> …

### Lokasi log
<di mana log ditulis, format, field penting, contoh perintah: `kubectl logs …`, `grep …`>

### Health check
<URL/perintah, arti tiap response>

### Error yang sering muncul
| Pesan / gejala | Artinya | Yang diperiksa |
|---|---|---|

### Config dan efeknya
| Key | Jika diubah | Gejala jika salah |
|---|---|---|

<!-- docgen:section id="glossary" -->
## 6. Glosarium
| Istilah | Arti |
|---|---|
| Settlement | Proses harian yang menandai pembayaran yang sudah dibayarkan ke merchant |
```

## Good vs. weak "Jika gagal"

Weak: "Jika gagal, hubungi tim developer."
Good: "Jika response `502` dan log berisi `gateway timeout`, payment gateway sedang lambat atau tidak bisa dihubungi. Periksa status gateway dan nilai `PAYMENT_TIMEOUT_MS`. Pembayaran tetap tersimpan dengan status `PENDING` dan akan dicoba ulang oleh cron `retry-pending-payments` setiap 5 menit."
