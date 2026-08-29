@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title PrintShop Agent - TEST

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

echo === Test koneksi + printer ===
%PY% print_agent.py --test
echo.
pause
