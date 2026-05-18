#!/bin/sh

# Stop Python myui and restore the vendor system UI when available.

set +e

BASE_DIR="${MYUI_BASE_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)}"
PID_FILE="${MYUI_PID_FILE:-$BASE_DIR/backend.pid}"
KIOSK_PID_FILE="${MYUI_KIOSK_PID_FILE:-$BASE_DIR/kiosk.pid}"

if [ -f "$KIOSK_PID_FILE" ]; then
  KP="$(cat "$KIOSK_PID_FILE" 2>/dev/null)"
  if [ -n "$KP" ]; then
    kill "$KP" >/dev/null 2>&1 || true
    sleep 0.5
    kill -9 "$KP" >/dev/null 2>&1 || true
  fi
  rm -f "$KIOSK_PID_FILE" >/dev/null 2>&1 || true
fi

killall chromium chromium-bin chromium-browser chrome_crashpad_handler >/dev/null 2>&1 || true

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null)"
  if [ -n "$PID" ]; then
    kill "$PID" >/dev/null 2>&1 || true
    for _ in $(seq 1 30); do
      kill -0 "$PID" >/dev/null 2>&1 || break
      sleep 0.2
    done
    kill -9 "$PID" >/dev/null 2>&1 || true
  fi
  rm -f "$PID_FILE" >/dev/null 2>&1 || true
fi

if command -v pkill >/dev/null 2>&1; then
  pkill -f "$BASE_DIR/backend.py" >/dev/null 2>&1 || true
else
  ps -ef | grep "$BASE_DIR/backend.py" | grep -v grep | awk '{print $2}' | while read pid; do
    [ -n "$pid" ] && kill "$pid" >/dev/null 2>&1 || true
  done
fi

[ -x /etc/init.d/S50systemui ] && /etc/init.d/S50systemui start >/dev/null 2>&1 || true

echo "myui stopped (python mode)"
