from __future__ import annotations

"""
BearWave remote node controller
===============================

WHAT THIS MODULE DOES
---------------------
This module is the main orchestration layer for the BearWave Raspberry Pi
remote node application.

It joins together the lower-level helper modules:

- esp_uart_client.py
- protocol.py
- js8_client.py
- pending_store.py

and implements the remote-node operating sequence.

REMOTE NODE DESIGN CONTEXT
--------------------------
The BearWave remote node is power-constrained and does not run continuously.
Instead, it is powered periodically or on demand by the ESP32 supervisory
controller.

The Pi's job during each wake cycle is to:
- obtain current state from the ESP32
- determine whether a heartbeat or critical alarm must be sent
- transmit the correct BearWave message over JS8Call
- wait for acknowledgement from the control node
- retry if necessary
- preserve failed critical messages across boots
- request shutdown when finished

IMPORTANT LOGGING NOTE
----------------------
This version includes explicit UTC timing instrumentation so that the remote
node logs can be compared directly with the control-node logs during bench
testing.

The goal is to understand timing relationships between:
- outbound message handoff to JS8Call
- transmit settle completion
- acknowledgement wait windows
- inbound ACK fragment arrival
- ACK match success
- retry start

These timestamps are for diagnostics only. They are NOT added to the on-air
BearWave payload.
"""

from dataclasses import dataclass, field
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from esp_uart_client import (
    BatteryStatus,
    EspProtocolError,
    EspTimeoutError,
    EspUartClient,
    EventStatus,
)
from js8_client import Js8CallClient, Js8TimeoutError, Js8ClientError
from pending_store import PendingMessage, PendingMessageStore, PendingStoreError
from protocol import (
    BearWaveMessage,
    EventFlag,
    MessageType,
    build_data_token,
    build_heartbeat_message,
    build_low_battery_message,
    build_message,
    build_trap_alarm_message,
)
from sstv_image import SstvImageConfig, SstvImageTransmitter


