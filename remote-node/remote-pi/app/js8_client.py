from __future__ import annotations

"""
BearWave JS8Call client module
==============================

WHAT THIS MODULE DOES
---------------------
This module provides a Python interface to the local JS8Call TCP API.

It is written specifically for the BearWave Raspberry Pi remote-node
application, where the Pi must be able to:

- connect to the locally running JS8Call API
- send outbound directed JS8 messages
- observe inbound JS8 messages
- recognise BearWave acknowledgements from the control node
- cope with the fact that JS8Call may deliver received traffic in fragments

WHY THIS VERSION EXISTS
-----------------------
Bench testing showed several real-world behaviors that the client must handle:

1. A BearWave acknowledgement may arrive as RX.ACTIVITY fragments rather than
   one neat RX.DIRECTED event.

2. The first fragment of an ACK can be missed while the tail fragment still
   arrives.

3. It is useful to log exactly when fragments arrive and when candidate ACK
   strings are formed, so the remote node can be correlated with the control
   node timing.

IMPORTANT LOGGING NOTE
----------------------
This module now emits explicit UTC-tagged diagnostic lines for:
- outbound handoff timing
- transmit-settle timing
- RX.ACTIVITY fragment arrival
- candidate ACK assembly
- ACK candidate checking

These timestamps are for diagnostics only. They do NOT alter the on-air
BearWave protocol payload.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import json
import queue
import socket
import threading
import time
import uuid
from datetime import datetime, timezone

from protocol import AckMessage, ack_matches, parse_ack_message


class Js8ClientError(Exception):
    """Base exception for JS8Call client errors."""


class Js8ConnectionError(Js8ClientError):
    """Raised when the JS8Call API socket is unavailable or drops."""


class Js8TimeoutError(Js8ClientError):
    """Raised when something did not arrive within the allowed wait period."""


class Js8ProtocolError(Js8ClientError):
    """Raised when an incoming JS8Call API message is malformed or unusable."""


@dataclass(frozen=True)
class Js8ApiMessage:
    """
    Structured representation of one JS8Call API message.
    """
    raw: Dict[str, Any]
    type: str
    value: Optional[str]
    params: Dict[str, Any]
    timestamp_utc: Optional[str]
    from_callsign: Optional[str]
    to_callsign: Optional[str]
    text: Optional[str]


@dataclass(frozen=True)
class DirectedMessage:
    """
    Structured representation of an inbound candidate message BearWave should
    consider for ACK handling.
    """
    from_callsign: Optional[str]
    to_callsign: Optional[str]
    text: str
    timestamp_utc: Optional[str]
    raw_message: Js8ApiMessage


def utc_now_iso() -> str:
    """
    Return current UTC time in ISO-like format with millisecond precision.
    """
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_upper(value: Optional[str]) -> Optional[str]:
    """
    Upper-case and strip a string if present.
    """
    if value is None:
        return None
    return value.strip().upper()


def _extract_first_string(data: Dict[str, Any], candidate_keys: List[str]) -> Optional[str]:
    """
    Return the first present string-like value among candidate keys.
    """
    for key in candidate_keys:
        if key in data and data[key] is not None:
            value = data[key]
            if isinstance(value, str):
                return value
            return str(value)
    return None


def _extract_message_fields(message: Dict[str, Any]) -> Js8ApiMessage:
    """
    Convert a raw JSON dictionary into a structured Js8ApiMessage.
    """
    msg_type = _extract_first_string(message, ["type", "TYPE"])
    if not msg_type:
        raise Js8ProtocolError(f"Incoming API message has no type field: {message!r}")

    params = message.get("params") or message.get("PARAMS") or {}
    if not isinstance(params, dict):
        params = {}

    value = _extract_first_string(message, ["value", "VALUE"])

    timestamp_utc = (
        _extract_first_string(params, ["UTC", "utc", "time", "TIME", "timestamp", "TIMESTAMP"])
        or _extract_first_string(message, ["UTC", "utc", "time", "TIME", "timestamp", "TIMESTAMP"])
    )

    from_callsign = _safe_upper(
        _extract_first_string(params, ["FROM", "from", "origin", "ORIGIN", "CALL", "call"])
        or _extract_first_string(message, ["FROM", "from", "origin", "ORIGIN"])
    )

    to_callsign = _safe_upper(
        _extract_first_string(params, ["TO", "to", "destination", "DESTINATION"])
        or _extract_first_string(message, ["TO", "to", "destination", "DESTINATION"])
    )

    text = (
        _extract_first_string(params, ["TEXT", "text", "VALUE", "value"])
        or _extract_first_string(message, ["TEXT", "text"])
        or value
    )

    return Js8ApiMessage(
        raw=message,
        type=msg_type,
        value=value,
        params=params,
        timestamp_utc=timestamp_utc,
        from_callsign=from_callsign,
        to_callsign=to_callsign,
        text=text,
    )


class Js8CallClient:
    """
    Python client for the local JS8Call TCP API.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 2442,
        socket_timeout_s: float = 1.0,
        tx_settle_time_s: float = 40.0,
        activity_assembly_window_s: float = 20.0,
    ) -> None:
        self.host = host
        self.port = port
        self.socket_timeout_s = socket_timeout_s
        self.tx_settle_time_s = tx_settle_time_s
        self.activity_assembly_window_s = activity_assembly_window_s

        self._sock: Optional[socket.socket] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._connected = False

        self._message_history: List[Js8ApiMessage] = []
        self._directed_queue: "queue.Queue[DirectedMessage]" = queue.Queue()
        self._lock = threading.Lock()

        self._last_send_time_monotonic: Optional[float] = None
        self._recv_buffer = b""

        # RX.ACTIVITY assembly state
        self._activity_text_buffer = ""
        self._activity_last_update_monotonic: Optional[float] = None
        self._activity_last_emitted_text = ""

    # ------------------------------------------------------------------
    # Structured UTC log helper
    # ------------------------------------------------------------------

    def _trace(self, event_label: str, **fields: object) -> None:
        """
        Emit a structured UTC trace line.

        This is intentionally print-based so that it appears alongside the raw
        JS8 diagnostic output during bench testing.
        """
        parts = [f"{key}={value}" for key, value in fields.items()]
        print(f"{event_label} utc={utc_now_iso()} " + " ".join(parts).strip())

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "Js8CallClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Connect to the JS8Call TCP API and start the background reader.
        """
        with self._lock:
            if self._connected:
                return

            try:
                sock = socket.create_connection(
                    (self.host, self.port),
                    timeout=self.socket_timeout_s,
                )
                sock.settimeout(self.socket_timeout_s)
            except OSError as exc:
                raise Js8ConnectionError(
                    f"Could not connect to JS8Call at {self.host}:{self.port}"
                ) from exc

            self._sock = sock
            self._recv_buffer = b""
            self._stop_event.clear()
            self._connected = True

            self._activity_text_buffer = ""
            self._activity_last_update_monotonic = None
            self._activity_last_emitted_text = ""

            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                name="Js8CallReader",
                daemon=True,
            )
            self._reader_thread.start()

    def close(self) -> None:
        """
        Close the socket and stop the background reader.
        """
        with self._lock:
            if not self._connected and self._sock is None:
                return

            self._stop_event.set()

            try:
                if self._sock is not None:
                    self._sock.close()
            except Exception:
                pass

            self._sock = None
            self._connected = False

        if self._reader_thread is not None and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)

        self._reader_thread = None

    def is_connected(self) -> bool:
        """
        Return True if the client believes the socket is connected.
        """
        return self._connected

    def _require_connected(self) -> socket.socket:
        """
        Ensure a live socket exists before sending.
        """
        if not self._connected or self._sock is None:
            raise Js8ConnectionError("JS8Call client is not connected.")
        return self._sock

    # ------------------------------------------------------------------
    # Outbound sending
    # ------------------------------------------------------------------

    def _build_request(
        self,
        request_type: str,
        value: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build a generic JS8Call API request.
        """
        request: Dict[str, Any] = {
            "type": request_type,
            "_ID": str(uuid.uuid4()),
        }
        if value is not None:
            request["value"] = value
        if params is not None:
            request["params"] = params
        return request

    def _send_json(self, payload: Dict[str, Any]) -> None:
        """
        Send one JSON object to JS8Call over TCP.
        """
        sock = self._require_connected()
        try:
            encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
            with self._lock:
                sock.sendall(encoded)
        except OSError as exc:
            self._connected = False
            raise Js8ConnectionError("Failed while sending JSON to JS8Call.") from exc

    def send_text_message(self, target_callsign: str, text: str) -> None:
        """
        Send one directed text message via JS8Call.

        IMPORTANT
        ---------
        This only hands the message to JS8Call. It does not mean RF
        transmission has completed.
        """
        target = target_callsign.strip().upper()
        payload_text = text.strip()

        if not target:
            raise ValueError("Target callsign must not be empty.")
        if not payload_text:
            raise ValueError("Message text must not be empty.")

        directed_text = f"{target} {payload_text}"

        request = self._build_request(
            request_type="TX.SEND_MESSAGE",
            value=directed_text,
        )

        self._trace(
            "BW_TX_HANDOFF",
            target=target,
            payload=payload_text,
            js8_text=directed_text,
        )

        self._send_json(request)
        self._last_send_time_monotonic = time.monotonic()

    def send_raw_request(
        self,
        request_type: str,
        value: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send a generic raw JS8Call API request.
        """
        request = self._build_request(
            request_type=request_type,
            value=value,
            params=params,
        )
        self._send_json(request)

    # ------------------------------------------------------------------
    # RX.ACTIVITY assembly helpers
    # ------------------------------------------------------------------

    def _clear_activity_buffer_if_stale(self) -> None:
        """
        Clear the fragment assembly buffer if it has been idle too long.
        """
        if self._activity_last_update_monotonic is None:
            return

        age = time.monotonic() - self._activity_last_update_monotonic
        if age > self.activity_assembly_window_s:
            self._activity_text_buffer = ""
            self._activity_last_update_monotonic = None
            self._activity_last_emitted_text = ""

    def _extract_candidate_payload_from_activity_buffer(self) -> Optional[str]:
        """
        Try to extract a BearWave-related payload candidate from the assembled
        RX.ACTIVITY buffer.

        This method looks for:
        - legacy ACK beginning with ACK|
        - compact ACK beginning with A|
        - normal BearWave payload beginning with BW1|
        """
        text = self._activity_text_buffer.strip().upper()

        if "ACK|" in text:
            return text[text.index("ACK|"):]

        if "A|" in text:
            return text[text.index("A|"):]

        if "BW1|" in text:
            return text[text.index("BW1|"):]

        return None

    def _handle_rx_activity(self, message: Js8ApiMessage) -> None:
        """
        Handle one RX.ACTIVITY fragment.

        This is the practical fragment assembly logic used to recognise BearWave
        payloads and acknowledgements in bench testing.
        """
        fragment = (message.value or message.text or "").strip()
        if not fragment:
            return

        self._trace(
            "BW_ACK_FRAGMENT_RX",
            js8_type=message.type,
            fragment=repr(fragment),
            from_call=message.from_callsign,
            to_call=message.to_callsign,
        )

        self._clear_activity_buffer_if_stale()

        self._activity_text_buffer += fragment
        self._activity_last_update_monotonic = time.monotonic()

        candidate = self._extract_candidate_payload_from_activity_buffer()
        if not candidate:
            return

        if candidate == self._activity_last_emitted_text:
            return

        self._activity_last_emitted_text = candidate

        self._trace(
            "BW_ACK_CANDIDATE",
            candidate=repr(candidate),
            from_call=message.from_callsign,
            to_call=message.to_callsign,
        )

        print(f"[JS8 RX.ACTIVITY ASSEMBLED] TEXT={candidate!r}")

        assembled = DirectedMessage(
            from_callsign=message.from_callsign,
            to_callsign=message.to_callsign,
            text=candidate,
            timestamp_utc=message.timestamp_utc,
            raw_message=message,
        )
        self._directed_queue.put(assembled)

    # ------------------------------------------------------------------
    # Background reader
    # ------------------------------------------------------------------

    def _reader_loop(self) -> None:
        """
        Background reader loop for newline-delimited JSON JS8 API messages.
        """
        while not self._stop_event.is_set():
            sock = self._sock
            if sock is None:
                break

            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                self._clear_activity_buffer_if_stale()
                continue
            except OSError:
                self._connected = False
                break
            except Exception:
                self._connected = False
                break

            if not chunk:
                self._connected = False
                break

            self._recv_buffer += chunk

            while b"\n" in self._recv_buffer:
                line, self._recv_buffer = self._recv_buffer.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue

                try:
                    raw_message = json.loads(line.decode("utf-8", errors="strict"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                if not isinstance(raw_message, dict):
                    continue

                print(f"RAW JS8 MESSAGE: {json.dumps(raw_message, separators=(',', ':'))}")

                try:
                    message = _extract_message_fields(raw_message)
                except Js8ProtocolError:
                    continue

                self._message_history.append(message)

                msg_type = message.type.upper()

                if msg_type == "RX.DIRECTED" and message.text:
                    directed = DirectedMessage(
                        from_callsign=message.from_callsign,
                        to_callsign=message.to_callsign,
                        text=message.text.strip(),
                        timestamp_utc=message.timestamp_utc,
                        raw_message=message,
                    )

                    print(
                        "[JS8 RX.DIRECTED]",
                        f"FROM={directed.from_callsign}",
                        f"TO={directed.to_callsign}",
                        f"TEXT={directed.text!r}",
                    )

                    self._trace(
                        "BW_ACK_CANDIDATE",
                        candidate=repr(directed.text),
                        from_call=directed.from_callsign,
                        to_call=directed.to_callsign,
                        source="RX.DIRECTED",
                    )

                    self._directed_queue.put(directed)

                elif msg_type == "RX.ACTIVITY":
                    self._handle_rx_activity(message)

    # ------------------------------------------------------------------
    # Inspection helpers
    # ------------------------------------------------------------------

    def get_message_history(self) -> List[Js8ApiMessage]:
        """
        Return a copy of all JS8 API messages seen so far.
        """
        return list(self._message_history)

    def drain_directed_messages(self) -> List[DirectedMessage]:
        """
        Remove and return all queued inbound candidate messages.
        """
        items: List[DirectedMessage] = []
        while True:
            try:
                items.append(self._directed_queue.get_nowait())
            except queue.Empty:
                break
        return items

    # ------------------------------------------------------------------
    # TX settle helper
    # ------------------------------------------------------------------

    def wait_for_tx_to_finish(self, timeout_s: Optional[float] = None) -> bool:
        """
        Conservatively wait long enough for JS8Call to finish handling the last
        outbound message.

        This is intentionally simple and conservative.
        """
        if self._last_send_time_monotonic is None:
            return True

        settle_time = self.tx_settle_time_s if timeout_s is None else timeout_s
        deadline = self._last_send_time_monotonic + settle_time

        self._trace("BW_TX_SETTLE_START", settle_s=settle_time)

        while time.monotonic() < deadline:
            if not self.is_connected():
                return False
            time.sleep(0.25)

        self._trace("BW_TX_SETTLE_DONE")
        return self.is_connected()

    # ------------------------------------------------------------------
    # ACK wait helpers
    # ------------------------------------------------------------------

    def wait_for_directed_message(
        self,
        timeout_s: float,
        expected_from_callsign: Optional[str] = None,
    ) -> DirectedMessage:
        """
        Wait for the next inbound candidate message for up to timeout_s.
        """
        deadline = time.monotonic() + timeout_s
        expected_from = _safe_upper(expected_from_callsign)

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Js8TimeoutError("Timed out waiting for directed message.")

            try:
                msg = self._directed_queue.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue

            if expected_from is not None:
                if msg.from_callsign is not None and _safe_upper(msg.from_callsign) != expected_from:
                    continue

            return msg

    def wait_for_ack(
        self,
        expected_node_id: str,
        expected_message_id: str,
        timeout_s: float,
        expected_from_callsign: Optional[str] = None,
    ) -> AckMessage:
        """
        Wait for a matching BearWave acknowledgement over the FULL timeout
        window.

        IMPORTANT
        ---------
        This function keeps polling until the full ACK window expires. It does
        not stop after a single short queue timeout.
        """
        deadline = time.monotonic() + timeout_s
        expected_from = _safe_upper(expected_from_callsign)

        self._trace(
            "BW_ACK_WAIT_START",
            expected_node=expected_node_id,
            expected_msg_id=expected_message_id,
            timeout_s=timeout_s,
        )

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Js8TimeoutError(
                    f"Timed out waiting for ACK for node {expected_node_id} "
                    f"message {expected_message_id}."
                )

            try:
                directed = self._directed_queue.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue

            if expected_from is not None:
                if directed.from_callsign is not None and _safe_upper(directed.from_callsign) != expected_from:
                    self._trace(
                        "BW_ACK_CHECK",
                        expected_node=expected_node_id,
                        expected_msg_id=expected_message_id,
                        candidate=repr(directed.text),
                        observed_from=directed.from_callsign,
                        accepted=False,
                        reason="unexpected_sender",
                    )
                    continue

            if not directed.text:
                continue

            print(
                "[JS8 ACK CHECK]",
                f"FROM={directed.from_callsign}",
                f"TO={directed.to_callsign}",
                f"TEXT={directed.text!r}",
            )

            matched = ack_matches(
                ack_text=directed.text,
                expected_node_id=expected_node_id,
                expected_message_id=expected_message_id,
            )

            self._trace(
                "BW_ACK_CHECK",
                expected_node=expected_node_id,
                expected_msg_id=expected_message_id,
                candidate=repr(directed.text),
                observed_from=directed.from_callsign,
                accepted=matched,
            )

            if not matched:
                continue

            return parse_ack_message(directed.text)


if __name__ == "__main__":
    TEST_TARGET_CALLSIGN = "G7PRW"
    TEST_NODE_ID = "ND01"
    TEST_MESSAGE_ID = "7K"
    TEST_PAYLOAD = "BW1|ND01|HB|7K|0|B72"

    client = Js8CallClient()

    try:
        with client:
            print("Connected to JS8Call.")
            stale = client.drain_directed_messages()
            print(f"Drained {len(stale)} stale directed message(s).")

            print(f"Sending test message to {TEST_TARGET_CALLSIGN}: {TEST_PAYLOAD}")
            client.send_text_message(
                target_callsign=TEST_TARGET_CALLSIGN,
                text=TEST_PAYLOAD,
            )

            print("Waiting for transmit settle...")
            print("TX settle result:", client.wait_for_tx_to_finish())

            print("Waiting for ACK...")
            ack = client.wait_for_ack(
                expected_node_id=TEST_NODE_ID,
                expected_message_id=TEST_MESSAGE_ID,
                expected_from_callsign=TEST_TARGET_CALLSIGN,
                timeout_s=45.0,
            )

            print("Received matching ACK:")
            print(ack)

    except Exception as exc:
        print("JS8Call test failed:", exc)