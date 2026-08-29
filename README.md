# PrintShop OS

**Sistem manajemen print shop berbasis web** — setara fitur MIS komersial (Printavo-class),
tapi self-hosted, gratis, mobile-first, dan gampang dipakai untuk usaha kecil dengan **Epson L3110**.

Lokasi: `/home/ubuntu/printshop-os`

---

## Hasil riset (ringkas)

Software print shop komersial (Printavo, ShopVOX, InfoFlo, PrintPLANR) biasanya bilang:
$89–$349/bulan. Fitur wajib mereka:

| Modul | Kenapa penting | Di PrintShop OS |
|---|---|---|
| Web-to-Print / portal order | Pelanggan order sendiri, kurangi chat | ✅ `/order` + upload |
| Live quote / pricing engine | Harga + diskon volume otomatis | ✅ + API `/api/quote` |
| Approval + tracking | Kurangi tanya "sudah selesai?" | ✅ link lacak token |
| Production board | Floor production tidak chaos | ✅ Kanban 7 tahap |
| POS walk-in | Kasir cepat | ✅ `/admin/pos` |
| Payments & invoice | Omzet ke-track | ✅ lunas/DP + struk |
| Inventory | Kertas/tinta jangan empty | ✅ stok L3110 auto-consume |
| CRM ringan | Pelanggan repeat | ✅ `/admin/customers` |
| Reporting | Tahu untung harian | ✅ dashboard + range report |
| Print bridge | Optional auto-print | ✅ CUPS stub (`lp`) |

Open-source terdekat: **SavaPage** (print portal kampus — terlalu enterprise), **ERPNext** (terlalu berat).
Tidak ada MIS print shop kecil yang pas → **PrintShop OS** mengisi gap itu.

---

## Akses (gampang)

| Siapa | URL | Butuh login? |
|---|---|---|
| Pelanggan | `http://IP:8088/` | Tidak |
| Order | `http://IP:8088/order` | Tidak |
| Lacak | `http://IP:8088/track` | Tidak (kode/token) |
| Admin/Kasir | `http://IP:8088/admin` | Ya |

Default login: **admin / admin123** (ganti di `.env`)

HP & laptop sama-sama nyaman (responsive).

---

## Fitur lengkap

### Portal pelanggan
- Landing + kalkulator harga live
- Daftar harga + diskon volume
- Form order multi-file upload
- Tracking progress bar + timeline
- Link privat per order (`/track/{token}`)

### Admin MIS
- **Dashboard**: omzet, antrian, profit, chart 7 hari, low stock, top layanan
- **Kanban produksi**: Baru → Dikonfirmasi → Prepress → Antrian → Proses → Finishing → Siap
- **Order detail**: status, bayar, file, print CUPS, struk thermal
- **POS kasir**: walk-in 10 detik
- **CRM**: pelanggan + total belanja
- **Stok L3110**: kertas A4/F4, tinta CMYK, spiral, laminating (auto-kurang saat status Proses)
- **Harga**: edit inline per layanan
- **Pengeluaran + laporan range tanggal**
- **Struk 72mm** siap print browser

### Engine
- Multi-item quote ready (API)
- Diskon volume tiered (50/100/250)
- Add-on: rush, jilid, laminating, duplex
- Estimasi margin (price − cost_estimate)
- SQLite single-file (backup gampang)

---

## Quick start

```bash
cd /home/ubuntu/printshop-os
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit SHOP_NAME, ADMIN_PASS, CUPS_PRINTER (opsional)
chmod +x scripts/run.sh
./scripts/run.sh
```

Buka: **http://localhost:8088**

Test:
```bash
export PYTHONPATH=$PWD
python tests/test_smoke.py
```

### systemd (auto-start)
```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/printshop-os.service << 'EOF'
[Unit]
Description=PrintShop OS
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/printshop-os
Environment=PYTHONPATH=%h/printshop-os
ExecStart=%h/printshop-os/.venv/bin/python -m app.main
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now printshop-os.service
```

### Auto-print L3110 (opsional)
Di mesin yang USB-nya nyambung printer:
```bash
# install driver + cups, lalu:
lpstat -a
# set di .env:
CUPS_PRINTER=Nama_Queue_L3110
```
Tombol **Print CUPS** di detail order akan kirim file ke antrian printer.

---

## Alur harian recommended

1. Buka `/admin` di HP/tablet kasir
2. Order online masuk → muncul di Kanban **Baru**
3. Cek file → **Dikonfirmasi** → **Proses** (stok auto-potong)
4. Print di L3110 (manual atau CUPS)
5. **Finishing** → **Siap** → bayar **Lunas** → cetak struk
6. Malam buka **Laporan**

Walk-in: langsung **POS**.

---

## Struktur

```
printshop-os/
├── app/
│   ├── main.py              # FastAPI entry
│   ├── config.py
│   ├── db.py                # schema + business logic
│   ├── utils.py
│   ├── routers/
│   │   ├── public.py        # portal
│   │   └── admin.py         # MIS
│   ├── services/print_bridge.py
│   ├── templates/           # Jinja mobile-first UI
│   └── static/css/app.css
├── data/printshop.db        # auto-created
├── data/uploads/
├── scripts/run.sh
└── tests/test_smoke.py
```

---

## Roadmap (lanjutan)

- [ ] Multi-line item di form order publik (sekarang 1 layanan + add-on; POS/API sudah siap multi)
- [ ] WhatsApp notifikasi status (Fonnte/Wablas)
- [ ] QRIS dinamis Midtrans/Xendit webhook
- [ ] Multi-user role (kasir vs owner)
- [ ] Drag-and-drop kanban (HTMX/Sortable)
- [ ] PWA install-to-homescreen
- [ ] Export Excel laporan

---

## Keamanan cepat

1. Ganti `ADMIN_PASS` + `SECRET_KEY` di `.env`
2. Jangan expose port 8088 publik tanpa HTTPS/reverse proxy
3. Backup `data/printshop.db` harian

---

Dibangun untuk operator yang **capek order berantakan di chat**, tapi butuh sistem setara software bayar bulanan — tanpa langganan.
