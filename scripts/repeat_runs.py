"""Run today's pipeline twice from the recorded inputs, then compare the two runs.

    uv run python scripts/repeat_runs.py --out artifacts/repeat-runs/2026-11-16 \\
        --slicer-dir artifacts/tools/orcaslicer-2.5.0 \\
        --prusaslicer-dir artifacts/tools/prusaslicer-2.9.7 \\
        --images-dir <folder with roadie.png and oddie.png>

A measurement script (restructure plan, Task 0). It does not change the pipeline.

**Inputs.** The jobs are the six slice runs in `artifacts/slice-runs/fd8/` (the two R1
models and the four owner color plans) and the calibration strip. The script follows
each slice record back to the records it was made from, by their recorded SHA-256:
slice.json -> flat.json or colored.json -> colors.json -> selection.json. Every
parameter comes from those records. A parameter that the records do not give, or a
record that cannot be found, stops the script before anything runs (PlanError).

**Runs.** It drives the real CLI (`python -m tdmg.cli`, the code behind `tdmg`) into
OUT/run-a, then OUT/run-b. Each command's output is kept in RUN/_logs/.

**Comparison.** For every file in either run: present in both, byte-identical or not.
For a JSON file that differs, the JSON paths that differ. For a text file (G-code, logs),
the number of lines that differ and the first few. For a zip (3MF), the members that
differ. The result goes to OUT/report.json and OUT/report.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# The recorded jobs: slice runs in SLICE_RECORDS made with today's code (fd8, 2026-11-16).
R1_JOBS = ("roadie-r1", "oddie-r1")
COLOR_JOBS = ("roadie-tol30-60-drop-v3-f64", "roadie-tol30-60-keep-v4-f64",
              "oddie-60-merge-blues-v3-f64", "oddie-60-keep-merge-blues-greens-v4-f64")
SLICE_RECORDS = "slice-runs/fd8"
STRIP_RECORD = "test-strips/strip.json"
# The file the owner printed (written 2026-11-13); the rebuild is checked against it.
ROADIE_DROP_PRINTED_3MF = "ec2961184e1b235fb4f051c00824095f9642128a565a829e4f1527b1a4f822d7"

TEXT_SUFFIXES = {".gcode", ".txt", ".md", ".log", ".failed", ".yaml", ".csv"}
ZIP_SUFFIXES = {".3mf"}
EXAMPLE_LINES = 3      # differing text lines shown per file in the report


class PlanError(RuntimeError):
    """A job cannot be rebuilt from its records alone."""


# ---------------------------------------------------------------- comparison helpers

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_diff_paths(a, b, path: str = "$") -> list[str]:
    """The JSON paths at which a and b differ, in a stable order.

    Dicts are compared key by key (a key in one only is reported at its path). Lists are
    compared index by index; extra items in the longer list are reported at their index.
    A type change, or unequal scalars, is reported at that path. 1 and 1.0 are equal, as in
    JSON; True and 1 are not.
    """
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for key in sorted(set(a) | set(b)):
            sub = f"{path}.{key}"
            if key not in a or key not in b:
                out.append(sub)
            else:
                out += json_diff_paths(a[key], b[key], sub)
        return out
    if isinstance(a, list) and isinstance(b, list):
        out = []
        for i in range(max(len(a), len(b))):
            sub = f"{path}[{i}]"
            if i >= len(a) or i >= len(b):
                out.append(sub)
            else:
                out += json_diff_paths(a[i], b[i], sub)
        return out
    if isinstance(a, bool) != isinstance(b, bool) or type(a) is not type(b) and not (
            isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return [path]
    return [] if a == b else [path]


def generalize(path: str) -> str:
    """A JSON path with every list index replaced by [*]."""
    return re.sub(r"\[\d+\]", "[*]", path)


def _text_diff(a: bytes, b: bytes) -> dict:
    la, lb = a.decode("utf-8", "replace").splitlines(), b.decode("utf-8", "replace").splitlines()
    differing = [(i, x, y) for i, (x, y) in enumerate(zip(la, lb)) if x != y]
    return {"lines_a": len(la), "lines_b": len(lb), "differing_lines": len(differing),
            "examples": [{"line": i + 1, "a": x[:200], "b": y[:200]}
                         for i, x, y in differing[:EXAMPLE_LINES]]}


def _zip_diff(pa: Path, pb: Path) -> dict:
    with zipfile.ZipFile(pa) as za, zipfile.ZipFile(pb) as zb:
        ma = {i.filename: i for i in za.infolist()}
        mb = {i.filename: i for i in zb.infolist()}
        differ = sorted(n for n in set(ma) & set(mb) if za.read(n) != zb.read(n))
        meta = sorted(n for n in set(ma) & set(mb)
                      if (ma[n].date_time, ma[n].compress_type) !=
                      (mb[n].date_time, mb[n].compress_type))
        return {"only_a": sorted(set(ma) - set(mb)), "only_b": sorted(set(mb) - set(ma)),
                "members_differ": differ, "member_metadata_differ": meta}


def compare_file(pa: Path, pb: Path) -> dict:
    a, b = pa.read_bytes(), pb.read_bytes()
    entry = {"identical": a == b, "sha256_a": hashlib.sha256(a).hexdigest(),
             "sha256_b": hashlib.sha256(b).hexdigest()}
    if a == b:
        return entry
    if pa.suffix == ".json":
        try:
            paths = json_diff_paths(json.loads(a), json.loads(b))
        except ValueError as e:
            entry["json_error"] = str(e)
        else:
            entry["json_paths"] = paths
            if not paths:
                entry["note"] = "same JSON value, different bytes"
    elif pa.suffix in ZIP_SUFFIXES:
        entry["zip"] = _zip_diff(pa, pb)
    elif pa.suffix in TEXT_SUFFIXES or pa.name.endswith(".gcode.failed"):
        entry["text"] = _text_diff(a, b)
    return entry


def _files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def compare_runs(run_a: Path, run_b: Path) -> dict[str, dict]:
    """Every file under either run (logs aside), by relative path."""
    fa = {f for f in _files(run_a) if not f.startswith("_logs/")}
    fb = {f for f in _files(run_b) if not f.startswith("_logs/")}
    out = {}
    for rel in sorted(fa | fb):
        if rel not in fa or rel not in fb:
            out[rel] = {"identical": False, "only_in": "run-a" if rel in fa else "run-b"}
        else:
            out[rel] = compare_file(run_a / rel, run_b / rel)
    return out


# ---------------------------------------------------------------- recorded inputs

def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _by_sha(folder: Path, name: str, sha: str) -> Path:
    """The record `name` under folder/*/ whose file SHA-256 is sha (exactly one folder)."""
    hits = sorted(p for p in folder.glob(f"*/{name}") if sha256_file(p) == sha)
    if not hits:
        raise PlanError(f"no {folder}/*/{name} has SHA-256 {sha}")
    return hits[0]      # equal bytes: any copy gives the same inputs


