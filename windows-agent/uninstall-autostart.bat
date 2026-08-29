@echo off
setlocal
echo Menghapus Task Scheduler PrintShopAgent...
schtasks /Delete /TN PrintShopAgent /F
echo Selesai.
pause
