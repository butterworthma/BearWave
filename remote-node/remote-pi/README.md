# Remote Pi Software

This folder contains the Raspberry Pi side of the BearWave remote node.

`app/` is the current Python application copied from the live remote Pi.

`scripts/` contains the boot-cycle and integration scripts:

- `bearwave_boot_cycle.sh` is launched by systemd at boot.
- `esp32_set_time.py` reads `TIME?` from the ESP32 and sets Linux UTC time.
- `js8_prepare.py` configures JS8Call over its TCP API.
- `esp32_shutdown_request.py` sends the fallback `SHUTDOWN` command.
- `sstv_transmit_qdx.sh` keys the QDX and plays the encoded SSTV WAV.

`systemd/` contains the service template for `/etc/systemd/system/bearwave-cycle.service`.

Install the Python dependencies into `/home/mark/bearwave/.venv`:

```bash
pip install -r remote-pi/requirements.txt
```

The SSTV path uses `Pillow` and `PySSTV`; ImageMagick `convert` is not required.