def _by_field(folder: Path, name: str, key: str, value: str) -> list[Path]:
    return sorted(p for p in folder.glob(f"*/{name}") if _load(p).get(key) == value)


@dataclass
class Step:
    name: str                  # also the output folder, relative to the run folder
    args: list[str]            # CLI arguments after `tdmg`; {run} is the run folder
    expect_exit: set[int] = field(default_factory=lambda: {0})


def _rule_or_flag(control: dict, flag: str) -> list[str]:
    """No flag when the value came from its rule; else the flag with the recorded value."""
    if control.get("rule"):
        return []
    value = control["value"]
    return [flag, f"{value:g}" if isinstance(value, float) else str(value)]


def select_step(name: str, sel_json: Path, images_dir: Path) -> Step:
    rec = _load(sel_json)
    controls = rec["controls"]
    if controls.get("source") != "controls":
        raise PlanError(f"{sel_json}: made from a mask ({controls.get('source')}); "
                        "the mask file is not recorded")
    image = images_dir / rec["input"]["name"]
    if not image.is_file():
        raise PlanError(f"{image}: source image not found")
    if sha256_file(image) != rec["input"]["file_sha256"]:
        raise PlanError(f"{image}: SHA-256 differs from {sel_json} input.file_sha256")
    args = ["select", str(image), "--out", "{run}/" + name]
    interp = rec["interpretation"]
    if interp.get("machine_interpreted"):
        raise PlanError(f"{sel_json}: machine-interpreted instructions")
    if interp.get("text") is not None:
        args += ["--instructions", interp["text"]]
    args += _rule_or_flag(controls["alpha_min"], "--alpha-min")
    if "color_tolerance" in controls:
        args += _rule_or_flag(controls["color_tolerance"], "--tolerance")
    for x, y in controls["remove_at"]:
        args += ["--remove-at", f"{x},{y}"]
    for x, y in controls["keep_at"]:
        args += ["--keep-at", f"{x},{y}"]
    return Step(name, args)


