"""The PrusaSlicer pin, its verification and locate (docs/plans/2026-11-11-portability-check.md).

The pin's values come from research/verification/2026-11-11-prusaslicer-windows/; the
tests check them against that record where it has them.
"""

import hashlib
import io
import json
import os
from pathlib import Path

import numpy as np
import pytest
import trimesh

from tdmg.flat import STL_COORD_RTOL
from tdmg.paths import REPO_ROOT
from tdmg.portability import (
    INFO_HALF_UNIT,
    PRUSA_ENV_VAR,
    PRUSA_PIN_ID,
    PrusaPin,
    explicit_settings,
    gcode_args,
    gcode_layers,
    info_args,
    load_prusa_pin,
    locate_prusaslicer,
    parse_info,
    prusa_gcode_hashes,
    size_tolerance_mm,
    verify_prusa_install,
    volume_error_bound,
    volume_tolerance_mm3,
)
from tdmg.slicer import SlicerError

RECORD = REPO_ROOT / "research" / "verification" / "2026-11-11-prusaslicer-windows"
PIN = load_prusa_pin()
EXE = "app/PrusaSlicer-2.9.7/prusa-slicer-console.exe"
DLL = "app/PrusaSlicer-2.9.7/PrusaSlicer.dll"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tris(stl: bytes) -> np.ndarray:
    mesh = trimesh.load(io.BytesIO(stl), file_type="stl", process=False)
    return np.asarray(mesh.vertices, dtype=np.float64)[np.asarray(mesh.faces)]


def _hash_lines(name: str) -> dict[str, str]:
    """`<sha256> *<path>` lines (sha256sum's binary-mode output) as {path: sha256}."""
    out = {}
    for line in (RECORD / name).read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, path = line.split(" *", 1)
            out[path] = digest
    return out


# --- The pin -------------------------------------------------------------------------

def test_pin_loads_by_id():
    assert PIN.id == PRUSA_PIN_ID == "prusaslicer-2.9.7"
    assert (PIN.name, PIN.version, PIN.tag) == ("PrusaSlicer", "2.9.7", "version_2.9.7")
    assert PIN.release.platform == "windows-x64"
    assert PIN.release.asset == "PrusaSlicer-2.9.7.zip"
    assert PIN.release.url == ("https://github.com/prusa3d/PrusaSlicer/releases/download/"
                               "version_2.9.7/PrusaSlicer-2.9.7.zip")
    assert PIN.exe.path == EXE
    assert [lib.path for lib in PIN.libraries] == [DLL]
    assert PIN.app_tree.folder == "app"
    assert PIN.record == "research/verification/2026-11-11-prusaslicer-windows/README.md"
    assert (REPO_ROOT / PIN.record).is_file()


def test_pin_hashes_equal_the_research_record():
    install = _hash_lines("install-hashes.txt")
    assert PIN.release.sha256 == install["download/" + PIN.release.asset]
    assert PIN.release.sha256 == ("5d4f395aeb6c344b300e0e1be37a0e1931622b642c3c3085eb19cd"
                                  "ae211bc008")
    assert PIN.exe.sha256 == install[PIN.exe.path]
    # The README gives the zip digest GitHub publishes, too.
    assert PIN.release.sha256 in (RECORD / "README.md").read_text(encoding="utf-8")


def test_pin_decoding_is_the_measured_one():
    win = PIN.decoding["windows"]
    assert (win.error_exit, win.status) == (1, "measured")
    readme = (RECORD / "README.md").read_text(encoding="utf-8")
    assert "PrusaSlicer reports errors with exit code 1" in readme
    assert "An exit code of 0 is not success." in readme
    assert win.source.startswith(PIN.record)


def test_pin_refuses_an_exe_outside_the_app_folder():
    data = PIN.model_dump()
    data["exe"]["path"] = "elsewhere/prusa-slicer-console.exe"
    with pytest.raises(ValueError, match="inside app/"):
        PrusaPin.model_validate(data)


# --- Verifying and locating an install --------------------------------------------------

APP = {"PrusaSlicer-2.9.7/prusa-slicer-console.exe": b"exe",
       "PrusaSlicer-2.9.7/PrusaSlicer.dll": b"dll",
       "PrusaSlicer-2.9.7/resources/x.txt": b"x"}


def _tree(app: dict[str, bytes]) -> str:
    """The tree hash, computed here from its definition (not with tdmg.slicer)."""
    lines = sorted(f"{rel}\t{_sha(d)}" for rel, d in app.items())
    return _sha("".join(x + "\n" for x in lines).encode())


