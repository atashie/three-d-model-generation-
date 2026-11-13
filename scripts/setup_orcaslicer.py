"""Install the pinned OrcaSlicer 2.5.0 and flatten the Bambu A1 profiles (Windows x64 only).

    uv run python scripts/setup_orcaslicer.py --dest artifacts/tools/orcaslicer-2.5.0
    uv run python scripts/setup_orcaslicer.py --dest DIR --zip PATH   # an already downloaded zip
    uv run python scripts/setup_orcaslicer.py --verify-only DIR       # check hashes only
    uv run python scripts/setup_orcaslicer.py --profiles-only DIR     # re-flatten the profiles

Everything is checked against profiles/slicers/orcaslicer-2.5.0.yaml:
1. download the release asset to DIR/download/ (or take --zip) and check its SHA-256;
2. extract it into a fresh DIR/app/ and check the exe, the main library and the whole
   app tree (every file) against the pin;
3. fetch the A1 preset chains from the OrcaSlicer source at the pinned tag, check every
   upstream file against the pinned manifest, merge each chain, and check the merged
   files and source-manifest.json against the pinned hashes before writing
   DIR/profiles-flat/.
--verify-only checks the same hashes, including the whole app tree, without downloading.
--profiles-only checks the installed app (whole tree), flattens the profiles again (step 3)
and swaps them in; the old DIR/profiles-flat/ is kept as DIR/profiles-flat.previous/.

The merge is the one in research/verification/2026-11-10-orcaslicer-windows/
flatten_profiles.py (each chain parent first, child keys override, the pin's drop_keys
removed, "name" set to the leaf preset and "from" to "User"), plus, since 2026-11-13, the
templates a preset's include key names, layered between its parent and its own keys as
OrcaSlicer v2.5.0 does. research/verification/2026-11-13-a1-profile-include/
flatten_with_include.py produced the pinned hashes.
That script wrote its files with Path.write_text on Windows, so they have CRLF line ends;
this one writes the same bytes explicitly.

OrcaSlicer is AGPL-3.0. Its files are only downloaded to DIR (git-ignored under artifacts/);
none enters the repo. tdmg itself never downloads anything. The download, extraction and
app checks are shared with scripts/setup_prusaslicer.py (scripts/_slicer_setup.py).
Exit codes: 0 installed (or verified), 2 refused; the message says why.
"""

from __future__ import annotations

import argparse
import contextlib
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

from tdmg.slicer import SlicerError, SlicerPin, load_pin, verify_app, verify_install, verify_tree

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


# Keys of a template preset that OrcaSlicer reads as attributes, not as settings
# (ConfigBase::load_from_json); none is layered into the includer. A template must have
# exactly these and one setting, as each pinned A1 template has: anything else (its own
# inherits or include, which OrcaSlicer would follow, or more settings) is refused.
TEMPLATE_ATTRIBUTES = frozenset({"type", "name", "instantiation"})


def _include_names(cfg: dict, where: str) -> list[str]:
    """The preset names in cfg's include key: an array of names, or one bare name."""
    names = cfg.get("include", [])
    if isinstance(names, str):
        names = [names]
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise SetupError(f"{where}: include must be a name or a list of names")
    return names


