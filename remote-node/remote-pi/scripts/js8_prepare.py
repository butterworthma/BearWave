#!/usr/bin/env python3
"""
BearWave JS8Call preparation helper
-----------------------------------

Purpose:
  - Wait for the JS8Call TCP API.
  - Set the JS8Call dial frequency to 7.078 MHz.
  - Verify the configured frequency using RIG.GET_FREQ.

JS8Call API messages are newline-delimited JSON.

The frequency used here is the JS8Call dial frequency:

  7.078 MHz = 7078000 Hz

The audio offset is left to the JS8Call/radio configuration.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from typing import Any


def send_json(sock: socket.socket, message: dict[str, Any]) -> None:
    payload = json.dumps(message, separators=(",", ":")) + "\n"
    sock.sendall(payload.encode("utf-8"))


def read_json_line(sock: socket.socket, timeout_s: float) -> dict[str, Any] | None:
    sock.settimeout(timeout_s)

    buffer = b""

    while True:
        try:
            chunk = sock.recv(1)
        except socket.timeout:
            return None

        if not chunk:
            return None

        if chunk == b"\n":
            break

        buffer += chunk

    if not buffer.strip():
        return None

    try:
        return json.loads(buffer.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None


def wait_for_js8_api(host: str, port: int, timeout_s: float) -> socket.socket:
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            sock = socket.create_connection((host, port), timeout=2.0)
            print(f"[JS8] Connected to JS8Call API at {host}:{port}")
            return sock
        except Exception as exc:
            last_error = exc
            time.sleep(1.0)

    raise RuntimeError(f"JS8Call API did not become available: {last_error}")


def set_frequency(sock: socket.socket, dial_hz: int) -> None:
    message_id = str(int(time.time() * 1000))

    message = {
        "type": "RIG.SET_FREQ",
        "value": "",
        "params": {
            "DIAL": dial_hz,
            "_ID": message_id,
        },
    }

    print(f"[JS8] Setting dial frequency to {dial_hz} Hz")
    send_json(sock, message)


def request_frequency(sock: socket.socket) -> None:
    message_id = str(int(time.time() * 1000))

    message = {
        "type": "RIG.GET_FREQ",
        "value": "",
        "params": {
            "_ID": message_id,
        },
    }

    send_json(sock, message)


def wait_for_frequency(sock: socket.socket, expected_dial_hz: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        request_frequency(sock)

        response = read_json_line(sock, timeout_s=2.0)

        if response is None:
            continue

        msg_type = response.get("type")
        params = response.get("params") or {}

        if msg_type in {"RIG.FREQ", "STATION.STATUS"}:
            dial = params.get("DIAL")

            print(f"[JS8] Frequency response type={msg_type} DIAL={dial}")

            if int(dial) == int(expected_dial_hz):
                return True

    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2442)
    parser.add_argument("--dial-hz", type=int, default=7078000)
    parser.add_argument("--api-timeout", type=float, default=60.0)
    parser.add_argument("--verify-timeout", type=float, default=20.0)
    args = parser.parse_args()

    try:
        with wait_for_js8_api(args.host, args.port, args.api_timeout) as sock:
            set_frequency(sock, args.dial_hz)

            ok = wait_for_frequency(
                sock=sock,
                expected_dial_hz=args.dial_hz,
                timeout_s=args.verify_timeout,
            )

            if not ok:
                print(
                    f"[JS8] Frequency verification failed for {args.dial_hz} Hz",
                    file=sys.stderr,
                )
                return 1

            print(f"[JS8] Frequency verified at {args.dial_hz} Hz")
            return 0

    except Exception as exc:
        print(f"[JS8] Preparation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
