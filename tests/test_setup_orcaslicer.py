"""scripts/setup_orcaslicer.py, offline: every download is replaced by local bytes."""

import hashlib
import importlib.util
import io
import json
import zipfile

import pytest

from tdmg.paths import REPO_ROOT
from tdmg.slicer import load_pin

_spec = importlib.util.spec_from_file_location(
    "setup_orcaslicer", REPO_ROOT / "scripts" / "setup_orcaslicer.py")
setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup)

PIN = load_pin()
EXE = b"not really an exe"
MEMBERS = {"orca-slicer.exe": EXE, "OrcaSlicer.dll": b"dll", "resources/x.txt": b"x"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def _tree(app: dict[str, bytes]) -> tuple[int, str]:
    """File count and tree hash, from the definition in the pin file."""
    lines = sorted(f"{rel}\t{_sha(d)}" for rel, d in app.items())
    return len(lines), _sha("".join(x + "\n" for x in lines).encode())


def _crlf_json(obj) -> bytes:
    return json.dumps(obj, indent=1, sort_keys=True).replace("\n", "\r\n").encode()


def _pin_with(release_sha=None, app=None, flat=None, upstream=None, manifest=None):
    """PIN with its hashes replaced: app is the extracted tree the pin should expect."""
    profiles = PIN.profiles
    updates = {k: v for k, v in (("flat", flat), ("upstream_sha256", upstream),
                                 ("manifest_sha256", manifest)) if v is not None}
    if updates:
        profiles = profiles.model_copy(update=updates)
    new = {"release": PIN.release.model_copy(
               update={"sha256": release_sha or PIN.release.sha256}),
           "profiles": profiles}
    if app is not None:
        files, tree = _tree(app)
        new["exe"] = PIN.exe.model_copy(update={"sha256": _sha(app["orca-slicer.exe"])})
        new["libraries"] = [PIN.libraries[0].model_copy(
            update={"sha256": _sha(app["OrcaSlicer.dll"])})]
        new["app_tree"] = PIN.app_tree.model_copy(update={"files": files, "sha256": tree})
    return PIN.model_copy(update=new)


# --- Installing the app from the release zip ------------------------------------------

def _fake_download(data: bytes, calls: list):
    def download(url, path):
        calls.append(url)
        path.write_bytes(data)
    return download


def test_install_app_verifies_and_extracts(tmp_path, monkeypatch):
    archive = _zip(MEMBERS)
    pin = _pin_with(release_sha=_sha(archive), app=MEMBERS)
    calls = []
    monkeypatch.setattr(setup, "download", _fake_download(archive, calls))
    setup.install_app(tmp_path, pin)
    assert calls == [pin.release.url]
    assert (tmp_path / "app" / "orca-slicer.exe").read_bytes() == EXE
    assert (tmp_path / "app" / "resources" / "x.txt").read_bytes() == b"x"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["app", "download"]


def test_install_app_refuses_a_wrong_zip_hash(tmp_path, monkeypatch):
    archive = _zip(MEMBERS)
    pin = _pin_with(release_sha=_sha(b"something else"), app=MEMBERS)
    monkeypatch.setattr(setup, "download", _fake_download(archive, []))
    with pytest.raises(setup.SetupError, match="OrcaSlicer_Windows_V2.5.0_x64_portable.zip.*"
                                               "does not match the pin"):
        setup.install_app(tmp_path, pin)
    assert not (tmp_path / "app").exists()
    assert not (tmp_path / "download" / pin.release.asset).exists()   # not kept as verified


@pytest.mark.parametrize(("change", "what"), [
    ({"orca-slicer.exe": b"tampered"}, "orca-slicer.exe"),
    ({"OrcaSlicer.dll": b"tampered"}, "OrcaSlicer.dll"),
    ({"resources/x.txt": b"tampered"}, "app tree"),
    ({"resources/extra.txt": b"new"}, "app tree")])
def test_install_app_refuses_any_changed_file_and_leaves_no_app(tmp_path, monkeypatch,
                                                                change, what):
    archive = _zip({**MEMBERS, **change})
    pin = _pin_with(release_sha=_sha(archive), app=MEMBERS)
    monkeypatch.setattr(setup, "download", _fake_download(archive, []))
    with pytest.raises(setup.SetupError, match=f"{what}.*does not match the pin"):
        setup.install_app(tmp_path, pin)
    assert not (tmp_path / "app").exists()
    assert [p.name for p in tmp_path.iterdir()] == ["download"]   # no extraction leftovers


def test_install_app_refuses_a_corrupt_cached_zip_and_says_to_delete_it(tmp_path,
                                                                       monkeypatch):
    archive = _zip(MEMBERS)
    pin = _pin_with(release_sha=_sha(archive), app=MEMBERS)
    (tmp_path / "download").mkdir()
    cached = tmp_path / "download" / pin.release.asset
    cached.write_bytes(archive[:-10])          # an interrupted or corrupted earlier copy
    calls = []
    monkeypatch.setattr(setup, "download", _fake_download(archive, calls))
    with pytest.raises(setup.SetupError, match="delete .*" + pin.release.asset):
        setup.install_app(tmp_path, pin)
    assert calls == [] and not (tmp_path / "app").exists()


def test_install_app_keeps_a_parent_path_member_inside_the_folder(tmp_path, monkeypatch):
    members = {**MEMBERS, "../evil.txt": b"evil"}
    dest = tmp_path / "dest"
    dest.mkdir()
    archive = _zip(members)
    # zipfile drops ".." components, so the member lands at app/evil.txt.
    pin = _pin_with(release_sha=_sha(archive), app={**MEMBERS, "evil.txt": b"evil"})
    monkeypatch.setattr(setup, "download", _fake_download(archive, []))
    setup.install_app(dest, pin)
    assert not (tmp_path / "evil.txt").exists() and not (dest / "evil.txt").exists()
    assert (dest / "app" / "evil.txt").read_bytes() == b"evil"


def test_install_app_refuses_a_non_empty_app_folder_before_downloading(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "old.txt").write_bytes(b"old")
    calls = []
    monkeypatch.setattr(setup, "download", _fake_download(b"", calls))
    with pytest.raises(setup.SetupError, match="not empty"):
        setup.install_app(tmp_path, PIN)
    assert calls == []


def test_install_app_uses_a_local_zip_after_checking_it(tmp_path, monkeypatch):
    archive = _zip(MEMBERS)
    local = tmp_path / "local.zip"
    local.write_bytes(archive)
    dest = tmp_path / "dest"
    dest.mkdir()
    calls = []
    monkeypatch.setattr(setup, "download", _fake_download(b"", calls))
    setup.install_app(dest, _pin_with(release_sha=_sha(archive), app=MEMBERS), zip_path=local)
    assert calls == []
    assert (dest / "app" / "orca-slicer.exe").read_bytes() == EXE
    with pytest.raises(setup.SetupError, match="local.zip.*does not match the pin"):
        setup.install_app(tmp_path / "other", _pin_with(release_sha=_sha(b"x")),
                          zip_path=local)

# --- Flattening the profile chains ------------------------------------------------------

def _upstream():
    """A tiny vendor: one chain per kind, two files each, with the research merge applied."""
    files = {
        "machine/base_m.json": {"name": "base_m", "a": "1", "b": "1", "from": "system",
                                "instantiation": "false"},
        "machine/M.json": {"name": "M", "inherits": "base_m", "b": "2", "setting_id": "X",
                           "description": "d"},
        "process/base_p.json": {"name": "base_p", "layer_height": "0.1"},
        "process/P.json": {"name": "P", "inherits": "base_p", "layer_height": "0.2"},
        "filament/base_f.json": {"name": "base_f", "t": ["200"]},
        "filament/F.json": {"name": "F", "inherits": "base_f", "from": "system"},
    }
    raw = {path: json.dumps(cfg).encode() for path, cfg in files.items()}
    index = {"machine_list": [{"name": "base_m", "sub_path": "machine/base_m.json"},
                              {"name": "M", "sub_path": "machine/M.json"}],
             "process_list": [{"name": "base_p", "sub_path": "process/base_p.json"},
                              {"name": "P", "sub_path": "process/P.json"}],
             "filament_list": [{"name": "base_f", "sub_path": "filament/base_f.json"},
                               {"name": "F", "sub_path": "filament/F.json"}]}
    # Expected outputs, written by hand: child overrides parent, the dropped keys go,
    # name is the leaf and from is "User"; indent 1, sorted keys, CRLF line ends.
    expected = {"machine.json": {"name": "M", "a": "1", "b": "2", "from": "User"},
                "process.json": {"name": "P", "layer_height": "0.2", "from": "User"},
                "filament.json": {"name": "F", "t": ["200"], "from": "User"}}
    expected = {k: _crlf_json(v) for k, v in expected.items()}
    return raw, index, expected


def _fake_fetch(raw: dict, index: dict, served: list):
    base = PIN.profiles.source_base + PIN.profiles.vendor

    def fetch(url):
        served.append(url)
        if url == base + ".json":
            return json.dumps(index).encode()
        for path, data in raw.items():
            if url == base + "/" + path:
                return data
        raise AssertionError(f"unexpected url {url}")
    return fetch


def _flat_pin(raw, expected, **override):
    chains = {"machine": ["base_m", "M"], "process": ["base_p", "P"],
              "filament": ["base_f", "F"]}
    flat = {k: p.model_copy(update={"preset": chains[k][-1], "chain": chains[k],
                                    "includes": [], "sha256": _sha(expected[p.file])})
            for k, p in PIN.profiles.flat.items()}
    upstream = {path: _sha(data) for path, data in raw.items()}
    upstream.update(override.get("upstream", {}))
    for kind, sha in override.get("flat", {}).items():
        flat[kind] = flat[kind].model_copy(update={"sha256": sha})
    manifest = override.get("manifest") or _sha(_crlf_json(
        {"tag": PIN.tag, "files_sha256": {p: _sha(d) for p, d in raw.items()}}))
    return _pin_with(flat=flat, upstream=upstream, manifest=manifest)


def test_flatten_merges_chains_into_the_pinned_bytes(monkeypatch):
    raw, index, expected = _upstream()
    served = []
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, served))
    out = setup.flatten(_flat_pin(raw, expected))
    assert {k: out[k] for k in expected} == expected
    manifest = json.loads(out["source-manifest.json"])
    assert manifest == {"tag": PIN.tag, "files_sha256": {p: _sha(d) for p, d in raw.items()}}
    assert all(u.startswith(PIN.profiles.source_base) for u in served)


