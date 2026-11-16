"""scripts/repeat_runs.py: the JSON-diff and comparison helpers (the full run is not a test)."""

import json
import zipfile

import repeat_runs as rr  # scripts/ is on the pytest pythonpath (pyproject.toml)


def test_equal_values_give_no_paths():
    doc = {"a": [1, {"b": None}], "c": "x"}
    assert rr.json_diff_paths(doc, json.loads(json.dumps(doc))) == []


def test_nested_dict_and_list_paths():
    a = {"faces": {"up": {"gcode_sha256": "aa", "n": 1}}, "list": [1, [2, 3], {"k": 4}]}
    b = {"faces": {"up": {"gcode_sha256": "bb", "n": 1}}, "list": [1, [2, 9], {"k": 5}]}
    assert rr.json_diff_paths(a, b) == ["$.faces.up.gcode_sha256", "$.list[1][1]",
                                        "$.list[2].k"]


def test_missing_key_and_extra_list_items():
    assert rr.json_diff_paths({"a": 1, "b": 2}, {"a": 1, "c": 2}) == ["$.b", "$.c"]
    assert rr.json_diff_paths([1, 2], [1, 2, 3, 4]) == ["$[2]", "$[3]"]


def test_type_changes_are_differences():
    assert rr.json_diff_paths({"a": None}, {"a": {}}) == ["$.a"]
    assert rr.json_diff_paths({"a": [1]}, {"a": {"0": 1}}) == ["$.a"]
    assert rr.json_diff_paths(True, 1) == ["$"]
    assert rr.json_diff_paths(1, 1.0) == []          # equal JSON numbers
    assert rr.json_diff_paths(1, 1.5) == ["$"]


def test_generalize_replaces_indices():
    assert rr.generalize("$.list[12].a[0][3]") == "$.list[*].a[*][*]"


def test_compare_runs(tmp_path):
    a, b = tmp_path / "run-a", tmp_path / "run-b"
    for run, sha, line in ((a, "aa", "; time 1"), (b, "bb", "; time 2")):
        (run / "x").mkdir(parents=True)
        (run / "_logs").mkdir()
        (run / "_logs" / "step.txt").write_text(str(run))            # logs are left out
        (run / "same.bin").write_bytes(b"\x00\x01")
        (run / "x" / "rec.json").write_text(json.dumps({"id": "1", "gcode_sha256": sha}))
        (run / "x" / "plate_1.gcode").write_text(f"G1 X0\n{line}\nG1 X1\n")
        with zipfile.ZipFile(run / "m.3mf", "w") as z:
            z.writestr("same.xml", "<a/>")
            z.writestr("model.xml", sha)
    (a / "only.txt").write_text("a")
    out = rr.compare_runs(a, b)
    assert set(out) == {"same.bin", "x/rec.json", "x/plate_1.gcode", "m.3mf", "only.txt"}
    assert out["same.bin"]["identical"]
    assert out["x/rec.json"]["json_paths"] == ["$.gcode_sha256"]
    text = out["x/plate_1.gcode"]["text"]
    assert text["differing_lines"] == 1
    assert text["examples"] == [{"line": 2, "a": "; time 1", "b": "; time 2"}]
    assert out["m.3mf"]["zip"]["members_differ"] == ["model.xml"]
    assert out["only.txt"] == {"identical": False, "only_in": "run-a"}
    table = rr.volatile_table(out)
    assert table == [{"record": "rec.json", "path": "$.gcode_sha256",
                      "files": ["x/rec.json"]}]


def test_same_json_value_different_bytes(tmp_path):
    (tmp_path / "a.json").write_text('{"a": 1}')
    (tmp_path / "b.json").write_text('{"a":1}')
    e = rr.compare_file(tmp_path / "a.json", tmp_path / "b.json")
    assert not e["identical"] and e["json_paths"] == []
    assert e["note"] == "same JSON value, different bytes"
