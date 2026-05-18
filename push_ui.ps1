param(
  [string]$Port = "COM3",
  [int]$Baud = 1500000
)

$ToolsDir = "tools\serial"
$Sender = "$ToolsDir\serial_send_file_b64.ps1"

if (!(Test-Path $Sender)) {
    Write-Host "Cannot find $Sender" -ForegroundColor Red
    exit 1
}

Write-Host "Pushing index.html..." -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Sender -Port $Port -Baud $Baud -LocalPath "index.html" -RemotePath "/userdata/myui/index.html"

Write-Host "Pushing wifi.html..." -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Sender -Port $Port -Baud $Baud -LocalPath "wifi.html" -RemotePath "/userdata/myui/wifi.html"

Write-Host "Pushing stitch.html..." -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Sender -Port $Port -Baud $Baud -LocalPath "stitch.html" -RemotePath "/userdata/myui/stitch.html"

Write-Host "Installing S51myui boot service..." -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Sender -Port $Port -Baud $Baud -LocalPath "S51myui" -RemotePath "/etc/init.d/S51myui"

Write-Host "Restarting myui service and clearing cache..." -ForegroundColor Yellow
$Cmd = "chmod 755 /etc/init.d/S51myui /userdata/myui/start_myui.sh /userdata/myui/stop_myui.sh; rm -rf /tmp/myui_chrome_profile/Default/Cache; /etc/init.d/S51myui restart"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$ToolsDir\serial_quick_proc.ps1" -Port $Port -Baud $Baud -Command $Cmd

Write-Host "Done! Please check the screen." -ForegroundColor Green
