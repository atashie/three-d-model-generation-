"""tdmg job confirm and the staleness of confirmations (restructure plan Task 8), with the
fake slicers of tests/test_slice.py.

The fake OrcaSlicer's G-code has no layers, so every slice it gives is NOT CERTIFIED. To
test a PRINTABLE slice, _printable rewrites slice.json's verdicts in place and stores the
new record's SHA-256 in state.json, as job run would have after a real PRINTABLE slice:
so the slice stage stays done, and confirm reads PRINTABLE. (Without the state.json
update the stage is stale: "its record changed since tdmg job run wrote it".)
"""

import datetime
import hashlib
import json
from pathlib import Path

import pytest
import test_slice
import yaml
from test_colored_flat import five_stripes
from test_job_runner import R1_SELECT, _invoke, _new, _plain, _run, _set

from tdmg import confirmations, job_runner, jobs
from tdmg.job_runner import (
    LOCK_FILE,
    STATE_FILE,
    STATE_SCHEMA,
    Machine,
    confirm,
    confirm_date,
    job_status,
)
from tdmg.jobs import JobError, load_job, save_job

fake = test_slice.fake
prusa = test_slice.prusa
WORDS = "done, and the newly printed items look great"


# The PrusaSlicer folder each test's jobs ran with, so confirm and status give the same
# --prusaslicer-dir as job run (it is part of the slice stage's key).
_PRUSA: dict[Path, Path] = {}


@pytest.fixture
def slicers(fake, prusa, tmp_path):
    orca, proot = fake(layers="auto"), prusa()
    _PRUSA[tmp_path / "jobs"] = proot
    yield orca, proot
    _PRUSA.pop(tmp_path / "jobs", None)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _r1(tmp_path, slicers, name="roadie"):
    folder = _new(tmp_path, name)
    _set(folder, *R1_SELECT, "flat.width_mm=60", "flat.thickness_mm=3")
    assert _run(folder, *slicers).exit_code in (0, 1)
    return folder


def _r2(tmp_path, slicers, name="roadie-drop", *extra):
    folder = _new(tmp_path, name, colors=True)
    _set(folder, "colors.width_mm=60", "colored_flat.thickness_mm=3", *extra)
    assert _run(folder, *slicers).exit_code in (0, 1)
    return folder


def _prusa_args(folder) -> list:
    proot = _PRUSA.get(folder.parent)
    return [] if proot is None else ["--prusaslicer-dir", proot]


def _confirm(folder, *args):
    return _invoke("job", "confirm", folder.name, *args, "--jobs-dir", folder.parent,
                   *_prusa_args(folder))


def _machine(folder) -> Machine:
    return Machine(None, _PRUSA.get(folder.parent))


def _printable(folder: Path) -> None:
    """slice.json with every verdict PRINTABLE (module docstring)."""
    path = folder / "slice" / "slice.json"
    rec = json.loads(path.read_bytes())
    if "faces" in rec:
        for face in rec["faces"].values():
            face["verdict"] = "PRINTABLE"
        for plate in rec["glue"]["plates"].values():
            plate["verdict"] = "PRINTABLE"
    else:
        rec["verdict"] = "PRINTABLE"
    _write_record(folder, "slice", rec)


def _write_record(folder: Path, stage: str, rec: dict) -> None:
    """Write a stage record and record its SHA-256 in state.json (module docstring)."""
    path = folder / stage / job_runner.STAGE_RECORDS[stage]
    path.write_bytes(json.dumps(rec).encode())
    state_path = folder / STATE_FILE
    state = json.loads(state_path.read_bytes())
    state["stages"][stage]["record_sha256"] = _sha(path)
    state_path.write_bytes(json.dumps(state).encode())


def _status(folder) -> str:
    result = _invoke("job", "status", folder.name, "--jobs-dir", folder.parent,
                     *_prusa_args(folder))
    assert result.exit_code == 0, result.output
    return _plain(result.output)


# --- each subject ---------------------------------------------------------------------------

