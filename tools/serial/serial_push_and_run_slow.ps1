param(
  [string]$Port = "COM3",
  [int]$Baud = 1500000,
  [string]$ScriptPath,
  [int]$TimeoutSec = 60,
  [int]$LineDelayMs = 20
)

if ([string]::IsNullOrWhiteSpace($ScriptPath)) {
  throw "ScriptPath is required"
}
if (!(Test-Path $ScriptPath)) {
  throw "script not found: $ScriptPath"
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

$lines = Get-Content -Path $ScriptPath
$m = [guid]::NewGuid().ToString("N").Substring(0, 8)
$begin = "__BEGIN_${m}__"
$end = "__END_${m}__"
$pattern = "${end}:[0-9]+"

$p = New-Object System.IO.Ports.SerialPort $Port, $Baud, "None", 8, "One"
$p.Handshake = [System.IO.Ports.Handshake]::None
$p.DtrEnable = $false
$p.RtsEnable = $false
$p.ReadTimeout = 200
$p.WriteTimeout = 3000

$p.Open()
Start-Sleep -Milliseconds 300

$p.Write([char]3)
Start-Sleep -Milliseconds 200
$p.Write("`r`n")
Start-Sleep -Milliseconds 200
$warmup = Read-SerialAvailable $p 500
if ($warmup -match "debug>") {
  $p.Write("console`r`n")
  Start-Sleep -Milliseconds 500
  $warmup += Read-SerialAvailable $p 800
  $p.Write([char]3)
  Start-Sleep -Milliseconds 200
  $p.Write("`r`n")
}

$p.Write("stty -echo 2>/dev/null || true`r`n")
Start-Sleep -Milliseconds $LineDelayMs
$p.Write("echo $begin`r`n")
Start-Sleep -Milliseconds $LineDelayMs
$p.Write("cat >/tmp/serial_task.sh <<'EOF'`r`n")
Start-Sleep -Milliseconds $LineDelayMs
foreach ($line in $lines) {
  $p.Write(($line -replace "`r", "") + "`n")
  Start-Sleep -Milliseconds $LineDelayMs
}
$p.Write("EOF`n")
Start-Sleep -Milliseconds $LineDelayMs
$p.Write("stty echo 2>/dev/null || true`r`n")
Start-Sleep -Milliseconds $LineDelayMs
$p.Write("sh /tmp/serial_task.sh`r`n")
Start-Sleep -Milliseconds $LineDelayMs
$p.Write("rc=`$?; echo ${end}:`$rc`r`n")

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
