# BearWave Control Node

BearWave Control Node is the Raspberry Pi side of the BearWave remote trap monitor. It runs beside SparkSDR, JS8Call, and QSSTV on the control-node Pi and provides a permanent 7 inch dashboard for node status, alarms, received images, event history, and logs.

The reliable part of the system is the low-power JS8Call alarm/heartbeat/ACK path. SSTV image reception is an optional best-effort extension: when the remote node sends an image after an alarm, QSSTV decodes any valid picture it can hear and the dashboard links the latest image to the most recent alarming node.

## Repository Contents

- `src/index.js` starts the Express/Socket.IO dashboard, connects to JS8Call, parses BearWave messages, schedules delayed ACKs, and starts the SSTV image watcher.
- `src/protocol/` parses and encodes compact BearWave protocol payloads.
- `src/js8/` manages the JS8Call TCP API connection, message assembly, and ACK scheduling.
- `src/state/` stores node status, alarm state, heartbeat freshness, telemetry, and linked SSTV thumbnails.
- `src/images/imageStore.js` watches the SSTV inbox and publishes new images to the dashboard.
- `src/ui/public/` contains the touch-screen dashboard.
- `scripts/start_control_desktop.sh` starts SparkSDR, JS8Call, the QSSTV audio router, and Chromium kiosk mode.
- `scripts/start_qsstv_rx.sh` starts QSSTV and repeatedly routes the SparkSDR monitor audio into QSSTV and JS8Call at controlled capture levels.
- `scripts/sstv_rx_loop.sh` is an optional non-GUI recording/decoder loop used during bench testing.
- `scripts/sstv_decode_file.py` decodes a recorded SSTV WAV file using the local SSTV Python environment.
- `systemd/bearwave-sstv-rx.service` is an optional service file for the headless recording/decoder loop.

## Hardware Assumptions

The tested control node used:

- Raspberry Pi with desktop environment and 7 inch display.
- Hermes-Lite SDR connected to the control Pi network.
- USB audio route from SparkSDR monitor audio.
- SparkSDR for SDR receive/control.
- JS8Call for BearWave alarm and heartbeat messages.
- QSSTV for receive-only SSTV image decode.

The exact SDR, audio device names, callsigns, and frequencies are site-specific. Treat the provided defaults as the tested bench configuration, not universal settings.

## Install System Packages

Start from Raspberry Pi OS with a graphical desktop.

```bash
sudo apt update
sudo apt install -y git curl nodejs npm chromium-browser x11-utils pulseaudio-utils ffmpeg python3 python3-venv qsstv js8call
```

Install SparkSDR using the package or installer appropriate for the control-node Pi. Confirm it can connect to the Hermes-Lite before configuring BearWave.

## Clone And Install

```bash
cd /home/mark
git clone https://github.com/butterworthma/ControlNode.git control-node
cd /home/mark/control-node
npm install
mkdir -p logs sstv-images/inbox sstv-audio
cp .env.example .env
```

Edit `.env` for your station:

```bash
nano .env
```

At minimum, set:

- `SIMULATE_JS8=0` for live JS8Call operation.
- `JS8CALL_HOST=127.0.0.1`
- `JS8CALL_PORT=2442`
- `BEARWAVE_REMOTE_CALLSIGN` and per-node callsign overrides if required.
- `BEARWAVE_SSTV_IMAGE_DIR=/home/mark/control-node/sstv-images/inbox`

Do not commit `.env`; it may contain local station details.

## JS8Call Configuration

In JS8Call:

1. Configure the station callsign and radio/audio settings as normal.
2. Enable the TCP API server.
3. Use TCP port `2442` unless you also change `JS8CALL_PORT`.
4. Confirm JS8Call can decode BearWave messages from the remote node.
5. Confirm JS8Call can transmit a directed ACK from the control station.

The control-node software expects BearWave payloads in this form:

```text
BW1|<nodeId>|<type>|<messageId>|<flags>|<data>
```

Example:

```text
BW1|ND01|ALARM|7K|0|B72
```

The ACK is compact and node-specific:

```text
A|ND01|7K
```

## SparkSDR And Audio Routing

SparkSDR should provide the received audio that both JS8Call and QSSTV listen to. In the tested setup, the monitor source was:

```text
alsa_output.usb-C-Media_Electronics_Inc._USB_Audio_Device-00.analog-stereo.monitor
```

Check your own PulseAudio/PipeWire source names with:

```bash
pactl list short sources
pactl list source-outputs
```

If your source name differs, edit `scripts/start_qsstv_rx.sh` and update `MONITOR_SOURCE`, or export the correct value before starting the script.

The tested capture volume after tuning was:

```bash
BEARWAVE_QSSTV_CAPTURE_VOLUME=60%
BEARWAVE_JS8CALL_CAPTURE_VOLUME=60%
```

These values reduce overloading and improve reliable JS8Call decode while keeping SSTV decode usable.

## QSSTV Configuration

QSSTV is used as a receive-only image decoder.

1. Start QSSTV once from the desktop.
2. Configure the input audio device to the SparkSDR monitor audio or the routed PulseAudio source.
3. Configure receive/save output to:

```text
/home/mark/control-node/sstv-images/inbox
```

