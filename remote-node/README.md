# BearWave Remote Node

This repository contains the current BearWave remote-node software and setup material.

The remote node is the low-power Raspberry Pi and ESP32/Heltec field unit. The ESP32 supervises power, trap inputs, GPS/RTC time, battery state, and deep sleep. The Raspberry Pi boots only during a wake cycle, sends BearWave messages through JS8Call, optionally sends an SSTV image after an acknowledged alarm, asks the ESP32 to shut it down, and then the ESP32 removes the Pi/radio power rail.

The reliable part of BearWave remains the JS8Call alarm and ACK path. The SSTV image is an optional best-effort extension. A missed or undecoded image must not be treated as a missed alarm.

## Repository Layout

```text
remote-pi/
  app/                 Current Raspberry Pi Python application
  scripts/             Boot-cycle, ESP32 UART, JS8Call, and SSTV TX scripts
  systemd/             bearwave-cycle.service template
  requirements.txt     Python packages for the Pi virtual environment

esp32-supervisor/
  BearWave_ESP32_Remote_Node_Supervisor.ino
  README.md

docs/
  live-pi-setup-check.md
```

## Live Deployment Model

Tested live path on the remote Pi:

```text
/home/mark/bearwave
```

Main live systemd service:

```text
/etc/systemd/system/bearwave-cycle.service
```

Main service target:

```text
graphical.target
```

The service runs as root because it sets system time, launches GUI JS8Call into the `mark` desktop session, communicates with `/dev/serial0`, and halts the Pi at the end of the wake cycle.

## Wake Cycle Summary

1. ESP32 wakes from timer or event.
2. ESP32 checks the latched 5 V and 12 V rail feedback lines and forces both rails OFF so each cycle starts from a known state.
3. ESP32 refreshes GPS/RTC state, then pulses the 5 V latch on and pulses the 12 V latch on.
4. Raspberry Pi boots into the graphical target.
5. `bearwave-cycle.service` runs `remote-pi/scripts/bearwave_boot_cycle.sh`.
6. The boot script waits for the ESP32 UART at `/dev/serial0`.
7. The boot script waits for the QDX CAT/audio device at `/dev/ttyACM0` before launching JS8Call.
8. The Pi asks the ESP32 for UTC time with `TIME?`.
9. The Pi starts JS8Call from the desktop launcher.
10. The Pi waits for the JS8Call TCP API on `127.0.0.1:2442`, then sets JS8Call to 7.078 MHz.
11. The Python app in `remote-pi/app/` sends heartbeat, trap alarm, low-battery, or pending critical messages.
12. The Pi waits for the control-node ACK.
13. If an alarm is acknowledged and SSTV is enabled, the Pi captures, encodes, and transmits one SSTV image.
14. The Pi sends `EVENT_ACKED,<type>` for delivered critical events.
15. The Pi sends `SHUTDOWN` to the ESP32 and halts Linux.
16. ESP32 waits for Linux shutdown, pulses the 12 V latch off, pulses the 5 V latch off, turns the OLED off, and sleeps until the next wake.

## Current SSTV Extension

The SSTV extension is intentionally thin and isolated from the alarm path:

- `remote-pi/app/sstv_image.py` handles image capture, resize/prepare, SSTV WAV encoding, optional JS8Call stop, and transmit command orchestration.
- `remote-pi/scripts/sstv_transmit_qdx.sh` keys the QDX with `rigctl`, plays the generated WAV with `aplay`, and always attempts to release PTT on exit.
- `remote-pi/scripts/bearwave_boot_cycle.sh` passes SSTV configuration into the Python app through environment variables.

Current live defaults from the Pi:

```bash
BEARWAVE_SSTV_ENABLED=1
BEARWAVE_SSTV_DRY_RUN=0
BEARWAVE_SSTV_REPEAT_COUNT=1
BEARWAVE_SSTV_MODE=Robot36
BEARWAVE_SSTV_TX_GAIN=1.0
BEARWAVE_SSTV_WORK_DIR=/home/mark/bearwave/sstv
```

Image capture:

```bash
rpicam-still -o {image} --width 1280 --height 960 --timeout 1000 --nopreview
```

Encoding:

```bash
/home/mark/bearwave/.venv/bin/python -m pysstv --mode {mode} {prepared} {wav}
```

Transmit:

```bash
/home/mark/bearwave/scripts/sstv_transmit_qdx.sh {wav}
```

The control node receives this image using QSSTV and displays any decoded image as a clickable thumbnail. Image reception is not guaranteed.

## Raspberry Pi Install

Start from Raspberry Pi OS with a desktop environment. The live node uses user `mark`.