def test_flatten_refuses_a_manifest_that_differs_from_the_pin(monkeypatch):
    raw, index, expected = _upstream()
    pin = _flat_pin(raw, expected, manifest=_sha(b"other"))
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="source-manifest.json.*does not match the pin"):
        setup.flatten(pin)


def test_json_bytes_reproduce_the_research_manifest():
    # Parsed, so the checkout's line ends do not matter; the bytes the research script
    # wrote (CRLF) are pinned by hash (2026-11-10 README addendum, item 5; the 2026-11-13
    # record's manifest adds the A1 templates).
    record = REPO_ROOT / "research" / "verification" / "2026-11-13-a1-profile-include"
    manifest = json.loads((record / "source-manifest.json").read_text(encoding="utf-8"))
    assert _sha(setup._json_bytes(manifest)) == PIN.profiles.manifest_sha256
    assert manifest["files_sha256"] == PIN.profiles.upstream_sha256


def test_flatten_refuses_a_changed_upstream_file(monkeypatch):
    raw, index, expected = _upstream()
    pin = _flat_pin(raw, expected)
    raw["process/base_p.json"] = json.dumps({"name": "base_p", "layer_height": "0.3"}).encode()
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="process/base_p.json.*does not match the pin"):
        setup.flatten(pin)


def test_flatten_refuses_an_output_that_differs_from_the_pin(monkeypatch):
    raw, index, expected = _upstream()
    pin = _flat_pin(raw, expected, flat={"filament": _sha(b"other")})
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="filament.json.*does not match the pin"):
        setup.flatten(pin)


