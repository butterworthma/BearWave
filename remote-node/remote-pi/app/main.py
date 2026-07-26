from __future__ import annotations

"""
BearWave remote-node main entry point
=====================================

WHAT THIS FILE DOES
-------------------
This file is the executable entry point for the Raspberry Pi remote-node
application.

It is intentionally small and focused. Most of the real logic lives in:

- esp_uart_client.py
- protocol.py
- js8_client.py
- pending_store.py
- remote_node_controller.py

This file is responsible for:

1. loading configuration
2. configuring logging
3. creating the main RemoteNodeController
4. running one complete wake-cycle transaction
5. returning a useful process exit code

WHY THIS FILE SHOULD STAY SMALL
-------------------------------
In BearWave, the controller logic is already complex enough. Keeping the entry
point clean makes the project easier to understand, test, and document.

This also makes deployment easier, because a systemd service or boot script can
simply run this file and rely on its process exit code.

EXPECTED EXECUTION MODEL
------------------------
This script is intended to be launched once per Pi wake cycle.

Typical lifecycle:
- ESP32 powers the Pi
- Linux boots
- this script starts
- it performs one full remote-node communications cycle
- the controller requests shutdown from the ESP32 when appropriate
- the process exits

PROCESS EXIT CODE POLICY
------------------------
The process returns an integer exit code so that:
- logs are easier to interpret
- systemd or shell wrappers can detect high-level outcomes
- future automation can distinguish major failure classes

Current exit codes:

    0   Success
        A message transaction completed successfully and the controller
        requested shutdown successfully.

    1   Controlled failure
        The controller ran, but the message was not acknowledged or another
        non-crashing operational failure occurred.

    2   Startup/configuration failure
        Something was wrong before the controller could run properly.

    3   Unexpected fatal exception
        The script encountered an exception outside the normal controller
        result path.

CONFIGURATION SOURCES
---------------------
This file currently supports configuration from environment variables.
That keeps it simple and avoids requiring an external configuration parser
at this stage.

If an environment variable is absent, a sensible default is used.

SUPPORTED ENVIRONMENT VARIABLES
-------------------------------
BEARWAVE_SERIAL_PORT
    Serial device path for the ESP32 UART link.
    Example: /dev/serial0

BEARWAVE_SERIAL_BAUDRATE
    UART baud rate for the ESP32 link.
    Example: 115200

BEARWAVE_JS8_HOST
    Hostname/IP for local JS8Call API.
    Example: 127.0.0.1

BEARWAVE_JS8_PORT
    Port for local JS8Call API.
    Example: 2442

BEARWAVE_CONTROL_CALLSIGN
    Callsign of the control node station.
    Example: G7PRW

BEARWAVE_NODE_ID
    Short internal BearWave node ID.
    Example: ND01

BEARWAVE_PENDING_STORE_PATH
    Filesystem path for the pending critical message JSON file.
    Example: /home/mark/bearwave/state/pending_message.json

BEARWAVE_ACK_WAIT_PER_ATTEMPT_S
    Seconds to wait for acknowledgement on each send attempt.
    Example: 45.0

BEARWAVE_MAX_SEND_ATTEMPTS
    Maximum number of send attempts per run.
    Example: 3

BEARWAVE_STARTUP_JS8_DRAIN
    Whether to drain stale directed JS8 messages on startup.
    Accepted true values:
        1, true, yes, on
    Accepted false values:
        0, false, no, off

BEARWAVE_ALLOW_COMBINED_ALARM_MESSAGE
    Whether TRAP+LOW_BAT should be sent as one combined critical message.
    Accepted values are the same as above.

BEARWAVE_LOG_LEVEL
    Python logging level.
    Example:
        DEBUG
        INFO
        WARNING
        ERROR

BEARWAVE_SSTV_ENABLED
    Enable the optional post-ACK SSTV image stage for critical messages.
    Defaults to false.

BEARWAVE_SSTV_DRY_RUN
    Log SSTV capture/encode/transmit commands without running them.
    Defaults to true for safe bench testing.

BEARWAVE_SSTV_WORK_DIR
    Directory for captured images and generated SSTV WAV files.

BEARWAVE_SSTV_MODE
    SSTV mode label passed to the encoder. Example: Robot36.

BEARWAVE_SSTV_REPEAT_COUNT
    Number of times to play/transmit the generated SSTV WAV.

BEARWAVE_SSTV_PREPARE_COMMAND
    Image preparation step. The default "__pillow__" uses built-in Pillow
    resizing and avoids an ImageMagick dependency.

BEARWAVE_SSTV_TRANSMIT_COMMAND
    Shell command used to transmit the generated SSTV WAV. In the deployed
    QDX setup this should key CAT PTT, play the WAV, then release PTT.

EXAMPLE USAGE
-------------
Manual execution from a virtual environment:

    source ~/bearwave/.venv/bin/activate
    python main.py

With overrides:

    BEARWAVE_NODE_ID=ND03 \
    BEARWAVE_CONTROL_CALLSIGN=G7PRW \
    python main.py
"""

