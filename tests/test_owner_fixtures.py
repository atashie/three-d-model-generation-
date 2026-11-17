"""The owner-image fixtures' resolution (tests/conftest.py, restructure plan Task 11): a
library source first, then a job source, then the legacy artifacts/selection-runs folder;
a skip names every path looked at; a present source that gives another selection is
passed over with a warning, and fails when nothing else gives the recorded one."""

import hashlib
import json
import shutil

import numpy as np
import pytest
from conftest import (
    OWNER_SOURCES,
    OwnerSelectionAbsent,
    OwnerSelectionDiffers,
    OwnerSources,
    build_owner_selection,
)
from PIL import Image

from tdmg.jobs import load_job, new_job, save_job
from tdmg.selection import SelectionSpec, load_image, select_subject, write_selection

NAME = "pic"
SOURCES = {NAME: OwnerSources(library="pic-print", job="pic-job", legacy="pic-legacy")}


def _sha16(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


@pytest.fixture
def repo(tmp_path):
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
            "cutout": _sha16(legacy / "cutout.png")}
    return root, want


def _build(root, want, out):
    return build_owner_selection(NAME, out, want, repo=root, sources=SOURCES)


def test_the_library_source_comes_first(repo, tmp_path):
    root, want = repo
    built = _build(root, want, tmp_path / "out")
    assert (built.source, built.path) == ("library", root / "prints" / "pic-print")
    assert built.folder.parent == tmp_path / "out"
    # The rebuilt selection is the recorded one, byte for byte.
    legacy = root / "artifacts" / "selection-runs" / "pic-legacy"
    for f in ("selection.json", "mask.png", "cutout.png", "preview.png"):
        assert (built.folder / f).read_bytes() == (legacy / f).read_bytes()


def test_a_library_entry_without_its_source_images_falls_to_the_job(repo, tmp_path):
    root, want = repo
    shutil.rmtree(root / "prints" / "pic-print" / "source")   # git-ignored: another clone
    built = _build(root, want, tmp_path / "out")
    assert (built.source, built.path) == ("job", root / "jobs" / "pic-job")
    assert built.passed_over == ()


def test_then_the_legacy_folder_copied_and_left_as_it_was(repo, tmp_path):
    root, want = repo
    shutil.rmtree(root / "prints")
    shutil.rmtree(root / "jobs")
    legacy = root / "artifacts" / "selection-runs" / "pic-legacy"
    before = {p.name: p.read_bytes() for p in legacy.iterdir()}
    built = _build(root, want, tmp_path / "out")
    assert built.source == "artifacts" and built.folder != legacy
    assert {p.name: p.read_bytes() for p in built.folder.iterdir()} == before
    assert {p.name: p.read_bytes() for p in legacy.iterdir()} == before


def test_with_no_source_the_message_names_each_path(repo, tmp_path):
    root, want = repo
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


def test_an_unmapped_source_is_named(repo, tmp_path):
    root, want = repo
    sources = {NAME: OwnerSources(library=None, job=None, legacy=None)}
    with pytest.raises(OwnerSelectionAbsent, match="library: none is mapped for pic"):
        build_owner_selection(NAME, tmp_path / "out", want, repo=root, sources=sources)


def _change_instructions(folder):
    job = load_job(folder)
    job["stages"]["select"]["instructions"] = "another selection"
    save_job(folder, job)


def test_a_library_source_giving_another_selection_is_passed_over_with_a_warning(
        repo, tmp_path):
    root, want = repo
    _change_instructions(root / "prints" / "pic-print")
    with pytest.warns(UserWarning, match="library source .*pic-print was not used: its "
                                         "selection_id is"):
        built = _build(root, want, tmp_path / "out")
    assert built.source == "job" and len(built.passed_over) == 1


def test_present_sources_that_all_differ_fail(repo, tmp_path):
    root, want = repo
    _change_instructions(root / "prints" / "pic-print")
    _change_instructions(root / "jobs" / "pic-job")
    shutil.rmtree(root / "artifacts")
    with pytest.raises(OwnerSelectionDiffers, match="no source gives the selection "
                                                    "recorded"):
        _build(root, want, tmp_path / "out")


def test_a_legacy_file_differing_from_the_record_fails(repo, tmp_path):
    root, want = repo
    shutil.rmtree(root / "prints")
    shutil.rmtree(root / "jobs")
    with pytest.raises(OwnerSelectionDiffers, match="cutout.png has sha256"):
        _build(root, {**want, "cutout": "0" * 16}, tmp_path / "out")


def test_a_changed_source_image_is_refused(repo, tmp_path):
    root, want = repo
    image = root / "jobs" / "pic-job" / "source" / "pic.png"
    shutil.rmtree(root / "prints")
    Image.fromarray(np.zeros((30, 40, 4), np.uint8)).save(image)
    with pytest.warns(UserWarning, match="job source .* was not used: source file "
                                         "source/pic.png has changed"):
        built = _build(root, want, tmp_path / "out")
    assert built.source == "artifacts"


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
    from conftest import SELECTIONS
    for name, rec in research_rows.items():
        path = SELECTIONS / OWNER_SOURCES[name].legacy / "selection.json"
        if not path.is_file():
            continue
        assert json.loads(path.read_bytes())["selection_id"] == rec["selection_id"]