def test_flatten_refuses_a_file_the_pin_does_not_list(monkeypatch):
    raw, index, expected = _upstream()
    pin = _flat_pin(raw, expected)
    upstream = dict(pin.profiles.upstream_sha256)
    del upstream["machine/base_m.json"]
    pin = _pin_with(flat=pin.profiles.flat, upstream=upstream)
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="machine/base_m.json.*not in the pin"):
        setup.flatten(pin)


def test_flatten_refuses_when_a_pinned_file_is_not_used(monkeypatch):
    raw, index, expected = _upstream()
    pin = _flat_pin(raw, expected, upstream={"process/unused.json": _sha(b"u")})
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="process/unused.json"):
        setup.flatten(pin)


def test_flatten_refuses_a_different_chain(monkeypatch):
    raw, index, expected = _upstream()
    pin = _flat_pin(raw, expected)
    flat = dict(pin.profiles.flat)
    flat["machine"] = flat["machine"].model_copy(update={"chain": ["other", "M"]})
    pin = _pin_with(flat=flat, upstream=pin.profiles.upstream_sha256)
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="chain"):
        setup.flatten(pin)


# --- include: template presets layered between the parent and the preset ----------------
# OrcaSlicer v2.5.0, PresetBundle::resolve_vendor_preset: the parent's resolved config,
# then each included preset's own keys in the order listed, then the preset's own keys
# (research/verification/2026-11-13-a1-profile-include/README.md).

