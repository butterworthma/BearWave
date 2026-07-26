from __future__ import annotations

"""
BearWave pending message store
==============================

WHAT THIS MODULE DOES
---------------------
This module provides a simple persistent store for unsent critical BearWave
messages on the Raspberry Pi.

In the BearWave remote-node design, routine heartbeat messages are NOT stored
for later retry if they fail. However, critical messages MUST be retained if
they were sent but never acknowledged by the control node.

Examples of critical messages include:
- trap alarms
- low-battery alarms
- future critical fault/alarm types if added later

This module allows the Pi application to:
- save a critical message before shutdown if delivery failed
- load a previously saved critical message on the next boot
- clear the stored message only after a valid acknowledgement is received
- inspect whether a pending message exists
- update retry metadata for audit and control purposes

WHY A SIMPLE FILE STORE IS USED
-------------------------------
For BearWave, a file-based persistent store is a sensible first design because:

- the amount of data is very small
- only one outstanding critical message is expected at a time
- it is easy to inspect during development
- it is easy to document in the PhD work
- it keeps dependencies minimal
- it is easy to back up and understand

At this stage, a JSON file is sufficient.

WHAT THIS MODULE DOES NOT DO
----------------------------
This module does NOT:
- talk to the ESP32 over UART
- talk to JS8Call
- parse acknowledgements
- decide whether a message is critical
- decide when to retry
- shut the system down

Those are responsibilities of other modules.

EXPECTED HIGH-LEVEL USAGE
-------------------------
Typical usage pattern:

    store = PendingMessageStore("/home/pi/bearwave/pending_message.json")

    # On boot:
    pending = store.load()
    if pending is not None:
        # Attempt resend before normal heartbeat logic
        ...

    # If a critical send fails:
    store.save(
        PendingMessage(
            node_id="ND01",
            message_id="7L",
            message_type="TA",
            flags="T1",
            data="B68",
            text="BW1|ND01|TA|7L|T1|B68",
            created_utc="2026-04-17T08:15:22Z",
            attempt_count=3,
            last_attempt_utc="2026-04-17T08:16:45Z",
            reason="No valid ACK received",
        )
    )

    # If it is later successfully acknowledged:
    store.clear()

STORE FORMAT
------------
The JSON file stores one pending critical message record at a time.

This matches the current BearWave design assumption that only one critical
message needs to survive across boots.

If the system later evolves to support a queue of multiple pending messages,
this module can be extended, but for now the single-record design is simpler
and aligns with the current architecture.
"""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional
import json
import os
import shutil
import tempfile


# ============================================================================
# Custom exceptions
# ============================================================================
#
# These exceptions allow higher-level code to distinguish persistence problems
# from protocol, UART, or JS8 transport problems.
# ============================================================================


class PendingStoreError(Exception):
    """
    Base exception for all pending-message-store problems.
    """
    pass


class PendingStoreFormatError(PendingStoreError):
    """
    Raised when the JSON file exists but is malformed or structurally invalid.
    """
    pass


class PendingStoreIOError(PendingStoreError):
    """
    Raised when the store cannot be read or written due to filesystem or I/O
    problems.
    """
    pass


# ============================================================================
# Dataclass representing one pending critical message
# ============================================================================
#
# This record is intentionally explicit. The goal is not only to store the
# message text itself, but also enough metadata to:
# - understand why it is pending
# - support future debugging
# - support later analysis in the PhD work
# - track retry history across boots
# ============================================================================


@dataclass(frozen=True)
class PendingMessage:
    """
    Representation of one persisted BearWave critical message.

    FIELD PURPOSES
    --------------
    node_id:
        Short internal node identifier, for example "ND01".

    message_id:
        Compact BearWave message ID, for example "7L".

    message_type:
        BearWave message type code, for example:
        - TA
        - LB
        - FT

    flags:
        Compact BearWave flags field, for example:
        - T1
        - L1
        - T1L1

    data:
        Compact BearWave data field, for example:
        - B68
        - B18
        - X03,B52

    text:
        Full encoded BearWave message body, for example:
        BW1|ND01|TA|7L|T1|B68

    created_utc:
        UTC timestamp representing when this pending record was first created.

    attempt_count:
        Total send attempts made so far for this message.
        This should include attempts made before the message was persisted.

    last_attempt_utc:
        UTC timestamp of the most recent send attempt, if known.

    reason:
        Human-readable explanation for why the record was stored.
        Example:
            "No valid ACK received after 3 attempts"

    extra:
        Optional dictionary for future extensibility.
        This can hold additional fields without redesigning the dataclass,
        for example:
        - boot_reason
        - battery_percent
        - gps_status
        - source_event
    """
    node_id: str
    message_id: str
    message_type: str
    flags: str
    data: str
    text: str
    created_utc: str
    attempt_count: int
    last_attempt_utc: Optional[str] = None
    reason: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


