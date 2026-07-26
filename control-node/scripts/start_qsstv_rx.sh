#!/usr/bin/env bash
set -u

LOG_FILE="/home/mark/control-node/logs/qsstv-rx.log"

# Route both QSSTV and JS8Call to the audio that SparkSDR is playing. The
# default name is the tested USB audio monitor source on the control-node Pi.
MONITOR_SOURCE="alsa_output.usb-C-Media_Electronics_Inc._USB_Audio_Device-00.analog-stereo.monitor"
ROUTE_INTERVAL_S="${BEARWAVE_QSSTV_ROUTE_INTERVAL_S:-5}"

# These were reduced during bench testing because too much receive audio made
# both JS8 and SSTV less reliable.
QSSTV_CAPTURE_VOLUME="${BEARWAVE_QSSTV_CAPTURE_VOLUME:-60%}"
JS8CALL_CAPTURE_VOLUME="${BEARWAVE_JS8CALL_CAPTURE_VOLUME:-60%}"

log() {
  printf '%s %s\n' "$(date -Is)" "$*" >> "$LOG_FILE"
}

export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-/home/mark/.Xauthority}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"

mkdir -p "$(dirname "$LOG_FILE")"

if ! pgrep -u mark -x qsstv >/dev/null 2>&1; then
  log "starting qsstv"
  qsstv >> "$LOG_FILE" 2>&1 &
else
  log "qsstv already running"
fi

route_streams_once() {
  # pactl output is text-heavy, so use a tiny Python parser to identify capture
  # streams by process name and return just "stream_id binary" pairs.
  python3 - <<'PY' | while read -r stream_id binary; do
import subprocess
out = subprocess.run(['pactl', 'list', 'source-outputs'], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
for block in out.split('Source Output #'):
    if not block.strip():
        continue
    first, *rest = block.splitlines()
    sid = first.strip()
    body = '\n'.join(rest).lower()
    if 'application.process.binary = "qsstv"' in body:
        print(sid, 'qsstv')
    elif 'application.process.binary = "js8call"' in body:
        print(sid, 'js8call')
PY
    [ -n "$stream_id" ] || continue
    # Re-apply routing repeatedly. If JS8Call/QSSTV restarts, PulseAudio creates
    # new source-output IDs and the old route no longer applies.
    if pactl move-source-output "$stream_id" "$MONITOR_SOURCE" >> "$LOG_FILE" 2>&1; then
      log "routed source-output $stream_id ($binary) to $MONITOR_SOURCE"
    fi
    if [ "$binary" = "qsstv" ]; then
      if pactl set-source-output-volume "$stream_id" "$QSSTV_CAPTURE_VOLUME" >> "$LOG_FILE" 2>&1; then
        log "set qsstv source-output $stream_id capture volume to $QSSTV_CAPTURE_VOLUME"
      fi
    elif [ "$binary" = "js8call" ]; then
      if pactl set-source-output-volume "$stream_id" "$JS8CALL_CAPTURE_VOLUME" >> "$LOG_FILE" 2>&1; then
        log "set js8call source-output $stream_id capture volume to $JS8CALL_CAPTURE_VOLUME"
      fi
    fi
  done
}

log "audio router active: monitor_source=$MONITOR_SOURCE interval=${ROUTE_INTERVAL_S}s qsstv_capture_volume=$QSSTV_CAPTURE_VOLUME js8call_capture_volume=$JS8CALL_CAPTURE_VOLUME"
while true; do
  route_streams_once
  sleep "$ROUTE_INTERVAL_S"
done