T1 = "M template g"
T2 = "M template b"
T3 = "M template g again"
# OrcaSlicer's default for each key a fixture template sets: none of the templates' values.
DEFAULTS = {"a": "default a", "b": "default b", "g": "default g"}


def _upstream_with_include():
    """_upstream, with the machine chain including three templates (M) and one (base_m).

    Each template has exactly type, name, instantiation and one setting, as the A1 ones."""
    raw, index, _ = _upstream()
    files = {
        "machine/base_m.json": {"name": "base_m", "a": "1", "b": "1", "g": "base",
                                "from": "system", "instantiation": "false",
                                "include": "TB"},          # one bare name is allowed
        "machine/M.json": {"name": "M", "inherits": "base_m", "b": "2", "setting_id": "X",
                           "description": "d", "include": [T1, T2, T3]},
        "machine/TB.json": {"type": "machine", "name": "TB", "instantiation": "false",
                            "a": "tb"},
        "machine/T1.json": {"type": "machine", "name": T1, "instantiation": "false",
                            "g": "t1"},
        "machine/T2.json": {"type": "machine", "name": T2, "instantiation": "false",
                            "b": "t2"},
        "machine/T3.json": {"type": "machine", "name": T3, "instantiation": "false",
                            "g": "t3"},
    }
    raw.update({path: json.dumps(cfg).encode() for path, cfg in files.items()})
    index["machine_list"] += [{"name": "TB", "sub_path": "machine/TB.json"},
                              {"name": T1, "sub_path": "machine/T1.json"},
                              {"name": T2, "sub_path": "machine/T2.json"},
                              {"name": T3, "sub_path": "machine/T3.json"}]
    # Written by hand: base_m's include goes under base_m's own keys (a stays 1); M's
    # includes go over base_m in order (g from T1, then T3), under M's own b (T2's b goes).
    # The templates' type, name and instantiation are not config keys; include is dropped.
    expected = _upstream()[2]
    expected["machine.json"] = _crlf_json(
        {"name": "M", "a": "1", "b": "2", "g": "t3", "from": "User"})
    return raw, index, expected


INCLUDES = ["TB", T1, T2, T3]


def _include_pin(raw, expected, includes=INCLUDES, defaults=None, **override):
    pin = _flat_pin(raw, expected, **override)
    flat = dict(pin.profiles.flat)
    flat["machine"] = flat["machine"].model_copy(update={"includes": includes})
    defaults = DEFAULTS if defaults is None else defaults
    profiles = pin.profiles.model_copy(update={
        "flat": flat, "include_defaults_sha256": {k: _sha(v.encode()) for k, v in
                                                  defaults.items()}})
    return pin.model_copy(update={"profiles": profiles})


def test_pin_includes_default_to_none_for_process_and_filament():
    assert PIN.profiles.flat["process"].includes == []
    assert PIN.profiles.flat["filament"].includes == []
    assert "include" in PIN.profiles.drop_keys


def test_flatten_layers_includes_between_parent_and_preset(monkeypatch):
    raw, index, expected = _upstream_with_include()
    served = []
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, served))
    out = setup.flatten(_include_pin(raw, expected))
    assert {k: out[k] for k in expected} == expected
    manifest = json.loads(out["source-manifest.json"])
    assert manifest["files_sha256"] == {p: _sha(d) for p, d in raw.items()}
    assert "include" not in json.loads(out["machine.json"])


def test_flatten_without_include_is_unchanged_by_the_include_support(monkeypatch):
    raw, index, expected = _upstream()
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    out = setup.flatten(_flat_pin(raw, expected))
    assert {k: out[k] for k in expected} == expected


