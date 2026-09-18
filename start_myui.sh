#!/bin/sh

# Python myui launcher for the RK3588/Buildroot board.
# Keep this script POSIX-sh compatible: /etc/init.d/S51myui calls it directly.

set +e

BASE_DIR="${MYUI_BASE_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)}"
PID_FILE="${MYUI_PID_FILE:-$BASE_DIR/backend.pid}"
KIOSK_PID_FILE="${MYUI_KIOSK_PID_FILE:-$BASE_DIR/kiosk.pid}"
LOG_FILE="${MYUI_LOG_FILE:-$BASE_DIR/backend.log}"
KIOSK_LOG_FILE="${MYUI_KIOSK_LOG_FILE:-/tmp/myui_kiosk.log}"
KIOSK_URL="${MYUI_KIOSK_URL:-http://127.0.0.1:18080/index.html}"
DISABLE_KIOSK="${MYUI_DISABLE_KIOSK:-0}"
PYTHON_BIN="${MYUI_PYTHON_BIN:-python3}"
# Keep the kiosk close to a 480 CSS-pixel-wide touch UI.  Chromium on the
# board otherwise treats every panel pixel as one CSS pixel, making the
# phone-oriented controls and text unnecessarily small on a 1080px panel.
# Override either value from the init environment when another display is used.
MYUI_LOGICAL_WIDTH="${MYUI_LOGICAL_WIDTH:-480}"
MYUI_DEVICE_SCALE_FACTOR="${MYUI_DEVICE_SCALE_FACTOR:-}"

probe_camera_device() {
  dev="$1"
  [ -n "$dev" ] || return 1
  [ -e "$dev" ] || return 1
  command -v v4l2-ctl >/dev/null 2>&1 || return 1
  out="/tmp/myui_camera_probe_$$.bin"
  rm -f "$out" >/dev/null 2>&1 || true
  if ! v4l2-ctl -d "$dev" --stream-mmap=2 --stream-count=1 --stream-to="$out" >/dev/null 2>&1; then
    rm -f "$out" >/dev/null 2>&1 || true
    return 1
  fi
  size="$(wc -c <"$out" 2>/dev/null)"
  rm -f "$out" >/dev/null 2>&1 || true
  [ "${size:-0}" -gt 0 ]
}

bootstrap_camera_alias() {
  link="/dev/video-camera0"
  seen=""
  candidates=""

  add_candidate() {
    dev="$1"
    [ -n "$dev" ] || return 0
    case " $seen " in
      *" $dev "*) return 0 ;;
    esac
    seen="$seen $dev"
    candidates="$candidates $dev"
  }

  if [ -L "$link" ]; then
    target="$(readlink -f "$link" 2>/dev/null || true)"
    add_candidate "$target"
  fi

  for name_file in /sys/class/video4linux/video*/name; do
    [ -f "$name_file" ] || continue
    if [ "$(cat "$name_file" 2>/dev/null)" = "rkisp_mainpath" ]; then
      add_candidate "/dev/$(basename "$(dirname "$name_file")")"
    fi
  done

  add_candidate "/dev/video22"
  add_candidate "/dev/video31"
  add_candidate "/dev/video44"
  add_candidate "/dev/video62"

  for dev in $candidates; do
    if probe_camera_device "$dev"; then
      ln -sfn "$(basename "$dev")" "$link" >/dev/null 2>&1 || true
      echo "camera alias ready: $link -> $(basename "$dev")"
      return 0
    fi
  done

  echo "camera alias probe failed, keep existing mapping"
  return 1
}

mkdir -p "$BASE_DIR" || exit 1
cd "$BASE_DIR" || exit 1
touch "$LOG_FILE" "$KIOSK_LOG_FILE" 2>/dev/null || true

export MYUI_BASE_DIR="$BASE_DIR"
export MYUI_CONFIG="${MYUI_CONFIG:-$BASE_DIR/config.json}"

bootstrap_camera_alias >/dev/null 2>>"$LOG_FILE" || true

if [ ! -f "$BASE_DIR/backend.py" ]; then
  echo "backend.py not found: $BASE_DIR/backend.py"
  [ -x /etc/init.d/S50systemui ] && /etc/init.d/S50systemui start >/dev/null 2>&1 || true
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
  else
    echo "python not found"
    [ -x /etc/init.d/S50systemui ] && /etc/init.d/S50systemui start >/dev/null 2>&1 || true
    exit 1
  fi
fi

if ps -ef | grep "$BASE_DIR/backend.py" | grep -v grep >/dev/null 2>&1; then
  :
else
  # The serial console uses Ctrl-C to recover a shell.  Put the backend in a
  # separate session so that recovery cannot interrupt the HTTP service.
  if command -v setsid >/dev/null 2>&1; then
    nohup setsid "$PYTHON_BIN" "$BASE_DIR/backend.py" >>"$LOG_FILE" 2>&1 </dev/null &
  else
    nohup "$PYTHON_BIN" "$BASE_DIR/backend.py" >>"$LOG_FILE" 2>&1 </dev/null &
  fi
  echo "$!" > "$PID_FILE"
  sleep 1
