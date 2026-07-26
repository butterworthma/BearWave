from __future__ import annotations

"""
BearWave ESP32 UART helper module
=================================

WHAT THIS MODULE DOES
---------------------
This module provides a clean Python interface between the Raspberry Pi and the
ESP32 supervisory controller used in the BearWave remote node.

The ESP32 is responsible for:
- maintaining local hardware awareness
- exposing UTC time from the RTC
- reporting battery status
- reporting GPS coordinates if available
- reporting current event state (trap, low battery, both, or none)
- accepting commands from the Pi to mark events as successfully reported
- accepting a shutdown request from the Pi before Pi power is removed

The Raspberry Pi should NOT need to know the low-level UART details each time
it wants to query the ESP32. Instead, it should be able to call clear Python
methods such as:

    get_time_iso()
    get_battery()
    get_coordinates()
    get_event()
    acknowledge_event("TRAP")
    request_shutdown()

This module hides the UART details and exposes those higher-level methods.
"""

from dataclasses import dataclass
from typing import Optional
import re
import time

import serial


# ============================================================================
# Custom exceptions
# ============================================================================


class EspUartError(Exception):
    """
    Base exception for all ESP32 UART helper problems.
    """


class EspTimeoutError(EspUartError):
    """
    Raised when the ESP32 does not respond within the configured timeout.
    """


class EspProtocolError(EspUartError):
    """
    Raised when the ESP32 responds, but the response format is invalid or
    unexpected.
    """


# ============================================================================
# Structured result dataclasses
# ============================================================================


@dataclass(frozen=True)
class BatteryStatus:
    """
    Parsed battery status returned by BAT?
    """
    voltage_v: float
    percent: int


@dataclass(frozen=True)
class CoordinateStatus:
    """
    Parsed coordinate status returned by COORD?
    """
    valid: bool
    latitude: Optional[float] = None
    longitude: Optional[float] = None


@dataclass(frozen=True)
class EventStatus:
    """
    Parsed event state returned by EVENT?
    """
    raw: str
    trap_active: bool
    low_battery_active: bool

    @property
    def is_none(self) -> bool:
        """
        True only when neither trap nor low battery is active.
        """
        return not self.trap_active and not self.low_battery_active


# ============================================================================
# Main UART client
# ============================================================================