def test_flatten_refuses_a_template_missing_from_the_pin(monkeypatch):
    raw, index, expected = _upstream_with_include()
    pin = _include_pin(raw, expected)
    upstream = dict(pin.profiles.upstream_sha256)
    del upstream["machine/T2.json"]
    pin = pin.model_copy(update={"profiles": pin.profiles.model_copy(
        update={"upstream_sha256": upstream})})
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="machine/T2.json.*not in the pin"):
        setup.flatten(pin)


def test_flatten_refuses_a_changed_template(monkeypatch):
    raw, index, expected = _upstream_with_include()
    pin = _include_pin(raw, expected)
    raw["machine/T1.json"] = json.dumps({"type": "machine", "name": T1, "g": "x"}).encode()
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="machine/T1.json.*does not match the pin"):
        setup.flatten(pin)


def test_flatten_refuses_includes_that_differ_from_the_pin(monkeypatch):
    raw, index, expected = _upstream_with_include()
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    for wrong in ([], ["TB", T2, T1, T3], ["TB", T1, T2]):
        with pytest.raises(setup.SetupError, match="includes"):
            setup.flatten(_include_pin(raw, expected, includes=wrong))


def test_flatten_refuses_a_pinned_template_nothing_includes(monkeypatch):
    raw, index, expected = _upstream()
    t1 = _upstream_with_include()[0]["machine/T1.json"]
    index["machine_list"].append({"name": T1, "sub_path": "machine/T1.json"})
    pin = _flat_pin(raw, expected, upstream={"machine/T1.json": _sha(t1)})
    raw["machine/T1.json"] = t1
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="machine/T1.json"):
        setup.flatten(pin)


def test_flatten_refuses_an_include_not_in_the_kinds_index(monkeypatch):
    raw, index, expected = _upstream_with_include()
    # OrcaSlicer looks an include up among the presets of the same collection only.
    entry = next(e for e in index["machine_list"] if e["name"] == T2)
    index["machine_list"].remove(entry)
    index["process_list"].append(entry)
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="not in the BBL machine_list"):
        setup.flatten(_include_pin(raw, expected))


@pytest.mark.parametrize("extra", [{"inherits": "base_m"}, {"include": ["TB"]},
                                   {"name": "another name"}, {"setting_id": "S"},
                                   {"h": "a second setting"}])
def test_flatten_refuses_a_template_it_cannot_resolve_like_orcaslicer(monkeypatch, extra):
    # A template's own inherits or include would be followed by OrcaSlicer; this
    # flattener does not model that, so it refuses rather than merge something else.
    raw, index, expected = _upstream_with_include()
    cfg = json.loads(raw["machine/T1.json"])
    cfg.update(extra)
    raw["machine/T1.json"] = json.dumps(cfg).encode()
    pin = _include_pin(raw, expected)
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="template"):
        setup.flatten(pin)


@pytest.mark.parametrize("drop", ["type", "instantiation", "g"])
def test_flatten_refuses_a_template_without_exactly_its_three_attributes_and_one_setting(
        monkeypatch, drop):
    raw, index, expected = _upstream_with_include()
    cfg = json.loads(raw["machine/T1.json"])
    del cfg[drop]
    raw["machine/T1.json"] = json.dumps(cfg).encode()
    pin = _include_pin(raw, expected)
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="template"):
        setup.flatten(pin)


def test_flatten_refuses_a_template_value_equal_to_orcaslicers_default(monkeypatch):
    # OrcaSlicer layers an include's diff against the default, so a value equal to the
    # default would not override the parent; a plain merge would. Refused, not guessed.
    raw, index, expected = _upstream_with_include()
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="equals OrcaSlicer's default"):
        setup.flatten(_include_pin(raw, expected, defaults={**DEFAULTS, "g": "t1"}))


@pytest.mark.parametrize(("key", "value", "message"), [
    ("instantiation", "true", "instantiation"), ("instantiation", False, "instantiation"),
    ("type", "process", "type"), ("type", "filament", "type")])
def test_flatten_refuses_a_template_that_is_not_an_uninstantiated_preset_of_the_kind(
        monkeypatch, key, value, message):
    # OrcaSlicer registers an include only for a preset with instantiation "false"
    # (PresetBundle.cpp:7844, source-excerpts.txt), and looks it up among its own kind.
    raw, index, expected = _upstream_with_include()
    cfg = json.loads(raw["machine/T1.json"])
    cfg[key] = value
    raw["machine/T1.json"] = json.dumps(cfg).encode()
    pin = _include_pin(raw, expected)
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match=f"template machine/T1.json.*{message}"):
        setup.flatten(pin)