4. Leave QSSTV listening. It should only save images when it decodes a valid SSTV transmission.

The BearWave dashboard watches this inbox. When a new image appears, it displays a clickable thumbnail and tries to associate it with the most recent alarm within the configured association window.

## Run Manually

Simulator mode is useful before JS8Call and radio software are ready:

```bash
cd /home/mark/control-node
npm run simulate
```

Live mode:

```bash
cd /home/mark/control-node
npm start
```

Open the dashboard:

```text
http://127.0.0.1:3000/
```

Useful diagnostic endpoints:

```text
http://127.0.0.1:3000/api/nodes
http://127.0.0.1:3000/api/events
http://127.0.0.1:3000/api/images
```

## Start The Desktop Stack On Boot

The intended control-node boot behaviour is:

1. Start SparkSDR.
2. Start JS8Call.
3. Start QSSTV and keep the SparkSDR monitor audio routed into QSSTV and JS8Call.
4. Start the BearWave web application.
5. Open Chromium in kiosk mode on the 7 inch dashboard.

One practical setup is to run the Node application as a user service and run the desktop launcher from the graphical user session.

Create a user service for the dashboard:

```bash
mkdir -p ~/.config/systemd/user
nano ~/.config/systemd/user/bearwave-control-node.service
```

Paste:

```ini
[Unit]
Description=BearWave control-node dashboard
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/mark/control-node
EnvironmentFile=/home/mark/control-node/.env
ExecStart=/usr/bin/npm start
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

Enable it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now bearwave-control-node.service
loginctl enable-linger mark
```

Then add the desktop launcher to the Pi desktop autostart:

```bash
mkdir -p ~/.config/autostart
nano ~/.config/autostart/bearwave-control-desktop.desktop
```

Paste:

```ini
[Desktop Entry]
Type=Application
Name=BearWave Control Desktop
Exec=/home/mark/control-node/scripts/start_control_desktop.sh
Terminal=false
X-GNOME-Autostart-enabled=true
```

Make scripts executable:

```bash
chmod +x /home/mark/control-node/scripts/*.sh
```

Reboot and confirm the dashboard appears automatically:

```bash
sudo reboot
```

## Optional SSTV Recording/Decode Loop

The primary live image path is QSSTV. The optional loop in `scripts/sstv_rx_loop.sh` records overlapping audio chunks with `ffmpeg` and tries to decode them using `scripts/sstv_decode_file.py`.

Set up the Python environment:

```bash
cd /home/mark/control-node
python3 -m venv .venv-sstv
. .venv-sstv/bin/activate
pip install --upgrade pip
pip install PySSTV Pillow
```

Install the service if required:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/bearwave-sstv-rx.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now bearwave-sstv-rx.service
```

For the current control-node design, QSSTV is usually the better permanent receiver because it is visual, interactive, and only saves valid decodes.

## Logs

Application events are written to:

```text
/home/mark/control-node/logs/events.log
```

Desktop startup and audio routing logs are written to:

```text
/home/mark/control-node/logs/desktop-start.log
/home/mark/control-node/logs/qsstv-rx.log
```

The dashboard `Logs` tab displays the control-node event log for quick checking when a monitor is attached.

## Validation Checklist

1. Start SparkSDR and confirm the Hermes-Lite waterfall and audio are present.
2. Start JS8Call and confirm it decodes normal JS8 traffic.
3. Run `npm run simulate` and confirm the dashboard loads at `http://127.0.0.1:3000/`.
4. Run `npm start` and confirm the log reports `Connected to JS8Call`.
5. Trigger or simulate a BearWave heartbeat and confirm the node appears on the dashboard.
6. Trigger a BearWave alarm and confirm the dashboard marks the node as alarmed.
7. Confirm the delayed ACK is scheduled and transmitted by JS8Call.
8. Leave QSSTV receiving and send a remote-node SSTV image.
9. Confirm QSSTV saves the decoded image into `sstv-images/inbox`.
10. Confirm the dashboard shows a clickable SSTV thumbnail for the node.

## Troubleshooting

- Dashboard unreachable: confirm `npm start` is running and `PORT` is set to `3000`.
- No JS8 messages: confirm JS8Call TCP API is enabled and `JS8CALL_HOST`/`JS8CALL_PORT` match.
- ACK not transmitted: confirm JS8Call is connected to the radio, PTT works from JS8Call, and the remote callsign mapping is correct.
- QSSTV does not decode: confirm QSSTV input is the receive audio path, not an output/speaker device.
- Audio sounds distorted: reduce `BEARWAVE_QSSTV_CAPTURE_VOLUME` and `BEARWAVE_JS8CALL_CAPTURE_VOLUME`.
- No SSTV thumbnails: confirm decoded image files are being saved into `sstv-images/inbox` and that `BEARWAVE_SSTV_IMAGE_DIR` matches that folder.
- Kiosk does not open: check `logs/desktop-start.log`, confirm the Pi desktop is running, and confirm Chromium is installed.

## Security And Repository Hygiene

This repository intentionally excludes:

- `node_modules/`
- `.env`
- `logs/`
- SSTV audio recordings and received images
- Python virtual environments

Generated dependencies should be recreated with `npm install` and Python virtual environments should be recreated from the instructions above.
