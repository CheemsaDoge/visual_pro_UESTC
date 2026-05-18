# Repository Guidelines

## Project Structure & Module Organization
This repository is a lightweight Python/HTML GUI for a visual stitching workbench on the RK3588 board.
- `backend.py`: HTTP server, API routes, Wi-Fi helpers, camera capture, and built-in OpenCV stitching.
- `index.html`, `stitch.html`, `wifi.html`: static vanilla HTML/CSS/JS pages.
- `config.json`: runtime defaults for port, UI font size, stitch paths, and camera settings.
- `stitch_demo.py`: optional external stitcher used when `stitch.engine` is `script`.
- `_stitch_work/`, `stitch_input/`, `stitch_output/`: runtime directories; commit only their `.gitkeep` files.
- `start_myui.sh` and `stop_myui.sh`: target-device backend and kiosk lifecycle scripts.

## Build, Test, and Development Commands
- `python3 backend.py` — run the local server at `http://127.0.0.1:18080`.
- `MYUI_CONFIG=/path/to/config.json python3 backend.py` — test an alternate configuration.
- `python3 -m py_compile backend.py stitch_demo.py` — quick syntax check.
- `python3 stitch_demo.py --output stitch_output/test.jpg stitch_input/a.jpg stitch_input/b.jpg` — exercise script-based stitching.
- `./start_myui.sh` / `./stop_myui.sh` — start or stop the device kiosk workflow.

## Development Board Serial Access
The board was verified over Windows serial port `COM3`, shown as `USB-Enhanced-SERIAL CH343`, using `1500000` baud, `8N1`, and no flow control. From WSL, use the Windows PowerShell helper rather than guessing `/dev/ttyS*` mappings:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass \
  -File "$(wslpath -w tools/serial/serial_probe_prompt.ps1)" \
  -Port COM3 -Baud 1500000 -TimeoutSec 12
```

A successful probe returns a shell prompt like `root@ATK-DLRK3588:/#` and prints `__SERIAL_READY__`, `whoami`, `pwd`, and `date`.

## Preferred Dev-Board Skills
Reusable board-access skills are installed globally under `C:\Users\ywjhn\.agents\skills\`:
- `devboard-toolkit`: shared PowerShell helpers for serial recovery, Wi-Fi join, SSH bootstrap, and `scp`
- `devboard-serial`: focused serial-console workflow
- `devboard-scp`: serial-assisted Wi-Fi plus `scp` workflow

Primary script entrypoints:
- `C:\Users\ywjhn\.agents\skills\devboard-toolkit\bin\board_serial_probe.ps1`
- `C:\Users\ywjhn\.agents\skills\devboard-toolkit\bin\board_wifi_connect.ps1`
- `C:\Users\ywjhn\.agents\skills\devboard-toolkit\bin\board_ssh_bootstrap.ps1`
- `C:\Users\ywjhn\.agents\skills\devboard-toolkit\bin\board_scp_push.ps1`

Board-access defaults in those skills:
- serial port `COM3`, baud `1500000`
- Wi-Fi SSID hint `zizek`
- Wi-Fi password `12345678`
- SSH user `root`

The Wi-Fi join logic intentionally matches by case-insensitive SSID and then substring, so the default hint `zizek` still finds hotspot names like `ZIZEK 6512`.

## Board Wi-Fi And SCP
When network transfer is available, prefer Wi-Fi plus `scp` over large serial payloads.
- Host hotspot network observed during validation: `192.168.137.1/24`
- Board IP observed after join: `192.168.137.123`
- The older ad hoc key used in this repo session is `.tmp/board_scp_key`
- The reusable skill pack now defaults to a temporary host key under `%TEMP%\devboard_skill_ed25519`

Typical pull/push flow should be:
1. recover shell over serial
2. join hotspot with `connmanctl`
3. install SSH public key through serial
4. transfer files with `scp`
5. verify integrity with `md5sum`

## Board Artifact Snapshots
Fetched board artifacts should be stored as dated snapshots under `reports/`, not mixed into runtime directories.

Current snapshot from `/userdata/myui/stitch_input` and `/userdata/myui/stitch_output`:
- `reports/board-fetch-20260518-213920/in`
- `reports/board-fetch-20260518-213920/stitchout`

Do not commit fetched image data unless the user explicitly asks for those artifacts to become part of the repo history.

## Coding Style & Naming Conventions
Use 4-space indentation and `snake_case` for Python. Keep API routes lowercase and path-like, for example `/api/stitch/image`. Preserve POSIX `sh` compatibility in shell scripts. Keep frontend changes framework-free unless a build system is introduced. Format JSON with two-space indentation and keep deployment paths configurable.

## Testing Guidelines
There is no formal test suite. For backend changes, run `py_compile`, start `backend.py`, and smoke-test `/api/status`, `/api/config/public`, and modified routes. For UI changes, verify all three pages in a browser and check the console. For stitching changes, test built-in mode and, when relevant, `stitch.engine = "script"`.

## Commit & Pull Request Guidelines
No Git history is available in this checkout. Use short imperative commit messages, optionally scoped: `backend: validate stitch uploads`, `ui: simplify camera controls`. Pull requests should include a summary, changed routes or files, manual test steps, configuration changes, and screenshots or clips for UI behavior.

## Security & Configuration Tips
Do not commit generated images, logs, PID files, local `.codex` markers, or device-specific secrets. Validate uploaded filenames and sizes consistently with `ALLOWED_IMAGE_EXTS` and `max_image_bytes`.
