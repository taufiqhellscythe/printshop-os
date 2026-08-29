@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title PrintShop Agent - L3110

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  set "PY=python"
)

if not exist "config.env" (
  echo config.env belum ada. Jalankan install.bat dulu.
  pause
  exit /b 1
)

echo ============================================
echo  PrintShop Agent START
echo  Jangan tutup jendela ini saat toko buka
echo ============================================
echo.
%PY% print_agent.py
echo.
echo Agent berhenti.
pause