import logging
import os
import sys
from dataclasses import asdict

from remote_node_controller import (
    ControllerRunResult,
    RemoteNodeConfig,
    RemoteNodeController,
    configure_default_logging,
)
from sstv_image import SstvImageConfig


# ============================================================================
# Exit-code constants
# ============================================================================
#
# These symbolic constants make the code easier to read than raw integers.
# ============================================================================

EXIT_SUCCESS = 0
EXIT_CONTROLLED_FAILURE = 1
EXIT_STARTUP_FAILURE = 2
EXIT_FATAL_EXCEPTION = 3


# ============================================================================
# Environment parsing helpers
# ============================================================================
#
# These helpers convert environment variables into the strongly typed values
# expected by RemoteNodeConfig.
# ============================================================================


def env_str(name: str, default: str) -> str:
    """
    Read a string environment variable, returning a default if unset.

    Whitespace is stripped from both the environment value and the default.
    """
    value = os.getenv(name)
    if value is None:
        return default.strip()
    return value.strip()


def env_int(name: str, default: int) -> int:
    """
    Read an integer environment variable.

    Raises:
        ValueError if the environment variable exists but is not a valid
        integer.

    WHY THIS RAISES
    ---------------
    Configuration errors should fail early and clearly rather than silently
    producing unexpected behavior later.
    """
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {name!r} must be an integer, got {value!r}."
        ) from exc


def env_float(name: str, default: float) -> float:
    """
    Read a floating-point environment variable.

    Raises:
        ValueError if the environment variable exists but is not a valid float.
    """
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return float(value.strip())
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {name!r} must be a float, got {value!r}."
        ) from exc


def env_bool(name: str, default: bool) -> bool:
    """
    Read a boolean-like environment variable.

    Accepted true values:
        1, true, yes, on

    Accepted false values:
        0, false, no, off

    Raises:
        ValueError if the variable exists but is not a recognised boolean-like
        string.

    WHY THIS EXISTS
    ---------------
    Environment variables are strings, so booleans need explicit conversion.
    """
    value = os.getenv(name)
    if value is None:
        return default

    normalized = value.strip().lower()

    if normalized in {"1", "true", "yes", "on"}:
        return True

    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ValueError(
        f"Environment variable {name!r} must be a boolean-like value, got {value!r}."
    )


def parse_log_level(name: str, default: int = logging.INFO) -> int:
    """
    Read a logging level from the environment.

    Accepted values include:
        DEBUG
        INFO
        WARNING
        ERROR
        CRITICAL

    If the variable is absent, the default is returned.
    """
    raw = os.getenv(name)
    if raw is None:
        return default

    normalized = raw.strip().upper()

    if normalized == "DEBUG":
        return logging.DEBUG
    if normalized == "INFO":
        return logging.INFO
    if normalized == "WARNING":
        return logging.WARNING
    if normalized == "ERROR":
        return logging.ERROR
    if normalized == "CRITICAL":
        return logging.CRITICAL

    raise ValueError(
        f"Environment variable {name!r} has unsupported log level {raw!r}."
    )


# ============================================================================
# Configuration loading
# ============================================================================
#
# This function centralises all config loading in one place.
# ============================================================================


def load_config_from_environment() -> RemoteNodeConfig:
    """
    Build a RemoteNodeConfig from environment variables.

    RETURNS
    -------
    RemoteNodeConfig

    RAISES
    ------
    ValueError if any environment variable has an invalid value.

    WHY THIS FUNCTION EXISTS
    ------------------------
    Keeping configuration loading separate from main() makes the script easier
    to test and easier to extend later.
    """
    sstv_config = SstvImageConfig(
        enabled=env_bool("BEARWAVE_SSTV_ENABLED", False),
        dry_run=env_bool("BEARWAVE_SSTV_DRY_RUN", True),
        work_dir=env_str("BEARWAVE_SSTV_WORK_DIR", "/home/mark/bearwave/sstv"),
        mode=env_str("BEARWAVE_SSTV_MODE", "Robot36"),
        repeat_count=env_int("BEARWAVE_SSTV_REPEAT_COUNT", 2),
        capture_command=env_str(
            "BEARWAVE_SSTV_CAPTURE_COMMAND",
            "rpicam-still -o {image} --width 1280 --height 960 --timeout 1000",
        ),
        prepare_command=env_str(
            "BEARWAVE_SSTV_PREPARE_COMMAND",
            "__pillow__",
        ),
        pillow_python=env_str("BEARWAVE_SSTV_PILLOW_PYTHON", "/usr/bin/python3"),
        encode_command=env_str(
            "BEARWAVE_SSTV_ENCODE_COMMAND",
            "python3 -m pysstv --mode {mode} {prepared} {wav}",
        ),
        transmit_command=env_str("BEARWAVE_SSTV_TRANSMIT_COMMAND", "aplay {wav}"),
        stop_js8call_command=env_str(
            "BEARWAVE_SSTV_STOP_JS8CALL_COMMAND",
            "pkill -x js8call",
        ),
    )

    return RemoteNodeConfig(
        serial_port=env_str("BEARWAVE_SERIAL_PORT", "/dev/serial0"),
        serial_baudrate=env_int("BEARWAVE_SERIAL_BAUDRATE", 115200),
        js8_host=env_str("BEARWAVE_JS8_HOST", "127.0.0.1"),
        js8_port=env_int("BEARWAVE_JS8_PORT", 2442),
        control_callsign=env_str("BEARWAVE_CONTROL_CALLSIGN", "G7PRW"),
        node_id=env_str("BEARWAVE_NODE_ID", "ND01"),
        pending_store_path=env_str(
            "BEARWAVE_PENDING_STORE_PATH",
            "/home/mark/bearwave/state/pending_message.json",
        ),
        ack_wait_per_attempt_s=env_float("BEARWAVE_ACK_WAIT_PER_ATTEMPT_S", 90.0),
        max_send_attempts=env_int("BEARWAVE_MAX_SEND_ATTEMPTS", 3),
        startup_js8_drain=env_bool("BEARWAVE_STARTUP_JS8_DRAIN", True),
        allow_combined_alarm_message=env_bool(
            "BEARWAVE_ALLOW_COMBINED_ALARM_MESSAGE",
            True,
        ),
        sstv=sstv_config,
    )