# ============================================================================
# Validation helpers
# ============================================================================
#
# These helpers validate PendingMessage content before it is written to disk or
# reconstructed from disk.
# ============================================================================


def _ensure_non_empty_string(field_name: str, value: Optional[str]) -> str:
    """
    Ensure that a required string field is present and non-empty.

    This helper is used repeatedly because many fields in the pending-message
    record are essential for correct operation.
    """
    if value is None:
        raise PendingStoreFormatError(f"Required field {field_name!r} is missing.")

    normalized = str(value).strip()
    if not normalized:
        raise PendingStoreFormatError(f"Required field {field_name!r} is empty.")

    return normalized


def _ensure_non_negative_int(field_name: str, value: Any) -> int:
    """
    Ensure that a field can be interpreted as a non-negative integer.

    Used for attempt_count.
    """
    try:
        converted = int(value)
    except (TypeError, ValueError) as exc:
        raise PendingStoreFormatError(
            f"Field {field_name!r} must be an integer."
        ) from exc

    if converted < 0:
        raise PendingStoreFormatError(
            f"Field {field_name!r} must not be negative."
        )

    return converted


def _validate_pending_message(record: PendingMessage) -> PendingMessage:
    """
    Validate a PendingMessage dataclass instance.

    WHY THIS EXISTS
    ---------------
    Even if the application builds the record, it is still good practice to
    validate it before writing it to disk. This reduces the chance of silently
    persisting broken data that later causes harder-to-debug failures.
    """
    node_id = _ensure_non_empty_string("node_id", record.node_id)
    message_id = _ensure_non_empty_string("message_id", record.message_id)
    message_type = _ensure_non_empty_string("message_type", record.message_type)
    flags = _ensure_non_empty_string("flags", record.flags)
    data = _ensure_non_empty_string("data", record.data)
    text = _ensure_non_empty_string("text", record.text)
    created_utc = _ensure_non_empty_string("created_utc", record.created_utc)

    attempt_count = _ensure_non_negative_int("attempt_count", record.attempt_count)

    last_attempt_utc = None
    if record.last_attempt_utc is not None:
        last_attempt_utc = _ensure_non_empty_string(
            "last_attempt_utc", record.last_attempt_utc
        )

    reason = None
    if record.reason is not None:
        reason = _ensure_non_empty_string("reason", record.reason)

    extra = record.extra
    if extra is not None and not isinstance(extra, dict):
        raise PendingStoreFormatError("Field 'extra' must be a dictionary if present.")

    return PendingMessage(
        node_id=node_id,
        message_id=message_id,
        message_type=message_type,
        flags=flags,
        data=data,
        text=text,
        created_utc=created_utc,
        attempt_count=attempt_count,
        last_attempt_utc=last_attempt_utc,
        reason=reason,
        extra=extra,
    )


def _pending_message_from_dict(data: Dict[str, Any]) -> PendingMessage:
    """
    Reconstruct a PendingMessage from a dictionary loaded from JSON.

    This performs structural validation and returns a clean dataclass instance.
    """
    if not isinstance(data, dict):
        raise PendingStoreFormatError("Pending message JSON must be an object.")

    record = PendingMessage(
        node_id=data.get("node_id"),
        message_id=data.get("message_id"),
        message_type=data.get("message_type"),
        flags=data.get("flags"),
        data=data.get("data"),
        text=data.get("text"),
        created_utc=data.get("created_utc"),
        attempt_count=data.get("attempt_count", 0),
        last_attempt_utc=data.get("last_attempt_utc"),
        reason=data.get("reason"),
        extra=data.get("extra"),
    )

    return _validate_pending_message(record)


# ============================================================================
# Main store class
# ============================================================================
#
# This class provides a small clean interface for saving, loading, updating,
# clearing, and inspecting the pending-message record.
# ============================================================================


