# Operator guide template (template version 2)

Audience: an operator who runs and monitors the app and wants to investigate an incident without asking a developer. They know servers, logs and databases, but they don't read the source code.

## Language

- Bahasa Indonesia, **casual**: like a senior colleague explaining in chat. Everyday slang is fine (`nggak`, `udah`, `aja`, `kalau`, `bikin`, `cek`) when it reads naturally. Don't force it.
- **No "Anda" and no "kamu".** Write sentences that don't address anyone: imperatives (`Cek log …`, `Restart service …`) or plain statements (`Kalau timeout, request-nya dicoba lagi 3 kali`).
- Tech terms stay in English: endpoint, request, response, queue, topic, consumer, retry, timeout, log, config, deploy, health check, cache, cron job, payload, status code.
- Business/domain terms stay as the code and the business write them: "settlement", "top-up", "refund", "Faktur".
- No file paths or line numbers. Env var names, table/queue names, URLs, log and CLI commands are fine, in backticks.
- No Unverified/Contradiction/Security marks. Leave out anything uncertain, without hinting that something is missing.
- The final text goes through the Indonesian humanizer (`humanizer-id.md`). Write naturally from the start anyway, since the humanizer polishes, it doesn't rescue.

| Kaku / AI banget | Natural |
|---|---|
| "Apabila permintaan mengalami kegagalan, Anda dapat memeriksa log aplikasi." | "Kalau request gagal, cek log di `/var/log/payment/app.log`." |
| "Proses settlement memainkan peran penting dalam memastikan…" | "Settlement jalan tiap hari jam 01.00, tugasnya nandain pembayaran yang udah dibayar ke merchant." |
| "Permintaan akan diteruskan ke antrean pesan." | "Request-nya diterusin ke queue `order.created`." |

## Structure

Anchors and subtitles exactly as in conventions §3–4. Diagrams as in `diagrams.md`: the same files as the dev guide.

```markdown
# <App name> — Panduan Operator

<!-- docgen:section id="setup" -->
## 1. Setup
> `a1b2c3d` · `main` · 2026-11-16 · verified by Rizki Tegar

<1–2 kalimat: aplikasi ini buat apa, siapa yang pakai.>

### Yang dibutuhkan
<database, broker, cache, service lain, plus versinya>

### Konfigurasi
| Key | Wajib | Fungsi | Contoh / default |
|---|---|---|---|
| `DB_DSN` | ya | Koneksi ke database Postgres | `<postgres://user:password@host:5432/db>` |
| `PAYMENT_TIMEOUT_MS` | nggak | Batas waktu manggil payment gateway | default `5000` |

### Cara menjalankan
<perintah start/stop/restart, port, cara cek aplikasinya udah siap>

### Deployment
<apa yang ada di repo, atau placeholder "Belum diketahui" dari conventions §8>

<!-- docgen:section id="how-it-works" -->
## 2. Cara Aplikasi Bekerja
> …

### Komponen
<structure diagram>
<Penjelasan singkat tiap komponen: apa tugasnya, ngobrol sama siapa (DB, queue, service lain, sistem eksternal).>

### Dari start sampai siap
<startup diagram>
<Urutan langkah dari aplikasi dinyalakan sampai siap terima request. Sebutkan kondisi yang bikin aplikasi langsung mati (config kosong, DB nggak bisa dihubungi) dan apa yang muncul di log.>

<!-- docgen:section id="app-flow" -->
## 3. Alur Aplikasi
> …

| Flow | Fungsi | Kalau gagal, cek |
|---|---|---|
| `POST /v1/payments` | Bikin pembayaran | log `payment create failed`, tabel `payments` |

<!-- docgen:section id="app-flow/create-payment" -->
### 3.1 Bikin pembayaran (`POST /v1/payments`)
> …

**Flowchart**
<flowchart + sub-flows>

**Sequence**
<sequence diagram>

1. Data request dicek dulu. Kalau `order_id` kosong, response-nya `400`.
2. …

**Tanda berhasil:** <row baru di tabel `payments` status `PENDING`, log `payment created`>
**Kalau gagal:** <gejala → penyebab paling mungkin → apa yang dicek, untuk tiap cabang error di flowchart>

<!-- docgen:section id="data-flow" -->
## 4. Alur Data
> …

<data-flow diagram, lalu tabel: data apa, disimpan di mana, siapa yang nulis/baca, disimpan berapa lama>

<!-- docgen:section id="troubleshooting" -->
## 5. Troubleshooting
> …

### Lokasi log
<di mana log ditulis, format, field penting, contoh perintah: `kubectl logs …`, `grep …`>

### Health check
<URL/perintah, arti tiap response>

### Error yang sering muncul
| Pesan / gejala | Artinya | Yang dicek |
|---|---|---|

### Config dan efeknya
| Key | Kalau diubah | Gejala kalau salah |
|---|---|---|

<!-- docgen:section id="glossary" -->
## 6. Glosarium
| Istilah | Arti |
|---|---|
| Settlement | Proses harian yang nandain pembayaran udah dibayarkan ke merchant |
```

## Good vs. weak "Kalau gagal"

Weak: "Kalau gagal, hubungi tim developer."
Good: "Kalau response-nya `502` dan di log ada `gateway timeout`, berarti payment gateway lagi lambat atau nggak bisa dihubungi. Cek status gateway dan nilai `PAYMENT_TIMEOUT_MS`. Pembayarannya tetap kesimpan dengan status `PENDING`, nanti dicoba lagi sama cron `retry-pending-payments` tiap 5 menit."
