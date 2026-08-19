#!/usr/bin/env bash
set -u
set -o pipefail

# -------------------------------------------------------------------
# BearWave remote-node boot cycle.
# -------------------------------------------------------------------
#
# Runs at Raspberry Pi boot under systemd.
#
# Sequence:
#   1. Wait for ESP32 UART.
#   2. Set Pi system time from ESP32 TIME?.
#   3. Launch JS8Call using the desktop launcher.
#   4. Wait for JS8Call to initialise.
#   5. Set JS8Call dial frequency to 7.078 MHz.
#   6. Run BearWave remote-node Python app.
#   7. Send fallback SHUTDOWN to ESP32 if required.
#   8. Halt Linux.
#
# Important:
#   JS8Call is launched via /usr/share/applications/js8call.desktop
#   because the desktop launcher loads the correct saved sound-card/profile
#   behaviour on this Pi.
# -------------------------------------------------------------------

LOG_DIR="/home/mark/bearwave/logs"
LOG_FILE="${LOG_DIR}/boot_cycle.log"

BEARWAVE_DIR="/home/mark/bearwave"
VENV_PYTHON="${BEARWAVE_DIR}/.venv/bin/python"

ESP32_PORT="/dev/serial0"
ESP32_BAUD="115200"

QDX_CAT_PORT="${BEARWAVE_QDX_CAT_PORT:-/dev/ttyACM0}"

JS8_HOST="127.0.0.1"
JS8_PORT="2442"
JS8_DIAL_HZ="7078000"
# JS8Call starts noticeably more slowly on the Raspberry Pi Zero 2 W than on
# the Pi 4 development node. Give the GUI and TCP API enough time to initialise
# before js8_prepare.py begins probing 127.0.0.1:2442.
JS8_START_DELAY_S="45"

SSTV_ENABLED="${BEARWAVE_SSTV_ENABLED:-1}"
SSTV_DRY_RUN="${BEARWAVE_SSTV_DRY_RUN:-0}"
SSTV_REPEAT_COUNT="${BEARWAVE_SSTV_REPEAT_COUNT:-1}"
SSTV_MODE="${BEARWAVE_SSTV_MODE:-ScottieS1}"
SSTV_WORK_DIR="${BEARWAVE_SSTV_WORK_DIR:-/home/mark/bearwave/sstv}"
SSTV_PILLOW_PYTHON="${BEARWAVE_SSTV_PILLOW_PYTHON:-/usr/bin/python3}"
DIAGNOSTIC_WINDOW_ENABLED="${BEARWAVE_DIAGNOSTIC_WINDOW_ENABLED:-1}"
JS8_HEADLESS_DISPLAY="${BEARWAVE_JS8_HEADLESS_DISPLAY:-:99}"

# The SSTV commands are template strings consumed by app/sstv_image.py. The
# placeholders {image}, {prepared}, {wav}, and {mode} are filled in for each
# alarm image using filenames that include node ID, message ID, and UTC stamp.
if [ -n "${BEARWAVE_SSTV_CAPTURE_COMMAND:-}" ]; then
  SSTV_CAPTURE_COMMAND="${BEARWAVE_SSTV_CAPTURE_COMMAND}"
else
  SSTV_CAPTURE_COMMAND='rpicam-still -o {image} --width 1280 --height 960 --timeout 1000 --nopreview'
fi

if [ -n "${BEARWAVE_SSTV_ENCODE_COMMAND:-}" ]; then
  SSTV_ENCODE_COMMAND="${BEARWAVE_SSTV_ENCODE_COMMAND}"
else
  SSTV_ENCODE_COMMAND='/home/mark/bearwave/.venv/bin/python -m pysstv --mode {mode} {prepared} {wav}'
fi

if [ -n "${BEARWAVE_SSTV_TRANSMIT_COMMAND:-}" ]; then
  SSTV_TRANSMIT_COMMAND="${BEARWAVE_SSTV_TRANSMIT_COMMAND}"
else
  SSTV_TRANSMIT_COMMAND='/home/mark/bearwave/scripts/sstv_transmit_qdx.sh {wav}'
fi

if [ -n "${BEARWAVE_SSTV_STOP_JS8CALL_COMMAND:-}" ]; then
  SSTV_STOP_JS8CALL_COMMAND="${BEARWAVE_SSTV_STOP_JS8CALL_COMMAND}"
