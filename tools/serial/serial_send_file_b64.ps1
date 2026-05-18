param(
  [string]$Port = "COM3",
  [int]$Baud = 1500000,
  [string]$LocalPath,
  [string]$RemotePath,
  [int]$TimeoutSec = 45,
  [int]$LineDelayMs = 2,
  [string]$Mode = "0644"
)

if ([string]::IsNullOrWhiteSpace($LocalPath)) {
  throw "LocalPath is required"
}
if ([string]::IsNullOrWhiteSpace($RemotePath)) {
  throw "RemotePath is required"
}
if (!(Test-Path $LocalPath)) {
  throw "local file not found: $LocalPath"
}
if ($RemotePath.Contains("'")) {
  throw "RemotePath cannot contain a single quote"
}

function Read-SerialAvailable($PortObj, [int]$Ms) {
  $buf = ""
  $deadline = (Get-Date).AddMilliseconds($Ms)
  while ((Get-Date) -lt $deadline) {
    $chunk = $PortObj.ReadExisting()
    if ($chunk) { $buf += $chunk }
    Start-Sleep -Milliseconds 50
  }
  return $buf
}

$bytes = [IO.File]::ReadAllBytes($LocalPath)
$localMd5 = (Get-FileHash -Algorithm MD5 -Path $LocalPath).Hash.ToLowerInvariant()
$b64 = [Convert]::ToBase64String($bytes)
$lines = ($b64 -split '(.{1,76})' | Where-Object { $_ })

$m = [guid]::NewGuid().ToString("N").Substring(0, 8)
$tmp = "/tmp/serial_file_${m}.b64"
$end = "__SEND_FILE_${m}__"
$pattern = "${end}:[0-9]+"

$p = New-Object System.IO.Ports.SerialPort $Port, $Baud, "None", 8, "One"
$p.Handshake = [System.IO.Ports.Handshake]::None
$p.DtrEnable = $false
$p.RtsEnable = $false
$p.ReadTimeout = 200
$p.WriteTimeout = 3000

$p.Open()
Start-Sleep -Milliseconds 250

$p.Write([char]3)
Start-Sleep -Milliseconds 150
$p.Write("`r`n")
$warmup = Read-SerialAvailable $p 350
if ($warmup -match "debug>") {
  $p.Write("console`r`n")
  Start-Sleep -Milliseconds 400
  $warmup += Read-SerialAvailable $p 600
  $p.Write([char]3)
  Start-Sleep -Milliseconds 150
  $p.Write("`r`n")
}

$slash = $RemotePath.LastIndexOf("/")
if ($slash -le 0) {
  $remoteDir = "."
} else {
  $remoteDir = $RemotePath.Substring(0, $slash)
}
$p.Write("stty -echo 2>/dev/null || true`r`n")
Start-Sleep -Milliseconds $LineDelayMs
$p.Write("mkdir -p '$remoteDir'`r`n")
Start-Sleep -Milliseconds $LineDelayMs
$p.Write("cat >'$tmp' <<'B64'`r`n")
foreach ($line in $lines) {
  $p.Write($line + "`n")
  Start-Sleep -Milliseconds $LineDelayMs
}
$p.Write("B64`n")
Start-Sleep -Milliseconds $LineDelayMs
$p.Write("base64 -d '$tmp' >'$RemotePath'`r`n")
Start-Sleep -Milliseconds $LineDelayMs
$p.Write("rc=`$?`r`n")
Start-Sleep -Milliseconds $LineDelayMs
$p.Write("rm -f '$tmp'`r`n")
Start-Sleep -Milliseconds $LineDelayMs
$p.Write("chmod $Mode '$RemotePath' 2>/dev/null || true`r`n")
Start-Sleep -Milliseconds $LineDelayMs
$p.Write("stty echo 2>/dev/null || true`r`n")
Start-Sleep -Milliseconds $LineDelayMs
$p.Write("printf 'remote_md5='; md5sum '$RemotePath' 2>/dev/null || true`r`n")
Start-Sleep -Milliseconds $LineDelayMs
$p.Write("echo local_md5=$localMd5`r`n")
Start-Sleep -Milliseconds $LineDelayMs
$p.Write("echo ${end}:`$rc`r`n")

$buf = $warmup
$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
  $chunk = $p.ReadExisting()
  if ($chunk) {
    $buf += $chunk
    if ($buf -match $pattern) {
      break
    }
  }
  Start-Sleep -Milliseconds 100
}

$p.Close()
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$buf
