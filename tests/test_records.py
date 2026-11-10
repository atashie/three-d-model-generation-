import json

import numpy as np
import pytest
from PIL import Image

import tdmg.records as records_module
from tdmg.records import (
    RecordError,
    canonical_json,
    check_output_dir,
    environment,
    png_bytes,
    write_outputs,
)

FILES = {"a.png": b"first", "b.png": b"second"}
RECORD = b'{"k": 1}\n'


def test_canonical_json_is_compact_and_key_sorted():
    assert canonical_json({"b": 1, "a": [1, {"d": 2, "c": "é"}]}) == (
        '{"a":[1,{"c":"é","d":2}],"b":1}'.encode())


def test_canonical_json_refuses_nan():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_environment_has_exactly_the_recorded_keys():
    assert set(environment()) == {"python", "numpy", "pillow", "opencv", "zlib"}


def test_png_bytes_round_trips(tmp_path):
    arr = np.arange(12, dtype=np.uint8).reshape(3, 4)
    (tmp_path / "x.png").write_bytes(png_bytes(arr))
    assert (np.asarray(Image.open(tmp_path / "x.png")) == arr).all()


def test_write_outputs_writes_all_files_and_the_record(tmp_path):
    out = tmp_path / "new" / "out"
    write_outputs(out, FILES, "rec.json", RECORD)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == {**FILES, "rec.json": RECORD}


def test_no_temporary_file_is_left_after_success(tmp_path):
    write_outputs(tmp_path / "a", FILES, "rec.json", RECORD)
    assert not [p for p in (tmp_path / "a").iterdir() if p.suffix == ".tmp"
                or p.name.startswith(".")]


def test_writes_into_an_existing_empty_folder(tmp_path):
    (tmp_path / "a").mkdir()
    write_outputs(tmp_path / "a", FILES, "rec.json", RECORD)
    assert json.loads((tmp_path / "a" / "rec.json").read_bytes()) == {"k": 1}


def test_refuses_a_non_empty_folder(tmp_path):
    out = tmp_path / "a"
    out.mkdir()
    (out / "keep.txt").write_bytes(b"x")
    with pytest.raises(RecordError, match="not empty"):
        write_outputs(out, FILES, "rec.json", RECORD)
    assert [p.name for p in out.iterdir()] == ["keep.txt"]


def test_refuses_a_file_as_output_folder(tmp_path):
    (tmp_path / "a").write_bytes(b"x")
    with pytest.raises(RecordError, match="is a file, not a folder"):
        write_outputs(tmp_path / "a", FILES, "rec.json", RECORD)
    assert (tmp_path / "a").read_bytes() == b"x"


def test_record_error_is_a_value_error():
    assert issubclass(RecordError, ValueError)


def test_a_concurrent_writer_is_detected_and_its_file_kept(tmp_path, monkeypatch):
    out = tmp_path / "a"
    out.mkdir()
    real = records_module.check_output_dir

    def racing(path):                     # another run writes b.png just after our check
        create = real(path)
        (out / "b.png").write_bytes(b"other run")
        return create

    monkeypatch.setattr(records_module, "check_output_dir", racing)
    with pytest.raises(RecordError, match="another run is writing"):
        write_outputs(out, FILES, "rec.json", RECORD)
    assert (out / "b.png").read_bytes() == b"other run"
    assert not (out / "rec.json").exists()


def test_a_concurrently_created_folder_is_detected(tmp_path):
    out = tmp_path / "a"
    create = check_output_dir(out)        # the caller checks, then encodes its files
    out.mkdir()                           # meanwhile another run creates the folder
    with pytest.raises(RecordError, match="another run is writing"):
        write_outputs(out, FILES, "rec.json", RECORD, create_folder=create)
    assert list(out.iterdir()) == []