else
  SSTV_STOP_JS8CALL_COMMAND='pkill -x js8call'
fi

PI_USER="mark"
PI_UID="$(id -u "${PI_USER}")"

JS8_DESKTOP_FILE="/usr/share/applications/js8call.desktop"

mkdir -p "${LOG_DIR}"

exec >> "${LOG_FILE}" 2>&1

display_is_ready() {
  local display_name="${1:-:0}"

  if command -v xdpyinfo >/dev/null 2>&1; then
    DISPLAY="${display_name}" xdpyinfo >/dev/null 2>&1
    return $?
  fi

  [ -S "/tmp/.X11-unix/X${display_name#:}" ]
}

start_headless_display() {
  if display_is_ready "${JS8_HEADLESS_DISPLAY}"; then
    echo "[BOOT] Headless JS8 display already available on ${JS8_HEADLESS_DISPLAY}"
    return 0
  fi

  if ! command -v Xvfb >/dev/null 2>&1; then
    echo "[BOOT] ERROR: No physical display found and Xvfb is not installed"
    echo "[BOOT] Install with: sudo apt install -y xvfb"
    return 1
  fi

  echo "[BOOT] Starting headless Xvfb display on ${JS8_HEADLESS_DISPLAY}"
  runuser -u "${PI_USER}" -- env \
    XDG_RUNTIME_DIR="/run/user/${PI_UID}" \
    Xvfb "${JS8_HEADLESS_DISPLAY}" -screen 0 1024x768x24 -nolisten tcp &

  for i in $(seq 1 15); do
    if display_is_ready "${JS8_HEADLESS_DISPLAY}"; then
      echo "[BOOT] Headless JS8 display ready on ${JS8_HEADLESS_DISPLAY}"
      return 0
    fi
    sleep 1
  done

  echo "[BOOT] ERROR: Headless JS8 display did not become ready"
  return 1
}

prepare_js8_display() {
  if display_is_ready ":0"; then
    JS8_DISPLAY=":0"
    JS8_XAUTHORITY="/home/${PI_USER}/.Xauthority"
    JS8_LAUNCH_MODE="desktop"
    echo "[BOOT] Physical display found; JS8Call will use DISPLAY=${JS8_DISPLAY}"
    return 0
  fi

  echo "[BOOT] No physical DISPLAY=:0 found; using headless JS8Call display"
  if ! start_headless_display; then
    return 1
  fi

  JS8_DISPLAY="${JS8_HEADLESS_DISPLAY}"
  JS8_XAUTHORITY=""
  JS8_LAUNCH_MODE="headless"
  return 0
}

if [ "${DIAGNOSTIC_WINDOW_ENABLED}" = "1" ]; then
  if pgrep -u "${PI_USER}" -f "tail -n +1 -F ${LOG_FILE}" >/dev/null 2>&1; then
    echo "[BOOT] Diagnostic log window already running"
  elif display_is_ready ":0" && command -v lxterminal >/dev/null 2>&1; then
    echo "[BOOT] Launching diagnostic log window"
    runuser -u "${PI_USER}" -- env \
      DISPLAY=:0 \
      XAUTHORITY="/home/${PI_USER}/.Xauthority" \
      XDG_RUNTIME_DIR="/run/user/${PI_UID}" \
      lxterminal \
        --title="BearWave Diagnostics" \
        --geometry=120x34 \
        -e bash -lc "echo 'BearWave diagnostics - tailing ${LOG_FILE}'; echo; tail -n +1 -F '${LOG_FILE}'" &
  elif ! display_is_ready ":0"; then
    echo "[BOOT] Diagnostic log window skipped because no physical display is available"
  else
    echo "[BOOT] Diagnostic log window requested but lxterminal was not found"
  fi
fi

echo
echo "============================================================"
echo "[BOOT] BearWave boot cycle started at $(date -u --iso-8601=seconds)"
echo "============================================================"

export BEARWAVE_SERIAL_PORT="${ESP32_PORT}"
export BEARWAVE_SERIAL_BAUDRATE="${ESP32_BAUD}"
export BEARWAVE_JS8_HOST="${JS8_HOST}"
export BEARWAVE_JS8_PORT="${JS8_PORT}"
export BEARWAVE_NODE_ID="${BEARWAVE_NODE_ID:-ND01}"
export BEARWAVE_CONTROL_CALLSIGN="${BEARWAVE_CONTROL_CALLSIGN:-G7PRW}"