fi

API_OK=0
for _ in $(seq 1 40); do
  if wget -T 1 -q -O /tmp/myui_api_ready.json http://127.0.0.1:18080/api/status >/dev/null 2>&1; then
    API_OK=1
    break
  fi
  sleep 0.25
done

if [ "$API_OK" != "1" ]; then
  echo "backend api is not ready yet, skip kiosk start"
  [ -x /etc/init.d/S50systemui ] && /etc/init.d/S50systemui start >/dev/null 2>&1 || true
  exit 0
fi

if [ "$DISABLE_KIOSK" = "1" ]; then
  echo "myui kiosk disabled (MYUI_DISABLE_KIOSK=1)"
  exit 0
fi

BROWSER_BIN=""
if command -v chromium >/dev/null 2>&1; then
  BROWSER_BIN="$(command -v chromium)"
elif command -v chromium-browser >/dev/null 2>&1; then
  BROWSER_BIN="$(command -v chromium-browser)"
elif [ -x /usr/bin/chromium ]; then
  BROWSER_BIN=/usr/bin/chromium
fi

if [ -z "$BROWSER_BIN" ]; then
  echo "chromium not found, backend keeps running"
  [ -x /etc/init.d/S50systemui ] && /etc/init.d/S50systemui start >/dev/null 2>&1 || true
  exit 0
fi

if [ -z "$MYUI_DEVICE_SCALE_FACTOR" ]; then
  FRAMEBUFFER_SIZE=""
  for FB_SIZE_FILE in /sys/class/graphics/fb*/virtual_size; do
    if [ -r "$FB_SIZE_FILE" ]; then
      FRAMEBUFFER_SIZE="$(cat "$FB_SIZE_FILE" 2>/dev/null || true)"
      [ -n "$FRAMEBUFFER_SIZE" ] && break
    fi
  done
  FRAMEBUFFER_WIDTH="${FRAMEBUFFER_SIZE%%,*}"
  case "$FRAMEBUFFER_WIDTH:$MYUI_LOGICAL_WIDTH" in
    *[!0-9:]*|:*|*:) MYUI_DEVICE_SCALE_FACTOR="2" ;;
    *)
      MYUI_DEVICE_SCALE_FACTOR="$(awk -v width="$FRAMEBUFFER_WIDTH" -v logical="$MYUI_LOGICAL_WIDTH" \
        'BEGIN { scale = width / logical; if (scale < 1) scale = 1; if (scale > 3) scale = 3; printf "%.2f", scale }')"
      ;;
  esac
fi
echo "kiosk display scale: $MYUI_DEVICE_SCALE_FACTOR (logical width: $MYUI_LOGICAL_WIDTH)"

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/var/run}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"

WAYLAND_SOCK="$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY"
READY=0
for _ in $(seq 1 100); do
  if [ -S "$WAYLAND_SOCK" ]; then
    READY=1
    break
  fi
  sleep 0.1
done

if [ "$READY" != "1" ]; then
  echo "wayland socket not ready: $WAYLAND_SOCK"
  [ -x /etc/init.d/S50systemui ] && /etc/init.d/S50systemui start >/dev/null 2>&1 || true
  exit 0
fi

[ -x /etc/init.d/S50systemui ] && /etc/init.d/S50systemui stop >/dev/null 2>&1 || true
killall systemui >/dev/null 2>&1 || true
killall chromium chromium-bin chromium-browser chrome_crashpad_handler >/dev/null 2>&1 || true
rm -f "$KIOSK_PID_FILE" >/dev/null 2>&1 || true

nohup "$BROWSER_BIN" \
  --ozone-platform=wayland \
  --enable-features=UseOzonePlatform \
  --no-sandbox \
  --disable-infobars \
  --no-first-run \
  --disable-session-crashed-bubble \
  --user-data-dir=/tmp/myui_chrome_profile \
  --force-device-scale-factor="$MYUI_DEVICE_SCALE_FACTOR" \
  --kiosk "$KIOSK_URL" \
  >"$KIOSK_LOG_FILE" 2>&1 </dev/null &

KP=$!
echo "$KP" > "$KIOSK_PID_FILE"
sleep 2

if kill -0 "$KP" >/dev/null 2>&1; then
  echo "myui started (python+kiosk, pid=$KP, url=$KIOSK_URL)"
  exit 0
fi

rm -f "$KIOSK_PID_FILE" >/dev/null 2>&1 || true
[ -x /etc/init.d/S50systemui ] && /etc/init.d/S50systemui start >/dev/null 2>&1 || true
echo "myui backend started, but kiosk failed"
exit 0