def fake_prusa_pin(app=None) -> PrusaPin:
    app = app or APP
    return PIN.model_copy(update={
        "exe": PIN.exe.model_copy(update={
            "sha256": _sha(app["PrusaSlicer-2.9.7/prusa-slicer-console.exe"])}),
        "libraries": [PIN.libraries[0].model_copy(update={
            "sha256": _sha(app["PrusaSlicer-2.9.7/PrusaSlicer.dll"])})],
        "app_tree": PIN.app_tree.model_copy(update={"files": len(app), "sha256": _tree(app)})})


def fake_prusa_install(root, app=None):
    for rel, data in (app or APP).items():
        path = root / "app" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def test_verify_accepts_matching_hashes(tmp_path):
    pin = fake_prusa_pin()
    found = verify_prusa_install(fake_prusa_install(tmp_path), pin, full_tree=True)
    assert found == {"exe_sha256": pin.exe.sha256,
                     "libraries": {DLL: pin.libraries[0].sha256},
                     "app_tree": {"files": 3, "sha256": pin.app_tree.sha256}}
    assert "app_tree" not in verify_prusa_install(tmp_path, pin)


@pytest.mark.parametrize(("change", "what"), [
    ({"PrusaSlicer-2.9.7/prusa-slicer-console.exe": b"other"}, "prusa-slicer-console.exe"),
    ({"PrusaSlicer-2.9.7/PrusaSlicer.dll": b"patched"}, "PrusaSlicer.dll")])
def test_verify_refuses_a_changed_exe_or_library(tmp_path, change, what):
    pin = fake_prusa_pin()
    fake_prusa_install(tmp_path, {**APP, **change})
    with pytest.raises(SlicerError, match=f"{what}.*does not match the pin.*"
                                          "setup_prusaslicer.py"):
        verify_prusa_install(tmp_path, pin)


@pytest.mark.parametrize("change", [{"PrusaSlicer-2.9.7/resources/x.txt": b"changed"},
                                    {"PrusaSlicer-2.9.7/extra.dll": b"new"}])
def test_verify_full_tree_refuses_any_other_change(tmp_path, change):
    pin = fake_prusa_pin()
    fake_prusa_install(tmp_path, {**APP, **change})
    assert verify_prusa_install(tmp_path, pin)["exe_sha256"] == pin.exe.sha256
    with pytest.raises(SlicerError, match="app tree.*does not match the pin"):
        verify_prusa_install(tmp_path, pin, full_tree=True)


def test_verify_refuses_a_missing_exe(tmp_path):
    with pytest.raises(SlicerError, match="prusa-slicer-console.exe is missing.*"
                                          "setup_prusaslicer.py"):
        verify_prusa_install(tmp_path, fake_prusa_pin())


def test_locate_is_none_when_not_configured(monkeypatch):
    monkeypatch.delenv(PRUSA_ENV_VAR, raising=False)
    assert locate_prusaslicer(None, fake_prusa_pin()) is None


def test_locate_from_the_argument_or_the_environment(tmp_path, monkeypatch):
    pin = fake_prusa_pin()
    root = fake_prusa_install(tmp_path / "prusa")
    monkeypatch.delenv(PRUSA_ENV_VAR, raising=False)
    found = locate_prusaslicer(root, pin)
    assert found.exe == root.resolve() / EXE
    assert found.verified["app_tree"] == {"files": 3, "sha256": pin.app_tree.sha256}
    assert found.pin == pin
    monkeypatch.setenv(PRUSA_ENV_VAR, str(root))
    assert locate_prusaslicer(None, pin) == found
    quick = locate_prusaslicer(None, pin, full_tree=False)
    assert "app_tree" not in quick.verified


def test_locate_refuses_a_folder_that_does_not_exist_or_does_not_match(tmp_path):
    pin = fake_prusa_pin()
    with pytest.raises(SlicerError, match="not a folder.*setup_prusaslicer.py"):
        locate_prusaslicer(tmp_path / "nowhere", pin)
    root = fake_prusa_install(tmp_path / "prusa",
                              {**APP, "PrusaSlicer-2.9.7/PrusaSlicer.dll": b"patched"})
    with pytest.raises(SlicerError, match="PrusaSlicer.dll.*does not match the pin"):
        locate_prusaslicer(root, pin)


