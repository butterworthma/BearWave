#!/usr/bin/env python3
"""
BearWave ESP32 time synchronisation helper
------------------------------------------

Purpose:
  - Open the Pi UART connected to the ESP32.
  - Send PING to confirm the ESP32 is alive.
  - Send TIME? to retrieve RTC/GPS-derived UTC time.
  - Set the Raspberry Pi Linux system clock from that UTC time.

Expected ESP32 command behaviour:

  PING
    -> PONG

  TIME?
    -> TIME,YYYY-MM-DDTHH:MM:SSZ

This script should run as root because setting the Linux system clock requires
elevated privileges.

Example:
  sudo /home/mark/bearwave/.venv/bin/python /home/mark/bearwave/scripts/esp32_set_time.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import time

import serial


def read_line(ser: serial.Serial, timeout_s: float) -> str | None:
    """
    Read one line from the ESP32 UART.

    Returns:
      - stripped text line if received
      - None on timeout
    """
    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        raw = ser.readline()

        if not raw:
            continue

        try:
            line = raw.decode("utf-8", errors="replace").strip()
        except Exception:
            continue

        if line:
            return line

    return None


def send_command(ser: serial.Serial, command: str, timeout_s: float) -> str:
    """
    Send one line-based command and return one line of response.
    """
    ser.reset_input_buffer()
    ser.write((command + "\n").encode("ascii"))
    ser.flush()

    response = read_line(ser, timeout_s)

    if response is None:
        raise RuntimeError(f"No response from ESP32 for command {command!r}")

    return response


def parse_esp32_time(response: str) -> dt.datetime:
    """
    Parse:

      TIME,YYYY-MM-DDTHH:MM:SSZ

    into a timezone-aware UTC datetime.
    """
    if not response.startswith("TIME,"):
        raise RuntimeError(f"ESP32 did not return TIME response: {response!r}")

    iso_text = response.removeprefix("TIME,").strip()

    if not iso_text.endswith("Z"):
        raise RuntimeError(f"ESP32 time is not UTC/Zulu format: {iso_text!r}")

    clean = iso_text.removesuffix("Z")

    parsed = dt.datetime.strptime(clean, "%Y-%m-%dT%H:%M:%S")
    return parsed.replace(tzinfo=dt.timezone.utc)


def set_system_time_utc(timestamp: dt.datetime) -> None:
    """
    Set Linux system time to UTC.

    This disables NTP first so systemd-timesyncd or another time service does
    not immediately fight the manual time set during isolated field operation.
    """
    if os.geteuid() != 0:
        raise RuntimeError("This script must run as root to set system time")

    date_arg = timestamp.strftime("%Y-%m-%d %H:%M:%S")

    subprocess.run(
        ["timedatectl", "set-ntp", "false"],
        check=False,
    )

    subprocess.run(
        ["date", "-u", "-s", date_arg],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/serial0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--retries", type=int, default=20)
    args = parser.parse_args()

    last_error: Exception | None = None

    for attempt in range(1, args.retries + 1):
        try:
            print(f"[TIME] Opening ESP32 UART {args.port} attempt {attempt}/{args.retries}")

            with serial.Serial(
                port=args.port,
                baudrate=args.baud,
                timeout=0.5,
                write_timeout=1.0,
            ) as ser:
                time.sleep(0.5)

                pong = send_command(ser, "PING", args.timeout)

                if pong != "PONG":
                    raise RuntimeError(f"Unexpected PING response: {pong!r}")

                time_response = send_command(ser, "TIME?", args.timeout)
                esp_time = parse_esp32_time(time_response)

                print(f"[TIME] ESP32 UTC time: {esp_time.isoformat()}")

                set_system_time_utc(esp_time)

                print("[TIME] Raspberry Pi system time set from ESP32")
                return 0

        except Exception as exc:
            last_error = exc
            print(f"[TIME] Attempt {attempt} failed: {exc}", file=sys.stderr)
            time.sleep(1.0)

    print(f"[TIME] Failed to set time after {args.retries} attempts: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
