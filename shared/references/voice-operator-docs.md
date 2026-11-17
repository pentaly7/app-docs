# Preset suara: Panduan Operator (app-docs)

Preset untuk skill humanizer-indonesia, dipakai plugin app-docs saat merapikan Panduan Operator. Bagian 0 sampai 3 dan bagian 6 mengikuti susunan preset bawaan skill.

## 0. Asal korpus dan tingkat keyakinan

- Preset ini **sintetis**, bukan hasil kalibrasi dari korpus penulis tertentu. Isinya disusun dari kebutuhan pembaca: operator yang menyelidiki insiden tanpa membaca kode.
- Tingkat keyakinan: sedang. Bila tim sudah punya contoh tulisan operasional yang baik, ganti bagian 2 dengan penanda dari contoh itu.
- Register: `semiformal`.

## 1. Target metrik

Sama dengan preset `semiformal` di `scripts/metrik.py`:

| Metrik | Target |
|---|---|
| Rerata panjang kalimat | 13 sampai 17 kata |
| Simpangan baku panjang kalimat | minimal 6,4 |
| Konektor per 100 kata | maksimal 0,40 |
| Verba ringan per 100 kata | maksimal 0,40 |
| Enumerasi per 1.000 kata | maksimal 1,00 (daftar langkah dan tabel tidak dihitung sebagai masalah) |
| "merupakan" per 1.000 kata | maksimal 1,00 |
| Em dash dan en dash | 0 |
| Kalimat 28 kata ke atas | maksimal 15 persen |
| Koordinasi pada kalimat panjang | maksimal 1,50 |

## 2. Penanda suara

- Kalimat dibuka dengan tindakan atau gejala: "Periksa log …", "Jika response `502` …", "Settlement berjalan setiap hari pukul 01.00."
- Kalimat perintah untuk langkah yang harus dilakukan; kalimat pernyataan untuk perilaku aplikasi. Tidak menyapa pembaca: tanpa "Anda", tanpa "kamu".
- Setiap klaim memakai nama nyata: nama key config, nama tabel, nama queue, status code, angka timeout. "Periksa nilai `PAYMENT_TIMEOUT_MS`", bukan "periksa konfigurasi terkait".
- Istilah teknis tetap dalam bahasa Inggris tanpa huruf miring dan tanpa padanan dalam kurung: request, retry, queue, log, deploy.
- Hubungan sebab-akibat ditulis langsung: "Jika gateway timeout, pembayaran tetap `PENDING`." Bukan rantai "sehingga … oleh karena itu …".
- Panjang kalimat bervariasi: kalimat pendek untuk perintah, kalimat sedang untuk menjelaskan penyebab.
- Kohesi dibangun dengan mengulang istilah yang sama, bukan dengan kata penghubung.

## 3. Yang bukan bagian dari suara ini

- Bahasa gaul: "nggak", "gak", "udah", "aja", "banget", "bikin", "kalo", "gimana".
- Bahasa birokratis: "dalam rangka", "guna", "adapun", "yang bersangkutan", "sehubungan dengan", "melakukan pengecekan terhadap".
- Gaya akademik: kutipan penulis-tahun, kalimat pembuka bab ("Pada bagian ini akan dijelaskan"), istilah asing bercetak miring dengan padanan dalam kurung.
- Pembesaran makna: "memainkan peran penting", "sangat krusial", "komponen vital".
- Penutup kosong: "Semoga bermanfaat", "Dengan memahami alur ini, operator dapat …".
- Em dash dan en dash.
- Personifikasi sistem yang berlebihan: "aplikasi berusaha keras", "sistem merasa".

## 6. Hipotesis yang sudah diuji

Belum ada. Preset ini belum dikalibrasi terhadap tulisan tim. Catat hasilnya di sini setelah beberapa Panduan Operator selesai ditinjau manusia.