@pytest.mark.slicer
@pytest.mark.skipif(not os.environ.get(PRUSA_ENV_VAR),
                    reason="TDMG_PRUSASLICER_DIR is not set to a verified PrusaSlicer install")
def test_the_real_install_matches_the_pin():
    found = locate_prusaslicer(None)
    assert found.verified["exe_sha256"] == PIN.exe.sha256
    assert found.verified["app_tree"] == {"files": PIN.app_tree.files,
                                          "sha256": PIN.app_tree.sha256}


# --- The explicit settings ----------------------------------------------------------------

# The A1 values in the flattened OrcaSlicer profiles (see tests/test_slice.py).
MACHINE = {"printable_area": ["0x0", "256x0", "256x256", "0x256"], "printable_height": "256",
           "nozzle_diameter": ["0.4"]}
PROCESS = {"layer_height": "0.2", "initial_layer_print_height": "0.2"}
FILAMENT = {"filament_diameter": ["1.75"]}


def test_explicit_settings_come_from_the_orca_profiles():
    settings = explicit_settings(MACHINE, PROCESS, FILAMENT)
    assert settings == {
        "--bed-shape": {"value": "0x0,256x0,256x256,0x256", "profile": "machine",
                        "key": "printable_area"},
        "--max-print-height": {"value": "256", "profile": "machine", "key": "printable_height"},
        "--nozzle-diameter": {"value": "0.4", "profile": "machine", "key": "nozzle_diameter"},
        "--layer-height": {"value": "0.2", "profile": "process", "key": "layer_height"},
        "--first-layer-height": {"value": "0.2", "profile": "process",
                                 "key": "initial_layer_print_height"},
        "--filament-diameter": {"value": "1.75", "profile": "filament",
                                "key": "filament_diameter"}}
    # The research record's command used exactly these values.
    readme = (RECORD / "README.md").read_text(encoding="utf-8")
    for flag, s in settings.items():
        assert f"{flag} {s['value']}" in readme, flag
    stl, gcode = Path("m.stl"), Path("o.gcode")
    assert gcode_args(stl, gcode, settings) == [
        "--export-gcode", "m.stl", "-o", "o.gcode", "--bed-shape", "0x0,256x0,256x256,0x256",
        "--max-print-height", "256", "--nozzle-diameter", "0.4", "--layer-height", "0.2",
        "--first-layer-height", "0.2", "--filament-diameter", "1.75"]
    assert info_args(stl) == ["--info", "m.stl"]


@pytest.mark.parametrize(("profiles", "message"), [
    (({**MACHINE, "printable_height": None}, PROCESS, FILAMENT), "printable_height"),
    (({k: v for k, v in MACHINE.items() if k != "printable_area"}, PROCESS, FILAMENT),
     "printable_area"),
    (({**MACHINE, "printable_area": ["0x0", "256y0", "256x256"]}, PROCESS, FILAMENT),
     "printable_area"),
    (({**MACHINE, "nozzle_diameter": ["0.4", "0.6"]}, PROCESS, FILAMENT), "nozzle_diameter"),
    ((MACHINE, {**PROCESS, "layer_height": "nan"}, FILAMENT), "layer_height"),
    ((MACHINE, {"layer_height": "0.2"}, FILAMENT), "initial_layer_print_height"),
    ((MACHINE, PROCESS, {"filament_diameter": ["-1.75"]}), "filament_diameter"),
    ((MACHINE, PROCESS, {}), "filament_diameter")])
def test_a_missing_or_bad_setting_is_refused(profiles, message):
    with pytest.raises(SlicerError, match=message):
        explicit_settings(*profiles)


# --- Reading --info and the G-code -----------------------------------------------------------

# The research record's --info output for the Roadie (results.txt), as the exe prints it.
ROADIE_INFO = ("[model.stl]\r\nsize_x = 59.970630\r\nsize_y = 49.404216\r\nsize_z = 3.000000\r\n"
               "min_x = 0.029370\r\nmin_y = 0.000432\r\nmin_z = 0.000000\r\n"
               "max_x = 60.000000\r\nmax_y = 49.404648\r\nmax_z = 3.000000\r\n"
               "number_of_facets = 31200\r\nmanifold = yes\r\nnumber_of_parts =  1\r\n"
               "volume = 2277.742188\r\n")


