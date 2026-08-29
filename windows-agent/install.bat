@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================
echo  PrintShop OS - Install Windows Agent
echo ============================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PY=python"
  ) else (
    echo [ERROR] Python belum terpasang.
    echo Install Python 3.11+ dari https://www.python.org/downloads/
    echo Centang "Add python.exe to PATH" saat install.
    echo.
    pause
    exit /b 1
  )
)

echo [1/4] Python:
%PY% --version
if errorlevel 1 (
  echo [ERROR] Gagal jalankan Python
  pause
  exit /b 1
)

if not exist "config.env" (
  echo [2/4] Membuat config.env dari contoh...
  copy /Y "config.example.env" "config.env" >nul
) else (
  echo [2/4] config.env sudah ada
)

echo [3/4] Cek koneksi server + printer...
%PY% print_agent.py --test
if errorlevel 1 (
  echo.
  echo [WARN] Self-test gagal. Cek:
  echo  - PRINTSHOP_URL di config.env
  echo  - PRINT_AGENT_TOKEN sama dengan server
  echo  - PC online / firewall
  echo  - Printer L3110 terpasang
  echo.
)

echo [4/4] Selesai.
echo.
echo Lanjut:
echo  1. Edit config.env  (nama printer + token)
echo  2. Double-click start.bat
echo  3. Opsional: install-autostart.bat  (jalan tiap boot)
echo.
pause