def test_confirm_selection(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    before = load_job(folder)
    assert "check select/preview.png" in _status(folder)
    result = _confirm(folder, "--subject", "selection", "--owner-said", "yes, that's him")
    assert result.exit_code == 0, result.output
    job = load_job(folder)
    assert job["revision"] == before["revision"] + 1
    assert job["schema"] == "tdmg.job/2"
    [entry] = job["confirmations"]
    assert entry == {
        "subject": "selection", "owner_said": "yes, that's him",
        "date": datetime.date.today().isoformat(), "revision": before["revision"],
        "covers": {"select/selection.json": _sha(folder / "select" / "selection.json"),
                   "select/preview.png": _sha(folder / "select" / "preview.png")}}
    out = _plain(result.output)
    assert f"covers select/preview.png {entry['covers']['select/preview.png']}" in out
    status = _status(folder)
    assert "1. selection, " in status and '"yes, that\'s him": current' in status
    assert "check select/preview.png" not in status


def test_confirm_colors(tmp_path, slicers):
    folder = _r2(tmp_path, slicers)
    assert "check colors/regions.png" in _status(folder)
    result = _confirm(folder, "--subject", "colors", "--owner-said", "those colors",
                      "--date", "2026-11-16")
    assert result.exit_code == 0, result.output
    [entry] = load_job(folder)["confirmations"]
    assert entry["date"] == "2026-11-16"
    assert entry["covers"] == {"colors/colors.json": _sha(folder / "colors" / "colors.json"),
                               "colors/regions.png": _sha(folder / "colors" / "regions.png")}
    assert "check colors/regions.png" not in _status(folder)


def test_confirm_print_r1(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    _printable(folder)
    rec = json.loads((folder / "slice" / "slice.json").read_bytes())
    result = _confirm(folder, "--subject", "print", "--owner-said", WORDS)
    assert result.exit_code == 0, result.output
    [entry] = load_job(folder)["confirmations"]
    assert entry["route"] == "single" and entry["face"] is None
    assert entry["covers"] == {"flat/model.stl": _sha(folder / "flat" / "model.stl")}
    assert entry["slice_id"] == rec["slice_id"]
    assert entry["verdicts"] == {"flat/model.stl": "PRINTABLE"}
    assert entry["accept_not_certified"] is False
    status = _status(folder)
    assert "1. print (single), " in status and ": current" in status
    assert "to print (model.stl is in flat/)" not in status      # confirmed: not waiting


def test_confirm_print_ams_needs_the_face_and_binds_it(tmp_path, slicers):
    folder = _r2(tmp_path, slicers)
    _printable(folder)
    rec = json.loads((folder / "slice" / "slice.json").read_bytes())
    result = _confirm(folder, "--subject", "print", "--owner-said", WORDS)
    assert result.exit_code == 2 and "needs --face up or --face down" in _plain(result.output)
    result = _confirm(folder, "--subject", "print", "--owner-said", WORDS, "--face", "down")
    assert result.exit_code == 0, result.output
    [entry] = load_job(folder)["confirmations"]
    cf = folder / "colored_flat"
    assert entry["route"] == "ams" and entry["face"] == "down"
    assert entry["covers"] == {"colored_flat/model.3mf": _sha(cf / "model.3mf"),
                               "colored_flat/palette.json": _sha(cf / "palette.json")}
    assert entry["slice_id"] == rec["colorslice_id"]
    assert entry["verdicts"] == {"colored_flat/model.3mf": "PRINTABLE"}
    assert "1. print (ams, face down), " in _status(folder)


def test_confirm_print_glue_covers_every_plate(tmp_path, slicers):
    folder = _r2(tmp_path, slicers)
    colored = json.loads((folder / "colored_flat" / "colored.json").read_bytes())
    assert colored["glue"]["built"] is True
    plates = [b["file"] for b in colored["bodies"] if b["route"] == "glue"]
    assert "glue-base.stl" in plates and len(plates) >= 2
    # Not PRINTABLE (the fake slicer): refused, then accepted and recorded.
    result = _confirm(folder, "--subject", "print", "--route", "glue", "--owner-said", WORDS)
    out = _plain(result.output)
    assert result.exit_code == 2 and "not PRINTABLE" in out and "glue-base.stl" in out
    result = _confirm(folder, "--subject", "print", "--route", "glue", "--owner-said", WORDS,
                      "--accept-not-certified")
    assert result.exit_code == 0, result.output
    [entry] = load_job(folder)["confirmations"]
    assert sorted(entry["covers"]) == sorted(f"colored_flat/{p}" for p in plates)
    assert entry["face"] is None and entry["accept_not_certified"] is True
    assert set(entry["verdicts"].values()) == {"NOT CERTIFIED"}
    assert "print (glue, accepted NOT CERTIFIED)" in _status(folder)
    # A face is refused for the glue route.
    result = _confirm(folder, "--subject", "print", "--route", "glue", "--owner-said", WORDS,
                      "--face", "up", "--accept-not-certified")
    assert result.exit_code == 2 and "has no face" in _plain(result.output)


def test_a_glue_route_not_built_is_refused(tmp_path, slicers):
    folder = _r2(tmp_path, slicers, "roadie-keep", "colors.outlines=keep")
    colored = json.loads((folder / "colored_flat" / "colored.json").read_bytes())
    assert colored["glue"]["built"] is False
    result = _confirm(folder, "--subject", "print", "--route", "glue", "--owner-said", WORDS,
                      "--accept-not-certified")
    assert result.exit_code == 2 and "glue version not built" in _plain(result.output)


def test_print_not_certified_is_refused_unless_accepted(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    result = _confirm(folder, "--subject", "print", "--owner-said", WORDS)
    out = _plain(result.output)
    assert result.exit_code == 2 and "not PRINTABLE: flat/model.stl NOT CERTIFIED" in out
    assert load_job(folder)["confirmations"] == []
    result = _confirm(folder, "--subject", "print", "--owner-said", WORDS,
                      "--accept-not-certified")
    assert result.exit_code == 0, result.output
    [entry] = load_job(folder)["confirmations"]
    assert entry["accept_not_certified"] is True
    assert entry["verdicts"] == {"flat/model.stl": "NOT CERTIFIED"}


def test_accept_not_certified_is_refused_when_not_needed(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    _printable(folder)
    result = _confirm(folder, "--subject", "print", "--owner-said", WORDS,
                      "--accept-not-certified")
    assert result.exit_code == 2 and "is not needed" in _plain(result.output)


def test_a_face_that_was_not_sliced_is_refused(tmp_path, slicers):
    folder = _r2(tmp_path, slicers, "roadie-drop", "slice.face=up")
    result = _confirm(folder, "--subject", "print", "--owner-said", WORDS, "--face", "down",
                      "--accept-not-certified")
    assert result.exit_code == 2
    assert "face down was not sliced (faces sliced: up)" in _plain(result.output)


# --- staleness ------------------------------------------------------------------------------

def test_a_rerun_that_changes_bytes_makes_covering_confirmations_stale(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    for subject in ("selection", "print"):
        args = ["--accept-not-certified"] if subject == "print" else []
        assert _confirm(folder, "--subject", subject, "--owner-said", WORDS,
                        *args).exit_code == 0
    _set(folder, "flat.width_mm=50")
    result = _run(folder, *slicers)
    out = _plain(result.output)
    # Confirmed at revision 2 (job new, then one job set); select did not rerun.
    day = datetime.date.today().isoformat()
    assert f'1. selection, {day}, revision 2, "{WORDS}": current' in out
    assert "2. print (single, accepted NOT CERTIFIED)" in out
    assert "STALE (flat/model.stl changed)" in out
    assert "confirmation 2 (print (single, accepted NOT CERTIFIED)) is stale" in out
    status = job_status(folder, _machine(folder))
    assert [c.current for c in status.confirmations] == [True, False]
    # Nothing was removed or edited: the stale entry stays in job.yaml.
    assert len(load_job(folder)["confirmations"]) == 2
    # Confirming again adds a current entry; the stale one stays but no longer waits.
    assert _confirm(folder, "--subject", "print", "--owner-said", "the new one is fine",
                    "--accept-not-certified").exit_code == 0
    status = _status(folder)
    assert "2. print" in status and "STALE (flat/model.stl changed)" in status
    assert '3. print (single, accepted NOT CERTIFIED)' in status
    assert "is stale: ask the owner" not in status


def test_a_rerun_with_identical_bytes_keeps_confirmations_current(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    assert _confirm(folder, "--subject", "selection", "--owner-said", "yes").exit_code == 0
    assert _confirm(folder, "--subject", "print", "--owner-said", WORDS,
                    "--accept-not-certified").exit_code == 0
    before = (folder / "slice" / "slice.json").read_bytes()
    result = _invoke("job", "run", folder.name, "--jobs-dir", folder.parent, "--slicer-dir",
                     slicers[0], "--prusaslicer-dir", slicers[1], "--rerun", "select",
                     "--rerun", "flat", "--rerun", "slice")
    assert "select: ran" in result.output and "slice: ran" in result.output
    # The slice record's bytes may differ (G-code timestamps); its identity does not.
    after = json.loads((folder / "slice" / "slice.json").read_bytes())
    assert after["slice_id"] == json.loads(before)["slice_id"]
    status = job_status(folder, _machine(folder))
    assert [c.problem for c in status.confirmations] == [None, None]
    assert "STALE" not in _plain(result.output)


def test_a_hand_edit_to_a_covered_file_makes_it_stale(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    assert _confirm(folder, "--subject", "selection", "--owner-said", "yes").exit_code == 0
    (folder / "select" / "preview.png").write_bytes(b"edited")
    assert "STALE (select/preview.png changed)" in _status(folder)
    (folder / "select" / "preview.png").unlink()
    assert "STALE (select/preview.png is missing)" in _status(folder)


def test_a_changed_slice_verdict_makes_a_print_confirmation_stale(tmp_path, slicers):
    folder = _r2(tmp_path, slicers)
    _printable(folder)
    assert _confirm(folder, "--subject", "print", "--owner-said", WORDS, "--face",
                    "down").exit_code == 0
    path = folder / "slice" / "slice.json"
    rec = json.loads(path.read_bytes())
    rec["faces"]["down"]["verdict"] = "NOT CERTIFIED"
    path.write_bytes(json.dumps(rec).encode())
    assert "STALE (a slice verdict changed)" in _status(folder)
    rec["faces"]["down"]["verdict"] = "PRINTABLE"
    rec["colorslice_id"] = "0" * 64
    path.write_bytes(json.dumps(rec).encode())
    assert "STALE (the slice is a different one" in _status(folder)


# --- refusals --------------------------------------------------------------------------------

@pytest.mark.parametrize("words", ["", "   ", "\n\t"])
def test_empty_words_are_refused(tmp_path, slicers, words):
    folder = _r1(tmp_path, slicers)
    result = _confirm(folder, "--subject", "selection", "--owner-said", words)
    assert result.exit_code == 2 and "cannot be empty" in _plain(result.output)
    assert load_job(folder)["confirmations"] == []


def test_words_are_kept_verbatim(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    words = "  Looks great — \"done\"!\nSecond line✓ "
    _, entry = confirm(folder, "selection", words, machine=_machine(folder))
    assert entry["owner_said"] == words
    assert load_job(folder)["confirmations"][0]["owner_said"] == words
    assert (folder / "job.yaml").read_bytes().isascii()


def test_refusals_before_any_stage_ran(tmp_path):
    folder = _new(tmp_path, "roadie")
    result = _confirm(folder, "--subject", "selection", "--owner-said", "yes")
    assert result.exit_code == 2
    assert "stage select is not run; run tdmg job run first" in _plain(result.output)
    result = _confirm(folder, "--subject", "colors", "--owner-said", "yes")
    assert result.exit_code == 2
    assert "a R1 job confirms selection, print" in _plain(result.output)
    result = _confirm(folder, "--subject", "selection", "--owner-said", "yes", "--face", "up")
    assert result.exit_code == 2 and "are for --subject print" in _plain(result.output)
    result = _confirm(folder, "--subject", "print", "--owner-said", "yes", "--route", "ams")
    assert result.exit_code == 2
    assert load_job(folder)["revision"] == 1


def test_print_needs_every_stage_done(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    _set(folder, "flat.width_mm=50")             # flat and slice now stale
    result = _confirm(folder, "--subject", "print", "--owner-said", WORDS,
                      "--accept-not-certified")
    assert result.exit_code == 2 and "stage flat is stale" in _plain(result.output)


def test_an_unknown_route_is_refused(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    result = _confirm(folder, "--subject", "print", "--owner-said", WORDS, "--route", "ams",
                      "--accept-not-certified")
    assert result.exit_code == 2 and "has no route 'ams'" in _plain(result.output)


def test_a_color_plan_that_is_not_ready_cannot_be_confirmed(tmp_path, slicers):
    folder = _new(tmp_path, "stripes", colors=True, rgba=five_stripes())
    _set(folder, "colors.width_mm=60", "colored_flat.thickness_mm=3", "colors.colors=4",
         "colors.edges=exact")
    _run(folder, *slicers)
    result = _confirm(folder, "--subject", "colors", "--owner-said", "fine")
    assert result.exit_code == 2 and "the color plan is not ready" in _plain(result.output)


def test_a_file_that_differs_from_its_record_is_refused(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    (folder / "select" / "preview.png").write_bytes(b"edited")
    result = _confirm(folder, "--subject", "selection", "--owner-said", "yes")
    out = _plain(result.output)
    assert result.exit_code == 2
    assert "select/preview.png on disk is not the file select/selection.json names" in out
    (folder / "flat" / "model.stl").write_bytes(b"solid x\nendsolid x\n")
    result = _confirm(folder, "--subject", "print", "--owner-said", WORDS,
                      "--accept-not-certified")
    assert result.exit_code == 2
    assert "flat/model.stl on disk is not the file flat/flat.json names" in \
        _plain(result.output)


@pytest.mark.parametrize(("value", "match"), [
    ("16-11-2026", "must be a date written YYYY-MM-DD"),
    ("2026-02-30", "is not a real date"),
    ("2026-11-17", "is after today"),
])
def test_bad_dates_are_refused(value, match):
    with pytest.raises(JobError, match=match):
        confirm_date(value, today=datetime.date(2026, 11, 16))


def test_the_default_date_is_this_machines_local_date():
    before = datetime.date.today().isoformat()
    got = confirm_date(None)
    assert got in (before, datetime.date.today().isoformat())   # midnight may pass
    assert confirm_date(None, today=datetime.date(2026, 11, 16)) == "2026-11-16"
    assert confirm_date("2026-11-16", today=datetime.date(2026, 11, 16)) == "2026-11-16"


def test_the_lock_refuses_a_confirm(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    (folder / LOCK_FILE).write_bytes(b"pid 1\n")
    result = _confirm(folder, "--subject", "selection", "--owner-said", "yes")
    assert result.exit_code == 2 and "is locked" in _plain(result.output)


# --- append-only, and the schema ------------------------------------------------------------

def test_confirmations_are_append_only(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    confirm(folder, "selection", "yes", machine=_machine(folder))
    job, _ = confirm(folder, "selection", "yes again", machine=_machine(folder))
    assert [e["owner_said"] for e in job["confirmations"]] == ["yes", "yes again"]
    edited = load_job(folder)
    edited["confirmations"][0]["owner_said"] = "something else"
    with pytest.raises(JobError, match="cannot be changed or removed"):
        save_job(folder, edited)
    removed = load_job(folder)
    removed["confirmations"].pop(0)
    with pytest.raises(JobError, match="cannot be changed or removed"):
        save_job(folder, removed)
    # job set keeps them.
    _set(folder, "flat.smooth_px=0")
    assert len(load_job(folder)["confirmations"]) == 2


def test_a_job_1_file_is_read_and_written_as_job_2(tmp_path):
    folder = _new(tmp_path, "roadie")
    path = folder / "job.yaml"
    text = path.read_text().replace("schema: tdmg.job/2", "schema: tdmg.job/1")
    path.write_text(text, newline="\n")
    job = load_job(folder)
    assert job["schema"] == "tdmg.job/1"
    _set(folder, "flat.width_mm=60")
    assert load_job(folder)["schema"] == "tdmg.job/2"
    # A /1 file with confirmations is refused: /1 defines no entry.
    entry = {"subject": "selection", "owner_said": "yes", "date": "2026-11-16",
             "revision": 1, "covers": {"select/selection.json": "0" * 64,
                                       "select/preview.png": "0" * 64}}
    bad = {**job, "confirmations": [entry]}
    with pytest.raises(JobError, match="must be empty in a tdmg.job/1 job"):
        jobs.validate_job(bad)
    jobs.validate_job({**bad, "schema": "tdmg.job/2"})


def _entry(**kw):
    e = {"subject": "print", "owner_said": "yes", "date": "2026-11-16", "revision": 1,
         "covers": {"colored_flat/model.3mf": "0" * 64, "colored_flat/palette.json": "1" * 64},
         "route": "ams", "face": "down", "slice_id": "2" * 64,
         "verdicts": {"colored_flat/model.3mf": "PRINTABLE"}, "accept_not_certified": False}
    e.update(kw)
    return e


@pytest.mark.parametrize(("change", "match"), [
    ({"owner_said": " "}, "cannot be empty"),
    ({"date": "2026-13-01"}, "not a real date"),
    ({"revision": 5}, "from 1 to the job's revision"),
    ({"face": None}, "face must be one of up, down"),
    ({"route": "single"}, "must be one of ams, glue"),
    ({"slice_id": "x"}, "SHA-256"),
    ({"covers": {"colored_flat/model.3mf": "0" * 64}}, "covers must be exactly"),
    ({"covers": {"../model.3mf": "0" * 64}}, "'..'"),
    ({"verdicts": {"colored_flat/x.stl": "PRINTABLE"}}, "not a covered file"),
    ({"verdicts": {"colored_flat/model.3mf": "OK"}}, "must be one of PRINTABLE"),
    ({"accept_not_certified": True}, "must be false"),
    ({"verdicts": {"colored_flat/model.3mf": "NOT CERTIFIED"}}, "must be true"),
    ({"extra": 1}, "unknown key 'extra'"),
])
def test_entries_are_validated_strictly(tmp_path, change, match):
    folder = _new(tmp_path, "roadie-drop", colors=True)
    job = load_job(folder)
    jobs.validate_job({**job, "confirmations": [_entry()]})
    with pytest.raises(JobError, match=match):
        jobs.validate_job({**job, "confirmations": [_entry(**change)]})


def test_a_glue_entry_must_cover_the_base_plate(tmp_path):
    folder = _new(tmp_path, "roadie-drop", colors=True)
    job = load_job(folder)
    good = _entry(route="glue", face=None,
                  covers={"colored_flat/glue-base.stl": "0" * 64,
                          "colored_flat/glue-color-1-ff0000.stl": "1" * 64},
                  verdicts={"colored_flat/glue-base.stl": "PRINTABLE",
                            "colored_flat/glue-color-1-ff0000.stl": "PRINTABLE"})
    jobs.validate_job({**job, "confirmations": [good]})
    bad = {**good, "covers": {"colored_flat/glue-color-1-ff0000.stl": "1" * 64},
           "verdicts": {"colored_flat/glue-color-1-ff0000.stl": "PRINTABLE"}}
    with pytest.raises(JobError, match="glue route's files"):
        jobs.validate_job({**job, "confirmations": [bad]})


def test_the_status_line_without_confirmations():
    assert job_runner.CONFIRM_NOTE == "confirmations: none"


# --- review fixes (I-1, M-1, M-2, M-3, M-7, M-11) -------------------------------------------

def test_a_forged_slice_record_is_stale_and_confirm_refuses(tmp_path, slicers):
    """The review's P1: model.stl edited, slice.json's link and verdict edited to match."""
    folder = _r1(tmp_path, slicers)
    stl = folder / "flat" / "model.stl"
    stl.write_bytes(stl.read_bytes() + b"\n")
    path = folder / "slice" / "slice.json"
    rec = json.loads(path.read_bytes())
    rec["links"]["model_stl_sha256"] = _sha(stl)
    rec["verdict"] = "PRINTABLE"
    path.write_bytes(json.dumps(rec).encode())
    status = job_status(folder, _machine(folder))
    slice_ = status.stages[-1]
    assert slice_.state == "stale"
    assert slice_.note == "its record changed since tdmg job run wrote it"
    result = _confirm(folder, "--subject", "print", "--owner-said", WORDS)
    out = _plain(result.output)
    assert result.exit_code == 2 and "stage slice is stale" in out
    assert load_job(folder)["confirmations"] == []


def test_a_printable_file_must_match_the_record_that_made_it(tmp_path, slicers):
    """Even with the slice record's link matching, flat.json's outputs must too."""
    folder = _r1(tmp_path, slicers)
    stl = folder / "flat" / "model.stl"
    stl.write_bytes(stl.read_bytes() + b"\n")
    rec = json.loads((folder / "slice" / "slice.json").read_bytes())
    rec["links"]["model_stl_sha256"] = _sha(stl)
    _write_record(folder, "slice", rec)
    with pytest.raises(JobError, match="flat/model.stl on disk is not the file "
                                       "flat/flat.json names"):
        confirmations.print_cover(folder, load_job(folder), "single", None)


def test_state_json_holds_each_record_hash(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    state = json.loads((folder / STATE_FILE).read_bytes())
    assert state["schema"] == STATE_SCHEMA == "tdmg.jobstate/2"
    for stage, entry in state["stages"].items():
        record = folder / stage / job_runner.STAGE_RECORDS[stage]
        assert entry == {"key": entry["key"], "record_sha256": _sha(record)}


def test_an_old_state_file_makes_its_stages_rerun(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    path = folder / STATE_FILE
    state = json.loads(path.read_bytes())
    old = {"schema": "tdmg.jobstate/1",
           "stages": {s: {"key": e["key"]} for s, e in state["stages"].items()}}
    path.write_bytes(json.dumps(old).encode())
    status = job_status(folder, _machine(folder))
    assert status.stages[0].state == "stale"
    assert "an older tdmg" in status.stages[0].note
    result = _run(folder, *slicers)
    assert "select: ran" in result.output
    assert json.loads(path.read_bytes())["schema"] == "tdmg.jobstate/2"


def test_status_notes_a_printed_face_tdmg_did_not_choose(tmp_path, slicers):
    folder = _r2(tmp_path, slicers)
    rec = json.loads((folder / "slice" / "slice.json").read_bytes())
    for face in rec["faces"].values():
        face["verdict"] = "PRINTABLE"
    rec["preferred_face"] = "down"
    rec["print"] = "print face down"
    _write_record(folder, "slice", rec)
    assert _confirm(folder, "--subject", "print", "--owner-said", WORDS, "--face",
                    "up").exit_code == 0
    status = _status(folder)
    assert "printed face up; tdmg chose down" in status
    # A print of another face than tdmg's choice does not answer the print wait.
    assert "to print (files in colored_flat/)" in status
    assert _confirm(folder, "--subject", "print", "--owner-said", WORDS, "--face",
                    "down").exit_code == 0
    status = _status(folder)
    assert "to print (files in colored_flat/)" not in status
    assert status.count("tdmg chose") == 1


def test_a_glue_confirmation_does_not_answer_the_ams_wait(tmp_path, slicers):
    folder = _r2(tmp_path, slicers)
    assert _confirm(folder, "--subject", "print", "--route", "glue", "--owner-said", WORDS,
                    "--accept-not-certified").exit_code == 0
    assert "no face is PRINTABLE" in _status(folder)       # the ams wait (fake slicer)


def test_a_stale_entry_waits_unless_a_matching_one_is_current(tmp_path, slicers):
    folder = _r2(tmp_path, slicers)
    _printable(folder)
    assert _confirm(folder, "--subject", "print", "--owner-said", WORDS, "--face",
                    "down").exit_code == 0
    assert _confirm(folder, "--subject", "print", "--route", "glue", "--owner-said",
                    WORDS).exit_code == 0
    plate = next((folder / "colored_flat").glob("glue-base.stl"))
    plate.write_bytes(plate.read_bytes() + b"\n")
    status = _status(folder)
    # The ams entry is current, but it does not stand in for the stale glue entry.
    assert "confirmation 2 (print (glue)) is stale" in status


def test_current_with_stale_stages_says_a_rerun_decides(tmp_path, slicers):
    folder = _r1(tmp_path, slicers)
    assert _confirm(folder, "--subject", "print", "--owner-said", WORDS,
                    "--accept-not-certified").exit_code == 0
    _set(folder, "flat.width_mm=50")
    assert "current (stages stale: a rerun decides)" in _status(folder)


def test_verdicts_must_name_exactly_the_printed_models(tmp_path):
    folder = _new(tmp_path, "roadie-drop", colors=True)
    job = load_job(folder)
    both = {"colored_flat/model.3mf": "PRINTABLE", "colored_flat/palette.json": "PRINTABLE"}
    with pytest.raises(JobError, match="verdicts must name exactly colored_flat/model.3mf"):
        jobs.validate_job({**job, "confirmations": [_entry(verdicts=both)]})
    glue = _entry(route="glue", face=None,
                  covers={"colored_flat/glue-base.stl": "0" * 64,
                          "colored_flat/glue-color-1-ff0000.stl": "1" * 64},
                  verdicts={"colored_flat/glue-base.stl": "PRINTABLE"})
    with pytest.raises(JobError, match="verdicts must name exactly"):
        jobs.validate_job({**job, "confirmations": [glue]})


def test_an_unreadable_covered_file_makes_the_entry_stale(tmp_path, slicers, monkeypatch):
    folder = _r1(tmp_path, slicers)
    assert _confirm(folder, "--subject", "selection", "--owner-said", "yes").exit_code == 0
    real = Path.read_bytes

    def read_bytes(self):
        if self.name == "preview.png":
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    [c] = job_status(folder, _machine(folder)).confirmations
    assert c.problem.startswith("cannot read select/preview.png: Permission denied")


def test_a_hand_edit_of_job_yaml_is_not_prevented(tmp_path, slicers):
    """Documented limit (I-2): append-only holds for tdmg's own writes only."""
    folder = _r1(tmp_path, slicers)
    confirm(folder, "selection", "yes", machine=_machine(folder))
    confirm(folder, "selection", "yes again", machine=_machine(folder))
    path = folder / "job.yaml"
    data = yaml.safe_load(path.read_bytes())
    data["confirmations"].pop(0)
    path.write_bytes(yaml.safe_dump(data, sort_keys=False).encode())
    assert [e["owner_said"] for e in load_job(folder)["confirmations"]] == ["yes again"]


def test_the_help_says_a_print_confirmation_is_not_purge_permission():
    out = _plain(_invoke("job", "confirm", "--help").output)
    assert "A print confirmation is not permission to purge the job" in out
    assert "The owner's own words, verbatim" in out
    assert "Checked against this machine's date" in out