def test_parse_info_reads_the_measured_output():
    info = parse_info(ROADIE_INFO)
    assert info["size_mm"] == [59.97063, 49.404216, 3.0]
    assert (info["facets"], info["manifold"], info["parts"]) == (31200, True, 1)
    assert info["volume_mm3"] == 2277.742188
    assert info["open_edges"] is None and info["repairs"] == {}
    # The values results.txt recorded for the same run.
    results = (RECORD / "results.txt").read_text(encoding="utf-8")
    assert ("size_x = 59.970630; size_y = 49.404216; size_z = 3.000000; number_of_facets = "
            "31200; manifold = yes; number_of_parts =  1; volume = 2277.742188") in results


def test_parse_info_reads_an_open_or_repaired_mesh():
    text = ROADIE_INFO.replace("manifold = yes", "manifold = no\r\nopen_edges = 3")
    info = parse_info(text.replace("\r\n", "\n"))
    assert (info["manifold"], info["open_edges"]) == (False, 3)
    repaired = parse_info(ROADIE_INFO.replace("volume", "facets_reversed = 2\nvolume"))
    assert repaired["repairs"] == {"facets_reversed": 2}
    zero = parse_info(ROADIE_INFO.replace("volume", "open_edges = 0\nvolume"))
    assert (zero["manifold"], zero["open_edges"]) == (True, 0)


@pytest.mark.parametrize(("text", "message"), [
    ("", "no object"),
    ("garbage", "no object"),
    (ROADIE_INFO + ROADIE_INFO, "2 objects"),
    (ROADIE_INFO.replace("volume = 2277.742188\r\n", ""), "volume"),
    (ROADIE_INFO.replace("manifold = yes", "manifold = maybe"), "manifold"),
    (ROADIE_INFO.replace("31200", "31200.5"), "number_of_facets"),
    (ROADIE_INFO.replace("2277.742188", "nan"), "volume"),
    (ROADIE_INFO + "colour = red\r\n", "colour"),
    (ROADIE_INFO + "volume = 1\r\n", "twice"),
    (ROADIE_INFO + "just text\r\n", "key = value")])
def test_parse_info_refuses_anything_else(text, message):
    with pytest.raises(SlicerError, match=message):
        parse_info(text)


def _prusa_gcode(layers=15, first=0.2, height=0.2, end=True, skip=(), z_at=None,
                 extra_start=(), extra_layer=()):
    """A G-code in the form PrusaSlicer 2.9.7 writes (the measured files): G90, M82,
    G92 E0, per layer ;LAYER_CHANGE, ;Z:, a G1 Z, travel, then extruding moves."""
    lines = ["; generated by PrusaSlicer 2.9.7 on 2026-11-11 at 12:08:29 UTC", "",
             "M104 S200 ; set temperature", ";TYPE:Custom", "G28 ; home all axes",
             "G1 Z5 F5000 ; lift nozzle", "G21", "G90", "M82", "G92 E0", "M107",
             *extra_start]
    for i in range(layers):
        z = f"{first + i * height:.6g}"
        word = f"{first + i * height:.3f}"
        lines += [";LAYER_CHANGE", f";Z:{z}", f";HEIGHT:{height:g}", "G1 E-2 F2400",
                  "G92 E0", f"G1 Z{(z_at or {}).get(i + 1, word)} F7800",
                  "G1 X108.197 Y100.432", "G1 E2 F2400", ";TYPE:External perimeter"]
        if i + 1 not in skip:
            lines += ["G1 X110.5 Y100.432 E2.1", "G1 X110.5 Y102 E2.25"]
        lines += list(extra_layer)
    lines += ["M107", "M84 ; disable motors", "; filament used [mm] = 1.0",
              "; prusaslicer_config = begin", "; layer_height = 0.2"]
    if end:
        lines.append("; prusaslicer_config = end")
    return ("\n".join(lines) + "\n").encode()


def test_gcode_layers_reads_the_measured_form():
    g = gcode_layers(_prusa_gcode())
    assert g["layers"] == 15 and g["complete"] is True
    assert g["z_mm"] == [float(f"{0.2 * (i + 1):.6g}") for i in range(15)]
    assert g["extrusions"] == [2] * 15
    assert g["filament_mm"] == pytest.approx([0.25] * 15)
    assert g["extrusion_z_mm"] == [[float(f"{0.2 * (i + 1):.3f}")] * 2 for i in range(15)]
    assert gcode_layers(b"G28\n") == {"layers": 0, "z_mm": [], "extrusions": [],
                                       "filament_mm": [], "extrusion_z_mm": [],
                                       "complete": False}


