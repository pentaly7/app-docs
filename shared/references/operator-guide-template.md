# Operator guide template

Audience: an operator who runs and monitors the app and wants to investigate an incident without asking a developer. They know servers, logs and databases, but they don't read the source code.

## Language rules

- Bahasa Indonesia. Address the reader as **Anda**. Standard grammar, conversational tone: short sentences, active voice, explain like a helpful senior colleague.
- **No slang**: not "gak/nggak", "udah", "aja", "banget", "bikin", "kalo". Use "tidak", "sudah", "saja", "sangat", "membuat", "kalau/jika".
- **No stiff officialese**: avoid "sehubungan dengan", "adapun", "dalam rangka", "guna", "yang bersangkutan".
- Tech terms stay in English: endpoint, request, response, queue, topic, consumer, retry, timeout, log, config, deploy, health check, cache, cron job, payload, status code.
- Business/domain terms stay in their original form (as written in the code or by the business): "settlement", "top-up", "refund", "Faktur".
- Never write a file path or line number. Env var names, table/queue names, URLs, log and CLI commands are fine, wrapped in backticks.
- No Unverified/Contradiction/Security marks. Leave out anything uncertain. Don't hint that something is missing.

| Hindari | Gunakan |
|---|---|
| "Kalo request-nya gagal, cek aja log-nya." | "Jika request gagal, cek log di `/var/log/payment/app.log`." |
| "Adapun proses settlement dilaksanakan guna…" | "Settlement berjalan setiap hari pukul 01.00 untuk…" |
| "Permintaan akan diteruskan ke antrean pesan." | "Request diteruskan ke queue `order.created`." |

## Structure

```markdown
# <App name> — Panduan Operator

<!-- docgen:section id="setup" -->
## 1. Setup
> `a1b2c3d` · `main` · 2026-11-15 · verified by Rizki Tegar

<1–2 kalimat: aplikasi ini untuk apa, siapa yang memakainya.>

### Yang dibutuhkan
<database, broker, cache, service lain, beserta versinya>

### Konfigurasi
| Key | Wajib | Fungsi | Contoh / default |
|---|---|---|---|
| `DB_DSN` | ya | Koneksi ke database Postgres | `<postgres://user:password@host:5432/db>` |
| `PAYMENT_TIMEOUT_MS` | tidak | Batas waktu memanggil payment gateway | default `5000` |

### Cara menjalankan
<perintah untuk start/stop/restart, port yang dipakai, cara cek bahwa aplikasi sudah siap>

### Deployment
<apa yang ditemukan di repo, atau placeholder "Belum diketahui" dari conventions §8>

<!-- docgen:section id="app-flow" -->
## 2. Alur Aplikasi
> …

<Tabel semua flow:>
| Flow | Fungsi | Jika gagal, cek |
|---|---|---|
| `POST /v1/payments` | Membuat pembayaran | log `payment create failed`, tabel `payments` |

<!-- docgen:section id="app-flow/create-payment" -->
### 2.1 Membuat pembayaran (`POST /v1/payments`)
> …

<diagram yang sama dengan dev guide>

1. Aplikasi memeriksa data request. Jika `order_id` kosong, response `400`.
2. …

**Tanda berhasil:** <row baru di tabel `payments` dengan status `PENDING`, log `payment created`>
**Jika gagal:** <gejala → penyebab paling mungkin → apa yang dicek>

<!-- docgen:section id="data-flow" -->
## 3. Alur Data
> …

<Diagram yang sama dengan dev guide. Lalu tabel: data apa, disimpan di mana, siapa yang menulis/membaca, berapa lama disimpan.>

<!-- docgen:section id="troubleshooting" -->
## 4. Troubleshooting
> …

### Lokasi log
<di mana log ditulis, format, field penting, contoh perintah untuk mencari: `kubectl logs …`, `grep …`>

### Health check
<URL/perintah, arti setiap response>

### Error yang sering muncul
| Pesan / gejala | Artinya | Yang perlu dicek |
|---|---|---|

### Config dan perilakunya
| Key | Jika diubah | Gejala jika salah |
|---|---|---|

<!-- docgen:section id="glossary" -->
## 5. Glosarium
| Istilah | Arti |
|---|---|
| Settlement | Proses harian yang menandai pembayaran sudah dibayarkan ke merchant |
```

## Good vs. weak "Jika gagal"

Weak: "Jika gagal, hubungi tim developer."
Good: "Jika response `502` dan log berisi `gateway timeout`, payment gateway lambat atau tidak bisa dihubungi. Cek status gateway dan nilai `PAYMENT_TIMEOUT_MS`. Pembayaran tetap tercatat dengan status `PENDING` dan akan dicoba lagi oleh cron `retry-pending-payments` setiap 5 menit."
