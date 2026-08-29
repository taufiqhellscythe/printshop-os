# Auto-Printout Epson L3110

## Jawaban singkat
**Ya, bisa auto printout.**  
Tapi printer L3110 harus terhubung USB ke **PC toko**, bukan ke VPS cloud.

VPS (`129.226.135.26`) **tidak punya USB printer**. Jadi arsitektur yang benar:

```
HP pelanggan → Web PrintShop OS (VPS)
                    ↓ antrian print job
           Print Agent (PC toko + L3110 USB)
                    ↓
              kertas keluar
```

---

## 2 mode

### Mode A — App di PC yang nyambung L3110 (paling simpel)
1. Install driver Epson L3110 di PC
2. Install CUPS (Linux) / set default printer (Windows)
3. Di `.env`:
   ```env
   CUPS_PRINTER=Nama_Queue
   AUTO_PRINT_ON_STATUS=antrian,proses
   AUTO_PRINT_LOCAL=true
   ```
4. Saat order dipindah ke **Antrian/Proses** → file auto masuk `lp` → printer

### Mode B — Web di VPS + agent di PC toko (**recommended buat setup kamu sekarang**)
1. Biarkan web di VPS
2. Di PC toko jalankan `scripts/print_agent.py`
3. Agent poll job, download file, print ke L3110

```bat
:: Windows example
set PRINTSHOP_URL=http://129.226.135.26:8088
set PRINT_AGENT_TOKEN=print-agent-change-me
set CUPS_PRINTER=Epson_L3110
python print_agent.py
```

```bash
# Linux PC toko
export PRINTSHOP_URL=http://129.226.135.26:8088
export PRINT_AGENT_TOKEN=print-agent-change-me
export CUPS_PRINTER=Epson_L3110_Series
python3 scripts/print_agent.py
```

---

## Fitur yang sudah built-in
- Tabel `print_jobs` (queued → printing → done/failed)
- Auto-enqueue saat status `antrian` / `proses`
- Deteksi BW vs warna dari layanan
- Duplex kalau add-on bolak-balik
- Copies = qty item print
- Tombol **Auto Print Semua** di detail order
- Halaman admin `/admin/print-jobs`
- API agent: claim / download file / complete
- Retry job gagal

---

## Setup L3110 di PC Linux (ringkas)
```bash
sudo apt update
sudo apt install -y cups cups-client printer-driver-escpr
sudo usermod -aG lpadmin $USER
# buka http://localhost:631 → add printer USB Epson L3110
lpstat -a
# isi nama queue ke CUPS_PRINTER
```

Windows: install driver official Epson, set L3110 sebagai **default printer**. Agent fallback pakai `Start-Process -Verb Print`.

---

## Alur kerja harian (Mode B)
1. Pelanggan order + upload PDF di web
2. Kamu buka Kanban → klik ke **Antrian** / **Proses**
3. Job muncul di **Printout L3110**
4. Agent di PC toko ambil job → L3110 ngeprint
5. Status order otomatis bisa jadi **Proses**
6. Finishing → Siap → Lunas

---

## Batas realistis
| Bisa | Tidak / perlu hati-hati |
|---|---|
| Auto print PDF/JPG/DOC* | Print langsung dari VPS tanpa agent |
| Antrian + retry | Scan balik dari L3110 (belum) |
| BW/color/duplex option | 100% perfect color management semua file |
| Multi-copy | DOC butuh filter/app yang bisa render |

\*DOC/DOCX di Windows biasanya oke lewat app default; di Linux lebih aman minta pelanggan upload **PDF**.

---

## Keamanan
Ganti token:
```env
PRINT_AGENT_TOKEN=isi-string-panjang-random
```
sama di PC agent.