def configure_default_logging(level: int = logging.INFO) -> None:
    """
    Configure a simple root logger for console output.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def utc_now_iso() -> str:
    """
    Return current UTC time in ISO-like format with a Z suffix.

    Example:
        2026-05-04T20:12:11.074Z
    """
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class RemoteNodeConfig:
    """
    Configuration for the BearWave remote-node controller.
    """
    serial_port: str = "/dev/serial0"
    serial_baudrate: int = 115200
    js8_host: str = "127.0.0.1"
    js8_port: int = 2442
    control_callsign: str = "G7PRW"
    node_id: str = "ND01"
    pending_store_path: str = "/home/mark/bearwave/state/pending_message.json"
    ack_wait_per_attempt_s: float = 90.0
    max_send_attempts: int = 3
    startup_js8_drain: bool = True
    allow_combined_alarm_message: bool = True
    sstv: SstvImageConfig = field(default_factory=SstvImageConfig)


@dataclass(frozen=True)
class ControllerRunResult:
    """
    Summary of one remote-node run cycle.
    """
    success: bool
    sent_message: Optional[str]
    acknowledged: bool
    used_pending_message: bool
    persisted_new_pending_message: bool
    shutdown_requested: bool
    notes: str
    sstv_attempted: bool = False
    sstv_success: bool = False
    sstv_notes: Optional[str] = None


class RemoteNodeController:
    """
    Main BearWave remote-node controller.
    """

    def __init__(self, config: RemoteNodeConfig) -> None:
        self.config = config
        self.log = logging.getLogger(self.__class__.__name__)
        self.store = PendingMessageStore(config.pending_store_path)
        self.sstv = SstvImageTransmitter(
            config.sstv,
            logging.getLogger("SstvImageTransmitter"),
        )

    # ---------------------------------------------------------------------
    # Structured UTC logging helper
    # ---------------------------------------------------------------------

    def _log_utc_event(self, event_label: str, **fields: object) -> None:
        """
        Emit a structured UTC log line.

        WHY THIS EXISTS
        ---------------
        The ordinary Python logging timestamp is useful, but when comparing
        remote-node logs to control-node logs it is helpful to include a clear
        UTC timestamp inside the log message itself, along with compact event
        labels and key fields.

        Example output:
            BW_MSG_BUILT utc=2026-05-04T20:12:11.074Z node=ND01 msg_id=7K ...
        """
        parts = [f"{key}={value}" for key, value in fields.items()]
        self.log.info("%s utc=%s %s", event_label, utc_now_iso(), " ".join(parts).strip())

    # ---------------------------------------------------------------------
    # Pending-store helpers
    # ---------------------------------------------------------------------

    def _persist_critical_message(
        self,
        message: BearWaveMessage,
        created_utc: str,
        attempt_count: int,
        last_attempt_utc: Optional[str],
        reason: str,
        extra: Optional[dict] = None,
    ) -> None:
        """
        Persist a failed critical message to the pending-message store.
        """
        record = PendingMessage(
            node_id=message.node_id,
            message_id=message.message_id,
            message_type=message.message_type.value,
            flags=message.flags,
            data=message.data,
            text=message.text,
            created_utc=created_utc,
            attempt_count=attempt_count,
            last_attempt_utc=last_attempt_utc,
            reason=reason,
            extra=extra,
        )
        self.store.save(record)

    def _rebuild_message_from_pending(self, pending: PendingMessage) -> BearWaveMessage:
        """
        Reconstruct a BearWaveMessage from a stored pending record.
        """
        message_type = MessageType(pending.message_type)
        return build_message(
            node_id=pending.node_id,
            message_type=message_type,
            message_id=pending.message_id,
            flags=pending.flags,
            data=pending.data,
        )

    # ---------------------------------------------------------------------
    # Message-building helpers
    # ---------------------------------------------------------------------

    def _build_combined_critical_message(
        self,
        battery: BatteryStatus,
        event: EventStatus,
        message_id: str,
    ) -> BearWaveMessage:
        """
        Build a combined critical message when both TRAP and LOW_BAT are active.
        """
        battery_token = build_data_token("B", battery.percent)
        return build_message(
            node_id=self.config.node_id,
            message_type=MessageType.TRAP_ALARM,
            message_id=message_id,
            flags=EventFlag.TRAP_AND_LOW_BATTERY.value,
            data=battery_token,
        )

    def _build_fresh_message_for_current_state(
        self,
        battery: BatteryStatus,
        event: EventStatus,
        message_id: str,
    ) -> tuple[BearWaveMessage, bool]:
        """
        Build a fresh outbound BearWave message based on current ESP state.

        Returns:
            (message, is_critical)
        """
        if event.is_none:
            return (
                build_heartbeat_message(
                    node_id=self.config.node_id,
                    message_id=message_id,
                    battery_percent=battery.percent,
                ),
                False,
            )

        if event.trap_active and event.low_battery_active:
            if self.config.allow_combined_alarm_message:
                return (
                    self._build_combined_critical_message(
                        battery=battery,
                        event=event,
                        message_id=message_id,
                    ),
                    True,
                )

            return (
                build_trap_alarm_message(
                    node_id=self.config.node_id,
                    message_id=message_id,
                    battery_percent=battery.percent,
                ),
                True,
            )

        if event.trap_active:
            return (
                build_trap_alarm_message(
                    node_id=self.config.node_id,
                    message_id=message_id,
                    battery_percent=battery.percent,
                ),
                True,
            )

        if event.low_battery_active:
            return (
                build_low_battery_message(
                    node_id=self.config.node_id,
                    message_id=message_id,
                    battery_percent=battery.percent,
                ),
                True,
            )

        return (
            build_heartbeat_message(
                node_id=self.config.node_id,
                message_id=message_id,
                battery_percent=battery.percent,
            ),
            False,
        )

    def _mark_event_delivered_to_esp(
        self,
        esp: EspUartClient,
        message: BearWaveMessage,
    ) -> None:
        """
        Tell the ESP32 that a critical event has been successfully delivered.
        """
        if message.flags == EventFlag.TRAP.value:
            esp.acknowledge_event("TRAP")
        elif message.flags == EventFlag.LOW_BATTERY.value:
            esp.acknowledge_event("LOW_BAT")
        elif message.flags == EventFlag.TRAP_AND_LOW_BATTERY.value:
            esp.acknowledge_event("ALL")

    def _message_should_send_sstv(self, message: BearWaveMessage) -> bool:
        """
        Return True only for acknowledged trap-alarm messages.

        SSTV is intended as visual evidence for a trap event after the compact
        JS8 alarm has already been delivered and acknowledged. It must not run
        for routine heartbeats or low-battery-only messages, even though those
        messages also use the same acknowledgement path.
        """
        return (
            message.message_type == MessageType.TRAP_ALARM
            and message.flags in {
                EventFlag.TRAP.value,
                EventFlag.TRAP_AND_LOW_BATTERY.value,
            }
        )

    def _generate_message_id(self) -> str:
        """
        Generate a compact 2-character base36-style message ID.
        """
        value = int(time.time()) % 1296
        alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        high = value // 36
        low = value % 36
        return f"{alphabet[high]}{alphabet[low]}"

    def _run_post_ack_sstv_if_needed(
        self,
        *,
        message: BearWaveMessage,
    ):
        """
        Run the optional SSTV evidence-image stage after trap ACK success.

        The image stage is intentionally secondary. Failure here must not turn
        an already acknowledged trap alarm into an undelivered alarm.
        """
        if not self._message_should_send_sstv(message):
            self._log_utc_event(
                "BW_SSTV_IMAGE_STAGE_SKIPPED",
                node=message.node_id,
                msg_id=message.message_id,
                msg_type=message.message_type.value,
                flags=message.flags,
                reason="not_trap_alarm",
            )
            return None

        result = self.sstv.transmit_alarm_image(
            node_id=message.node_id,
            message_id=message.message_id,
        )

        self._log_utc_event(
            "BW_SSTV_IMAGE_STAGE",
            node=message.node_id,
            msg_id=message.message_id,
            attempted=result.attempted,
            success=result.success,
            skipped_reason=result.skipped_reason,
            image_path=result.image_path,
            wav_path=result.wav_path,
            mode=result.mode,
            repeat_count=result.repeat_count,
        )

        return result

    # ---------------------------------------------------------------------
    # Send / retry logic
    # ---------------------------------------------------------------------

    def _send_with_retries(
        self,
        js8: Js8CallClient,
        message: BearWaveMessage,
        *,
        is_critical: bool,
    ) -> tuple[bool, int, Optional[str]]:
        """
        Send a BearWave message with retries and ACK waiting.

        PROCESS
        -------
        For each attempt:
        - ensure JS8Call is connected
        - send one outbound BearWave message
        - wait for transmit settle
        - wait for a matching ACK over the full ACK window
        - retry only if no matching ACK arrives
        """
        attempts_used = 0
        last_attempt_utc: Optional[str] = None

        for attempt_number in range(1, self.config.max_send_attempts + 1):
            attempts_used = attempt_number
            last_attempt_utc = utc_now_iso()

            self._log_utc_event(
                "BW_RETRY_START",
                node=message.node_id,
                msg_id=message.message_id,
                msg_type=message.message_type.value,
                attempt=attempt_number,
                max_attempts=self.config.max_send_attempts,
            )

            if not js8.is_connected():
                self.log.warning(
                    "JS8Call client was disconnected; reconnecting before retry."
                )
                js8.connect()

                if not js8.is_connected():
                    raise Js8ClientError("JS8Call reconnect attempt failed.")

                if self.config.startup_js8_drain:
                    stale = js8.drain_directed_messages()
                    self.log.info(
                        "Drained %d stale directed JS8 message(s) after reconnect.",
                        len(stale),
                    )

            self.log.info(
                "Sending message attempt %d/%d: %s",
                attempt_number,
                self.config.max_send_attempts,
                message.text,
            )

            self._log_utc_event(
                "BW_TX_HANDOFF",
                node=message.node_id,
                msg_id=message.message_id,
                msg_type=message.message_type.value,
                attempt=attempt_number,
                payload=message.text,
            )

            js8.send_text_message(
                target_callsign=self.config.control_callsign,
                text=message.text,
            )

            self._log_utc_event(
                "BW_TX_SETTLE_START",
                node=message.node_id,
                msg_id=message.message_id,
                attempt=attempt_number,
                settle_s=js8.tx_settle_time_s,
            )

            self.log.info("Waiting for JS8Call transmit settle.")
            tx_ok = js8.wait_for_tx_to_finish()

            if not tx_ok:
                self.log.warning(
                    "JS8Call disconnected during transmit settle on attempt %d.",
                    attempt_number,
                )
                continue

            self._log_utc_event(
                "BW_TX_SETTLE_DONE",
                node=message.node_id,
                msg_id=message.message_id,
                attempt=attempt_number,
            )

            self.log.info(
                "Transmit settle complete. Waiting for ACK for message %s.",
                message.message_id,
            )

            self._log_utc_event(
                "BW_ACK_WAIT_START",
                node=message.node_id,
                expected_node=message.node_id,
                expected_msg_id=message.message_id,
                attempt=attempt_number,
                ack_wait_s=self.config.ack_wait_per_attempt_s,
            )

            try:
                ack = js8.wait_for_ack(
                    expected_node_id=message.node_id,
                    expected_message_id=message.message_id,
                    expected_from_callsign=self.config.control_callsign,
                    timeout_s=self.config.ack_wait_per_attempt_s,
                )

                self._log_utc_event(
                    "BW_ACK_MATCH",
                    node=message.node_id,
                    expected_node=message.node_id,
                    expected_msg_id=message.message_id,
                    observed_node=ack.node_id,
                    observed_msg_id=ack.message_id,
                    ack_text=ack.text,
                    attempt=attempt_number,
                )

                self.log.info(
                    "Received valid ACK for message %s from node %s.",
                    ack.message_id,
                    ack.node_id,
                )
                return True, attempts_used, last_attempt_utc

            except Js8TimeoutError:
                self._log_utc_event(
                    "BW_ACK_TIMEOUT",
                    node=message.node_id,
                    expected_node=message.node_id,
                    expected_msg_id=message.message_id,
                    attempt=attempt_number,
                )

                self.log.warning(
                    "No valid ACK received for message %s on attempt %d.",
                    message.message_id,
                    attempt_number,
                )

        return False, attempts_used, last_attempt_utc

    # ---------------------------------------------------------------------
    # Main run method
    # ---------------------------------------------------------------------

    def run_once(self) -> ControllerRunResult:
        """
        Perform one complete BearWave remote-node wake cycle.
        """
        sent_message: Optional[str] = None
        acknowledged = False
        used_pending_message = False
        persisted_new_pending_message = False
        shutdown_requested = False

        self.log.info("Starting BearWave remote-node controller run.")

        try:
            with EspUartClient(
                port=self.config.serial_port,
                baudrate=self.config.serial_baudrate,
            ) as esp, Js8CallClient(
                host=self.config.js8_host,
                port=self.config.js8_port,
            ) as js8:

                self.log.info("Checking ESP32 UART link.")
                esp.ping()
                status_banner = esp.get_status_banner()
                esp_time = esp.get_time_iso()

                self.log.info("ESP32 status: %s", status_banner)
                self.log.info("ESP32 reported time: %s", esp_time)

                if self.config.startup_js8_drain:
                    stale = js8.drain_directed_messages()
                    self.log.info("Drained %d stale directed JS8 message(s).", len(stale))

                pending = self.store.load_if_exists()

                if pending is not None:
                    self.log.info(
                        "Pending critical message found from prior run: %s",
                        pending.text,
                    )
                    used_pending_message = True

                    message = self._rebuild_message_from_pending(pending)
                    sent_message = message.text
                    is_critical = True

                    self._log_utc_event(
                        "BW_MSG_BUILT",
                        node=message.node_id,
                        msg_id=message.message_id,
                        msg_type=message.message_type.value,
                        source="pending_store",
                        payload=message.text,
                    )

                    acknowledged, attempts_used, last_attempt_utc = self._send_with_retries(
                        js8=js8,
                        message=message,
                        is_critical=is_critical,
                    )

                    if acknowledged:
                        self.log.info(
                            "Pending critical message delivered successfully; clearing store."
                        )
                        self.store.clear()
                        sstv_result = self._run_post_ack_sstv_if_needed(
                            message=message,
                        )
                        self._mark_event_delivered_to_esp(esp, message)

                        self._log_utc_event(
                            "BW_SHUTDOWN_REQUEST",
                            node=message.node_id,
                            msg_id=message.message_id,
                            reason="pending_message_acknowledged",
                        )

                        self.log.info("Requesting shutdown from ESP32.")
                        esp.request_shutdown()
                        shutdown_requested = True

                        return ControllerRunResult(
                            success=True,
                            sent_message=sent_message,
                            acknowledged=True,
                            used_pending_message=True,
                            persisted_new_pending_message=False,
                            shutdown_requested=shutdown_requested,
                            sstv_attempted=bool(sstv_result and sstv_result.attempted),
                            sstv_success=bool(sstv_result and sstv_result.success),
                            sstv_notes=sstv_result.notes if sstv_result else None,
                            notes="Pending critical message retransmitted and acknowledged.",
                        )

                    self.log.warning(
                        "Pending critical message was retried but still not acknowledged."
                    )

                    self.store.increment_attempt_count(
                        last_attempt_utc=last_attempt_utc,
                        reason="Retry on later boot also failed: no valid ACK received",
                    )

                    self._log_utc_event(
                        "BW_SHUTDOWN_REQUEST",
                        node=message.node_id,
                        msg_id=message.message_id,
                        reason="pending_message_retry_failed",
                    )

                    self.log.info("Requesting shutdown from ESP32.")
                    esp.request_shutdown()
                    shutdown_requested = True

                    return ControllerRunResult(
                        success=False,
                        sent_message=sent_message,
                        acknowledged=False,
                        used_pending_message=True,
                        persisted_new_pending_message=False,
                        shutdown_requested=shutdown_requested,
                        notes="Pending critical message retried but still not acknowledged.",
                    )

                self.log.info("No pending critical message found. Querying current ESP32 state.")
                battery = esp.get_battery()
                event = esp.get_event()

                self.log.info(
                    "ESP32 reported battery %.2f V / %d%% and event state %s.",
                    battery.voltage_v,
                    battery.percent,
                    event.raw,
                )

                message_id = self._generate_message_id()
                message, is_critical = self._build_fresh_message_for_current_state(
                    battery=battery,
                    event=event,
                    message_id=message_id,
                )
                sent_message = message.text

                self._log_utc_event(
                    "BW_MSG_BUILT",
                    node=message.node_id,
                    msg_id=message.message_id,
                    msg_type=message.message_type.value,
                    source="fresh_state",
                    payload=message.text,
                    battery_pct=battery.percent,
                    battery_v=f"{battery.voltage_v:.2f}",
                    event_state=event.raw,
                )

                self.log.info(
                    "Built fresh message type %s with ID %s: %s",
                    message.message_type.value,
                    message.message_id,
                    message.text,
                )

                acknowledged, attempts_used, last_attempt_utc = self._send_with_retries(
                    js8=js8,
                    message=message,
                    is_critical=is_critical,
                )

                if acknowledged:
                    self.log.info("Message acknowledged successfully.")

                    sstv_result = None
                    if is_critical:
                        self.log.info(
                            "Critical message succeeded; informing ESP32 of delivery."
                        )
                        sstv_result = self._run_post_ack_sstv_if_needed(
                            message=message,
                        )
                        self._mark_event_delivered_to_esp(esp, message)

                    self._log_utc_event(
                        "BW_SHUTDOWN_REQUEST",
                        node=message.node_id,
                        msg_id=message.message_id,
                        reason="fresh_message_acknowledged",
                    )

                    self.log.info("Requesting shutdown from ESP32.")
                    esp.request_shutdown()
                    shutdown_requested = True

                    return ControllerRunResult(
                        success=True,
                        sent_message=sent_message,
                        acknowledged=True,
                        used_pending_message=False,
                        persisted_new_pending_message=False,
                        shutdown_requested=shutdown_requested,
                        sstv_attempted=bool(sstv_result and sstv_result.attempted),
                        sstv_success=bool(sstv_result and sstv_result.success),
                        sstv_notes=sstv_result.notes if sstv_result else None,
                        notes="Fresh message transmitted and acknowledged successfully.",
                    )

                self.log.warning("Message was not acknowledged after all retries.")

                if is_critical:
                    self.log.warning(
                        "Critical message failed; persisting for later retry."
                    )
                    self._persist_critical_message(
                        message=message,
                        created_utc=utc_now_iso(),
                        attempt_count=attempts_used,
                        last_attempt_utc=last_attempt_utc,
                        reason="No valid ACK received after max attempts",
                        extra={
                            "battery_percent": battery.percent,
                            "battery_voltage_v": battery.voltage_v,
                            "event_raw": event.raw,
                        },
                    )
                    persisted_new_pending_message = True
                else:
                    self.log.info("Failed message was only a heartbeat; not persisting.")

                self._log_utc_event(
                    "BW_SHUTDOWN_REQUEST",
                    node=message.node_id,
                    msg_id=message.message_id,
                    reason="message_not_acknowledged",
                )

                self.log.info("Requesting shutdown from ESP32.")
                esp.request_shutdown()
                shutdown_requested = True

                return ControllerRunResult(
                    success=False,
                    sent_message=sent_message,
                    acknowledged=False,
                    used_pending_message=False,
                    persisted_new_pending_message=persisted_new_pending_message,
                    shutdown_requested=shutdown_requested,
                    notes=(
                        "Message not acknowledged. Critical message persisted."
                        if persisted_new_pending_message
                        else "Heartbeat not acknowledged; not persisted."
                    ),
                )

        except PendingStoreError as exc:
            self.log.exception("Pending-store error occurred.")
            return ControllerRunResult(
                success=False,
                sent_message=sent_message,
                acknowledged=acknowledged,
                used_pending_message=used_pending_message,
                persisted_new_pending_message=persisted_new_pending_message,
                shutdown_requested=shutdown_requested,
                notes=f"Pending-store error: {exc}",
            )

        except (EspTimeoutError, EspProtocolError) as exc:
            self.log.exception("ESP32 UART error occurred.")
            return ControllerRunResult(
                success=False,
                sent_message=sent_message,
                acknowledged=acknowledged,
                used_pending_message=used_pending_message,
                persisted_new_pending_message=persisted_new_pending_message,
                shutdown_requested=shutdown_requested,
                notes=f"ESP32 UART error: {exc}",
            )

        except Js8ClientError as exc:
            self.log.exception("JS8Call client error occurred.")
            return ControllerRunResult(
                success=False,
                sent_message=sent_message,
                acknowledged=acknowledged,
                used_pending_message=used_pending_message,
                persisted_new_pending_message=persisted_new_pending_message,
                shutdown_requested=shutdown_requested,
                notes=f"JS8Call client error: {exc}",
            )

        except Exception as exc:
            self.log.exception("Unexpected remote-node controller error.")
            return ControllerRunResult(
                success=False,
                sent_message=sent_message,
                acknowledged=acknowledged,
                used_pending_message=used_pending_message,
                persisted_new_pending_message=persisted_new_pending_message,
                shutdown_requested=shutdown_requested,
                notes=f"Unexpected controller error: {exc}",
            )


if __name__ == "__main__":
    configure_default_logging(logging.INFO)

    config = RemoteNodeConfig(
        serial_port="/dev/serial0",
        serial_baudrate=115200,
        js8_host="127.0.0.1",
        js8_port=2442,
        control_callsign="G7PRW",
        node_id="ND01",
        pending_store_path="/home/mark/bearwave/state/pending_message.json",
        ack_wait_per_attempt_s=90.0,
        max_send_attempts=3,
        startup_js8_drain=True,
        allow_combined_alarm_message=True,
    )

    controller = RemoteNodeController(config)
    result = controller.run_once()

    print("=== BearWave controller run result ===")
    print(result)