def _slice_flags(slice_rec: dict, path: Path) -> list[str]:
    """--timeout-s only if not from its rule; refuse a skipped tree check (not PRINTABLE)."""
    params = slice_rec["params"]
    flags = _rule_or_flag(params["timeout_s"], "--timeout-s")
    if "prusaslicer_timeout_s" in params and not params["prusaslicer_timeout_s"].get("rule"):
        raise PlanError(f"{path}: PrusaSlicer timeout not from its rule; --timeout-s sets both")
    if not slice_rec["slicer"]["app_tree_verified"]:
        raise PlanError(f"{path}: made with --skip-tree-check")
    return flags


def _uses_prusa(slice_rec: dict) -> bool:
    return bool(slice_rec["portability"].get("configured"))


def plan_jobs(records: Path, configs: Path, images_dir: Path, slicer_dir: Path,
              prusaslicer_dir: Path) -> tuple[list[Step], list[dict]]:
    """The steps of one run, and how each job's inputs were traced (for the report)."""
    steps: list[Step] = []
    trace: list[dict] = []
    selected: dict[str, str] = {}     # selection.json sha -> step name

    def selection(sel_sha: str) -> str:
        if sel_sha not in selected:
            sel_json = _by_sha(records / "selection-runs", "selection.json", sel_sha)
            name = "select/" + sel_json.parent.name
            steps.append(select_step(name, sel_json, images_dir))
            selected[sel_sha] = name
            trace.append({"step": name, "from": sel_json.as_posix()})
        return selected[sel_sha]

    slicers = ["--slicer-dir", str(slicer_dir)]
    for job in R1_JOBS:
        sl_path = records / SLICE_RECORDS / job / "slice.json"
        sl = _load(sl_path)
        flat_json = _by_sha(records / "flat-runs", "flat.json", sl["links"]["flat_record_sha256"])
        fl = _load(flat_json)
        sel_jsons = [p for p in (records / "selection-runs").glob("*/selection.json")
                     if _load(p)["selection_id"] == fl["selection"]["selection_id"]]
        sel_shas = {sha256_file(p) for p in sel_jsons}
        if len(sel_shas) != 1:
            raise PlanError(f"{flat_json}: {len(sel_shas)} distinct selection.json files have "
                            "its selection_id")
        sel = selection(sel_shas.pop())
        p = fl["params"]
        if not p["smoothing"]["sigma_px"].get("rule"):
            smooth = ["--smooth-px", f"{p['smoothing']['sigma_px']['value']:g}"]
        else:
            smooth = []
        flat_name = f"flat/{job}"
        steps.append(Step(flat_name, ["flat", "{run}/" + sel, "--width-mm", f"{p['width_mm']:g}",
                                      "--thickness-mm", f"{p['thickness_mm']:g}",
                                      "--printer", p["printer"], *smooth,
                                      "--out", "{run}/" + flat_name]))
        prusa = ["--prusaslicer-dir", str(prusaslicer_dir)] if _uses_prusa(sl) else []
        steps.append(Step(f"slice/{job}", ["slice", "{run}/" + flat_name, *slicers, *prusa,
                                           *_slice_flags(sl, sl_path),
                                           "--out", "{run}/slice/" + job],
                          expect_exit={sl_exit(records, job)}))
        trace.append({"step": flat_name, "from": flat_json.as_posix()})
        trace.append({"step": f"slice/{job}", "from": sl_path.as_posix()})

    config_by_sha = {sha256_file(c): c for c in sorted(configs.glob("*.yaml"))}
    flag_names = {"colors": "--colors", "extract": "--extract", "edges": "--edges",
                  "base": "--base", "outlines": "--outlines"}
    for job in COLOR_JOBS:
        sl_path = records / SLICE_RECORDS / job / "slice.json"
        sl = _load(sl_path)
        colored_json = _by_sha(records / "colored-runs", "colored.json",
                               sl["links"]["colored_record_sha256"])
        cd = _load(colored_json)
        colors_id = cd["identity"]["colors_id"]
        hits = _by_field(records / "colors-runs", "colors.json", "colors_id", colors_id)
        if not hits:
            raise PlanError(f"{colored_json}: no colors.json has colors_id {colors_id}")
        colors_json = next((h for h in hits if h.parent.name == job), hits[0])
        co = _load(colors_json)
        sel = selection(co["input"]["selection_json_sha256"])
        cargs = ["colors", "{run}/" + sel, "--width-mm", f"{co['width_mm']:g}"]
        st = co["settings"]
        for key, source in sorted(st["sources"].items()):
            if source == "flag":
                if key not in flag_names:
                    raise PlanError(f"{colors_json}: {key} from a flag that does not exist")
                cargs += [flag_names[key], str(st["settings"][key])]
        if st["config_sha256"] is not None:
            config = config_by_sha.get(st["config_sha256"])
            if config is None:
                raise PlanError(f"{colors_json}: no config in {configs} has SHA-256 "
                                f"{st['config_sha256']}")
            cargs += ["--config", str(config)]
        if co["printer"] != "bambu-a1":    # tdmg colors has no --printer: it is fixed
            raise PlanError(f"{colors_json}: printer {co['printer']}, not the CLI's")
        colors_name = f"colors/{job}"
        steps.append(Step(colors_name, [*cargs, "--out", "{run}/" + colors_name]))
        p = cd["identity"]["params"]
        if not p["smoothing"]["sigma_px"].get("rule"):
            raise PlanError(f"{colored_json}: smoothing not from its rule (not allowed with "
                            "--colors)")
        colored_name = f"colored/{job}"
        steps.append(Step(colored_name, ["flat", "{run}/" + sel, "--colors", "{run}/" + colors_name,
                                         "--thickness-mm", f"{p['thickness_mm']:g}",
                                         "--width-mm", f"{p['width_mm']:g}",
                                         "--printer", p["printer"],
                                         "--out", "{run}/" + colored_name]))
        prusa = ["--prusaslicer-dir", str(prusaslicer_dir)] if _uses_prusa(sl) else []
        steps.append(Step(f"slice/{job}", ["slice", "{run}/" + colored_name, *slicers, *prusa,
                                           "--face", sl["params"]["face"],
                                           *_slice_flags(sl, sl_path),
                                           "--out", "{run}/slice/" + job],
                          expect_exit={sl_exit(records, job)}))
        trace += [{"step": colors_name, "from": colors_json.as_posix(),
                   "config": None if st["config_sha256"] is None
                   else config_by_sha[st["config_sha256"]].as_posix()},
                  {"step": colored_name, "from": colored_json.as_posix()},
                  {"step": f"slice/{job}", "from": sl_path.as_posix()}]

    strip_path = records / STRIP_RECORD
    sp = _load(strip_path)["params"]
    if not sp["check_tree"]:
        raise PlanError(f"{strip_path}: made without the tree check")
    steps.append(Step("strip", ["strip", "{run}/strip", *slicers,
                                *_rule_or_flag(sp["timeout_s"], "--timeout-s")]))
    trace.append({"step": "strip", "from": strip_path.as_posix()})
    return steps, trace


