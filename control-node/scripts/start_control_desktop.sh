#!/usr/bin/env bash
set -u

BASE_DIR="${BEARWAVE_CONTROL_DIR:-/home/mark/control-node}"
LOG_FILE="${BEARWAVE_DESKTOP_START_LOG:-${BASE_DIR}/logs/desktop-start.log}"
DASHBOARD_URL="${BEARWAVE_DASHBOARD_URL:-http://127.0.0.1:3000/}"

# These defaults match the normal Raspberry Pi desktop session for user mark.
# They allow the script to run from autostart/systemd while still launching GUI
# applications onto the physical 7 inch display.
DISPLAY="${DISPLAY:-:0}"
XAUTHORITY="${XAUTHORITY:-/home/mark/.Xauthority}"
XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"
PULSE_RUNTIME_PATH="${PULSE_RUNTIME_PATH:-/run/user/1000/pulse}"
START_KIOSK="${BEARWAVE_START_KIOSK:-1}"

export DISPLAY XAUTHORITY XDG_RUNTIME_DIR PULSE_RUNTIME_PATH
mkdir -p "$(dirname "$LOG_FILE")"

log() {
  printf '%s %s\n' "$(date -Is)" "$*" >> "$LOG_FILE"
}

display_is_ready() {
  if command -v xdpyinfo >/dev/null 2>&1; then
    xdpyinfo -display "$DISPLAY" >/dev/null 2>&1
    return $?
  fi

  if command -v xset >/dev/null 2>&1; then
    xset q >/dev/null 2>&1
    return $?
  fi

  [ -S "/tmp/.X11-unix/X${DISPLAY#:}" ]
}

wait_for_display() {
  local i
  for i in $(seq 1 30); do
    if display_is_ready; then
      log "X display ready on $DISPLAY"
      return 0
    fi
    sleep 2
  done
  log "warning: X display $DISPLAY not ready; continuing anyway"
  return 0
}

wait_for_dashboard() {
  local i
  for i in $(seq 1 60); do
    if curl -fsS --max-time 2 "$DASHBOARD_URL" >/dev/null 2>&1; then
      log "dashboard ready at $DASHBOARD_URL"
      return 0
    fi
    sleep 2
  done
  log "warning: dashboard did not answer at $DASHBOARD_URL"
  return 1
}

start_once() {
  local label="$1"
  local pattern="$2"
  shift 2

  if pgrep -u mark -f "$pattern" >/dev/null 2>&1; then
    log "$label already running"
    return 0
  fi

  # Use nohup because this script may be started by the desktop session and
  # should not take SparkSDR/JS8Call down if the launcher exits.
  log "starting $label: $*"
  nohup "$@" >> "$LOG_FILE" 2>&1 &
  sleep 3
}

start_router_once() {
  if pgrep -u mark -f '/home/mark/control-node/scripts/start_qsstv_rx.sh' >/dev/null 2>&1; then
    log "QSSTV audio router already running"
    return 0
  fi

  log "starting QSSTV audio router"
  nohup /home/mark/control-node/scripts/start_qsstv_rx.sh >> "$LOG_FILE" 2>&1 &
  sleep 3
}

launch_kiosk() {
  if [ "$START_KIOSK" != "1" ]; then
    log "kiosk launch disabled by BEARWAVE_START_KIOSK=$START_KIOSK"
    return 0
  fi

  if pgrep -u mark -f 'chromium.*127\.0\.0\.1:3000|chromium.*192\.168\.1\.183:3000' >/dev/null 2>&1; then
    log "dashboard Chromium already running"
    return 0
  fi

  if command -v xset >/dev/null 2>&1; then
    # The control-node display is intended to be permanently visible during
    # monitoring, so disable normal screen blanking and DPMS power saving.
    xset s off >/dev/null 2>&1 || true
    xset -dpms >/dev/null 2>&1 || true
    xset s noblank >/dev/null 2>&1 || true
  fi

  local chromium
  chromium="$(command -v chromium-browser || command -v chromium || true)"
  if [ -z "$chromium" ]; then
    log "error: Chromium not found"
    return 1
  fi

  log "starting dashboard kiosk: $DASHBOARD_URL"
  nohup "$chromium" \
    --kiosk \
    --password-store=basic \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --check-for-update-interval=31536000 \
    --autoplay-policy=no-user-gesture-required \
    "$DASHBOARD_URL" >> "$LOG_FILE" 2>&1 &
}

log "BearWave desktop startup begin"
wait_for_display
start_once "SparkSDR" 'SparkSDR' /usr/local/bin/SparkSDR Last_Session
sleep 8
start_once "JS8Call" 'js8call' /usr/bin/js8call
sleep 6
start_router_once
wait_for_dashboard || true
launch_kiosk
log "BearWave desktop startup complete"
