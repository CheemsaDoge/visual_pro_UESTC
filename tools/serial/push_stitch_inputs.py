#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shlex
import sys
import time
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
PYDEPS = ROOT / ".tmp" / "pydeps"
if str(PYDEPS) not in sys.path:
    sys.path.insert(0, str(PYDEPS))

import serial  # type: ignore
from xmodem import XMODEM1k  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Push local stitch input images to the board over serial XMODEM."
    )
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--baud", type=int, default=1_500_000)
    parser.add_argument(
        "--tty",
        default="",
        help="Remote tty device for rx redirection. Leave empty to use the current shell session.",
    )
    parser.add_argument("--images-dir", default=str(ROOT / "reports" / "imgs"))
    parser.add_argument("--dest-dir", default="/userdata/myui/stitch_input")
    parser.add_argument("--glob", default="*.JPG")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--settle-ms", type=int, default=400)
    return parser.parse_args()


def log(msg: str) -> None:
    print(msg, flush=True)


def md5sum(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_until_quiet(ser: serial.Serial, seconds: float) -> bytes:
    deadline = time.monotonic() + seconds
    buf = bytearray()
    while time.monotonic() < deadline:
        chunk = ser.read(max(1, ser.in_waiting or 1))
        if chunk:
            buf.extend(chunk)
            deadline = time.monotonic() + seconds
        else:
            time.sleep(0.05)
    return bytes(buf)


def wait_for_pattern(
    ser: serial.Serial,
    pattern: bytes,
    timeout: float,
    label: str,
) -> bytes:
    deadline = time.monotonic() + timeout
    buf = bytearray()
    while time.monotonic() < deadline:
        chunk = ser.read(max(1, ser.in_waiting or 1))
        if chunk:
            buf.extend(chunk)
            if pattern in buf:
                return bytes(buf)
        else:
            time.sleep(0.05)
    tail = bytes(buf[-400:]).decode("utf-8", errors="replace")
    raise TimeoutError(f"Timed out waiting for {label}. Tail:\n{tail}")


def write_line(ser: serial.Serial, line: str) -> None:
    ser.write(line.encode("utf-8") + b"\r\n")
    ser.flush()


def abort_inflight_xmodem(ser: serial.Serial) -> None:
    # BusyBox rx exits cleanly when it sees repeated CAN bytes.
    ser.write(b"\x18" * 8)
    ser.write(b"\x03" * 2)
    ser.write(b"\r\n")
    ser.flush()


def recover_console(ser: serial.Serial, settle_ms: int) -> None:
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    abort_inflight_xmodem(ser)
    time.sleep(settle_ms / 1000.0)
    warmup = read_until_quiet(ser, 0.8).decode("utf-8", errors="replace")
    if "debug>" in warmup:
        log("debug> detected, switching back to shell")
        write_line(ser, "console")
        time.sleep(0.8)
        read_until_quiet(ser, 0.6)
        abort_inflight_xmodem(ser)
    token = "__SERIAL_READY__"
    for attempt in range(2):
        write_line(ser, f"printf '{token}\\n'")
        try:
            wait_for_pattern(ser, token.encode("utf-8"), 8, token)
            break
        except TimeoutError:
            if attempt == 1:
                raise
            abort_inflight_xmodem(ser)
            time.sleep(0.8)
    read_until_quiet(ser, 0.2)


def wait_for_crc_request(ser: serial.Serial, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    buf = bytearray()
    while time.monotonic() < deadline:
        chunk = ser.read(max(1, ser.in_waiting or 1))
        if chunk:
            buf.extend(chunk)
            if b"C" in chunk or b"\x15" in chunk:
                return
        else:
            time.sleep(0.05)
    tail = bytes(buf[-400:]).decode("utf-8", errors="replace")
    raise TimeoutError(f"rx did not request CRC in time. Tail:\n{tail}")


def xmodem_send(ser: serial.Serial, path: Path) -> None:
    def getc(size: int, timeout: int = 10) -> bytes | None:
        old = ser.timeout
        ser.timeout = timeout
        try:
            data = ser.read(size)
            return data or None
        finally:
            ser.timeout = old

    def putc(data: bytes, timeout: int = 10) -> int | None:
        old_write = ser.write_timeout
        ser.write_timeout = timeout
        try:
            return ser.write(data)
        finally:
            ser.write_timeout = old_write

    sent_blocks = {"count": 0}

    def callback(total_packets: int, success_count: int, error_count: int) -> None:
        if success_count > sent_blocks["count"]:
            sent_blocks["count"] = success_count
            if success_count == 1 or success_count % 32 == 0 or success_count == total_packets:
                log(
                    f"  blocks {success_count}/{total_packets} errors={error_count}"
                )

    modem = XMODEM1k(getc, putc)
    with path.open("rb") as stream:
        ok = modem.send(stream, retry=32, timeout=12, quiet=True, callback=callback)
    if not ok:
        raise RuntimeError(f"XMODEM send failed for {path.name}")


def parse_verify_block(output: str, remote_path: str) -> tuple[int, str, str]:
    rc_match = re.search(r"__RXRC__:(\d+)", output)
    if not rc_match:
        raise RuntimeError(f"Missing rx exit code in output:\n{output}")
    rx_rc = int(rc_match.group(1))

    md5_match = re.search(
        rf"([0-9a-fA-F]{{32}})\s+{re.escape(remote_path)}",
        output,
    )
    if not md5_match:
        raise RuntimeError(f"Missing remote md5sum in output:\n{output}")
    remote_md5 = md5_match.group(1).lower()

    size_match = re.search(r"__SIZE__:(\d+)", output)
    if not size_match:
        raise RuntimeError(f"Missing remote size in output:\n{output}")
    remote_size = size_match.group(1)
    return rx_rc, remote_md5, remote_size


def verify_remote(
    ser: serial.Serial,
    remote_path: str,
    timeout: float,
) -> tuple[int, str, str]:
    token = "__VERIFY_DONE__"
    qpath = shlex.quote(remote_path)
    cmd = (
        f"rc=$?; printf '__RXRC__:%s\\n' \"$rc\"; "
        f"(md5sum {qpath} || busybox md5sum {qpath}) 2>/dev/null; "
        f"printf '__SIZE__:%s\\n' \"$(wc -c < {qpath})\"; "
        f"printf '{token}\\n'"
    )
    write_line(ser, cmd)
    raw = wait_for_pattern(ser, token.encode("utf-8"), timeout, token)
    text = raw.decode("utf-8", errors="replace")
    return parse_verify_block(text, remote_path)


def iter_images(images_dir: Path, pattern: str) -> Iterable[Path]:
    for path in sorted(images_dir.glob(pattern)):
        if path.is_file():
            yield path


def push_one(
    ser: serial.Serial,
    image: Path,
    dest_dir: str,
    tty: str,
    timeout: float,
) -> None:
    local_md5 = md5sum(image)
    local_size = image.stat().st_size
    remote_path = f"{dest_dir.rstrip('/')}/{image.name}"
    qdir = shlex.quote(dest_dir)
    qremote = shlex.quote(remote_path)
    log(f"Sending {image.name} ({local_size} bytes)")
    setup = f"mkdir -p {qdir} && rm -f {qremote} && rx {qremote}"
    if tty:
        qty = shlex.quote(tty)
        setup += f" < {qty} > {qty}"
    ser.reset_input_buffer()
    write_line(ser, setup)
    wait_for_crc_request(ser, timeout)
    xmodem_send(ser, image)
    time.sleep(0.3)

    rx_rc, remote_md5, remote_size = verify_remote(ser, remote_path, timeout + 30)
    if rx_rc != 0:
        raise RuntimeError(f"rx exited with rc={rx_rc} for {image.name}")
    if remote_md5 != local_md5:
        raise RuntimeError(
            f"MD5 mismatch for {image.name}: local={local_md5} remote={remote_md5}"
        )
    if remote_size != str(local_size):
        raise RuntimeError(
            f"Size mismatch for {image.name}: local={local_size} remote={remote_size}"
        )
    log(f"Verified {image.name} md5={remote_md5}")


def main() -> int:
    args = parse_args()
    images_dir = Path(args.images_dir).resolve()
    images = list(iter_images(images_dir, args.glob))
    if not images:
        raise SystemExit(f"No files matched {args.glob} under {images_dir}")

    log(f"Using images from {images_dir}")
    log(f"Target: {args.port} @ {args.baud} -> {args.dest_dir}")

    ser = serial.Serial(
        port=args.port,
        baudrate=args.baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.3,
        write_timeout=12,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )
    try:
        time.sleep(args.settle_ms / 1000.0)
        recover_console(ser, args.settle_ms)
        for image in images:
            push_one(ser, image, args.dest_dir, args.tty, args.timeout)
        log("All files pushed and verified.")
        return 0
    finally:
        ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
