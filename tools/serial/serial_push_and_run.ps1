param(
  [string]$Port = "COM3",
  [int]$Baud = 1500000,
  [string]$ScriptPath,
  [int]$TimeoutSec = 30
)

if ([string]::IsNullOrWhiteSpace($ScriptPath)) {
  throw "ScriptPath is required"
}
if (!(Test-Path $ScriptPath)) {
  throw "script not found: $ScriptPath"
}

$scriptText = Get-Content -Raw -Path $ScriptPath

$m = [guid]::NewGuid().ToString("N").Substring(0, 8)
$begin = "__BEGIN_${m}__"
$end = "__END_${m}__"
$pattern = "${end}:[0-9]+"

$p = New-Object System.IO.Ports.SerialPort $Port, $Baud, "None", 8, "One"
$p.Handshake = [System.IO.Ports.Handshake]::None
$p.DtrEnable = $true
$p.RtsEnable = $true
$p.ReadTimeout = 200
$p.WriteTimeout = 2000

$p.Open()
Start-Sleep -Milliseconds 250

$p.Write("echo $begin`r`n")
$p.Write("cat >/tmp/serial_task.sh <<'EOF'`r`n")
$normalized = ($scriptText -replace "`n", "`r`n")
$p.Write($normalized)
if (-not $scriptText.EndsWith("`n")) {
  $p.Write("`r`n")
}
$p.Write("EOF`r`n")
$p.Write("sh /tmp/serial_task.sh`r`n")
$p.Write("rc=`$?; echo ${end}:`$rc`r`n")

$buf = ""
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