class EspUartClient:
    """
    BearWave ESP32 UART helper.

    EXPECTED COMMAND/RESPONSE PAIRS
    -------------------------------
      PING                -> PONG
      STATUS?             -> OK,BEARWAVE_RTC_GPS_EVENTS
      TIME?               -> TIME,YYYY-MM-DDTHH:MM:SSZ
      BAT?                -> BAT,<voltage>,<percent>
      COORD?              -> COORD,<lat>,<lon> or COORD,INVALID
      EVENT?              -> EVENT,NONE / TRAP / LOW_BAT / TRAP+LOW_BAT
      EVENT_ACKED,TRAP    -> OK,EVENT_ACKED,TRAP
      EVENT_ACKED,LOW_BAT -> OK,EVENT_ACKED,LOW_BAT
      EVENT_ACKED,ALL     -> OK,EVENT_ACKED,ALL
      SHUTDOWN            -> OK,SHUTDOWN_RECEIVED
    """

    _TIME_RE = re.compile(
        r"^TIME,(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)$"
    )
    _BAT_RE = re.compile(r"^BAT,([0-9]+(?:\.[0-9]+)?),(\d{1,3})$")
    _COORD_RE = re.compile(
        r"^COORD,(-?[0-9]+(?:\.[0-9]+)?),(-?[0-9]+(?:\.[0-9]+)?)$"
    )
    _EVENT_RE = re.compile(r"^EVENT,(NONE|TRAP|LOW_BAT|TRAP\+LOW_BAT)$")

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout_s: float = 2.0,
        write_timeout_s: float = 2.0,
        startup_delay_s: float = 0.2,
    ) -> None:
        """
        Create a new UART client.

        port:
            Serial device path, for example /dev/serial0

        baudrate:
            Must match the ESP32 firmware UART setting

        timeout_s:
            Maximum time to wait for a response line

        write_timeout_s:
            Maximum time to allow for a UART write

        startup_delay_s:
            Small delay after opening the port so the interface can settle
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout_s = timeout_s
        self.write_timeout_s = write_timeout_s
        self.startup_delay_s = startup_delay_s
        self._ser: Optional[serial.Serial] = None

    def open(self) -> None:
        """
        Open the serial port if not already open.

        This also clears any stale bytes from the UART buffers.
        """
        if self._ser and self._ser.is_open:
            return

        self._ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout_s,
            write_timeout=self.write_timeout_s,
        )

        time.sleep(self.startup_delay_s)

        self._ser.reset_input_buffer()
        self._ser.reset_output_buffer()

    def close(self) -> None:
        """
        Close the serial port if open.
        """
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def __enter__(self) -> "EspUartClient":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _require_open(self) -> serial.Serial:
        """
        Ensure the serial port is open before use.
        """
        if self._ser is None or not self._ser.is_open:
            raise EspUartError("Serial port is not open.")
        return self._ser

    def _send_command(self, command: str) -> str:
        """
        Send one line-oriented command and return one line-oriented response.
        """
        ser = self._require_open()

        payload = (command.strip() + "\n").encode("ascii")
        ser.write(payload)
        ser.flush()

        line = ser.readline()
        if not line:
            raise EspTimeoutError(f"No response received for command: {command}")

        try:
            text = line.decode("ascii", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise EspProtocolError(
                f"Non-ASCII response received for command {command!r}"
            ) from exc

        if not text:
            raise EspProtocolError(f"Empty response received for command: {command}")

        if text.startswith("ERR,"):
            raise EspProtocolError(
                f"ESP32 returned error for command {command!r}: {text}"
            )

        return text

    def ping(self) -> bool:
        """
        Send a simple liveness test.
        """
        response = self._send_command("PING")
        if response != "PONG":
            raise EspProtocolError(f"Unexpected PING response: {response}")
        return True

    def get_status_banner(self) -> str:
        """
        Request the ESP32 firmware status banner.
        """
        response = self._send_command("STATUS?")
        if not response.startswith("OK,"):
            raise EspProtocolError(f"Unexpected STATUS? response: {response}")
        return response

    def get_time_iso(self) -> str:
        """
        Request current UTC time from the ESP32.
        """
        response = self._send_command("TIME?")
        match = self._TIME_RE.match(response)
        if not match:
            raise EspProtocolError(f"Unexpected TIME? response: {response}")
        return match.group(1)

    def get_battery(self) -> BatteryStatus:
        """
        Request battery voltage and percentage.
        """
        response = self._send_command("BAT?")
        match = self._BAT_RE.match(response)
        if not match:
            raise EspProtocolError(f"Unexpected BAT? response: {response}")

        voltage_v = float(match.group(1))
        percent = int(match.group(2))

        if not 0 <= percent <= 100:
            raise EspProtocolError(f"Battery percent out of range: {percent}")

        return BatteryStatus(voltage_v=voltage_v, percent=percent)

    def get_coordinates(self) -> CoordinateStatus:
        """
        Request GPS coordinates.
        """
        response = self._send_command("COORD?")
        if response == "COORD,INVALID":
            return CoordinateStatus(valid=False)

        match = self._COORD_RE.match(response)
        if not match:
            raise EspProtocolError(f"Unexpected COORD? response: {response}")

        latitude = float(match.group(1))
        longitude = float(match.group(2))
        return CoordinateStatus(valid=True, latitude=latitude, longitude=longitude)

    def get_event(self) -> EventStatus:
        """
        Request the compact event summary from the ESP32.
        """
        response = self._send_command("EVENT?")
        match = self._EVENT_RE.match(response)
        if not match:
            raise EspProtocolError(f"Unexpected EVENT? response: {response}")

        event_value = match.group(1)

        return EventStatus(
            raw=event_value,
            trap_active=("TRAP" in event_value),
            low_battery_active=("LOW_BAT" in event_value),
        )

    def acknowledge_event(self, event_type: str) -> bool:
        """
        Tell the ESP32 that a critical event was successfully delivered.

        Valid event_type values:
          TRAP
          LOW_BAT
          ALL
        """
        normalized = event_type.strip().upper()
        if normalized not in {"TRAP", "LOW_BAT", "ALL"}:
            raise ValueError(f"Unsupported event type: {event_type}")

        response = self._send_command(f"EVENT_ACKED,{normalized}")
        expected = f"OK,EVENT_ACKED,{normalized}"

        if response != expected:
            raise EspProtocolError(
                f"Unexpected EVENT_ACKED response: {response} "
                f"(expected {expected})"
            )

        return True

    def request_shutdown(self) -> bool:
        """
        Tell the ESP32 that the Pi is ready for shutdown power-cut handling.
        """
        response = self._send_command("SHUTDOWN")
        if response != "OK,SHUTDOWN_RECEIVED":
            raise EspProtocolError(f"Unexpected SHUTDOWN response: {response}")
        return True


if __name__ == "__main__":
    client = EspUartClient(port="/dev/serial0")

    try:
        with client:
            print("PING:", client.ping())
            print("STATUS:", client.get_status_banner())
            print("TIME:", client.get_time_iso())
            print("BAT:", client.get_battery())
            print("COORD:", client.get_coordinates())
            print("EVENT:", client.get_event())
    except Exception as exc:
        print("UART test failed:", exc)