#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import sstv.decode as sstv_decode_module
from sstv.decode import SSTVDecoder


def quiet(*_args, **_kwargs) -> None:
    """Replacement logger/progress function for pysstv under systemd."""
    return None


def decode_file(source: Path, target: Path, skip: float) -> int:
    # The upstream CLI assumes an interactive terminal for progress output.
    # This service wrapper disables that output so decoding works under systemd.
    sstv_decode_module.log_message = quiet
    sstv_decode_module.progress_bar = quiet

    with source.open("rb") as audio:
        with SSTVDecoder(audio) as decoder:
            image = decoder.decode(skip)

    if image is None:
        # Exit 2 means "no valid SSTV image found" rather than a script fault.
        return 2

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_target = target.with_name(f".{target.stem}.tmp{target.suffix}")
    # Atomic replace prevents the dashboard from seeing a half-written image.
    image.save(tmp_target)
    tmp_target.replace(target)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Headless BearWave SSTV audio decoder.")
    parser.add_argument("source", type=Path, help="Input WAV file")
    parser.add_argument("target", type=Path, help="Output image path")
    parser.add_argument("--skip", type=float, default=0.0, help="Seconds to skip before decoding")
    args = parser.parse_args()

    try:
        return decode_file(args.source, args.target, args.skip)
    except Exception as exc:
        print(f"decode failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