Install system packages:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip js8call rpicam-apps ffmpeg alsa-utils libhamlib-utils lxterminal
```

Clone the repository:

```bash
cd /home/mark
git clone https://github.com/butterworthma/BearWave.git BearWave
mkdir -p /home/mark/bearwave
```

Install the active remote Pi files:

```bash
cp -r /home/mark/BearWave/remote-node/remote-pi/app /home/mark/bearwave/
cp -r /home/mark/BearWave/remote-node/remote-pi/scripts /home/mark/bearwave/
mkdir -p /home/mark/bearwave/logs /home/mark/bearwave/state /home/mark/bearwave/sstv
chmod +x /home/mark/bearwave/scripts/*.sh
chmod +x /home/mark/bearwave/scripts/*.py
```

Create the Python virtual environment:

```bash
cd /home/mark/bearwave
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r /home/mark/BearWave/remote-node/remote-pi/requirements.txt
```

Install the systemd service:

```bash
sudo cp /home/mark/BearWave/remote-node/remote-pi/systemd/bearwave-cycle.service /etc/systemd/system/bearwave-cycle.service
sudo systemctl daemon-reload
sudo systemctl enable bearwave-cycle.service
```

Manual start for bench testing:

```bash
sudo systemctl start bearwave-cycle.service
```

Check status and logs:

```bash
systemctl status bearwave-cycle.service --no-pager -l
journalctl -u bearwave-cycle.service -f
tail -f /home/mark/bearwave/logs/boot_cycle.log
```

## JS8Call Setup

Before unattended testing, start JS8Call manually once and confirm:

- Station callsign is configured.
- TCP API and TCP request acceptance are enabled on `127.0.0.1:2442`.
- The QDX/radio audio device is selected.
- CAT/PTT works from JS8Call.
- The saved desktop profile starts correctly from `/usr/share/applications/js8call.desktop`.

The boot script launches JS8Call using the desktop launcher rather than directly invoking `js8call`, because the desktop path reproduced the saved audio/radio profile reliably on the live Pi.

## QDX SSTV Transmit Setup

Confirm QDX audio and CAT/PTT:

```bash
aplay -l
rigctl -m 2052 -r /dev/ttyACM0 -s 4800 T 0
```

Live tested playback device:

```text
plughw:CARD=Transceiver,DEV=0
```

The transmit helper defaults are:

```bash
BEARWAVE_SSTV_RIG_MODEL=2052
BEARWAVE_SSTV_RIG_DEVICE=/dev/ttyACM0
BEARWAVE_SSTV_RIG_SPEED=4800
BEARWAVE_SSTV_AUDIO_DEVICE=plughw:CARD=Transceiver,DEV=0
BEARWAVE_SSTV_PTT_SETTLE_S=0.5
BEARWAVE_SSTV_TX_GAIN=1.0
```

## ESP32 Supervisor

The ESP32 firmware is in:

```text
esp32-supervisor/BearWave_ESP32_Remote_Node_Supervisor.ino
```

It controls:

- 5 V Pi rail through the PCB V2 latch pulse on GPIO 7.
- 12 V QDX/radio/ATU rail through the PCB V2 latch pulse on GPIO 38.
- Active-low 5 V and 12 V rail feedback on GPIO 47 and GPIO 48.
- Trap inputs.
- Battery sensing.
- GPS/RTC time.
- OLED diagnostics.
- Pi UART command interface.
- Deep sleep and GPIO hold.

See `esp32-supervisor/README.md` for the pin map, UART protocol, OLED diagnostics, and sleep/wake sequence.

## Important Design Notes

- The ESP32 is the hardware authority.
- The Pi is the radio/application authority.
- The JS8Call alarm message and ACK are the reliable low-power messaging mechanism.
- SSTV is secondary evidence after an alarm and is best effort.
- Failed critical messages are preserved by the Pi app and retried on later boots.
- Routine heartbeats are not stored for retry.
- The control node must not assume an image will always be received.

## Validation Checklist

On the remote Pi:

```bash
test -x /home/mark/bearwave/scripts/bearwave_boot_cycle.sh
test -x /home/mark/bearwave/scripts/sstv_transmit_qdx.sh
/home/mark/bearwave/.venv/bin/python -m py_compile /home/mark/bearwave/app/*.py
/home/mark/bearwave/.venv/bin/python - <<'PY'
import serial
import PIL
import pysstv
print("remote Python dependencies OK")
PY
command -v rpicam-still
command -v aplay
command -v ffmpeg
command -v rigctl
command -v js8call
```

Live check on 2026-07-26 found:

- `rpicam-still` present.
- `aplay` present.
- `ffmpeg` present.
- `js8call` present.
- Python modules `serial`, `PIL`, and `pysstv` present.
- QDX playback device visible as `CARD=Transceiver`.
- `convert` was not present, which is acceptable because the current SSTV path uses Pillow rather than ImageMagick.

## Legacy Note

This repository previously contained a generic headless JS8Call/noVNC setup script. The live BearWave remote node now uses a different architecture: graphical JS8Call launched by the boot-cycle service, ESP32-supervised power, and a Pi app under `/home/mark/bearwave/app`. The old noVNC installer has therefore been removed from the active setup path.
