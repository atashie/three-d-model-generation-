"""tdmg library check and tdmg library verify (restructure plan Task 10), on entries made
by tdmg finish with the fake slicers (tests/test_finish.py's helpers), in temporary
folders only."""

import json
import shutil
import sys

import pytest
import test_finish
import test_slice
from test_finish import (
    R1,
    R2,
    STAMP_B,
    Crash,
    _call,
    _crash,
    _finish,
    _ready,
    _stamp,
    _tree,
)
from test_job_runner import _invoke, _plain

import tdmg
from tdmg import library
from tdmg.flat import THIN_RULE
from tdmg.library import COMPLETE_FILE, complete_bytes
from tdmg.records import replace_file
from tdmg.rules import load_rules

fake = test_slice.fake
prusa = test_slice.prusa
slicers = test_finish.slicers
repo = test_finish.repo


def _entry(tmp_path, tmp_path_factory, slicers, kind="r1"):
    folder = _ready(tmp_path, tmp_path_factory, slicers, kind)
    r = _finish(folder, slicers)
    assert r.exit_code == 0, r.output
    return tmp_path / "prints" / (R1 if kind == "r1" else R2)


def _check(prints, *args):
    r = _invoke("library", "check", *args, "--prints-dir", prints, "--jobs-dir",
                prints.parent / "jobs")
    return r, _plain(r.output)


def _verify(entry, slicers, *args, prusa_dir=True):
    extra = ["--prusaslicer-dir", slicers[1]] if prusa_dir else []
    r = _invoke("library", "verify", entry.name, "--prints-dir", entry.parent,
                "--slicer-dir", slicers[0], *extra, *args)
    return r, _plain(r.output)


def _snapshot(root):
    """Every file (with its SHA-256) and folder under root."""
    return _tree(root), sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


# --- check ------------------------------------------------------------------------------------

def test_a_clean_entry_passes(tmp_path, tmp_path_factory, slicers, repo):
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    for args in ((), (R1,)):
        r, out = _check(entry.parent, *args)
        assert r.exit_code == 0, r.output
        assert f"{R1}: ok" in out and "1 checked: 1 ok, 0 incomplete, 0 damaged" in out
        assert "unavailable" not in out


@pytest.mark.parametrize("rel", ["card.md", "private/model.stl", "source/roadie.png",
                                 "provenance.json"])
def test_a_tampered_file(tmp_path, tmp_path_factory, slicers, repo, rel):
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    path = entry / rel
    path.write_bytes(path.read_bytes() + b"x")
    r, out = _check(entry.parent)
    assert r.exit_code == 1, r.output
    assert f"{R1}: DAMAGED" in out
    assert f"{rel}: its SHA-256 is not the one COMPLETE lists" in out


def test_an_extra_unlisted_file(tmp_path, tmp_path_factory, slicers, repo):
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    (entry / "notes.txt").write_text("mine", encoding="utf-8")
    (entry / "empty").mkdir()
    r, out = _check(entry.parent, R1)
    assert r.exit_code == 1 and f"{R1}: DAMAGED" in out
    assert "notes.txt: not listed in COMPLETE (an extra file)" in out
    assert "empty/: a folder that holds no file COMPLETE lists" in out


def test_a_missing_tracked_file(tmp_path, tmp_path_factory, slicers, repo):
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    (entry / "card.md").unlink()
    r, out = _check(entry.parent)
    assert r.exit_code == 1 and "card.md: listed in COMPLETE but missing" in out


def test_a_clone_has_no_source_or_private_files(tmp_path, tmp_path_factory, slicers, repo):
    """source/ and private/ are git-ignored: a fresh clone has neither. That is a normal
    state, said plainly, not damage (exit 0); --require-private makes it a failure."""
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    shutil.rmtree(entry / "source")
    shutil.rmtree(entry / "private")
    r, out = _check(entry.parent)
    assert r.exit_code == 0, r.output
    assert f"{R1}: ok" in out and "DAMAGED" not in out
    assert "note: source unavailable: source/ is git-ignored and is not on this machine" in out
    assert "note: private files unavailable" in out
    assert "1 without their source on this machine" in out
    r, out = _check(entry.parent, "--require-private")
    assert r.exit_code == 1 and f"{R1}: UNAVAILABLE" in out


def test_a_source_folder_without_its_file_is_damage(tmp_path, tmp_path_factory, slicers,
                                                    repo):
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    (entry / "source" / "roadie.png").unlink()            # source/ is here, empty
    r, out = _check(entry.parent)
    assert r.exit_code == 1 and f"{R1}: DAMAGED" in out
    assert "source/roadie.png: listed in COMPLETE but missing (source/ is here" in out
    assert "source unavailable" not in out