def test_gcode_layers_reports_what_the_checks_need():
    assert gcode_layers(_prusa_gcode(end=False))["complete"] is False
    cut = _prusa_gcode()
    cut = cut[:cut.rindex(b";Z:3")]            # cut inside the last layer
    assert gcode_layers(cut)["complete"] is False
    assert gcode_layers(_prusa_gcode(skip=(15,)))["extrusions"][-1] == 0
    assert gcode_layers(_prusa_gcode(z_at={4: "1.2"}))["extrusion_z_mm"][3] == [1.2, 1.2]
    # Retraction and priming (E only) are not extruding moves; nor is travel.
    assert gcode_layers(_prusa_gcode(skip=range(1, 16)))["extrusions"] == [0] * 15


@pytest.mark.parametrize(("change", "message"), [
    ({"extra_start": ["M83"]}, "M83"),
    ({"extra_layer": ["G91"]}, "G91"),
    ({"extra_layer": ["G2 X1 Y1 I1 J0 E3"]}, "G2"),
    ({"extra_layer": ["G10"]}, "G10"),
    ({"extra_layer": ["G92 X0"]}, "G92"),
    ({"extra_layer": ["G1 X1 X2"]}, "move word"),
    ({"extra_layer": ["G1 A1"]}, "move word"),
    ({"extra_layer": ["G1 X1.23456"]}, "3 decimals"),
    ({"extra_layer": ["G1 Xnan"]}, "not a number"),
    ({"extra_start": ["G1 X1 Y1", "G1 X5 Y5 E1"]}, "before its first"),
])
def test_gcode_layers_refuses_forms_it_does_not_read(change, message):
    with pytest.raises(SlicerError, match=message):
        gcode_layers(_prusa_gcode(**change))


def test_gcode_layers_refuses_extrusion_before_absolute_modes():
    data = b"G28\n;LAYER_CHANGE\n;Z:0.2\nG1 Z.2\nG1 X1 Y1\nG92 E0\nG1 X2 Y1 E1\n"
    with pytest.raises(SlicerError, match="G90, M82"):
        gcode_layers(data)


def test_gcode_layers_refuses_unpaired_z_lines():
    with pytest.raises(SlicerError, match="Z"):
        gcode_layers(b";LAYER_CHANGE\n;Z:abc\n")
    for data in (b";Z:0.2\n", b";LAYER_CHANGE\n;Z:0.2\n;Z:0.2\n"):
        with pytest.raises(SlicerError, match="its own"):
            gcode_layers(data)


def test_prusa_gcode_hashes():
    data = _prusa_gcode()
    other = data.replace(b"12:08:29", b"13:00:00")
    a, b = prusa_gcode_hashes(data), prusa_gcode_hashes(other)
    assert a["sha256"] != b["sha256"] and a["normalised_sha256"] == b["normalised_sha256"]
    assert a["normalised_lines"] == 1
    # Only line 1 is normalised; the same line anywhere else is a change.
    assert prusa_gcode_hashes(b"G28\n" + data)["normalised_lines"] == 0


# --- The tolerances -------------------------------------------------------------------------

def test_the_volume_bound_covers_the_measured_cube():
    # measure_prusa.py's cube: trimesh's 20 mm box, which --info reported as 8000.000488.
    stl = trimesh.creation.box((20, 20, 20)).export(file_type="stl")
    results = (RECORD / "results.txt").read_text(encoding="utf-8")
    assert "number_of_parts =  1; volume = 8000.000488" in results
    bound = volume_error_bound(stl)
    assert abs(8000.000488 - 8000.0) <= bound <= 1e-4 * 8000.0
    assert volume_tolerance_mm3(stl) == 2 * bound + INFO_HALF_UNIT


OWNER = REPO_ROOT / "artifacts" / "flat-runs"


@pytest.mark.parametrize(("name", "reported"), [("roadie-tol30-60x3-s3", 2277.742188),
                                                ("oddie-60x3-s3", 5033.670898)])
@pytest.mark.skipif(not OWNER.is_dir(), reason="the owner's flat runs are not on this machine")
def test_the_volume_bound_covers_the_measured_owner_models(name, reported):
    stl = (OWNER / name / "model.stl").read_bytes()
    record = json.loads((OWNER / name / "flat.json").read_bytes())["mesh"]
    error = abs(reported - record["volume_mm3"])
    bound = volume_error_bound(stl)
    assert error <= bound <= 0.01 * record["volume_mm3"]     # sound, and still useful


