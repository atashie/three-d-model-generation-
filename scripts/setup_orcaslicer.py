"""Install the pinned OrcaSlicer 2.5.0 and flatten the Bambu A1 profiles (Windows x64 only).

    uv run python scripts/setup_orcaslicer.py --dest artifacts/tools/orcaslicer-2.5.0
    uv run python scripts/setup_orcaslicer.py --dest DIR --zip PATH   # an already downloaded zip
    uv run python scripts/setup_orcaslicer.py --verify-only DIR       # check hashes only

Everything is checked against profiles/slicers/orcaslicer-2.5.0.yaml:
1. download the release asset to DIR/download/ (or take --zip) and check its SHA-256;
2. extract it into a fresh DIR/app/ and check the exe, the main library and the whole
   app tree (every file) against the pin;
3. fetch the A1 preset chains from the OrcaSlicer source at the pinned tag, check every
   upstream file against the pinned manifest, merge each chain, and check the merged
   files and source-manifest.json against the pinned hashes before writing
   DIR/profiles-flat/.
--verify-only checks the same hashes, including the whole app tree, without downloading.

The merge is the one in research/verification/2026-11-10-orcaslicer-windows/
flatten_profiles.py, which produced the pinned hashes: each chain parent first, child keys
override, the pin's drop_keys removed, "name" set to the leaf preset and "from" to "User".
That script wrote its files with Path.write_text on Windows, so they have CRLF line ends;
this one writes the same bytes explicitly.

OrcaSlicer is AGPL-3.0. Its files are only downloaded to DIR (git-ignored under artifacts/);
none enters the repo. tdmg itself never downloads anything. The download, extraction and
app checks are shared with scripts/setup_prusaslicer.py (scripts/_slicer_setup.py).
Exit codes: 0 installed (or verified), 2 refused; the message says why.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import urllib.parse
from pathlib import Path

import _slicer_setup
from _slicer_setup import SetupError
from _slicer_setup import check_hash as _check
from _slicer_setup import require_empty as _require_empty

from tdmg.slicer import SlicerError, SlicerPin, load_pin, verify_install

USER_AGENT = "tdmg-setup-orcaslicer"
MAX_CHAIN = 20        # inherits links followed before refusing (guards against a cycle)


def check_platform(system: str | None = None, machine: str | None = None) -> None:
    """Refuse anything but Windows x64; reads this machine's platform when not given."""
    _slicer_setup.check_platform(platform.system() if system is None else system,
                                 platform.machine() if machine is None else machine)


def fetch(url: str) -> bytes:
    return _slicer_setup.fetch(url, USER_AGENT)


def download(url: str, path: Path) -> None:
    _slicer_setup.download(url, path, USER_AGENT)


def install_app(dest: Path, pin: SlicerPin, zip_path: Path | None = None) -> None:
    """Get the release zip, check it, extract it into dest/app and check the exe."""
    # download is looked up here, at call time, so tests can replace it.
    _slicer_setup.install_app(dest, pin, zip_path, download)


def _json_bytes(obj) -> bytes:
    """json.dumps(indent=1, sort_keys=True) with CRLF, as Path.write_text wrote on Windows."""
    return json.dumps(obj, indent=1, sort_keys=True).replace("\n", "\r\n").encode("ascii")


def flatten(pin: SlicerPin) -> dict[str, bytes]:
    """The flattened profiles and source-manifest.json, as bytes, every hash checked."""
    prof = pin.profiles
    base = prof.source_base + prof.vendor
    index = json.loads(fetch(base + ".json"))
    names = {}
    for kind in ("machine_list", "process_list", "filament_list", "machine_model_list"):
        for entry in index.get(kind, []):
            names[entry["name"]] = entry["sub_path"]
    seen: dict[str, str] = {}

    def chain(name: str) -> list[dict]:
        configs = []
        while name:
            if len(configs) >= MAX_CHAIN:
                raise SetupError(f"preset chain longer than {MAX_CHAIN} at {name!r}")
            if name not in names:
                raise SetupError(f"preset {name!r} is not in the {prof.vendor} index")
            sub = names[name]
            if sub not in prof.upstream_sha256:
                raise SetupError(f"upstream file {sub} is not in the pin's manifest")
            raw = fetch(base + "/" + urllib.parse.quote(sub))
            digest = hashlib.sha256(raw).hexdigest()
            _check(f"upstream file {sub}", digest, prof.upstream_sha256[sub])
            seen[sub] = digest
            cfg = json.loads(raw)
            configs.insert(0, cfg)
            name = cfg.get("inherits")
        return configs

    out = {}
    for kind in ("machine", "process", "filament"):
        p = prof.flat[kind]
        configs = chain(p.preset)
        got = [c["name"] for c in configs]
        if got != p.chain:
            raise SetupError(f"{kind} chain {got} differs from the pin's {p.chain}")
        merged: dict = {}
        for cfg in configs:
            merged.update(cfg)
        for key in prof.drop_keys:
            merged.pop(key, None)
        merged["name"] = p.preset
        merged["from"] = "User"
        data = _json_bytes(merged)
        _check(p.file, hashlib.sha256(data).hexdigest(), p.sha256)
        out[p.file] = data
    unused = sorted(set(prof.upstream_sha256) - set(seen))
    if unused:
        raise SetupError(f"pinned upstream files were not part of any chain: {unused}")
    manifest = _json_bytes({"tag": pin.tag, "files_sha256": seen})
    _check("source-manifest.json", hashlib.sha256(manifest).hexdigest(), prof.manifest_sha256)
    out["source-manifest.json"] = manifest
    return out


def write_profiles(dest: Path, pin: SlicerPin, files: dict[str, bytes]) -> None:
    folder = dest / pin.profiles.folder
    _require_empty(folder)
    tmp = Path(tempfile.mkdtemp(dir=dest, prefix=".profiles-"))
    try:
        for name, data in files.items():
            (tmp / name).write_bytes(data)
        if folder.exists():
            folder.rmdir()
        os.replace(tmp, folder)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def setup(dest: Path, zip_path: Path | None = None) -> dict:
    check_platform()
    pin = load_pin()
    for sub in ("app", pin.profiles.folder):
        _require_empty(dest / sub)
    dest.mkdir(parents=True, exist_ok=True)
    profiles = flatten(pin)            # small and quick: fail before a 200 MB download
    install_app(dest, pin, zip_path)
    write_profiles(dest, pin, profiles)
    return verify_install(dest, pin, full_tree=True)


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
            found = verify_install(args.verify_only, load_pin(), full_tree=True)
        else:
            found = setup(args.dest, args.zip)
    except (SetupError, SlicerError) as err:
        print(f"refused: {err}", file=sys.stderr)
        return 2
    print(json.dumps(found, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
