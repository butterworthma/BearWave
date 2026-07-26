from __future__ import annotations

"""
BearWave SSTV image helper
==========================

This module provides the first thin SSTV extension for the remote node.

It deliberately keeps the image path separate from the existing JS8/BW1 alarm
path. The controller can call this only after a critical alarm has been
acknowledged, so image transfer remains secondary evidence rather than the
primary alarm mechanism.
"""

from dataclasses import dataclass
from pathlib import Path
import logging
import shlex
import subprocess
from datetime import datetime, timezone
from typing import Optional


def utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


SSTV_MODE_SIZES: dict[str, tuple[int, int]] = {
    # PySSTV modes expect specific image dimensions. Preparing to the expected
    # size before encoding avoids relying on implicit resizing inside the
    # encoder and keeps transmitted pictures predictable across modes.
    "Robot36": (320, 240),
    "MartinM1": (320, 256),
    "MartinM2": (320, 256),
    "ScottieS1": (320, 256),
    "ScottieS2": (320, 256),
    "ScottieDX": (320, 256),
    "PD90": (320, 256),
    "PD120": (640, 496),
    "PD160": (512, 400),
    "PD180": (640, 496),
    "PD240": (640, 496),
    "PD290": (800, 616),
}


def sstv_dimensions_for_mode(mode: str, fallback_width: int, fallback_height: int) -> tuple[int, int]:
    return SSTV_MODE_SIZES.get(mode, (fallback_width, fallback_height))


@dataclass(frozen=True)
class SstvImageConfig:
    """
    Runtime configuration for one SSTV image stage.

    The values are passed in from the boot wrapper through environment
    variables. Keeping them in one dataclass makes it easy to tune capture,
    encode, transmit, and dry-run behaviour without changing controller logic.
    """

    enabled: bool = False
    dry_run: bool = True
    work_dir: str = "/home/mark/bearwave/sstv"
    mode: str = "Robot36"
    repeat_count: int = 2
    capture_command: str = "rpicam-still -o {image} --width 1280 --height 960 --timeout 1000"
    prepare_command: str = "__pillow__"
    pillow_python: str = "/usr/bin/python3"
    image_width: int = 320
    image_height: int = 240
    encode_command: str = "python3 -m pysstv --mode {mode} {prepared} {wav}"
    transmit_command: str = "aplay {wav}"
    stop_js8call_command: str = "pkill -x js8call"


@dataclass(frozen=True)
class SstvImageResult:
    """
    Structured result returned to the controller after the image stage.

    The controller logs this result but does not treat image failure as alarm
    failure. That separation is important: JS8 ACK delivery is the reliable
    alarm path, while SSTV is best-effort secondary evidence.
    """

    attempted: bool
    success: bool
    skipped_reason: Optional[str]
    image_path: Optional[str]
    prepared_path: Optional[str]
    wav_path: Optional[str]
    mode: str
    repeat_count: int
    notes: str