echo "[BOOT] Node ID: ${BEARWAVE_NODE_ID}"
echo "[BOOT] Control callsign: ${BEARWAVE_CONTROL_CALLSIGN}"
echo "[BOOT] ESP32 UART: ${ESP32_PORT} @ ${ESP32_BAUD}"
echo "[BOOT] QDX CAT port: ${QDX_CAT_PORT}"
echo "[BOOT] JS8 API: ${JS8_HOST}:${JS8_PORT}"
echo "[BOOT] JS8 dial frequency: ${JS8_DIAL_HZ} Hz"
echo "[BOOT] JS8 desktop launcher: ${JS8_DESKTOP_FILE}"
echo "[BOOT] SSTV enabled: ${SSTV_ENABLED}"
echo "[BOOT] SSTV dry run: ${SSTV_DRY_RUN}"
echo "[BOOT] SSTV mode: ${SSTV_MODE}"
echo "[BOOT] SSTV repeat count: ${SSTV_REPEAT_COUNT}"
echo "[BOOT] SSTV transmit command: ${SSTV_TRANSMIT_COMMAND}"
echo "[BOOT] Diagnostic window enabled: ${DIAGNOSTIC_WINDOW_ENABLED}"
echo "[BOOT] Headless JS8 display: ${JS8_HEADLESS_DISPLAY}"

# -------------------------------------------------------------------
# Step 1: wait for ESP32 UART
# -------------------------------------------------------------------

echo "[BOOT] Waiting for ${ESP32_PORT}"

for i in $(seq 1 30); do
  if [ -e "${ESP32_PORT}" ]; then
    echo "[BOOT] Found ${ESP32_PORT}"
    break
  fi

  echo "[BOOT] ${ESP32_PORT} not present yet, attempt ${i}/30"
  sleep 1
done

if [ ! -e "${ESP32_PORT}" ]; then
  echo "[BOOT] ERROR: ${ESP32_PORT} did not appear"
  shutdown -h now
  exit 1
fi

# -------------------------------------------------------------------
# Step 1b: wait for QDX USB CAT/audio
# -------------------------------------------------------------------
#
# JS8Call is configured to use the QDX CAT interface at /dev/ttyACM0. If
# JS8Call starts before the USB ACM device exists, Hamlib can fail to open the
# rig and the JS8Call TCP API may never become available to the BearWave app.
# -------------------------------------------------------------------

echo "[BOOT] Waiting for QDX CAT port ${QDX_CAT_PORT}"

for i in $(seq 1 30); do
  if [ -e "${QDX_CAT_PORT}" ]; then
    echo "[BOOT] Found QDX CAT port ${QDX_CAT_PORT}"
    break
  fi

  echo "[BOOT] ${QDX_CAT_PORT} not present yet, attempt ${i}/30"
  sleep 1
done

if [ ! -e "${QDX_CAT_PORT}" ]; then
  echo "[BOOT] ERROR: QDX CAT port ${QDX_CAT_PORT} did not appear"

  "${VENV_PYTHON}" "${BEARWAVE_DIR}/scripts/esp32_shutdown_request.py" \
    --port "${ESP32_PORT}" \
    --baud "${ESP32_BAUD}" || true

  shutdown -h now
  exit 1
fi

# -------------------------------------------------------------------
# Step 2: set Linux system time from ESP32
# -------------------------------------------------------------------

echo "[BOOT] Setting Pi system time from ESP32"

"${VENV_PYTHON}" "${BEARWAVE_DIR}/scripts/esp32_set_time.py" \
  --port "${ESP32_PORT}" \
  --baud "${ESP32_BAUD}"

TIME_RC=$?

if [ "${TIME_RC}" -ne 0 ]; then
  echo "[BOOT] WARNING: Failed to set time from ESP32"
  echo "[BOOT] Continuing for bench test, but JS8 timing may be unreliable"
else
  echo "[BOOT] Pi time after ESP32 sync: $(date -u --iso-8601=seconds)"
fi

