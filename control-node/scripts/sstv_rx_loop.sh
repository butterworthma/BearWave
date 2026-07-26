#!/usr/bin/env bash
set -u
set -o pipefail

BASE_DIR="${BEARWAVE_CONTROL_DIR:-/home/mark/control-node}"
VENV_DIR="${BEARWAVE_SSTV_VENV:-${BASE_DIR}/.venv-sstv}"

# Default to the tested SparkSDR monitor source. This script is optional; the
# preferred permanent receiver is QSSTV saving valid images into INBOX_DIR.
SOURCE="${BEARWAVE_SSTV_RX_SOURCE:-alsa_output.usb-C-Media_Electronics_Inc._USB_Audio_Device-00.analog-stereo.monitor}"
SOURCE_VOLUME="${BEARWAVE_SSTV_SOURCE_VOLUME:-60%}"

# Overlapping chunks improve the chance that one file contains a complete SSTV
# frame from VIS/header through image end, even when the alarm cycle timing is
# not perfectly aligned with the recorder.
CHUNK_SECONDS="${BEARWAVE_SSTV_CHUNK_SECONDS:-90}"
RECORD_INTERVAL="${BEARWAVE_SSTV_RECORD_INTERVAL:-45}"
SAMPLE_RATE="${BEARWAVE_SSTV_SAMPLE_RATE:-48000}"
AUDIO_DIR="${BEARWAVE_SSTV_AUDIO_DIR:-${BASE_DIR}/sstv-audio}"
INBOX_DIR="${BEARWAVE_SSTV_IMAGE_DIR:-${BASE_DIR}/sstv-images/inbox}"
LOG_FILE="${BEARWAVE_SSTV_LOG_FILE:-${BASE_DIR}/logs/sstv-rx.log}"
KEEP_AUDIO="${BEARWAVE_SSTV_KEEP_AUDIO:-1}"
SLEEP_AFTER_FAIL="${BEARWAVE_SSTV_FAIL_SLEEP:-5}"
MAX_DECODE_JOBS="${BEARWAVE_SSTV_MAX_DECODE_JOBS:-3}"

mkdir -p "${AUDIO_DIR}" "${INBOX_DIR}" "$(dirname "${LOG_FILE}")"

log() {
  printf '%s %s\n' "$(date -u --iso-8601=seconds)" "$*" | tee -a "${LOG_FILE}"
}

log "BearWave SSTV RX loop starting"
log "source=${SOURCE} source_volume=${SOURCE_VOLUME} chunk_seconds=${CHUNK_SECONDS} record_interval=${RECORD_INTERVAL} sample_rate=${SAMPLE_RATE}"
log "audio_dir=${AUDIO_DIR} inbox_dir=${INBOX_DIR}"
log "max_background_jobs=${MAX_DECODE_JOBS}"

if command -v pactl >/dev/null 2>&1; then
  if pactl set-source-volume "${SOURCE}" "${SOURCE_VOLUME}" >> "${LOG_FILE}" 2>&1; then
    log "set source volume ${SOURCE} to ${SOURCE_VOLUME}"
  else
    log "warning: failed to set source volume ${SOURCE} to ${SOURCE_VOLUME}"
  fi
else
  log "warning: pactl not found; source volume left unchanged"
fi

cleanup() {
  local PIDS
  PIDS="$(jobs -pr || true)"
  if [ -n "${PIDS}" ]; then
    log "stopping background SSTV jobs"
    kill ${PIDS} 2>/dev/null || true
  fi
}

stop() {
  trap - EXIT INT TERM
  cleanup
  exit 0
}

decode_chunk() {
  local WAV_PATH="$1"
  local PNG_PATH="$2"

  log "decoding ${WAV_PATH}"

  if "${VENV_DIR}/bin/python" "${BASE_DIR}/scripts/sstv_decode_file.py" "${WAV_PATH}" "${PNG_PATH}" >> "${LOG_FILE}" 2>&1; then
    log "decoded SSTV image to ${PNG_PATH}"
  else
    local RC="$?"
    log "no SSTV image decoded from ${WAV_PATH} rc=${RC}"
    rm -f "${PNG_PATH}" "${PNG_PATH}.tmp"
  fi

  if [ "${KEEP_AUDIO}" != "1" ]; then
    rm -f "${WAV_PATH}"
  fi
}

wait_for_job_slot() {
  # Decoding is CPU-heavy on a Pi. Limit concurrent jobs so the control-node UI,
  # SparkSDR, JS8Call, and QSSTV remain responsive.
  while [ "$(jobs -pr | wc -l)" -ge "${MAX_DECODE_JOBS}" ]; do
    wait -n || true
  done
}

record_and_decode_chunk() {
  local STAMP="$1"
  local WAV_PATH="${AUDIO_DIR}/sstv_rx_${STAMP}.wav"
  local PNG_PATH="${INBOX_DIR}/ND01_SSTV_RX_${STAMP}.png"

  log "recording ${CHUNK_SECONDS}s audio chunk to ${WAV_PATH}"

  if ! timeout "$((CHUNK_SECONDS + 10))" ffmpeg \
      -hide_banner \
      -loglevel warning \
      -f pulse \
      -i "${SOURCE}" \
      -t "${CHUNK_SECONDS}" \
      -ac 1 \
      -ar "${SAMPLE_RATE}" \
      -y "${WAV_PATH}" >> "${LOG_FILE}" 2>&1; then
    log "audio capture failed for ${WAV_PATH}; sleeping ${SLEEP_AFTER_FAIL}s"
    rm -f "${WAV_PATH}"
    sleep "${SLEEP_AFTER_FAIL}"
    return 1
  fi

  decode_chunk "${WAV_PATH}" "${PNG_PATH}"
}

trap cleanup EXIT
trap stop INT TERM

while true; do
  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  wait_for_job_slot
  record_and_decode_chunk "${STAMP}" &
  sleep "${RECORD_INTERVAL}"
done
