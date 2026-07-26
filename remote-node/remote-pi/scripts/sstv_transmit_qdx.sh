#!/usr/bin/env bash
set -u
set -o pipefail

# BearWave SSTV QDX transmit helper.
#
# This script is called by the remote-node Python application after a trap alarm
# has already been acknowledged over JS8Call. It keys the QDX, plays one encoded
# SSTV WAV file, and then releases PTT. Image transmission is best-effort; the
# JS8 alarm/ACK path remains the reliable part of the system.

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <sstv-wav>" >&2
  exit 2
fi

WAV_PATH="$1"

# Strip a stray carriage return. This protects manual invocations pasted from
# Windows terminals and avoids a confusing "file not found" when the path is
# otherwise correct.
WAV_PATH="${WAV_PATH%$'\r'}"

# Defaults match the tested QDX setup on the live remote Pi. Each value can be
# overridden from the environment for another radio, serial path, or audio card.
RIG_MODEL="${BEARWAVE_SSTV_RIG_MODEL:-2052}"
RIG_DEVICE="${BEARWAVE_SSTV_RIG_DEVICE:-/dev/ttyACM0}"
RIG_SPEED="${BEARWAVE_SSTV_RIG_SPEED:-4800}"
AUDIO_DEVICE="${BEARWAVE_SSTV_AUDIO_DEVICE:-plughw:CARD=Transceiver,DEV=0}"
PTT_SETTLE_S="${BEARWAVE_SSTV_PTT_SETTLE_S:-0.5}"
TX_GAIN="${BEARWAVE_SSTV_TX_GAIN:-1.0}"
PLAYBACK_WAV="${WAV_PATH}"
TMP_WAV=""

ptt_off() {
  # Always make PTT release best-effort and non-fatal. This function is called
  # from cleanup paths where masking the original error would make diagnostics
  # harder.
  rigctl -m "${RIG_MODEL}" -r "${RIG_DEVICE}" -s "${RIG_SPEED}" T 0 >/dev/null 2>&1 || true
}

if [ ! -f "${WAV_PATH}" ]; then
  echo "[SSTV_TX] ERROR: WAV file not found: ${WAV_PATH}" >&2
  exit 1
fi

if ! command -v rigctl >/dev/null 2>&1; then
  echo "[SSTV_TX] ERROR: rigctl is not installed or not on PATH" >&2
  exit 1
fi

if ! command -v aplay >/dev/null 2>&1; then
  echo "[SSTV_TX] ERROR: aplay is not installed or not on PATH" >&2
  exit 1
fi

cleanup() {
  # The trap below calls cleanup on normal exit, Ctrl-C, or service termination.
  # That makes the safest state "PTT released" even if aplay or ffmpeg fails.
  ptt_off
  if [ -n "${TMP_WAV}" ] && [ -f "${TMP_WAV}" ]; then
    rm -f "${TMP_WAV}"
  fi
}

trap cleanup EXIT INT TERM

if [ "${TX_GAIN}" != "1" ] && [ "${TX_GAIN}" != "1.0" ]; then
  # Optional per-SSTV gain control. During bench testing the received SSTV level
  # was tuned independently from JS8Call, so gain is kept local to this helper.
  if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "[SSTV_TX] ERROR: ffmpeg is required when BEARWAVE_SSTV_TX_GAIN=${TX_GAIN}" >&2
    exit 1
  fi

  TMP_WAV="$(mktemp --suffix=.wav /tmp/bearwave-sstv-tx.XXXXXX)"
  echo "[SSTV_TX] Preparing attenuated playback copy gain=${TX_GAIN}: ${TMP_WAV}"
  ffmpeg -hide_banner -loglevel error -y -i "${WAV_PATH}" -af "volume=${TX_GAIN}" -ar 48000 -ac 1 "${TMP_WAV}"
  PLAYBACK_WAV="${TMP_WAV}"
fi

echo "[SSTV_TX] Keying QDX PTT using rigctl model=${RIG_MODEL} device=${RIG_DEVICE} speed=${RIG_SPEED}"
rigctl -m "${RIG_MODEL}" -r "${RIG_DEVICE}" -s "${RIG_SPEED}" T 1

# Give the QDX/radio path a short moment to enter TX before audio begins, so
# the SSTV VIS/header is not clipped at the start of the transmission.
sleep "${PTT_SETTLE_S}"

echo "[SSTV_TX] Playing ${PLAYBACK_WAV} to ${AUDIO_DEVICE}"
aplay -D "${AUDIO_DEVICE}" "${PLAYBACK_WAV}"
AUDIO_RC=$?

echo "[SSTV_TX] Releasing QDX PTT"
ptt_off
trap - EXIT INT TERM

# Run cleanup once more after disabling the trap so the temporary gain-adjusted
# WAV is removed without recursively calling cleanup through EXIT.
cleanup

exit "${AUDIO_RC}"
