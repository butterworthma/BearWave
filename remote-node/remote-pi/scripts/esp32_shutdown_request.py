#!/usr/bin/env python3
"""
BearWave ESP32 shutdown request helper
--------------------------------------

This is a fallback helper used by the boot wrapper.

The normal BearWave remote-node controller should send SHUTDOWN to the ESP32
itself. This helper exists so the wrapper can still ask the ESP32 to cut power
if the main application crashes or exits early.
"""

from __future__ import annotations

import argparse
import sys
import time

import serial


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/serial0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()

    try:
        with serial.Serial(
            port=args.port,
            baudrate=args.baud,
            timeout=args.timeout,
            write_timeout=1.0,
        ) as ser:
            time.sleep(0.5)
            ser.reset_input_buffer()
            ser.write(b"SHUTDOWN\n")
            ser.flush()

            line = ser.readline().decode("utf-8", errors="replace").strip()

            print(f"[ESP32] Shutdown response: {line}")

            if line == "OK,SHUTDOWN_RECEIVED":
                return 0

            return 1

    except Exception as exc:
        print(f"[ESP32] Failed to request shutdown: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
