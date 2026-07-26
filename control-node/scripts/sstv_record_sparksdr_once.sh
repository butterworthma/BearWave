#!/usr/bin/env bash
set -uo pipefail

SECONDS_TO_RECORD="${1:-120}"
OUT_DIR="${BEARWAVE_SSTV_AUDIO_DIR:-/home/mark/control-node/sstv-audio/manual}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT_DIR"

# This is the tested SparkSDR monitor source on the control-node Pi. If the USB
# audio card name changes, run `pactl list short sources` and update this value.
SOURCE="alsa_output.usb-C-Media_Electronics_Inc._USB_Audio_Device-00.analog-stereo.monitor"

# Prefer recording SparkSDR's own sink-input stream when PulseAudio exposes it.
# That captures what SparkSDR is actually sending to the audio stack and avoids
# recording unrelated desktop audio during bench tests.
SINK_INPUT_ID="$(pactl list short sink-inputs | awk '/sparksdr-audio-op/ {print $1; exit}')"

BASE="${OUT_DIR}/sstv_direct_${STAMP}"

# Leave a breadcrumb for later copy/download commands while the user is running
# a timed test and may not know the final filename yet.
echo "$BASE" > /tmp/bearwave-current-sparksdr-recording-base

if [ -n "$SINK_INPUT_ID" ]; then
  echo "[SSTV_RECORD] Recording SparkSDR sink-input ${SINK_INPUT_ID} for ${SECONDS_TO_RECORD}s"
  timeout "$((SECONDS_TO_RECORD + 10))" parecord \
    --record \
    --monitor-stream="$SINK_INPUT_ID" \
    --file-format=wav \
    --rate=48000 \
    --channels=1 \
    "${BASE}_sparksdr_stream.wav"
else
  echo "[SSTV_RECORD] SparkSDR sink-input not found; falling back to monitor ${SOURCE}"
  timeout "$((SECONDS_TO_RECORD + 10))" parecord \
    --record \
    --device="$SOURCE" \
    --file-format=wav \
    --rate=48000 \
    --channels=1 \
    "${BASE}_usb_monitor.wav"
fi

for f in "${BASE}"_*.wav; do
  [ -f "$f" ] || continue
  echo "[SSTV_RECORD] wrote $f"
  # Print mean/max volume so clipping or very low SSTV levels can be spotted
  # without opening the WAV file in an editor.
  ffmpeg -hide_banner -nostats -i "$f" -af volumedetect -f null - 2>&1 | grep -E 'mean_volume|max_volume' || true
done