def test_a_missing_complete(tmp_path, tmp_path_factory, slicers, repo):
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    (entry / COMPLETE_FILE).unlink()
    r, out = _check(entry.parent)
    assert r.exit_code == 1, r.output
    assert f"{R1}: INCOMPLETE" in out and f"run tdmg finish {R1} again" in out


def test_a_complete_not_in_form_is_damage(tmp_path, tmp_path_factory, slicers, repo):
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    (entry / COMPLETE_FILE).write_text("{}", encoding="utf-8")
    r, out = _check(entry.parent)
    assert r.exit_code == 1 and "COMPLETE is not a tdmg.complete/1 manifest" in out


def test_a_complete_written_again_after_an_edit(tmp_path, tmp_path_factory, slicers, repo):
    """COMPLETE certifies only itself: written again over an edited card, every hash in it
    matches, but STAGED (checked after the rebuild) does not."""
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    (entry / "card.md").write_text("# edited\n", encoding="utf-8")
    replace_file(entry, COMPLETE_FILE, complete_bytes(entry))
    assert library.verify_complete(entry) == []
    r, out = _check(entry.parent)
    assert r.exit_code == 1 and "card.md: COMPLETE's SHA-256 is not STAGED's" in out


def test_a_staging_leftover(tmp_path, tmp_path_factory, slicers, repo, monkeypatch):
    folder = _ready(tmp_path, tmp_path_factory, slicers)
    monkeypatch.setattr(library, "rebuild", _crash)       # stops after staging
    with pytest.raises(Crash):
        _call(folder, slicers)
    prints = tmp_path / "prints"
    assert (prints / f".staging-{R1}").is_dir()
    for args in ((), (R1,)):
        r, out = _check(prints, *args)
        assert r.exit_code == 1, r.output
        assert f".staging-{R1}: INCOMPLETE" in out and f"run tdmg finish {R1} again" in out


def test_a_published_entry_without_complete(tmp_path, tmp_path_factory, slicers, repo,
                                            monkeypatch):
    folder = _ready(tmp_path, tmp_path_factory, slicers)
    monkeypatch.setattr(library, "_purge", _crash)        # published, then stopped
    with pytest.raises(Crash):
        _call(folder, slicers)
    r, out = _check(tmp_path / "prints")
    assert r.exit_code == 1 and f"{R1}: INCOMPLETE" in out
    assert "it was published, but its finish stopped before writing COMPLETE" in out


def test_a_purge_that_did_not_end(tmp_path, tmp_path_factory, slicers, repo, monkeypatch):
    folder = _ready(tmp_path, tmp_path_factory, slicers)
    monkeypatch.setattr(library, "purge_job", _crash)     # COMPLETE written, job still there
    with pytest.raises(Crash):
        _call(folder, slicers)
    r, out = _check(tmp_path / "prints")
    assert r.exit_code == 1 and f"{R1}: INCOMPLETE" in out
    assert "the entry verifies, but" in out and "before its purge ended" in out


def test_check_cannot_check(tmp_path, tmp_path_factory, slicers, repo):
    r, out = _check(tmp_path / "nowhere")
    assert r.exit_code == 2 and "there is no library folder" in out
    (tmp_path / "prints").mkdir()
    r, out = _check(tmp_path / "prints", "missing")
    assert r.exit_code == 2 and "no library entry missing" in out
    r, out = _check(tmp_path / "prints", "Bad..Name")
    assert r.exit_code == 2
    r, out = _check(tmp_path / "prints")
    assert r.exit_code == 0 and "the library has no entries" in out


def test_check_uses_the_default_library(tmp_path, tmp_path_factory, slicers, repo,
                                        monkeypatch):
    """Without --prints-dir, check reads library.default_prints_dir() (a temporary folder in
    every test: tests/conftest.py)."""
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    monkeypatch.setattr(library, "default_prints_dir", lambda: entry.parent)
    r = _invoke("library", "check")
    assert r.exit_code == 0 and f"{R1}: ok" in _plain(r.output)


def test_a_folder_that_is_not_an_entry(tmp_path):
    prints = tmp_path / "prints"
    (prints / "Not An Entry").mkdir(parents=True)
    (prints / "README.md").write_text("a file beside the entries", encoding="utf-8")
    r, out = _check(prints)
    assert r.exit_code == 1 and "Not An Entry: DAMAGED not a library entry" in out


# --- verify -----------------------------------------------------------------------------------