# ============================================================================
# Result-to-exit-code mapping
# ============================================================================
#
# This helper defines how a controller result becomes a process exit code.
# ============================================================================


def result_to_exit_code(result: ControllerRunResult) -> int:
    """
    Convert a ControllerRunResult into a shell-friendly process exit code.

    CURRENT POLICY
    --------------
    Success:
        - result.success is True
        - shutdown was requested successfully

    Controlled failure:
        - any normal run result where success is False
        - or success is True but shutdown request somehow failed

    WHY THIS POLICY
    ---------------
    A BearWave run is only truly "successful" if the communication cycle
    completed properly and the node moved toward orderly shutdown.
    """
    if result.success and result.shutdown_requested:
        return EXIT_SUCCESS

    return EXIT_CONTROLLED_FAILURE


# ============================================================================
# Result logging helper
# ============================================================================
#
# This helper prints a structured summary to the log.
# ============================================================================


def log_run_result(logger: logging.Logger, result: ControllerRunResult) -> None:
    """
    Log a clear summary of the controller run result.

    WHY THIS EXISTS
    ---------------
    A concise structured summary at the end of each run makes bench testing and
    field troubleshooting much easier.
    """
    logger.info("Controller run completed.")
    logger.info("  success: %s", result.success)
    logger.info("  sent_message: %s", result.sent_message)
    logger.info("  acknowledged: %s", result.acknowledged)
    logger.info("  used_pending_message: %s", result.used_pending_message)
    logger.info(
        "  persisted_new_pending_message: %s",
        result.persisted_new_pending_message,
    )
    logger.info("  shutdown_requested: %s", result.shutdown_requested)
    logger.info("  sstv_attempted: %s", result.sstv_attempted)
    logger.info("  sstv_success: %s", result.sstv_success)
    logger.info("  sstv_notes: %s", result.sstv_notes)
    logger.info("  notes: %s", result.notes)


# ============================================================================
# Main entry point
# ============================================================================


def main() -> int:
    """
    Main script entry point.

    PROCESS
    -------
    1. Load configuration from environment
    2. Configure logging
    3. Create controller
    4. Run one complete wake-cycle transaction
    5. Log the outcome
    6. Return the correct process exit code

    RETURNS
    -------
    Integer process exit code.
    """
    try:
        # Load config first. We do this before logging setup because bad config
        # values themselves may need to be reported cleanly.
        config = load_config_from_environment()

        # Configure logging level from environment.
        log_level = parse_log_level("BEARWAVE_LOG_LEVEL", logging.INFO)
        configure_default_logging(log_level)

        logger = logging.getLogger("main")
        logger.info("Starting BearWave main entry point.")
        logger.info("Loaded configuration for node %s.", config.node_id)
        logger.debug("Full configuration: %s", asdict(config))

        controller = RemoteNodeController(config)
        result = controller.run_once()

        log_run_result(logger, result)
        return result_to_exit_code(result)

    except ValueError as exc:
        # Configuration-related startup failure.
        # Example causes:
        # - invalid integer in an environment variable
        # - invalid boolean-like string
        # - invalid log level
        print(f"Startup configuration error: {exc}", file=sys.stderr)
        return EXIT_STARTUP_FAILURE

    except Exception as exc:
        # Any exception not already converted into a normal run result is
        # treated as an unexpected fatal startup/runtime exception.
        try:
            logging.getLogger("main").exception("Fatal exception in main.")
        except Exception:
            # If logging is not yet configured, fall back to stderr.
            print(f"Fatal exception in main: {exc}", file=sys.stderr)

        return EXIT_FATAL_EXCEPTION


# ============================================================================
# Standard Python script entry pattern
# ============================================================================

if __name__ == "__main__":
    sys.exit(main())
