@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo Membuat Task Scheduler: PrintShopAgent (jalan saat login)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-autostart.ps1"
echo.
pause