def _emulated_admesh_volume(stl: bytes) -> float:
    """admesh's get_volume as volume_error_bound describes it, in numpy float32."""
    f = np.float32
    tri = _tris(stl)
    t32 = tri.astype(f)
    p0 = t32[0, 0]
    cross = np.cross(t32[:, 1] - t32[:, 0], t32[:, 2] - t32[:, 0]).astype(f)
    length = np.sqrt((cross.astype(np.float64) ** 2).sum(axis=1))
    inverse = np.where(length < 1e-12, 0.0, 1 / np.where(length == 0, 1, length)).astype(f)
    normal = (cross * inverse[:, None]).astype(f)
    s = sum(np.cross(tri[:, i], tri[:, (i + 1) % 3]) for i in range(3)).astype(f)
    area = (f(0.5) * np.einsum("ij,ij->i", normal, s).astype(f)).astype(f)
    height = np.einsum("ij,ij->i", normal, (t32[:, 0] - p0).astype(f)).astype(f)
    terms = ((area * height).astype(f) / f(3)).astype(f)
    volume = f(0)
    for term in terms:
        volume = f(volume + term)
    return float(volume)


def test_the_emulation_reproduces_the_measured_cube():
    stl = trimesh.creation.box((20, 20, 20)).export(file_type="stl")
    assert f"{_emulated_admesh_volume(stl):.6f}" == "8000.000488"     # results.txt


@pytest.mark.parametrize("seed", range(12))
def test_the_volume_bound_holds_for_random_float32_meshes(seed):
    rng = np.random.default_rng(seed)
    kind = seed % 4
    if kind == 0:
        mesh = trimesh.creation.box(rng.uniform(0.2, 120, 3))
    elif kind == 1:
        mesh = trimesh.creation.icosphere(int(rng.integers(1, 4)), radius=rng.uniform(0.5, 40))
    elif kind == 2:          # slivers: a thin cylinder with many sections
        mesh = trimesh.creation.cylinder(radius=rng.uniform(0.05, 2),
                                         height=rng.uniform(5, 250),
                                         sections=int(rng.integers(200, 1500)))
    else:
        mesh = trimesh.creation.annulus(r_min=rng.uniform(1, 5), r_max=rng.uniform(6, 30),
                                        height=rng.uniform(0.2, 5))
    rotation = trimesh.transformations.random_rotation_matrix(rng.random(3))
    mesh.apply_transform(rotation)
    mesh.apply_translation(rng.uniform(-50, 250, 3))
    stl = mesh.export(file_type="stl")
    tri = _tris(stl)
    exact = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6
    error = abs(abs(_emulated_admesh_volume(stl)) - abs(exact))
    assert error <= volume_error_bound(stl), (seed, error)


@pytest.mark.parametrize("side", [5e-7, 1e-6, 1.0001e-6, 1.5e-6, 3e-6, 1e-5])
def test_the_volume_bound_covers_zeroed_normals(side):
    # Codex review 2026-11-11, finding 2: below admesh's normal cutoff a facet's term is 0.
    # A cube of side 1e-6 has |C| = 1e-12 per facet, so these straddle the cutoff.
    stl = trimesh.creation.box((side, side, side)).apply_translation((side,) * 3).export(
        file_type="stl")
    tri = _tris(stl)
    exact = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6
    error = abs(abs(_emulated_admesh_volume(stl)) - abs(exact))
    assert error <= volume_error_bound(stl), (side, error)


def test_the_volume_bound_covers_the_reviewers_cube():
    # Codex's case: a centred binary-STL cube of side 1e-6 mm. Every facet is zeroed, so
    # admesh's volume is 0; the old bound was about 4e-24 mm3 against an error of 1e-18.
    stl = trimesh.creation.box((1e-6, 1e-6, 1e-6)).export(file_type="stl")
    assert _emulated_admesh_volume(stl) == 0.0
    tri = _tris(stl)
    exact = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6
    error = abs(abs(_emulated_admesh_volume(stl)) - abs(exact))
    assert error <= volume_error_bound(stl)


def test_the_size_tolerance():
    assert size_tolerance_mm(60.0) == INFO_HALF_UNIT + 4 * STL_COORD_RTOL * 60.0
    # The Roadie's reported sizes are within it of the flat record (README, finding 2).
    for reported, record in ((59.970630, 59.97062849253416), (49.404216, 49.40421435981989)):
        assert abs(reported - record) <= size_tolerance_mm(60.0)
