"""The owner-image fixtures' resolution (tests/conftest.py, restructure plan Task 11): a
library source first, then a job source, then the legacy artifacts/selection-runs folder;
a skip names every path looked at; a present source that gives another selection is
passed over (with a warning at the test) and fails when nothing else gives the recorded
one. Rebuilt sources are compared by pixel hashes, the legacy copy by file bytes."""

import hashlib
import json
import shutil

import numpy as np
import pytest
import test_finish
import test_slice
from conftest import (
    OWNER_SOURCES,
    PIXELS_RECORD,
    SELECTIONS,
    BuiltSelection,
    OwnerSelectionAbsent,
    OwnerSelectionDiffers,
    OwnerSelections,
    OwnerSources,
    build_owner_selection,
    parse_research_rows,
    pixel_hashes,
    png_pixels,
    recorded,
    selection_ids,
)
from PIL import Image

from tdmg.jobs import load_job, new_job, save_job
from tdmg.selection import SelectionSpec, load_image, select_subject, write_selection

NAME = "pic"
SOURCES = {NAME: OwnerSources(library="pic-print", job="pic-job", legacy="pic-legacy")}
# Task 10's finished-entry helpers (fake slicers, a temporary git checkout).
fake = test_slice.fake
prusa = test_slice.prusa
slicers = test_finish.slicers
repo = test_finish.repo


