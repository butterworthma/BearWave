# Live Remote Pi Setup Check

Checked against remote node `192.168.1.182` on 2026-07-26.

## Live Paths

```text
/home/mark/bearwave
/home/mark/bearwave/app
/home/mark/bearwave/scripts
/home/mark/bearwave/logs
/home/mark/bearwave/state
/home/mark/bearwave/sstv
```

## Systemd

The live service is installed system-wide, not as a user service:

```text
/etc/systemd/system/bearwave-cycle.service
```

It is enabled:

```text
bearwave-cycle.service enabled
```

The service runs:

```text
ExecStart=/home/mark/bearwave/scripts/bearwave_boot_cycle.sh
User=root
WantedBy=graphical.target
```

The service showed `failed` during the check only because it had been manually stopped for editing/testing:

```text
code=killed, signal=TERM
```

That matches the bench-test history and is not treated as a setup mismatch.

## Dependency Check

Live command/module status:

```text
rpicam-still OK
aplay OK
ffmpeg OK
js8call OK
rigctl expected through libhamlib-utils on Debian Trixie
convert missing
serial OK 3.5
PIL OK 12.2.0
pysstv OK
```

`convert` is no longer required because the current SSTV path uses Pillow through `remote-pi/app/sstv_image.py`.

## Audio/Radio Check

`aplay -l` showed the QDX:

```text
card 3: Transceiver [QDX Transceiver], device 0: USB Audio [USB Audio]
```

The SSTV transmit helper therefore defaults to:

```text
plughw:CARD=Transceiver,DEV=0
```

## Live SSTV Configuration

The live `bearwave_boot_cycle.sh` uses:

```bash
SSTV_ENABLED="${BEARWAVE_SSTV_ENABLED:-1}"
SSTV_DRY_RUN="${BEARWAVE_SSTV_DRY_RUN:-0}"
SSTV_REPEAT_COUNT="${BEARWAVE_SSTV_REPEAT_COUNT:-1}"
SSTV_MODE="${BEARWAVE_SSTV_MODE:-Robot36}"
SSTV_WORK_DIR="${BEARWAVE_SSTV_WORK_DIR:-/home/mark/bearwave/sstv}"
SSTV_PILLOW_PYTHON="${BEARWAVE_SSTV_PILLOW_PYTHON:-/usr/bin/python3}"
```

Capture:

```bash
rpicam-still -o {image} --width 1280 --height 960 --timeout 1000 --nopreview
```

Encode:

```bash
/home/mark/bearwave/.venv/bin/python -m pysstv --mode {mode} {prepared} {wav}
```

Transmit:

```bash
/home/mark/bearwave/scripts/sstv_transmit_qdx.sh {wav}
```

## Differences From Old Setup Instructions

The old setup material described a generic headless JS8Call/noVNC Pi. The live BearWave remote node differs:

- It uses `/home/mark/bearwave`, not a generic `pi` user layout.
- It uses ESP32-supervised power and `/dev/serial0`.
- It uses a system-wide `bearwave-cycle.service`.
- It launches JS8Call through the desktop `.desktop` launcher.
- It includes SSTV capture/encode/transmit after acknowledged alarms.
- It uses Pillow/PySSTV rather than ImageMagick `convert`.
- It uses QDX PTT through `rigctl` and WAV playback through `aplay`.

The GitHub README and file layout have been updated to match the live Pi rather than the old noVNC package.