def test_flatten_refuses_a_template_setting_without_a_pinned_default(monkeypatch):
    raw, index, expected = _upstream_with_include()
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    with pytest.raises(setup.SetupError, match="no pinned default"):
        setup.flatten(_include_pin(raw, expected, defaults={"a": "x", "b": "y"}))


def test_write_profiles_refuses_a_non_empty_folder(tmp_path):
    (tmp_path / "profiles-flat").mkdir()
    (tmp_path / "profiles-flat" / "old.json").write_bytes(b"{}")
    with pytest.raises(setup.SetupError, match="not empty"):
        setup.write_profiles(tmp_path, PIN, {"machine.json": b"{}"})


# --- The whole setup, offline -----------------------------------------------------------

def test_setup_end_to_end_with_fake_downloads(tmp_path, monkeypatch, capsys):
    raw, index, expected = _upstream()
    archive = _zip(MEMBERS)
    flat_pin = _flat_pin(raw, expected)
    pin = _pin_with(release_sha=_sha(archive), app=MEMBERS, flat=flat_pin.profiles.flat,
                    upstream=flat_pin.profiles.upstream_sha256,
                    manifest=flat_pin.profiles.manifest_sha256)
    calls = []
    monkeypatch.setattr(setup, "check_platform", lambda: None)
    monkeypatch.setattr(setup, "load_pin", lambda: pin)
    monkeypatch.setattr(setup, "download", _fake_download(archive, calls))
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    dest = tmp_path / "orca"
    found = setup.setup(dest)
    assert calls == [pin.release.url]
    assert found["exe_sha256"] == pin.exe.sha256
    assert found["app_tree"] == {"files": 3, "sha256": pin.app_tree.sha256}
    assert {p.name: p.read_bytes() for p in (dest / "profiles-flat").iterdir()
            if p.name != "source-manifest.json"} == expected
    assert sorted(p.name for p in dest.iterdir()) == ["app", "download", "profiles-flat"]
    # --verify-only checks the whole tree, so one extra file is refused.
    assert setup.main(["--verify-only", str(dest)]) == 0
    (dest / "app" / "resources" / "added.txt").write_bytes(b"+")
    assert setup.main(["--verify-only", str(dest)]) == 2
    assert "app tree" in capsys.readouterr().err


def test_profiles_only_replaces_the_flat_profiles_and_keeps_the_old_ones(tmp_path,
                                                                          monkeypatch):
    raw, index, expected = _upstream()
    archive = _zip(MEMBERS)
    flat_pin = _flat_pin(raw, expected)
    pin = _pin_with(release_sha=_sha(archive), app=MEMBERS, flat=flat_pin.profiles.flat,
                    upstream=flat_pin.profiles.upstream_sha256,
                    manifest=flat_pin.profiles.manifest_sha256)
    calls = []
    monkeypatch.setattr(setup, "check_platform", lambda: None)
    monkeypatch.setattr(setup, "load_pin", lambda: pin)
    monkeypatch.setattr(setup, "download", _fake_download(archive, calls))
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    dest = tmp_path / "orca"
    dest.mkdir()
    setup.install_app(dest, pin)
    old = dest / "profiles-flat"
    old.mkdir()
    (old / "machine.json").write_bytes(b"old profile")
    calls.clear()
    assert setup.main(["--profiles-only", str(dest)]) == 0
    assert calls == []                                   # no app download
    assert {p.name: p.read_bytes() for p in old.iterdir()
            if p.name != "source-manifest.json"} == expected
    assert (dest / "profiles-flat.previous" / "machine.json").read_bytes() == b"old profile"
    assert setup.main(["--verify-only", str(dest)]) == 0
    # A second run would overwrite the kept copy, so it is refused until it is moved,
    # before anything is fetched, and nothing changes.
    before = {p.relative_to(dest): p.read_bytes() for p in dest.rglob("*") if p.is_file()}
    served = []
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, served))
    assert setup.main(["--profiles-only", str(dest)]) == 2
    assert served == []
    assert {p.relative_to(dest): p.read_bytes() for p in dest.rglob("*")
            if p.is_file()} == before
    assert sorted(p.name for p in dest.iterdir()) == [
        "app", "download", "profiles-flat", "profiles-flat.previous"]