def _sha16(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


@pytest.fixture
def stand_in(tmp_path):
    """A stand-in checkout with all three sources of one small image, and the recorded
    values (`want`) of its default selection."""
    root = tmp_path / "repo"
    images = tmp_path / "images"
    images.mkdir()
    rgba = np.zeros((30, 40, 4), np.uint8)
    rgba[5:25, 8:30] = (200, 30, 30, 255)
    Image.fromarray(rgba).save(images / "pic.png")
    new_job(root / "jobs", "pic-job", "flat-icon", images / "pic.png")
    # A library entry holds job.yaml and source/ as the job had them (tdmg.library).
    new_job(root / "prints", "pic-print", "flat-icon", images / "pic.png")
    legacy = root / "artifacts" / "selection-runs" / "pic-legacy"
    intake = load_image(images / "pic.png")
    record = write_selection(intake, select_subject(intake, SelectionSpec()), legacy)
    want = {"selection_id": record["selection_id"], "mask": _sha16(legacy / "mask.png"),
            "cutout": _sha16(legacy / "cutout.png"),
            "mask_pixels": png_pixels(legacy / "mask.png"),
            "cutout_pixels": png_pixels(legacy / "cutout.png")}
    return root, want


def _build(root, want, out):
    return build_owner_selection(NAME, out, want, repo=root, sources=SOURCES)


def _reason(note):
    return note.split(" was not used: ", 1)[1]


def test_the_library_source_comes_first(stand_in, tmp_path):
    root, want = stand_in
    built = _build(root, want, tmp_path / "out")
    assert (built.source, built.path) == ("library", root / "prints" / "pic-print")
    assert built.folder.parent == tmp_path / "out"
    # The rebuilt selection is the recorded one, byte for byte.
    legacy = root / "artifacts" / "selection-runs" / "pic-legacy"
    for f in ("selection.json", "mask.png", "cutout.png", "preview.png"):
        assert (built.folder / f).read_bytes() == (legacy / f).read_bytes()


def test_a_library_entry_without_its_source_images_falls_to_the_job(stand_in, tmp_path):
    root, want = stand_in
    shutil.rmtree(root / "prints" / "pic-print" / "source")   # git-ignored: another clone
    built = _build(root, want, tmp_path / "out")
    assert (built.source, built.path) == ("job", root / "jobs" / "pic-job")
    assert built.passed_over == ()


def test_then_the_legacy_folder_copied_and_left_as_it_was(stand_in, tmp_path):
    root, want = stand_in
    shutil.rmtree(root / "prints")
    shutil.rmtree(root / "jobs")
    legacy = root / "artifacts" / "selection-runs" / "pic-legacy"
    before = {p.name: p.read_bytes() for p in legacy.iterdir()}
    built = _build(root, want, tmp_path / "out")
    assert built.source == "artifacts" and built.folder != legacy
    assert {p.name: p.read_bytes() for p in built.folder.iterdir()} == before
    assert {p.name: p.read_bytes() for p in legacy.iterdir()} == before


def test_with_no_source_the_message_names_each_path(stand_in, tmp_path):
    root, want = stand_in
    shutil.rmtree(root / "prints" / "pic-print" / "source")
    shutil.rmtree(root / "jobs")
    (root / "artifacts" / "selection-runs" / "pic-legacy" / "mask.png").unlink()
    with pytest.raises(OwnerSelectionAbsent) as e:
        _build(root, want, tmp_path / "out")
    text = str(e.value)
    assert str(root / "prints" / "pic-print" / "source" / "pic.png") in text
    assert str(root / "jobs" / "pic-job" / "job.yaml") in text
    assert str(root / "artifacts" / "selection-runs" / "pic-legacy") in text
    assert "lacks mask.png" in text


def test_an_unmapped_source_is_named(stand_in, tmp_path):
    root, want = stand_in
    sources = {NAME: OwnerSources(library=None, job=None, legacy=None)}
    with pytest.raises(OwnerSelectionAbsent, match="library: none is mapped for pic"):
        build_owner_selection(NAME, tmp_path / "out", want, repo=root, sources=sources)


def _change_instructions(folder):
    job = load_job(folder)
    job["stages"]["select"]["instructions"] = "another selection"
    save_job(folder, job)


def test_a_library_source_giving_another_selection_is_passed_over(stand_in, tmp_path):
    root, want = stand_in
    _change_instructions(root / "prints" / "pic-print")
    built = _build(root, want, tmp_path / "out")
    assert built.source == "job"
    [note] = built.passed_over
    assert note.startswith(f"library source {root / 'prints' / 'pic-print'} was not used")
    assert _reason(note).startswith("its selection_id is")


def test_present_sources_that_all_differ_fail(stand_in, tmp_path):
    root, want = stand_in
    _change_instructions(root / "prints" / "pic-print")
    _change_instructions(root / "jobs" / "pic-job")
    shutil.rmtree(root / "artifacts")
    with pytest.raises(OwnerSelectionDiffers, match="no source gives the selection "
                                                    "recorded"):
        _build(root, want, tmp_path / "out")


def test_a_legacy_file_differing_from_the_record_fails(stand_in, tmp_path):
    root, want = stand_in
    shutil.rmtree(root / "prints")
    shutil.rmtree(root / "jobs")
    with pytest.raises(OwnerSelectionDiffers, match="cutout.png has sha256"):
        _build(root, {**want, "cutout": "0" * 16}, tmp_path / "out")


def test_a_changed_source_image_is_refused(stand_in, tmp_path):
    root, want = stand_in
    image = root / "jobs" / "pic-job" / "source" / "pic.png"
    shutil.rmtree(root / "prints")
    Image.fromarray(np.zeros((30, 40, 4), np.uint8)).save(image)
    built = _build(root, want, tmp_path / "out")
    assert built.source == "artifacts"
    [note] = built.passed_over
    assert note.startswith("job source")
    assert "source file source/pic.png has changed" in _reason(note)


def test_a_rebuilt_source_is_compared_by_pixels_not_file_bytes(stand_in, tmp_path):
    """PNG bytes depend on the Pillow and zlib versions: a rebuilt selection whose files
    differ from the recorded bytes but whose pixels agree is used; one whose pixels
    differ is passed over."""
    root, want = stand_in
    assert _build(root, {**want, "mask": "0" * 16, "cutout": "0" * 16},
                  tmp_path / "a").source == "library"
    shutil.rmtree(root / "artifacts")
    with pytest.raises(OwnerSelectionDiffers) as e:
        _build(root, {**want, "cutout_pixels": "0" * 64}, tmp_path / "b")
    assert "its cutout.png has pixel hash" in str(e.value)


def test_the_legacy_copy_is_compared_by_file_bytes(stand_in, tmp_path):
    root, want = stand_in
    shutil.rmtree(root / "prints")
    shutil.rmtree(root / "jobs")
    built = _build(root, {**want, "mask_pixels": "0" * 64}, tmp_path / "out")
    assert built.source == "artifacts"


def test_a_stage_error_is_passed_over(stand_in, tmp_path, monkeypatch):
    """What tdmg job run catches from a stage (STAGE_ERRORS: here an OSError) passes the
    source over, as a refusal does."""
    import conftest

    root, want = stand_in

    def fail(*a, **k):
        raise OSError("disk went away")
    monkeypatch.setattr(conftest, "_run_select", fail)
    built = _build(root, want, tmp_path / "out")
    assert built.source == "artifacts"
    assert [_reason(n) for n in built.passed_over] == [
        "its select stage failed: disk went away"] * 2


def test_a_finished_library_entry_is_a_source(tmp_path, tmp_path_factory, slicers,
                                              repo):
    """An entry made by tdmg finish (prints/NAME/ with job.yaml and source/; the job
    purged) rebuilds the selection the job had (Task 10's helpers, fake slicers)."""
    from test_library import _entry

    entry = _entry(tmp_path, tmp_path_factory, slicers)
    assert not (tmp_path / "jobs" / entry.name).exists()     # purged by finish
    select = test_finish._TEMPLATES["r1"] / "select"        # the job's select stage
    want = {"selection_id":
            json.loads((select / "selection.json").read_bytes())["selection_id"],
            "mask_pixels": png_pixels(select / "mask.png"),
            "cutout_pixels": png_pixels(select / "cutout.png")}
    sources = {"x": OwnerSources(library=entry.name, job=entry.name, legacy=None)}
    built = build_owner_selection("x", tmp_path / "out", want, repo=tmp_path,
                                  sources=sources)
    assert (built.source, built.path, built.passed_over) == ("library", entry, ())
    assert (built.folder / "selection.json").read_bytes() == (
        select / "selection.json").read_bytes()


def test_the_outcome_is_cached_and_the_warning_points_at_the_test(tmp_path):
    calls = []

    def build(name, out):
        calls.append(name)
        return BuiltSelection(out, "job", tmp_path / "jobs" / name,
                              ("library source X was not used: why",))
    sel = OwnerSelections(build, lambda base: tmp_path / base)
    for _ in range(2):
        with pytest.warns(UserWarning, match="library source X was not used: why; used "
                                             "the job source") as w:
            assert sel.get("n") == tmp_path / "owner-n"
        assert [r.filename for r in w] == [__file__]
    assert calls == ["n"]


def test_a_cached_skip_and_failure_are_given_again(tmp_path):
    calls = []

    def build(name, out):
        calls.append(name)
        raise (OwnerSelectionAbsent if name == "a" else OwnerSelectionDiffers)(f"{name}!")
    sel = OwnerSelections(build, lambda base: tmp_path / base)
    for _ in range(2):
        with pytest.raises(pytest.skip.Exception, match="a!"):
            sel.get("a")
        with pytest.raises(pytest.fail.Exception, match="d!"):
            sel.get("d")
    assert calls == ["a", "d"]


def test_band_survival_ids_must_agree_per_name():
    a, b = "a" * 64, "b" * 64
    text = f"== x: selection_id {a}, merge []\n== x: selection_id {a}, merge [[3, 1]]\n"
    assert selection_ids(text, "f.txt") == {"x": a}
    with pytest.raises(ValueError, match="f.txt gives selection x 2 different "
                                         "selection_ids"):
        selection_ids(f"== x: selection_id {a}\n== x: selection_id {b}\n", "f.txt")


def test_a_name_missing_from_a_record_names_the_file_and_the_selection():
    with pytest.raises(KeyError, match="f.txt records no selection_id for the owner "
                                       "selection oddie"):
        recorded({}, "oddie", "f.txt", "selection_id")


def test_the_records_give_every_owner_selection():
    assert set(pixel_hashes(PIXELS_RECORD.read_text(encoding="utf-8"))) == set(OWNER_SOURCES)
    assert set(parse_research_rows()) == set(OWNER_SOURCES)


def test_the_pixel_record_agrees_with_the_legacy_folders(research_rows):
    """PIXELS_RECORD's hashes are those of the legacy files, while they exist."""
    for name, rec in research_rows.items():
        d = SELECTIONS / OWNER_SOURCES[name].legacy
        if not (d / "cutout.png").is_file():
            continue
        assert png_pixels(d / "mask.png") == rec["mask_pixels"]
        assert png_pixels(d / "cutout.png") == rec["cutout_pixels"]


def test_the_mapping_covers_the_recorded_selections(research_rows):
    assert set(OWNER_SOURCES) == set(research_rows)
    for rec in research_rows.values():
        assert len(rec["selection_id"]) == 64
    # Roadie's library entry and job are the print of plan Task 14.
    assert OWNER_SOURCES["roadie-tol30"] == OwnerSources("roadie-drop", "roadie-drop",
                                                         "roadie-tol30")


def test_the_selection_id_record_agrees_with_the_legacy_folders(research_rows):
    """band-survival.txt's selection_id is the one the legacy selection.json holds, while
    that folder exists (Task 14 deletes Roadie's)."""
    for name, rec in research_rows.items():
        path = SELECTIONS / OWNER_SOURCES[name].legacy / "selection.json"
        if not path.is_file():
            continue
        assert json.loads(path.read_bytes())["selection_id"] == rec["selection_id"]