# -------------------------------------------------------------------
# Step 3: launch JS8Call using the desktop launcher
# -------------------------------------------------------------------
#
# The previous script launched JS8Call directly with:
#
#   js8call
#
# That can bypass some of the behaviour seen when JS8Call is started from the
# Start Menu. The Start Menu icon points to:
#
#   /usr/share/applications/js8call.desktop
#
# Therefore this script launches that desktop entry using gio.
#
# Required graphical environment variables:
#
#   DISPLAY=:0
#   XAUTHORITY=/home/mark/.Xauthority
#   XDG_RUNTIME_DIR=/run/user/<uid>
#
# These allow a root-started systemd service to launch the GUI application in
# the logged-in user's desktop session.
# -------------------------------------------------------------------

echo "[BOOT] Launching JS8Call from desktop launcher"

if ! prepare_js8_display; then
  "${VENV_PYTHON}" "${BEARWAVE_DIR}/scripts/esp32_shutdown_request.py" \
    --port "${ESP32_PORT}" \
    --baud "${ESP32_BAUD}" || true

  shutdown -h now
  exit 1
fi

if [ "${JS8_LAUNCH_MODE}" = "desktop" ] && [ ! -f "${JS8_DESKTOP_FILE}" ]; then
  echo "[BOOT] ERROR: JS8Call desktop file not found: ${JS8_DESKTOP_FILE}"

  "${VENV_PYTHON}" "${BEARWAVE_DIR}/scripts/esp32_shutdown_request.py" \
    --port "${ESP32_PORT}" \
    --baud "${ESP32_BAUD}" || true

  shutdown -h now
  exit 1
fi

if ! pgrep -u "${PI_USER}" -x js8call >/dev/null 2>&1; then
  if [ "${JS8_LAUNCH_MODE}" = "desktop" ]; then
    echo "[BOOT] JS8Call is not running; launching via desktop profile on ${JS8_DISPLAY}"

    runuser -u "${PI_USER}" -- env \
      DISPLAY="${JS8_DISPLAY}" \
      XAUTHORITY="${JS8_XAUTHORITY}" \
      XDG_RUNTIME_DIR="/run/user/${PI_UID}" \
      gio launch "${JS8_DESKTOP_FILE}" &

    JS8_LAUNCH_RC=$?

    if [ "${JS8_LAUNCH_RC}" -ne 0 ]; then
      echo "[BOOT] WARNING: gio launch returned ${JS8_LAUNCH_RC}"
      echo "[BOOT] Trying gtk-launch fallback"

      runuser -u "${PI_USER}" -- env \
        DISPLAY="${JS8_DISPLAY}" \
        XAUTHORITY="${JS8_XAUTHORITY}" \
        XDG_RUNTIME_DIR="/run/user/${PI_UID}" \
        gtk-launch js8call &

      GTK_LAUNCH_RC=$?

      if [ "${GTK_LAUNCH_RC}" -ne 0 ]; then
        echo "[BOOT] ERROR: gtk-launch also failed with ${GTK_LAUNCH_RC}"

        "${VENV_PYTHON}" "${BEARWAVE_DIR}/scripts/esp32_shutdown_request.py" \
          --port "${ESP32_PORT}" \
          --baud "${ESP32_BAUD}" || true

        shutdown -h now
        exit 1
      fi
    fi
  else
    echo "[BOOT] JS8Call is not running; launching directly on headless ${JS8_DISPLAY}"

    runuser -u "${PI_USER}" -- env \
      DISPLAY="${JS8_DISPLAY}" \
      XDG_RUNTIME_DIR="/run/user/${PI_UID}" \
      /usr/bin/js8call &

    JS8_LAUNCH_RC=$?

    if [ "${JS8_LAUNCH_RC}" -ne 0 ]; then
      echo "[BOOT] ERROR: headless JS8Call launch failed with ${JS8_LAUNCH_RC}"

      "${VENV_PYTHON}" "${BEARWAVE_DIR}/scripts/esp32_shutdown_request.py" \
        --port "${ESP32_PORT}" \
        --baud "${ESP32_BAUD}" || true

      shutdown -h now
      exit 1
    fi
  fi
else
  echo "[BOOT] JS8Call already running"
fi

echo "[BOOT] Waiting ${JS8_START_DELAY_S} seconds for JS8Call startup"
sleep "${JS8_START_DELAY_S}"