def sl_exit(records: Path, job: str) -> int:
    """The exit code in the recorded command output (SLICE_RECORDS/<job>.txt, last line
    'exit N'), so a step that exited as it did then is not reported as a failure."""
    txt = records / SLICE_RECORDS / f"{job}.txt"
    lines = txt.read_text(encoding="utf-8", errors="replace").split()
    if len(lines) < 2 or lines[-2] != "exit":
        raise PlanError(f"{txt}: no 'exit N' at the end")
    return int(lines[-1])


# ---------------------------------------------------------------- running

def run_steps(steps: list[Step], run_dir: Path, cwd: Path) -> list[dict]:
    if run_dir.exists():
        raise SystemExit(f"{run_dir} exists; give a fresh --out")
    (run_dir / "_logs").mkdir(parents=True)
    results = []
    for step in steps:
        args = [a.replace("{run}", run_dir.as_posix()) for a in step.args]
        t0 = time.monotonic()
        proc = subprocess.run([sys.executable, "-m", "tdmg.cli", *args], check=False,
                              cwd=cwd,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
        seconds = time.monotonic() - t0
        log = run_dir / "_logs" / (step.name.replace("/", "__") + ".txt")
        log.write_text(f"$ tdmg {' '.join(args)}\n{proc.stdout}"
                       f"--- stderr\n{proc.stderr}exit {proc.returncode}\n", encoding="utf-8")
        ok = proc.returncode in step.expect_exit
        print(f"{run_dir.name} {step.name}: exit {proc.returncode}"
              f"{'' if ok else ' (UNEXPECTED, recorded ' + str(sorted(step.expect_exit)) + ')'}"
              f" in {seconds:.0f} s", flush=True)
        results.append({"step": step.name, "args": args, "exit": proc.returncode,
                        "expected_exit": sorted(step.expect_exit), "seconds": round(seconds, 1)})
        if proc.returncode == 2:
            raise SystemExit(f"{step.name} failed with exit 2; see {log}")
    return results


def _log_diff(run_a: Path, run_b: Path) -> dict[str, dict]:
    """The command outputs, compared after replacing each run folder's name."""
    out = {}
    for la in sorted((run_a / "_logs").glob("*.txt")):
        lb = run_b / "_logs" / la.name
        ta = la.read_text(encoding="utf-8").replace(run_a.as_posix(), "{run}").replace(
            str(run_a), "{run}")
        tb = lb.read_text(encoding="utf-8").replace(run_b.as_posix(), "{run}").replace(
            str(run_b), "{run}")
        out[la.name] = ({"identical": True} if ta == tb else
                        {"identical": False, **_text_diff(ta.encode(), tb.encode())})
    return out


# ---------------------------------------------------------------- report

def volatile_table(files: dict[str, dict]) -> list[dict]:
    """(record file name, generalized JSON path) -> the run files where it differs."""
    rows: dict[tuple[str, str], list[str]] = {}
    for rel, e in files.items():
        for p in e.get("json_paths", []):
            rows.setdefault((Path(rel).name, generalize(p)), []).append(rel)
    return [{"record": k[0], "path": k[1], "files": v} for k, v in sorted(rows.items())]


def write_report(out: Path, report: dict) -> None:
    (out / "report.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n",
                                     encoding="utf-8")
    files = report["files"]
    same = [f for f, e in files.items() if e["identical"]]
    diff = [f for f, e in files.items() if not e["identical"]]
    lines = [f"# Repeat runs, {report['date']}", "",
             f"Machine: {report['machine']}", f"Command: `{report['command']}`", "",
             f"{len(files)} files; {len(same)} byte-identical; {len(diff)} differ.", "",
             "## Steps", "", "| step | exit run-a | exit run-b | recorded |", "|---|---|---|---|"]
    for a, b in zip(report["runs"]["run-a"], report["runs"]["run-b"]):
        lines.append(f"| {a['step']} | {a['exit']} | {b['exit']} | {a['expected_exit']} |")
    lines += ["", "## Files that differ", ""]
    for f in diff:
        e = files[f]
        lines.append(f"- `{f}`")
        if "only_in" in e:
            lines.append(f"  - only in {e['only_in']}")
        for p in e.get("json_paths", []):
            lines.append(f"  - `{p}`")
        if "text" in e:
            t = e["text"]
            lines.append(f"  - {t['differing_lines']} of {t['lines_a']}/{t['lines_b']} lines "
                         "differ; first:")
            for ex in t["examples"]:
                lines.append(f"    - line {ex['line']}: `{ex['a']}` / `{ex['b']}`")
        if "zip" in e:
            lines.append(f"  - members differ: {e['zip']['members_differ']}; metadata "
                         f"differ: {e['zip']['member_metadata_differ']}")
    lines += ["", "## JSON fields that differ", "", "| record | JSON path | files |",
              "|---|---|---|"]
    for row in report["volatile"]:
        lines.append(f"| {row['record']} | `{row['path']}` | {len(row['files'])} |")
    lines += ["", "## Command output (run folder name replaced)", ""]
    for name, e in report["logs"].items():
        lines.append(f"- {name}: {'identical' if e['identical'] else 'differs'}")
    lines += ["", "## Roadie drop model.3mf against the printed file", ""]
    for run, h in report["roadie_drop_3mf"].items():
        lines.append(f"- {run}: {h['sha256']} - "
                     f"{'matches' if h['matches_printed'] else 'DIFFERS from'} "
                     f"{ROADIE_DROP_PRINTED_3MF}")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True,
                    help="New folder; the runs go to OUT/run-a and OUT/run-b")
    ap.add_argument("--slicer-dir", type=Path, required=True, help="Pinned OrcaSlicer folder")
    ap.add_argument("--prusaslicer-dir", type=Path, required=True,
                    help="Pinned PrusaSlicer folder")
    ap.add_argument("--images-dir", type=Path, required=True,
                    help="Folder with the source images named in each selection.json")
    ap.add_argument("--records", type=Path, default=Path("artifacts"),
                    help="Folder holding the recorded runs (default artifacts)")
    ap.add_argument("--configs", type=Path, default=None,
                    help="Color configs folder (default RECORDS/colors-runs/configs)")
    ap.add_argument("--plan-only", action="store_true",
                    help="Print the steps of one run and stop")
    ns = ap.parse_args(argv)
    configs = ns.configs or ns.records / "colors-runs" / "configs"
    try:
        steps, trace = plan_jobs(ns.records, configs, ns.images_dir, ns.slicer_dir,
                                 ns.prusaslicer_dir)
    except PlanError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if ns.plan_only:
        for s in steps:
            print(f"{s.name}: tdmg {' '.join(s.args)}  (exit {sorted(s.expect_exit)})")
        return 0
    if ns.out.exists():
        print(f"error: {ns.out} exists; give a new folder", file=sys.stderr)
        return 2
    cwd = Path.cwd()
    runs = {name: run_steps(steps, ns.out / name, cwd) for name in ("run-a", "run-b")}
    files = compare_runs(ns.out / "run-a", ns.out / "run-b")
    drop = f"colored/{COLOR_JOBS[0]}/model.3mf"
    roadie = {}
    for name in runs:
        h = sha256_file(ns.out / name / drop)
        roadie[name] = {"file": drop, "sha256": h, "matches_printed": h == ROADIE_DROP_PRINTED_3MF}
    report = {"date": time.strftime("%Y-%m-%d"),
              "machine": f"{platform.platform()} {platform.machine()} "
                         f"Python {platform.python_version()}",
              "command": " ".join(["python", "scripts/repeat_runs.py", *(argv or sys.argv[1:])]),
              "trace": trace, "runs": runs, "files": files,
              "volatile": volatile_table(files),
              "logs": _log_diff(ns.out / "run-a", ns.out / "run-b"),
              "roadie_drop_3mf": roadie}
    write_report(ns.out, report)
    same = sum(e["identical"] for e in files.values())
    print(f"{len(files)} files; {same} byte-identical; {len(files) - same} differ; "
          f"see {ns.out / 'report.md'}")
    for name, h in roadie.items():
        print(f"{name} roadie drop model.3mf {h['sha256']} "
              f"{'matches' if h['matches_printed'] else 'DIFFERS from'} the printed file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