class SstvImageTransmitter:
    def __init__(self, config: SstvImageConfig, logger: Optional[logging.Logger] = None) -> None:
        self.config = config
        self.log = logger or logging.getLogger(self.__class__.__name__)

    def transmit_alarm_image(self, *, node_id: str, message_id: str) -> SstvImageResult:
        """
        Capture, prepare, encode, and transmit one alarm image.

        This method is intentionally a linear pipeline because it runs once per
        wake cycle after a critical alarm has already been acknowledged. If any
        required stage fails, the failure is logged and returned without raising
        back into the main alarm-delivery path.
        """
        if not self.config.enabled:
            return SstvImageResult(
                attempted=False,
                success=False,
                skipped_reason="sstv_disabled",
                image_path=None,
                prepared_path=None,
                wav_path=None,
                mode=self.config.mode,
                repeat_count=self.config.repeat_count,
                notes="SSTV image extension is disabled.",
            )

        work_dir = Path(self.config.work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

        stamp = utc_now_compact()
        # Include node ID and message ID in filenames so recordings can be
        # correlated later with JS8 logs on both the remote and control nodes.
        base = f"{node_id}_{message_id}_{stamp}"
        image_path = work_dir / f"{base}_capture.jpg"
        prepared_path = work_dir / f"{base}_sstv.jpg"
        wav_path = work_dir / f"{base}_{self.config.mode}.wav"

        self.log.info(
            "Starting SSTV image stage node=%s message_id=%s mode=%s dry_run=%s",
            node_id,
            message_id,
            self.config.mode,
            self.config.dry_run,
        )

        commands = [
            # Stop JS8Call before SSTV so the QDX/audio device is not being used
            # by two applications at the same time during the image transmission.
            ("stop_js8call", self.config.stop_js8call_command, False),
            ("capture", self.config.capture_command, True),
            ("encode", self.config.encode_command, True),
        ]

        try:
            for label, template, required in commands:
                if not template.strip():
                    if required:
                        raise RuntimeError(f"Required SSTV command {label} is empty.")
                    continue
                self._run_command(
                    label,
                    template,
                    image_path=image_path,
                    prepared_path=prepared_path,
                    wav_path=wav_path,
                    required=required,
                )

                if label == "capture":
                    # Capture produces the camera-native image. The prepare
                    # step crops/resizes it to the selected SSTV mode size.
                    self._prepare_image(image_path, prepared_path)

            for index in range(1, max(1, self.config.repeat_count) + 1):
                self._run_command(
                    f"transmit_{index}",
                    self.config.transmit_command,
                    image_path=image_path,
                    prepared_path=prepared_path,
                    wav_path=wav_path,
                    required=True,
                )

        except Exception as exc:
            self.log.exception("SSTV image stage failed.")
            return SstvImageResult(
                attempted=True,
                success=False,
                skipped_reason=None,
                image_path=str(image_path),
                prepared_path=str(prepared_path),
                wav_path=str(wav_path),
                mode=self.config.mode,
                repeat_count=self.config.repeat_count,
                notes=f"SSTV image stage failed: {exc}",
            )

        return SstvImageResult(
            attempted=True,
            success=True,
            skipped_reason=None,
            image_path=str(image_path),
            prepared_path=str(prepared_path),
            wav_path=str(wav_path),
            mode=self.config.mode,
            repeat_count=self.config.repeat_count,
            notes="SSTV image stage completed.",
        )

    def _prepare_image(self, image_path: Path, prepared_path: Path) -> None:
        """
        Prepare the captured camera image for the selected SSTV mode.

        The default "__pillow__" path avoids depending on ImageMagick `convert`,
        which was not present on the live Pi. A custom shell command can still
        be supplied for experiments or alternative image-processing pipelines.
        """
        if self.config.prepare_command.strip() != "__pillow__":
            self._run_command(
                "prepare",
                self.config.prepare_command,
                image_path=image_path,
                prepared_path=prepared_path,
                wav_path=prepared_path.with_suffix(".wav"),
                required=True,
            )
            return

        if self.config.dry_run:
            self.log.info(
                "SSTV dry-run prepare: pillow resize %s -> %s (%dx%d)",
                image_path,
                prepared_path,
                self.config.image_width,
                self.config.image_height,
            )
            return

        width, height = sstv_dimensions_for_mode(
            self.config.mode,
            self.config.image_width,
            self.config.image_height,
        )

        try:
            from PIL import Image, ImageOps
        except ImportError:
            # The boot script can point this at /usr/bin/python3 when Pillow is
            # installed system-wide rather than inside the BearWave venv.
            self._prepare_image_with_system_python(image_path, prepared_path, width, height)
            return

        with Image.open(image_path) as image:
            prepared = ImageOps.fit(
                image.convert("RGB"),
                (width, height),
                method=Image.Resampling.LANCZOS,
            )
            prepared.save(prepared_path, quality=90)

    def _prepare_image_with_system_python(
        self,
        image_path: Path,
        prepared_path: Path,
        width: int,
        height: int,
    ) -> None:
        """
        Fallback Pillow runner used when the current Python cannot import PIL.

        This keeps the SSTV path flexible on Raspberry Pi OS installations where
        camera/Pillow packages may have been installed by apt for system Python.
        """
        code = """
import sys
from PIL import Image, ImageOps

source, target, width, height = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
with Image.open(source) as image:
    prepared = ImageOps.fit(
        image.convert("RGB"),
        (width, height),
        method=Image.Resampling.LANCZOS,
    )
    prepared.save(target, quality=90)
"""
        completed = subprocess.run(
            [
                self.config.pillow_python,
                "-c",
                code,
                str(image_path),
                str(prepared_path),
                str(width),
                str(height),
            ],
            check=False,
            text=True,
            capture_output=True,
        )

        if completed.stdout:
            self.log.info("SSTV pillow prepare stdout: %s", completed.stdout.strip())
        if completed.stderr:
            self.log.warning("SSTV pillow prepare stderr: %s", completed.stderr.strip())
        if completed.returncode != 0:
            raise RuntimeError(
                f"SSTV Pillow prepare failed with exit code {completed.returncode}."
            )

    def _run_command(
        self,
        label: str,
        template: str,
        *,
        image_path: Path,
        prepared_path: Path,
        wav_path: Path,
        required: bool,
    ) -> None:
        """
        Expand and execute one configured shell command.

        The command templates use named placeholders so the boot wrapper can
        swap in different camera, encoder, or transmit commands without changing
        this Python module.
        """
        command = template.format(
            image=shlex.quote(str(image_path)),
            prepared=shlex.quote(str(prepared_path)),
            wav=shlex.quote(str(wav_path)),
            mode=shlex.quote(self.config.mode),
        )

        if self.config.dry_run:
            self.log.info("SSTV dry-run %s: %s", label, command)
            return

        self.log.info("SSTV running %s: %s", label, command)
        completed = subprocess.run(
            command,
            shell=True,
            check=False,
            text=True,
            capture_output=True,
        )

        if completed.stdout:
            self.log.info("SSTV %s stdout: %s", label, completed.stdout.strip())
        if completed.stderr:
            self.log.warning("SSTV %s stderr: %s", label, completed.stderr.strip())

        if required and completed.returncode != 0:
            raise RuntimeError(
                f"SSTV command {label} failed with exit code {completed.returncode}."
            )
