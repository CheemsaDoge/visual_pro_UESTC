$lines = @(
  'echo __PROC__',
  'ps -ef | grep -E "backend.py|chromium|systemui|weston" | grep -v grep',
  'echo ---kiosk---',
  'tail -n 30 /tmp/myui_kiosk.log || true'
)
& ./serial_run_lines.ps1 -Port COM3 -Baud 1500000 -Lines $lines -TimeoutSec 8 -ReadGapMs 350