def test_verify_identical(tmp_path, tmp_path_factory, slicers, fake, prusa, repo):
    """The same code and rules: identical, even with another G-code timestamp (slice.json's
    bytes are not compared); nothing in prints/ changes."""
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    before = _snapshot(entry.parent)
    _stamp(fake, prusa, STAMP_B)
    r, out = _verify(entry, slicers)
    assert r.exit_code == 0, r.output
    assert "identical to the historical run under the comparison rule" in out
    assert "PrusaSlicer configured (F6.portability was checked)" in out
    assert "unchanged since the historical run" in out
    assert "not compared: the stage folders' other files" in out
    assert _snapshot(entry.parent) == before


def test_verify_identical_r2(tmp_path, tmp_path_factory, slicers, repo):
    entry = _entry(tmp_path, tmp_path_factory, slicers, "r2")
    before = _snapshot(entry.parent)
    r, out = _verify(entry, slicers)
    assert r.exit_code == 0, r.output
    assert "identical to the historical run" in out
    assert _snapshot(entry.parent) == before


def _change_rule(monkeypatch, rule_id, value):
    """Every tdmg module that took load_rules by name sees rule_id with another default."""
    real = load_rules

    def patched(*args, **kw):
        rules = real(*args, **kw)
        rules[rule_id] = rules[rule_id].model_copy(update={"default": value})
        return rules
    for mod in [m for name, m in sys.modules.items()
                if name == "tdmg" or name.startswith("tdmg.")]:
        if getattr(mod, "load_rules", None) is real:
            monkeypatch.setattr(mod, "load_rules", patched)
    assert tdmg.library.load_rules is patched


def test_verify_with_a_changed_rule_value(tmp_path, tmp_path_factory, slicers, repo,
                                          monkeypatch):
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    before = _snapshot(entry.parent)
    old = load_rules()[THIN_RULE].default
    _change_rule(monkeypatch, THIN_RULE, old * 2)
    r, out = _verify(entry, slicers)
    assert r.exit_code == 1, r.output
    # What changed, named: the rule's value and the rules' hash.
    assert f"rule {THIN_RULE} default: was {json.dumps(old)}, now {json.dumps(old * 2)}" in out
    assert "rules_sha256" in out
    # How the outputs differ: the flat record, and its check's threshold.
    assert "differs from the historical run" in out
    assert "flat/flat.json: not byte for byte the historical record" in out
    assert ("check F3.thin_regions at $.checks[" in out
            and f"threshold was {json.dumps(old)}, now {json.dumps(old * 2)}" in out)
    assert "printable file flat/model.stl" not in out      # the STL itself is the same
    assert _snapshot(entry.parent) == before


def test_verify_refuses_without_the_source(tmp_path, tmp_path_factory, slicers, repo):
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    shutil.rmtree(entry / "source")
    before = _snapshot(entry.parent)
    r, out = _verify(entry, slicers)
    assert r.exit_code == 2 and "source unavailable" in out
    assert _snapshot(entry.parent) == before


def test_verify_without_private_files_compares_by_hash(tmp_path, tmp_path_factory, slicers,
                                                       repo):
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    shutil.rmtree(entry / "private")
    r, out = _verify(entry, slicers)
    assert r.exit_code == 0, r.output
    assert "identical to the historical run" in out


def test_verify_refuses_a_damaged_entry(tmp_path, tmp_path_factory, slicers, repo):
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    (entry / "job.yaml").write_bytes((entry / "job.yaml").read_bytes() + b"\n")
    r, out = _verify(entry, slicers)
    assert r.exit_code == 2 and "does not check" in out and "job.yaml" in out
    r = _invoke("library", "verify", "missing", "--prints-dir", entry.parent)
    assert r.exit_code == 2 and "no library entry missing" in _plain(r.output)


def test_verify_says_the_historical_prusaslicer_configuration(tmp_path, tmp_path_factory,
                                                              slicers, repo, monkeypatch):
    monkeypatch.delenv("TDMG_PRUSASLICER_DIR", raising=False)
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    r, out = _verify(entry, slicers, prusa_dir=False)
    assert "historical run" in out and "PrusaSlicer configured" in out
    assert "note: this run has PrusaSlicer not configured, unlike the historical run" in out
    assert "give --prusaslicer-dir" in out
    assert r.exit_code == 1, r.output                     # F6.portability differs
    assert "slice check F6.portability" in out


def test_verify_cannot_run_without_a_slicer(tmp_path, tmp_path_factory, slicers, repo,
                                            monkeypatch):
    monkeypatch.delenv("TDMG_ORCASLICER_DIR", raising=False)
    entry = _entry(tmp_path, tmp_path_factory, slicers)
    before = _snapshot(entry.parent)
    r = _invoke("library", "verify", R1, "--prints-dir", entry.parent, "--prusaslicer-dir",
                slicers[1])
    out = _plain(r.output)
    assert r.exit_code == 2 and "stage slice failed" in out
    assert _snapshot(entry.parent) == before
