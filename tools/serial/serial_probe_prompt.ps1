param(
  [string]$Port = "COM3",
  [int]$Baud = 1500000,
  [int]$TimeoutSec = 12
)

$p = New-Object System.IO.Ports.SerialPort $Port, $Baud, "None", 8, "One"
$p.Handshake = [System.IO.Ports.Handshake]::None
$p.DtrEnable = $false
$p.RtsEnable = $false
$p.ReadTimeout = 200
$p.WriteTimeout = 2000
$p.Open()
Start-Sleep -Milliseconds 300

# try to break foreground process
$p.Write([char]3)
Start-Sleep -Milliseconds 200
$p.Write("`r`n")
$p.Write("echo __SERIAL_READY__`r`n")
$p.Write("whoami`r`n")
$p.Write("pwd`r`n")
$p.Write("date`r`n")

$buf = ""
$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
  $chunk = $p.ReadExisting()
  if ($chunk) { $buf += $chunk }
  if ($buf -match "__SERIAL_READY__") {
    # wait a bit more for command outputs
    Start-Sleep -Milliseconds 700
    $buf += $p.ReadExisting()
    break
  }
  Start-Sleep -Milliseconds 120
}
$p.Close()
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$buf
