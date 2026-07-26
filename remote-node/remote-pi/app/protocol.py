from __future__ import annotations

"""
BearWave protocol helper module
===============================

WHAT THIS MODULE DOES
---------------------
This module defines the BearWave application-layer message format used between
the remote node and the control node.

The protocol is intentionally compact because it is designed for use over
JS8Call, where:
- airtime matters
- messages should be short for reliability
- acknowledgements must be matched deterministically
- future sensor fields may need to be added without redesigning the structure

This module is responsible for:
- building outbound BearWave messages
- building outbound acknowledgement messages
- parsing incoming acknowledgement messages
- validating protocol fields
- providing a single place where the message format is defined

WHAT THIS MODULE DOES NOT DO
----------------------------
This module does NOT:
- talk to the ESP32 over UART
- talk directly to JS8Call
- send messages over the radio
- store pending unsent messages
- implement retry logic

Those jobs belong in other modules.

CURRENT BEARWAVE MESSAGE FORMATS
--------------------------------
1. Outbound application message from remote node:

    BW1|<node>|<type>|<id>|<flags>|<data>

   Example:
    BW1|ND01|TA|7L|T1|B68

2. Acknowledgement message from control node

   New compact format:
    A|<node>|<id>

   Example:
    A|ND01|7L

   Legacy format still accepted for compatibility:
    ACK|<node>|<id>|OK

   Example:
    ACK|ND01|7L|OK

WHY TWO ACK FORMATS ARE SUPPORTED
---------------------------------
During bench testing, the longer legacy ACK format proved more likely to arrive
fragmented over JS8Call receive processing. In one observed case, the remote
node received:

    ACK|ND01|JB|

but did not receive the final trailing "OK" segment in time, causing the ACK to
be rejected.

The shorter compact format:

    A|ND01|JB

reduces fragmentation risk and is therefore preferred going forward.

This module still accepts the old format so that the system can transition
gradually without breaking compatibility.

DESIGN PRINCIPLES
-----------------
The protocol has been designed around these principles:

1. Compactness
   Messages should remain short so they can fit into short JS8Call
   transmission opportunities wherever possible.

2. Deterministic acknowledgement
   Every message contains a compact message ID so that acknowledgements can
   match a specific transmission.

3. Extensibility
   Additional data fields such as temperature, humidity, fault codes, and
   future sensor readings can be added to the <data> field without changing
   the outer envelope.

4. Human readability
   During development and field testing, it is useful that an operator can
   read the message directly without needing special tooling.

5. Strong separation of concerns
   Message syntax lives here. Transport and control logic live elsewhere.

EXAMPLE USAGE
-------------
Build a heartbeat message:

    msg = build_heartbeat_message(
        node_id="ND01",
        message_id="7K",
        battery_percent=72
    )

Result:
    BW1|ND01|HB|7K|0|B72

Build a compact acknowledgement:

    ack = build_ack_message("ND01", "7K")

Result:
    A|ND01|7K

Parse either ACK format:

    parse_ack_message("A|ND01|7K")
    parse_ack_message("ACK|ND01|7K|OK")

Both yield the same structured AckMessage object.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, Optional
import re


# ============================================================================
# Custom exceptions
# ============================================================================
#
# These exceptions make it easier for the higher-level application to
# distinguish protocol-related problems from transport or UART problems.
# ============================================================================


class ProtocolError(Exception):
    """
    Base exception for all BearWave protocol problems.
    """
    pass


class ProtocolValidationError(ProtocolError):
    """
    Raised when a field is invalid.

    Examples:
    - node ID contains illegal characters
    - message type is unknown
    - message ID is malformed
    - a data key is invalid
    """
    pass


class ProtocolParseError(ProtocolError):
    """
    Raised when a message string cannot be parsed as a valid BearWave message.

    Examples:
    - wrong number of fields
    - missing separators
    - wrong prefix marker
    - malformed acknowledgement
    """
    pass


# ============================================================================
# Protocol constants
# ============================================================================

PROTOCOL_VERSION = "BW1"

# Preferred new compact ACK marker.
ACK_MARKER = "A"

# Legacy ACK marker still accepted during transition.
LEGACY_ACK_MARKER = "ACK"

ACK_STATUS_OK = "OK"

MAX_NODE_ID_LENGTH = 8
MAX_MESSAGE_ID_LENGTH = 3
MAX_FLAGS_LENGTH = 12
MAX_DATA_FIELD_LENGTH = 64

NODE_ID_RE = re.compile(r"^[A-Z0-9]{2,8}$")
MESSAGE_ID_RE = re.compile(r"^[A-Z0-9]{1,3}$")
DATA_KEY_RE = re.compile(r"^[A-Z]$")
DATA_VALUE_RE = re.compile(r"^[A-Z0-9\-]+$")

# These regexes are used for flexible ACK extraction.
# They are intentionally NOT anchored with ^...$ because inbound JS8 text may
# contain surrounding callsign/addressing material or other wrapper text.
COMPACT_ACK_RE = re.compile(r"A\|([A-Z0-9]{2,8})\|([A-Z0-9]{1,3})")
LEGACY_ACK_RE = re.compile(r"ACK\|([A-Z0-9]{2,8})\|([A-Z0-9]{1,3})\|OK")


# ============================================================================
# Enumerations
# ============================================================================


class MessageType(str, Enum):
    """
    Supported BearWave application-layer message types.
    """
    HEARTBEAT = "HB"
    TRAP_ALARM = "TA"
    LOW_BATTERY = "LB"
    SENSOR_REPORT = "SR"
    FAULT = "FT"


class EventFlag(str, Enum):
    """
    Common short flag values used in the <flags> field.
    """
    NONE = "0"
    TRAP = "T1"
    LOW_BATTERY = "L1"
    TRAP_AND_LOW_BATTERY = "T1L1"


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass(frozen=True)
class BearWaveMessage:
    """
    Structured representation of an outbound BearWave application message.
    """
    version: str
    node_id: str
    message_type: MessageType
    message_id: str
    flags: str
    data: str
    text: str


@dataclass(frozen=True)
class AckMessage:
    """
    Structured representation of an inbound acknowledgement message.

    marker:
        Either the new compact marker "A" or the legacy marker "ACK"

    node_id:
        Node identifier referenced by the acknowledgement

    message_id:
        ID of the message being acknowledged

    status:
        For the compact format, we still normalise this to "OK" in the parsed
        object so the rest of the code can treat both formats the same way.

    text:
        The original normalised text we parsed from
    """
    marker: str
    node_id: str
    message_id: str
    status: str
    text: str


# ============================================================================
# Validation helpers
# ============================================================================


def validate_node_id(node_id: str) -> str:
    """
    Validate a BearWave node ID.

    RULES
    -----
    - upper-case letters and digits only
    - length between 2 and 8 characters
    """
    normalized = node_id.strip().upper()

    if not NODE_ID_RE.fullmatch(normalized):
        raise ProtocolValidationError(
            f"Invalid node ID {node_id!r}. "
            f"Expected 2-8 uppercase alphanumeric characters."
        )

    return normalized


def validate_message_id(message_id: str) -> str:
    """
    Validate a BearWave message ID.

    RULES
    -----
    - upper-case letters and digits only
    - length between 1 and 3 characters
    """
    normalized = message_id.strip().upper()

    if not MESSAGE_ID_RE.fullmatch(normalized):
        raise ProtocolValidationError(
            f"Invalid message ID {message_id!r}. "
            f"Expected 1-3 uppercase alphanumeric characters."
        )

    return normalized


def validate_flags(flags: str) -> str:
    """
    Validate the compact flags field.
    """
    normalized = flags.strip().upper()

    if not normalized:
        raise ProtocolValidationError("Flags field must not be empty.")

    if len(normalized) > MAX_FLAGS_LENGTH:
        raise ProtocolValidationError(
            f"Flags field {normalized!r} is too long."
        )

    if "|" in normalized or "," in normalized:
        raise ProtocolValidationError(
            f"Flags field {normalized!r} contains illegal separator characters."
        )

    return normalized


def validate_data_field(data: str) -> str:
    """
    Validate the raw <data> field.
    """
    normalized = data.strip().upper()

    if not normalized:
        raise ProtocolValidationError("Data field must not be empty.")

    if len(normalized) > MAX_DATA_FIELD_LENGTH:
        raise ProtocolValidationError(
            f"Data field {normalized!r} is too long."
        )

    if "|" in normalized:
        raise ProtocolValidationError(
            f"Data field {normalized!r} contains illegal field separator '|'."
        )

    return normalized


def validate_data_key(key: str) -> str:
    """
    Validate a one-letter compact data key.
    """
    normalized = key.strip().upper()

    if not DATA_KEY_RE.fullmatch(normalized):
        raise ProtocolValidationError(
            f"Invalid data key {key!r}. Expected a single uppercase letter."
        )

    return normalized


def validate_data_value(value: str) -> str:
    """
    Validate the value part of a compact data token.
    """
    normalized = value.strip().upper()

    if not normalized:
        raise ProtocolValidationError("Data value must not be empty.")

    if not DATA_VALUE_RE.fullmatch(normalized):
        raise ProtocolValidationError(
            f"Invalid data value {value!r}. "
            f"Expected compact uppercase alphanumeric text."
        )

    return normalized


# ============================================================================
# Compact data-token helpers
# ============================================================================


def build_data_token(key: str, value: str | int) -> str:
    """
    Build a single compact data token.

    Examples:
        build_data_token("B", 72) -> "B72"
        build_data_token("T", 23) -> "T23"
    """
    normalized_key = validate_data_key(key)
    normalized_value = validate_data_value(str(value))
    return f"{normalized_key}{normalized_value}"


def join_data_tokens(tokens: Iterable[str]) -> str:
    """
    Join one or more compact data tokens into the BearWave <data> field.
    """
    token_list = [token.strip().upper() for token in tokens if token.strip()]

    if not token_list:
        raise ProtocolValidationError("At least one data token is required.")

    data_field = ",".join(token_list)
    return validate_data_field(data_field)


# ============================================================================
# Message-building helpers
# ============================================================================


def build_message(
    node_id: str,
    message_type: MessageType,
    message_id: str,
    flags: str,
    data: str,
) -> BearWaveMessage:
    """
    Build a full BearWave application-layer message.

    Result format:
        BW1|<node>|<type>|<id>|<flags>|<data>
    """
    validated_node_id = validate_node_id(node_id)
    validated_message_id = validate_message_id(message_id)
    validated_flags = validate_flags(flags)
    validated_data = validate_data_field(data)

    text = (
        f"{PROTOCOL_VERSION}|"
        f"{validated_node_id}|"
        f"{message_type.value}|"
        f"{validated_message_id}|"
        f"{validated_flags}|"
        f"{validated_data}"
    )

    return BearWaveMessage(
        version=PROTOCOL_VERSION,
        node_id=validated_node_id,
        message_type=message_type,
        message_id=validated_message_id,
        flags=validated_flags,
        data=validated_data,
        text=text,
    )


def build_heartbeat_message(
    node_id: str,
    message_id: str,
    battery_percent: int,
) -> BearWaveMessage:
    """
    Build a standard heartbeat message.
    """
    battery_token = build_data_token("B", battery_percent)

    return build_message(
        node_id=node_id,
        message_type=MessageType.HEARTBEAT,
        message_id=message_id,
        flags=EventFlag.NONE.value,
        data=battery_token,
    )


def build_trap_alarm_message(
    node_id: str,
    message_id: str,
    battery_percent: int,
) -> BearWaveMessage:
    """
    Build a trap-alarm message.
    """
    battery_token = build_data_token("B", battery_percent)

    return build_message(
        node_id=node_id,
        message_type=MessageType.TRAP_ALARM,
        message_id=message_id,
        flags=EventFlag.TRAP.value,
        data=battery_token,
    )


def build_low_battery_message(
    node_id: str,
    message_id: str,
    battery_percent: int,
) -> BearWaveMessage:
    """
    Build a low-battery alarm message.
    """
    battery_token = build_data_token("B", battery_percent)

    return build_message(
        node_id=node_id,
        message_type=MessageType.LOW_BATTERY,
        message_id=message_id,
        flags=EventFlag.LOW_BATTERY.value,
        data=battery_token,
    )


def build_sensor_report_message(
    node_id: str,
    message_id: str,
    data_tokens: Iterable[str],
    flags: str = EventFlag.NONE.value,
) -> BearWaveMessage:
    """
    Build a general sensor-report message.
    """
    data_field = join_data_tokens(data_tokens)

    return build_message(
        node_id=node_id,
        message_type=MessageType.SENSOR_REPORT,
        message_id=message_id,
        flags=flags,
        data=data_field,
    )


def build_fault_message(
    node_id: str,
    message_id: str,
    fault_code: str,
    extra_tokens: Optional[Iterable[str]] = None,
) -> BearWaveMessage:
    """
    Build a compact fault message.
    """
    tokens = [build_data_token("X", fault_code)]

    if extra_tokens:
        tokens.extend(token.strip().upper() for token in extra_tokens)

    return build_message(
        node_id=node_id,
        message_type=MessageType.FAULT,
        message_id=message_id,
        flags=EventFlag.NONE.value,
        data=join_data_tokens(tokens),
    )


# ============================================================================
# ACK helpers
# ============================================================================


def build_ack_message(node_id: str, message_id: str) -> str:
    """
    Build the preferred compact acknowledgement message.

    Result format:
        A|<node>|<id>

    Example:
        A|ND01|JB
    """
    validated_node_id = validate_node_id(node_id)
    validated_message_id = validate_message_id(message_id)

    return f"{ACK_MARKER}|{validated_node_id}|{validated_message_id}"


def build_legacy_ack_message(node_id: str, message_id: str) -> str:
    """
    Build the legacy acknowledgement format.

    This is kept only for compatibility/testing.
    """
    validated_node_id = validate_node_id(node_id)
    validated_message_id = validate_message_id(message_id)

    return f"{LEGACY_ACK_MARKER}|{validated_node_id}|{validated_message_id}|{ACK_STATUS_OK}"


def parse_ack_message(text: str) -> AckMessage:
    """
    Parse an incoming acknowledgement string.

    This parser is intentionally tolerant of surrounding text because JS8Call
    may deliver wrapper/addressing text or assembled fragments that contain the
    ACK inside a larger string.

    Accepted formats:
        A|<node>|<id>
        ACK|<node>|<id>|OK

    Examples:
        A|ND01|JB
        G7PRW: A|ND01|JB
        ACK|ND01|JB|OK
        G7PRW ACK|ND01|JB|OK
    """
    normalized = text.strip().upper()

    # Prefer the legacy ACK search first only because "ACK|" contains "A|"
    # as a substring-like prefix pattern in a looser search context.
    legacy_match = LEGACY_ACK_RE.search(normalized)
    if legacy_match:
        node_id = legacy_match.group(1)
        message_id = legacy_match.group(2)

        return AckMessage(
            marker=LEGACY_ACK_MARKER,
            node_id=node_id,
            message_id=message_id,
            status=ACK_STATUS_OK,
            text=normalized,
        )

    compact_match = COMPACT_ACK_RE.search(normalized)
    if compact_match:
        node_id = compact_match.group(1)
        message_id = compact_match.group(2)

        return AckMessage(
            marker=ACK_MARKER,
            node_id=node_id,
            message_id=message_id,
            status=ACK_STATUS_OK,
            text=normalized,
        )

    raise ProtocolParseError(
        f"Text is not a valid BearWave acknowledgement: {text!r}"
    )


def ack_matches(
    ack_text: str,
    expected_node_id: str,
    expected_message_id: str,
) -> bool:
    """
    Check whether an acknowledgement text matches the expected node and message.

    Returns True if:
    - the text parses as either supported ACK format
    - the node ID matches
    - the message ID matches
    """
    try:
        ack = parse_ack_message(ack_text)
    except ProtocolError:
        return False

    return (
        ack.node_id == validate_node_id(expected_node_id)
        and ack.message_id == validate_message_id(expected_message_id)
        and ack.status == ACK_STATUS_OK
    )


# ============================================================================
# Optional utility helpers
# ============================================================================


def encode_voltage_tenths(voltage_v: float) -> str:
    """
    Convert a floating-point voltage into the compact tenths-of-a-volt
    representation used by the 'V' key.

    Examples:
        11.8  -> "118"
        12.14 -> "121"
    """
    tenths = round(voltage_v * 10)
    if tenths < 0:
        raise ProtocolValidationError("Voltage cannot be negative.")
    return str(tenths)


def validate_percentage(value: int) -> int:
    """
    Validate that a percentage-like value is between 0 and 100 inclusive.
    """
    if not 0 <= value <= 100:
        raise ProtocolValidationError(
            f"Percentage value {value} is out of range 0-100."
        )
    return value


# ============================================================================
# Example manual test block
# ============================================================================

if __name__ == "__main__":
    print("=== BearWave protocol self-test ===")

    heartbeat = build_heartbeat_message(
        node_id="ND01",
        message_id="7K",
        battery_percent=72,
    )
    print("Heartbeat:", heartbeat.text)

    trap = build_trap_alarm_message(
        node_id="ND01",
        message_id="7L",
        battery_percent=68,
    )
    print("Trap alarm:", trap.text)

    low_bat = build_low_battery_message(
        node_id="ND01",
        message_id="7M",
        battery_percent=18,
    )
    print("Low battery:", low_bat.text)

    compact_ack = build_ack_message("ND01", "7L")
    print("Compact ACK:", compact_ack)

    legacy_ack = build_legacy_ack_message("ND01", "7L")
    print("Legacy ACK:", legacy_ack)

    parsed_compact = parse_ack_message(compact_ack)
    print("Parsed compact ACK:", parsed_compact)

    parsed_legacy = parse_ack_message(legacy_ack)
    print("Parsed legacy ACK:", parsed_legacy)

    print(
        "Compact ACK matches expected?",
        ack_matches(
            ack_text="G7PRW: A|ND01|7L",
            expected_node_id="ND01",
            expected_message_id="7L",
        ),
    )

    print(
        "Legacy ACK matches expected?",
        ack_matches(
            ack_text="ACK|ND01|7L|OK",
            expected_node_id="ND01",
            expected_message_id="7L",
        ),
    )