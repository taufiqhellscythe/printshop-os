# Install auto-start PrintShop agent via Task Scheduler (current user logon)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartBat = Join-Path $Root "start-hidden.vbs"
$TaskName = "PrintShopAgent"

if (-not (Test-Path $StartBat)) {
  Write-Host "Missing start-hidden.vbs" -ForegroundColor Red
  exit 1
}

# Remove old task if exists
schtasks /Query /TN $TaskName 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
  schtasks /Delete /TN $TaskName /F | Out-Null
}

# Run at logon for current user, highest privileges not required
$cmd = "wscript.exe"
$arg = "`"$StartBat`""
schtasks /Create /TN $TaskName /SC ONLOGON /RL LIMITED /TR "$cmd $arg" /F | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Gagal create task. Coba Run as Administrator." -ForegroundColor Red
  exit 1
}

Write-Host "OK: Task '$TaskName' dibuat. Agent auto-jalan saat login Windows." -ForegroundColor Green
Write-Host "Cek: Task Scheduler → Task Scheduler Library → PrintShopAgent"
Write-Host "Hapus: uninstall-autostart.bat"