class PendingMessageStore:
    """
    File-backed store for a single pending BearWave critical message.

    STORAGE DESIGN
    --------------
    The store writes a single JSON file to disk.

    This class is deliberately simple because the current BearWave design needs
    only one pending critical message record at a time.

    SAFETY APPROACH
    ---------------
    Writes use an atomic replace pattern:
    - write JSON to a temporary file in the same directory
    - fsync the temporary file
    - replace the target file atomically

    This reduces the chance of corruption if power is lost during a write.
    """

    def __init__(self, path: str | Path) -> None:
        """
        Create a store bound to a specific file path.

        EXAMPLE
        -------
        PendingMessageStore("/home/pi/bearwave/pending_message.json")

        NOTE
        ----
        This constructor does not create the file immediately. The file is only
        created when save() is called.
        """
        self.path = Path(path)

    # ------------------------------------------------------------------------
    # Basic existence and filesystem helpers
    # ------------------------------------------------------------------------

    def exists(self) -> bool:
        """
        Return True if the pending-message file currently exists.

        This is a quick filesystem check only. It does not validate the file
        contents.
        """
        return self.path.exists()

    def ensure_parent_directory(self) -> None:
        """
        Ensure that the parent directory of the store file exists.

        This method creates the parent directory tree if required.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PendingStoreIOError(
                f"Could not create parent directory for store: {self.path.parent}"
            ) from exc

    # ------------------------------------------------------------------------
    # Save/load operations
    # ------------------------------------------------------------------------

    def save(self, record: PendingMessage) -> None:
        """
        Save a pending critical message to disk.

        PROCESS
        -------
        1. Validate the record
        2. Ensure the parent directory exists
        3. Write JSON to a temporary file
        4. Flush and fsync the temporary file
        5. Atomically replace the target file

        WHY ATOMIC REPLACE MATTERS
        --------------------------
        The remote node may lose power intentionally during shutdown or
        unexpectedly if something goes wrong. Atomic replacement reduces the
        risk of ending up with a partially written JSON file.
        """
        validated = _validate_pending_message(record)
        self.ensure_parent_directory()

        data = asdict(validated)
        json_text = json.dumps(data, indent=2, sort_keys=True)

        temp_path: Optional[Path] = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self.path.parent),
                prefix=self.path.name + ".tmp.",
                suffix=".json",
                delete=False,
            ) as tmp_file:
                temp_path = Path(tmp_file.name)
                tmp_file.write(json_text)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())

            os.replace(temp_path, self.path)

        except OSError as exc:
            raise PendingStoreIOError(
                f"Failed to save pending message store to {self.path}"
            ) from exc

        finally:
            # Best-effort cleanup if temp file still exists.
            if temp_path is not None and temp_path.exists():
                if temp_path != self.path:
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass

    def load(self) -> Optional[PendingMessage]:
        """
        Load the pending critical message from disk.

        RETURNS
        -------
        PendingMessage if a record exists and is valid.
        None if the file does not exist.

        RAISES
        ------
        PendingStoreFormatError if the file exists but contains invalid JSON or
        invalid structure.

        PendingStoreIOError if the file cannot be read for I/O reasons.
        """
        if not self.path.exists():
            return None

        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PendingStoreIOError(
                f"Failed to read pending message store from {self.path}"
            ) from exc

        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PendingStoreFormatError(
                f"Pending message store at {self.path} contains invalid JSON."
            ) from exc

        return _pending_message_from_dict(raw)

    def clear(self) -> None:
        """
        Remove the pending-message file if it exists.

        This method should be called only after a critical message has been
        successfully transmitted and acknowledged.

        It is safe to call even if the file is already absent.
        """
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError as exc:
            raise PendingStoreIOError(
                f"Failed to clear pending message store at {self.path}"
            ) from exc

    # ------------------------------------------------------------------------
    # Update-style helper methods
    # ------------------------------------------------------------------------
    #
    # These methods make it easier for the higher-level controller to adjust
    # retry metadata without manually reconstructing the entire dataclass every
    # time.
    # ------------------------------------------------------------------------

    def increment_attempt_count(
        self,
        last_attempt_utc: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> PendingMessage:
        """
        Load the current record, increment its attempt count, update selected
        metadata, and save it back.

        RETURNS
        -------
        The updated PendingMessage record.

        RAISES
        ------
        PendingStoreError if no record currently exists or save/load fails.

        WHY THIS METHOD EXISTS
        ----------------------
        Retrying a critical message is a normal part of BearWave operation.
        This helper keeps the retry metadata update compact and consistent.
        """
        current = self.load()
        if current is None:
            raise PendingStoreError(
                "Cannot increment attempt count because no pending record exists."
            )

        updated = PendingMessage(
            node_id=current.node_id,
            message_id=current.message_id,
            message_type=current.message_type,
            flags=current.flags,
            data=current.data,
            text=current.text,
            created_utc=current.created_utc,
            attempt_count=current.attempt_count + 1,
            last_attempt_utc=last_attempt_utc or current.last_attempt_utc,
            reason=reason or current.reason,
            extra=current.extra,
        )

        self.save(updated)
        return updated

    def overwrite_reason(self, reason: str) -> PendingMessage:
        """
        Replace the stored human-readable reason field and save the record.

        RETURNS
        -------
        The updated PendingMessage record.

        EXAMPLE
        -------
        This can be used to record a clearer explanation such as:
            "Retry on boot after prior no-ACK condition"
        """
        current = self.load()
        if current is None:
            raise PendingStoreError(
                "Cannot overwrite reason because no pending record exists."
            )

        updated = PendingMessage(
            node_id=current.node_id,
            message_id=current.message_id,
            message_type=current.message_type,
            flags=current.flags,
            data=current.data,
            text=current.text,
            created_utc=current.created_utc,
            attempt_count=current.attempt_count,
            last_attempt_utc=current.last_attempt_utc,
            reason=reason,
            extra=current.extra,
        )

        self.save(updated)
        return updated

    # ------------------------------------------------------------------------
    # Convenience inspection helpers
    # ------------------------------------------------------------------------

    def load_if_exists(self) -> Optional[PendingMessage]:
        """
        Convenience alias for load().

        This method exists because it reads clearly in higher-level code:
            pending = store.load_if_exists()
        """
        return self.load()

    def has_pending_message(self) -> bool:
        """
        Return True if a valid pending-message record exists.

        IMPORTANT
        ---------
        This method attempts to load the record and therefore validates the
        file contents. If the file exists but is malformed, an exception is
        raised rather than silently returning True.
        """
        return self.load() is not None

    # ------------------------------------------------------------------------
    # Recovery / backup helper
    # ------------------------------------------------------------------------
    #
    # This is optional, but useful during development and field testing.
    # If a store file becomes corrupted, it can be moved aside for later
    # inspection rather than simply deleted.
    # ------------------------------------------------------------------------

    def move_corrupt_store_aside(self, suffix: str = ".corrupt") -> Optional[Path]:
        """
        Move the current store file aside by renaming it with an added suffix.

        RETURNS
        -------
        The new path if a file existed and was moved.
        None if the store file did not exist.

        WHY THIS IS USEFUL
        ------------------
        During testing or field deployment, it may be valuable to preserve a
        corrupted store file for analysis rather than deleting it immediately.
        """
        if not self.path.exists():
            return None

        destination = self.path.with_name(self.path.name + suffix)

        try:
            shutil.move(str(self.path), str(destination))
        except OSError as exc:
            raise PendingStoreIOError(
                f"Failed to move corrupt store aside from {self.path} to {destination}"
            ) from exc

        return destination


# ============================================================================
# Example manual test block
# ============================================================================
#
# This block allows the module to be run directly during development.
# It demonstrates save/load/update/clear behavior using a test file in the
# current working directory.
# ============================================================================

if __name__ == "__main__":
    TEST_PATH = "pending_message_test.json"

    store = PendingMessageStore(TEST_PATH)

    print("=== BearWave pending store self-test ===")

    # Start from a clean state for the demonstration.
    if store.exists():
        store.clear()

    record = PendingMessage(
        node_id="ND01",
        message_id="7L",
        message_type="TA",
        flags="T1",
        data="B68",
        text="BW1|ND01|TA|7L|T1|B68",
        created_utc="2026-04-17T08:15:22Z",
        attempt_count=3,
        last_attempt_utc="2026-04-17T08:16:45Z",
        reason="No valid ACK received after 3 attempts",
        extra={"source_event": "trap"},
    )

    print("Saving test record...")
    store.save(record)

    print("Store exists?", store.exists())

    loaded = store.load()
    print("Loaded record:")
    print(loaded)

    print("Incrementing attempt count...")
    updated = store.increment_attempt_count(
        last_attempt_utc="2026-04-17T12:00:00Z",
        reason="Retry on later wake cycle",
    )
    print(updated)

    print("Clearing store...")
    store.clear()

    print("Store exists after clear?", store.exists())