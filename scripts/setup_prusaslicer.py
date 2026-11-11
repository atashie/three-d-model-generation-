"""Install the pinned PrusaSlicer 2.9.7 for F6.portability (Windows x64 only).

    uv run python scripts/setup_prusaslicer.py --dest artifacts/tools/prusaslicer-2.9.7
    uv run python scripts/setup_prusaslicer.py --dest DIR --zip PATH   # a downloaded zip
    uv run python scripts/setup_prusaslicer.py --verify-only DIR       # check hashes only

Everything is checked against profiles/slicers/prusaslicer-2.9.7.yaml:
1. download the release asset to DIR/download/ (or take --zip) and check its SHA-256;
2. extract it into a fresh DIR/app/ and check the console exe, PrusaSlicer.dll and the whole
   app tree (every file) against the pin.
--verify-only checks the same hashes, including the whole app tree, without downloading.
No profile is installed: tdmg slice passes every PrusaSlicer setting on the command line,
taken from the pinned OrcaSlicer A1 profiles. The download, extraction and checks are
shared with scripts/setup_orcaslicer.py (scripts/_slicer_setup.py).

PrusaSlicer is AGPL-3.0. Its files are only downloaded to DIR (git-ignored under
artifacts/); none enters the repo. tdmg itself never downloads anything.
Exit codes: 0 installed (or verified), 2 refused; the message says why.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

import _slicer_setup
from _slicer_setup import SetupError, require_empty

from tdmg.portability import PrusaPin, load_prusa_pin, verify_prusa_install
from tdmg.slicer import SlicerError

USER_AGENT = "tdmg-setup-prusaslicer"


def check_platform(system: str | None = None, machine: str | None = None) -> None:
    """Refuse anything but Windows x64; reads this machine's platform when not given."""
    _slicer_setup.check_platform(platform.system() if system is None else system,
                                 platform.machine() if machine is None else machine)


def download(url: str, path: Path) -> None:
    _slicer_setup.download(url, path, USER_AGENT)


def install_app(dest: Path, pin: PrusaPin, zip_path: Path | None = None) -> None:
    # download is looked up here, at call time, so tests can replace it.
    _slicer_setup.install_app(dest, pin, zip_path, download)


def setup(dest: Path, zip_path: Path | None = None) -> dict:
    check_platform()
    pin = load_prusa_pin()
    require_empty(dest / "app")
    dest.mkdir(parents=True, exist_ok=True)
    install_app(dest, pin, zip_path)
    return verify_prusa_install(dest, pin, full_tree=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dest", type=Path, help="folder to install into")
    mode.add_argument("--verify-only", type=Path, metavar="DIR",
                      help="check an existing install's hashes; download nothing")
    parser.add_argument("--zip", type=Path, help="use this downloaded release zip")
    args = parser.parse_args(argv)
    try:
        if args.verify_only is not None:
            found = verify_prusa_install(args.verify_only, load_prusa_pin(), full_tree=True)
        else:
            found = setup(args.dest, args.zip)
    except (SetupError, SlicerError) as err:
        print(f"refused: {err}", file=sys.stderr)
        return 2
    print(json.dumps(found, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