# -------------------------------------------------------------------
# Step 4: set and verify JS8Call frequency
# -------------------------------------------------------------------

echo "[BOOT] Preparing JS8Call API and setting frequency"

"${VENV_PYTHON}" "${BEARWAVE_DIR}/scripts/js8_prepare.py" \
  --host "${JS8_HOST}" \
  --port "${JS8_PORT}" \
  --dial-hz "${JS8_DIAL_HZ}" \
  --api-timeout 60 \
  --verify-timeout 20

JS8_RC=$?

if [ "${JS8_RC}" -ne 0 ]; then
  echo "[BOOT] ERROR: JS8Call preparation failed"

  "${VENV_PYTHON}" "${BEARWAVE_DIR}/scripts/esp32_shutdown_request.py" \
    --port "${ESP32_PORT}" \
    --baud "${ESP32_BAUD}" || true

  shutdown -h now
  exit 1
fi

# -------------------------------------------------------------------
# Step 5: run BearWave remote-node application
# -------------------------------------------------------------------

echo "[BOOT] Starting BearWave remote-node application"

cd "${BEARWAVE_DIR}" || exit 1

# Pass all operational settings explicitly into the unprivileged application
# process. This keeps the systemd/root wrapper in control of hardware paths
# while the Python app remains portable and testable.
runuser -u "${PI_USER}" -- env \
  BEARWAVE_SERIAL_PORT="${ESP32_PORT}" \
  BEARWAVE_SERIAL_BAUDRATE="${ESP32_BAUD}" \
  BEARWAVE_JS8_HOST="${JS8_HOST}" \
  BEARWAVE_JS8_PORT="${JS8_PORT}" \
  BEARWAVE_NODE_ID="${BEARWAVE_NODE_ID}" \
  BEARWAVE_CONTROL_CALLSIGN="${BEARWAVE_CONTROL_CALLSIGN}" \
  BEARWAVE_SSTV_ENABLED="${SSTV_ENABLED}" \
  BEARWAVE_SSTV_DRY_RUN="${SSTV_DRY_RUN}" \
  BEARWAVE_SSTV_REPEAT_COUNT="${SSTV_REPEAT_COUNT}" \
  BEARWAVE_SSTV_MODE="${SSTV_MODE}" \
  BEARWAVE_SSTV_WORK_DIR="${SSTV_WORK_DIR}" \
  BEARWAVE_SSTV_PILLOW_PYTHON="${SSTV_PILLOW_PYTHON}" \
  BEARWAVE_SSTV_CAPTURE_COMMAND="${SSTV_CAPTURE_COMMAND}" \
  BEARWAVE_SSTV_ENCODE_COMMAND="${SSTV_ENCODE_COMMAND}" \
  BEARWAVE_SSTV_TRANSMIT_COMMAND="${SSTV_TRANSMIT_COMMAND}" \
  BEARWAVE_SSTV_STOP_JS8CALL_COMMAND="${SSTV_STOP_JS8CALL_COMMAND}" \
  "${VENV_PYTHON}" "${BEARWAVE_DIR}/app/main.py"

APP_RC=$?

echo "[BOOT] BearWave remote-node application exited with code ${APP_RC}"

# -------------------------------------------------------------------
# Step 6: fallback ESP32 shutdown request
# -------------------------------------------------------------------
#
# The BearWave app should normally send SHUTDOWN to the ESP32 itself.
# This fallback is kept so that the ESP32 still receives SHUTDOWN if the
# application exits early or does not reach its normal shutdown path.
# -------------------------------------------------------------------

echo "[BOOT] Sending fallback SHUTDOWN request to ESP32"

if ! "${VENV_PYTHON}" "${BEARWAVE_DIR}/scripts/esp32_shutdown_request.py" \
  --port "${ESP32_PORT}" \
  --baud "${ESP32_BAUD}"; then
  echo "[BOOT] ERROR: ESP32 did not acknowledge fallback SHUTDOWN request"
  echo "[BOOT] Leaving Raspberry Pi running so the fault can be inspected"
  exit 20
fi

# -------------------------------------------------------------------
# Step 7: halt Linux
# -------------------------------------------------------------------

echo "[BOOT] Halting Raspberry Pi at $(date -u --iso-8601=seconds)"

sync
shutdown -h now

exit "${APP_RC}"
