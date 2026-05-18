#!/usr/bin/env python3
"""Wi-Fi routes and ConnMan helpers."""
from __future__ import annotations

import os
import pty
import re
import select
import shlex
import subprocess
import time

from app.routes.system_routes import run_cmd
from app.utils.log import log

SERVICE_RE = re.compile(r"^\s*(?P<prefix>[\*AOR ]{0,4})\s*(?P<name>.*?)\s{2,}(?P<service>wifi_[^\s]+)$")


def _wifi_technology_block(raw: str) -> str:
    block_lines = []
    capture = False
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("/net/connman/technology/"):
            capture = stripped.endswith("/wifi")
            if capture:
                block_lines = [line]
            continue
        if capture:
            if line and not line.startswith(" "):
                break
            block_lines.append(line)
    return "\n".join(block_lines)


def get_wifi_status() -> str:
    services = list_wifi_services()
    for item in services:
        if item.get("connected"):
            return f"{item.get('name', 'wifi')}: connected"
    tech = run_cmd("connmanctl technologies")
    wifi_block = _wifi_technology_block(tech)
    if wifi_block:
        if "Powered = False" in wifi_block:
            return "wifi: powered off"
        if "Powered = True" in wifi_block:
            if os.path.exists("/sys/class/net/wlan0/operstate"):
                try:
                    with open("/sys/class/net/wlan0/operstate", "r", encoding="utf-8") as f:
                        state = f.read().strip()
                    return f"wlan0: {state or 'idle'}"
                except Exception:
                    pass
            return "wifi: enabled"
    if "Powered = False" in tech:
        return "wifi: powered off"
    if os.path.exists("/sys/class/net/wlan0/operstate"):
        try:
            with open("/sys/class/net/wlan0/operstate", "r", encoding="utf-8") as f:
                state = f.read().strip()
            return f"wlan0: {state}"
        except Exception:
            pass
    return "wifi: idle"


def list_wifi_services() -> list:
    raw = run_cmd("connmanctl services")
    items = []
    for line in raw.splitlines():
        line = line.rstrip()
        if not line or "wifi_" not in line:
            continue
        m = SERVICE_RE.match(line)
        if not m:
            continue
        prefix = (m.group("prefix") or "").strip()
        name = (m.group("name") or "").strip()
        service = m.group("service").strip()
        if service.endswith("_managed_none"):
            security = "open"
        elif service.endswith("_managed_psk"):
            security = "psk"
        else:
            security = "other"
        items.append({
            "name": name if name else "(隐藏网络)",
            "service": service,
            "connected": "*" in prefix,
            "favorite": "A" in prefix,
            "online": "O" in prefix,
            "security": security,
        })
    return items


def service_is_connected(service_id: str) -> bool:
    for item in list_wifi_services():
        if item["service"] == service_id and item["connected"]:
            return True
    return False


def scan_wifi() -> dict:
    run_cmd("connmanctl enable wifi")
    msg = run_cmd("connmanctl scan wifi")
    time.sleep(1.0)
    return {"ok": True, "msg": msg or "scan requested", "services": list_wifi_services()}


def _read_some(fd: int, timeout: float = 0.5) -> str:
    buf = ""
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.1)
        if fd not in r:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk.decode("utf-8", errors="ignore")
        if len(chunk) < 4096:
            break
    return buf


def set_service_autoconnect(service_id: str, enabled: bool) -> str:
    value_candidates = ["yes" if enabled else "no", "true" if enabled else "false", "on" if enabled else "off"]
    cmd_prefix = f"connmanctl config {shlex.quote(service_id)} --autoconnect "
    last_msg = ""
    for value in value_candidates:
        msg = run_cmd(cmd_prefix + value)
        last_msg = msg
        low = msg.lower()
        if not msg or ("usage" not in low and "error" not in low and "invalid" not in low):
            return msg
    return last_msg


def connect_wifi(service_id: str, passphrase: str) -> dict:
    run_cmd("connmanctl enable wifi")
    master, slave = pty.openpty()
    proc = subprocess.Popen(["connmanctl"], stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    transcript = ""
    ok = False
    sent_pass = False
    try:
        deadline = time.time() + 45
        while time.time() < deadline:
            out = _read_some(master, 0.5)
            if out:
                transcript += out
                if "connmanctl>" in transcript:
                    break
        os.write(master, b"agent on\n")
        time.sleep(0.3)
        transcript += _read_some(master, 1.0)
        os.write(master, f"connect {service_id}\n".encode("utf-8"))
        deadline = time.time() + 40
        while time.time() < deadline:
            out = _read_some(master, 1.0)
            if out:
                transcript += out
                low = transcript.lower()
                if ("passphrase?" in low) and (not sent_pass):
                    os.write(master, (passphrase + "\n").encode("utf-8"))
                    sent_pass = True
                    continue
                if f"connected {service_id}".lower() in low or "already connected" in low:
                    ok = True
                    break
                if "error" in low and "already connected" not in low:
                    break
            if service_is_connected(service_id):
                ok = True
                break
        try:
            os.write(master, b"quit\n")
        except Exception:
            pass
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
        try:
            os.close(master)
        except Exception:
            pass
    if service_is_connected(service_id):
        ok = True
    if ok:
        set_service_autoconnect(service_id, True)
        return {"ok": True, "msg": "connected", "log": transcript[-1200:]}
    return {"ok": False, "msg": transcript[-1200:] or "connect failed"}


def disconnect_wifi(service_id: str) -> dict:
    service_id = (service_id or "").strip()
    if not service_id:
        return {"ok": False, "msg": "service is empty"}
    set_service_autoconnect(service_id, False)
    if not service_is_connected(service_id):
        return {"ok": True, "msg": "already disconnected"}
    msg = run_cmd(f"connmanctl disconnect {shlex.quote(service_id)}")
    time.sleep(1.0)
    if not service_is_connected(service_id):
        return {"ok": True, "msg": msg or "disconnected"}
    return {"ok": False, "msg": msg or "disconnect failed"}


def handle_get(path: str, query: dict | None = None):
    if path == "/api/wifi/list":
        return {"ok": True, "services": list_wifi_services()}, 200
    return None


def handle_post(path: str, payload: dict | None = None):
    payload = payload or {}
    if path == "/api/wifi/scan":
        log("POST /api/wifi/scan")
        return scan_wifi(), 200
    if path == "/api/wifi/connect":
        service = (payload.get("service") or "").strip()
        passphrase = payload.get("passphrase") or ""
        if not service:
            return {"ok": False, "msg": "service is empty"}, 400
        log(f"POST /api/wifi/connect {service}")
        result = connect_wifi(service, passphrase)
        return result, 200 if result.get("ok") else 500
    if path == "/api/wifi/disconnect":
        service = (payload.get("service") or "").strip()
        if not service:
            return {"ok": False, "msg": "service is empty"}, 400
        log(f"POST /api/wifi/disconnect {service}")
        result = disconnect_wifi(service)
        return result, 200 if result.get("ok") else 500
    return None