def test_profiles_only_restores_the_old_folder_when_the_swap_fails(tmp_path, monkeypatch):
    raw, index, expected = _upstream()
    archive = _zip(MEMBERS)
    flat_pin = _flat_pin(raw, expected)
    pin = _pin_with(release_sha=_sha(archive), app=MEMBERS, flat=flat_pin.profiles.flat,
                    upstream=flat_pin.profiles.upstream_sha256,
                    manifest=flat_pin.profiles.manifest_sha256)
    monkeypatch.setattr(setup, "check_platform", lambda: None)
    monkeypatch.setattr(setup, "load_pin", lambda: pin)
    monkeypatch.setattr(setup, "download", _fake_download(archive, []))
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    dest = tmp_path / "orca"
    dest.mkdir()
    setup.install_app(dest, pin)
    (dest / "profiles-flat").mkdir()
    (dest / "profiles-flat" / "machine.json").write_bytes(b"old profile")
    real_replace, calls = setup.os.replace, []

    def replace(src, dst):
        calls.append((src, dst))
        if len(calls) == 2:                     # the new folder into place
            raise OSError("disk full")
        real_replace(src, dst)
    monkeypatch.setattr(setup.os, "replace", replace)
    assert setup.main(["--profiles-only", str(dest)]) == 2
    monkeypatch.setattr(setup.os, "replace", real_replace)
    assert len(calls) == 3                      # old aside, new fails, old back
    assert sorted(p.name for p in dest.iterdir()) == ["app", "download", "profiles-flat"]
    assert (dest / "profiles-flat" / "machine.json").read_bytes() == b"old profile"


def test_profiles_only_refuses_without_a_verified_app_and_writes_nothing(tmp_path,
                                                                         monkeypatch, capsys):
    raw, index, expected = _upstream()
    monkeypatch.setattr(setup, "check_platform", lambda: None)
    monkeypatch.setattr(setup, "load_pin", lambda: _flat_pin(raw, expected))
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "orca-slicer.exe").write_bytes(b"not the pinned exe")
    assert setup.main(["--profiles-only", str(tmp_path)]) == 2
    assert "does not match the pin" in capsys.readouterr().err
    assert sorted(p.name for p in tmp_path.iterdir()) == ["app"]


def test_profiles_only_writes_nothing_when_flattening_fails(tmp_path, monkeypatch):
    raw, index, expected = _upstream()
    archive = _zip(MEMBERS)
    pin = _pin_with(release_sha=_sha(archive), app=MEMBERS,
                    flat=_flat_pin(raw, expected, flat={"process": _sha(b"x")}).profiles.flat,
                    upstream=_flat_pin(raw, expected).profiles.upstream_sha256)
    monkeypatch.setattr(setup, "check_platform", lambda: None)
    monkeypatch.setattr(setup, "load_pin", lambda: pin)
    monkeypatch.setattr(setup, "download", _fake_download(archive, []))
    monkeypatch.setattr(setup, "fetch", _fake_fetch(raw, index, []))
    setup.install_app(tmp_path, pin)
    (tmp_path / "profiles-flat").mkdir()
    (tmp_path / "profiles-flat" / "machine.json").write_bytes(b"old")
    assert setup.main(["--profiles-only", str(tmp_path)]) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["app", "download", "profiles-flat"]
    assert (tmp_path / "profiles-flat" / "machine.json").read_bytes() == b"old"


# --- Platform and command line --------------------------------------------------------

def test_only_windows_x64_is_supported():
    setup.check_platform("Windows", "AMD64")
    for system, machine in (("Linux", "x86_64"), ("Darwin", "arm64"), ("Windows", "ARM64")):
        with pytest.raises(setup.SetupError, match="Windows x64 only"):
            setup.check_platform(system, machine)


def test_main_exits_2_on_another_platform_without_writing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(setup.platform, "system", lambda: "Linux")
    dest = tmp_path / "orca"
    assert setup.main(["--dest", str(dest)]) == 2
    assert "Windows x64 only" in capsys.readouterr().err
    assert not dest.exists()


def test_main_verify_only_reports_a_mismatch(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "orca-slicer.exe").write_bytes(b"not the pinned exe")
    assert setup.main(["--verify-only", str(tmp_path)]) == 2
    assert "does not match the pin" in capsys.readouterr().err
