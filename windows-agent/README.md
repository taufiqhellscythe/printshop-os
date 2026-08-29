# PrintShop Windows Agent — Epson L3110

Paket ini dijalankan di **PC Windows toko** yang USB-nya nyambung ke printer L3110.

Server web tetap di VPS:
`http://129.226.135.26:8088`

```
Pelanggan order di web
        ↓
Job print antri di server
        ↓
Agent Windows (PC ini) ambil job
        ↓
Epson L3110 ngeprint
```

---

## Setup 5 menit

### 1) Siapkan printer
1. Install driver **Epson L3110** di Windows
2. Print test page manual (pasti keluar kertas)
3. Ideal: set L3110 sebagai **printer default**
   - Settings → Bluetooth & devices → Printers → Epson L3110 → Set as default

### 2) Install Python (sekali)
- Download: https://www.python.org/downloads/
- ✅ centang **Add python.exe to PATH**
- Finish

### 3) Copy folder ini ke PC toko
Contoh: `C:\PrintShopAgent\`

Isi penting:
- `install.bat`
- `start.bat`
- `config.env`
- `print_agent.py`

### 4) Edit `config.env`
```env
PRINTSHOP_URL=http://129.226.135.26:8088
PRINT_AGENT_TOKEN=print-agent-change-me
PRINTER_NAME=Epson L3110 Series
PRINT_WORKER_NAME=PC-TOKO-1
```

Cara lihat nama printer persis:
- Settings → Printers → klik printer → copy namanya
- Atau biarkan `PRINTER_NAME=` kosong = pakai default

**Token harus sama** dengan server (`PRINT_AGENT_TOKEN` di VPS `.env`).

### 5) Install + Start
1. Double-click `install.bat`
2. Double-click `start.bat`
3. Jendela agent biarkan terbuka saat toko buka

### 6) (Opsional) Auto-start saat Windows login
Double-click `install-autostart.bat`

---

## Recommended: SumatraPDF (print PDF lebih stabil)

1. Install: https://www.sumatrapdfreader.org/
2. Atau taruh `SumatraPDF.exe` di folder agent ini
3. Opsional isi di `config.env`:
```env
SUMATRA_PATH=C:\Program Files\SumatraPDF\SumatraPDF.exe
```

Tanpa Sumatra juga bisa (pakai Print verb Windows), tapi PDF kadang buka window sebentar.

---

## Cara pakai harian

1. Nyalakan PC + L3110
2. Pastikan agent jalan (`start.bat` atau autostart)
3. Di admin web: pindah order ke **Antrian** / **Proses**
   - atau klik **Auto Print Semua**
4. Kertas keluar di L3110
5. Cek antrian: http://129.226.135.26:8088/admin/print-jobs

---

## Troubleshooting

| Gejala | Solusi |
|---|---|
| `self-test FAIL` / koneksi gagal | Cek internet PC, URL `http://129.226.135.26:8088`, firewall |
| `Invalid print agent token` | Samakan `PRINT_AGENT_TOKEN` PC ↔ server |
| Job queued tapi tidak print | Agent belum jalan / tutup start.bat |
| Printer salah | Isi `PRINTER_NAME` persis, atau set default printer |
| PDF tidak keluar | Install SumatraPDF, atau buka file manual dulu |
| Log | Lihat `agent.log` di folder ini |

Perintah test cepat:
- `test.bat`

Stop agent:
- tutup jendela `start.bat`, atau `stop.bat`

---

## Keamanan
Ganti token default:
```env
PRINT_AGENT_TOKEN=ganti-dengan-random-panjang
```
Lalu update juga di server VPS `/home/ubuntu/printshop-os/.env` dan restart app.