def flatten(pin: SlicerPin) -> dict[str, bytes]:
    """The flattened profiles and source-manifest.json, as bytes, every hash checked.

    Each preset resolves as OrcaSlicer v2.5.0 resolves a vendor preset
    (PresetBundle::resolve_vendor_preset): its parent's resolved keys, then the own keys of
    each preset its include key names, in the order listed, then its own keys. The
    included templates must be pinned like the chain files.
    """
    prof = pin.profiles
    base = prof.source_base + prof.vendor
    index = json.loads(fetch(base + ".json"))
    names: dict[str, dict[str, str]] = {}
    for kind in ("machine_list", "process_list", "filament_list", "machine_model_list"):
        names[kind] = {entry["name"]: entry["sub_path"] for entry in index.get(kind, [])}
    every = {n: sub for listed in names.values() for n, sub in listed.items()}
    seen: dict[str, str] = {}

    def get(sub: str) -> dict:
        if sub not in prof.upstream_sha256:
            raise SetupError(f"upstream file {sub} is not in the pin's manifest")
        raw = fetch(base + "/" + urllib.parse.quote(sub))
        digest = hashlib.sha256(raw).hexdigest()
        _check(f"upstream file {sub}", digest, prof.upstream_sha256[sub])
        seen[sub] = digest
        return json.loads(raw)

    def chain(name: str) -> list[dict]:
        configs = []
        while name:
            if len(configs) >= MAX_CHAIN:
                raise SetupError(f"preset chain longer than {MAX_CHAIN} at {name!r}")
            if name not in every:
                raise SetupError(f"preset {name!r} is not in the {prof.vendor} index")
            cfg = get(every[name])
            configs.insert(0, cfg)
            name = cfg.get("inherits")
        return configs

    def template(name: str, kind: str) -> dict:
        """A template's settings; OrcaSlicer finds it among the same kind's presets."""
        listed = names[kind + "_list"]
        if name not in listed:
            raise SetupError(f"included preset {name!r} is not in the {prof.vendor} "
                             f"{kind}_list")
        sub = listed[name]
        cfg = get(sub)
        settings = sorted(set(cfg) - TEMPLATE_ATTRIBUTES)
        if not TEMPLATE_ATTRIBUTES <= set(cfg) or len(settings) != 1:
            raise SetupError(f"included template {sub} has keys {sorted(cfg)}, not exactly "
                             f"{sorted(TEMPLATE_ATTRIBUTES)} and one setting")
        if cfg["name"] != name:
            raise SetupError(f"included template {sub} is named {cfg['name']!r}, "
                             f"not {name!r}")
        key = settings[0]
        # OrcaSlicer layers an include's diff against the option's default, so a value
        # equal to the default would leave the parent's value; a plain merge would not.
        if key not in prof.include_defaults_sha256:
            raise SetupError(f"included template {sub} sets {key!r}, which has no pinned "
                             "default (include_defaults_sha256)")
        value = cfg[key]
        if not isinstance(value, str):
            raise SetupError(f"included template {sub}: {key!r} is not a string")
        if hashlib.sha256(value.encode("utf-8")).hexdigest() == prof.include_defaults_sha256[key]:
            raise SetupError(f"included template {sub}: {key!r} equals OrcaSlicer's default, "
                             "which OrcaSlicer would not layer over the parent")
        return {key: value}

    out = {}
    for kind in ("machine", "process", "filament"):
        p = prof.flat[kind]
        configs = chain(p.preset)
        got = [c["name"] for c in configs]
        if got != p.chain:
            raise SetupError(f"{kind} chain {got} differs from the pin's {p.chain}")
        included = [n for cfg in configs for n in _include_names(cfg, cfg["name"])]
        if included != p.includes:
            raise SetupError(f"{kind} includes {included} differ from the pin's {p.includes}")
        merged: dict = {}
        for cfg in configs:
            for name in _include_names(cfg, cfg["name"]):
                merged.update(template(name, kind))
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
        raise SetupError(f"pinned upstream files were not part of any chain or include: "
                         f"{unused}")
    manifest = _json_bytes({"tag": pin.tag, "files_sha256": seen})
    _check("source-manifest.json", hashlib.sha256(manifest).hexdigest(), prof.manifest_sha256)
    out["source-manifest.json"] = manifest
    return out


@contextlib.contextmanager
def _staged(dest: Path, files: dict[str, bytes]):
    """A new folder in dest holding files; removed afterwards unless it was moved away."""
    tmp = Path(tempfile.mkdtemp(dir=dest, prefix=".profiles-"))
    try:
        for name, data in files.items():
            (tmp / name).write_bytes(data)
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_profiles(dest: Path, pin: SlicerPin, files: dict[str, bytes]) -> None:
    folder = dest / pin.profiles.folder
    _require_empty(folder)
    with _staged(dest, files) as tmp:
        if folder.exists():
            folder.rmdir()
        os.replace(tmp, folder)


PREVIOUS_SUFFIX = ".previous"


def replace_profiles(dest: Path) -> dict:
    """Re-flatten the profiles of an installed, verified app; keep the old folder."""
    check_platform()
    pin = load_pin()
    folder = dest / pin.profiles.folder
    kept = folder.with_name(folder.name + PREVIOUS_SUFFIX)
    if kept.exists():                   # before any check or fetch: nothing would be kept
        raise SetupError(f"{kept} exists; move or delete it first")
    verify_app(dest, pin)               # the exe and libraries,
    verify_tree(dest, pin)              # and every file of the app tree
    profiles = flatten(pin)
    with _staged(dest, profiles) as tmp:
        moved = False
        try:
            if folder.exists():
                os.replace(folder, kept)
                moved = True
            os.replace(tmp, folder)
        except OSError as err:
            if moved and not folder.exists():
                os.replace(kept, folder)    # put the old profiles back
            raise SetupError(f"could not put the new profiles in place: {err}") from err
    return verify_install(dest, pin, full_tree=True)


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
    mode.add_argument("--profiles-only", type=Path, metavar="DIR",
                      help="flatten the profiles again for a verified install; keep the "
                           "old ones as profiles-flat.previous")
    parser.add_argument("--zip", type=Path, help="use this downloaded release zip")
    args = parser.parse_args(argv)
    try:
        if args.verify_only is not None:
            found = verify_install(args.verify_only, load_pin(), full_tree=True)
        elif args.profiles_only is not None:
            found = replace_profiles(args.profiles_only)
        else:
            found = setup(args.dest, args.zip)
    except (SetupError, SlicerError) as err:
        print(f"refused: {err}", file=sys.stderr)
        return 2
    print(json.dumps(found, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
