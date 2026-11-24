"""F3.line_coverage on the roadie-thanksgiving job (widen plan, Task 5b; README, Addendum,
2026-11-23).

Reads jobs/roadie-thanksgiving/ (select/, colors/, job.yaml) only, copying them into a
scratch folder outside the repository, then runs tdmg flat --colors and tdmg slice (both
faces) there with the pinned slicers, and prints one table row per face.

    uv run python research/verification/2026-11-22-thin-line-print/measure_line_coverage.py \
        WIDTH OUT_DIR

WIDTH: "job" uses the job's own plan (colors/, 0.41 mm); a number in mm remakes the plan
with that line_width_mm and the job's other colors settings. OUT_DIR must be outside the
repository and must not exist yet; it is created, and nothing is deleted. The slicers:
artifacts/tools/orcaslicer-2.5.0 and artifacts/tools/prusaslicer-2.9.7.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import yaml

from tdmg.color_slicing import make_color_slice
from tdmg.colored_flat import make_colored_flat
from tdmg.colors import COLORS_PRINTER, make_colors
from tdmg.job_runner import COLOR_FLAG_KEYS, COLORS_CONFIG_NAME, colors_config
from tdmg.profiles import load_printer
from tdmg.rules import load_rules

REPO = Path(__file__).resolve().parents[3]
JOB = REPO / "jobs" / "roadie-thanksgiving"
ORCA = REPO / "artifacts" / "tools" / "orcaslicer-2.5.0"
PRUSA = REPO / "artifacts" / "tools" / "prusaslicer-2.9.7"


def main(width: str, out: Path) -> None:
    out = out.resolve()
    if out == REPO or REPO in out.parents or out in REPO.parents:
        raise SystemExit(f"OUT_DIR must be outside the repository: {out}")
    if out.exists():
        raise SystemExit(f"OUT_DIR must not exist yet (nothing is deleted): {out}")
    if not JOB.is_dir():
        raise SystemExit(f"{JOB} is missing: this script runs only while the job exists")
    out.mkdir(parents=True)
    shutil.copytree(JOB / "select", out / "select")
    job = yaml.safe_load((JOB / "job.yaml").read_text(encoding="utf-8"))
    if width == "job":
        shutil.copytree(JOB / "colors", out / "colors")
    else:
        p = dict(job["stages"]["colors"], line_width_mm=float(width))
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / COLORS_CONFIG_NAME
            config.write_bytes(colors_config(p))
            make_colors(out / "select", out / "colors", width_mm=p["width_mm"],
                        flags={k: p[k] for k in COLOR_FLAG_KEYS}, config_path=config,
                        rules=load_rules(), printer=load_printer(COLORS_PRINTER))
    cf = job["stages"]["colored_flat"]
    flat = make_colored_flat(out / "select", out / "colors", out / "colored_flat",
                             thickness_mm=cf["thickness_mm"], width_mm=cf["width_mm"],
                             printer=cf["printer"])
    lines = flat["lines"]
    rec = make_color_slice(out / "colored_flat", out / "slice", slicer_dir=ORCA,
                           prusaslicer_dir=PRUSA, face="both")
    print("| Line width | Face | F3.line_coverage | Worst gap | Where | Samples over "
          "| Face verdict |")
    print("|---|---|---|---|---|---|---|")
    for face, f in rec["faces"].items():
        c = next(c for c in f["checks"] if c["id"] == "F3.line_coverage")
        m = c["measured"] or {}
        w = m.get("worst") or {}
        gap = ("not printed" if w and w["gap_mm"] is None else
               f"{w['gap_mm']:.3f} mm vs {w['allowance_mm']:g}" if w else "-")
        where = (f"layer {w['layer']} (z {w['z']:g}), line item {w['item']}, colored.json "
                 f"({w['at_colored_mm'][0]:.2f}, {w['at_colored_mm'][1]:.2f})" if w else "-")
        print(f"| {lines['width_mm']:g} mm ({lines['drawn']} lines) | {face} | "
              f"{c['status']} | {gap} | {where} | {m.get('samples_over_allowance', '-')} | "
              f"{f['verdict']} |")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], Path(sys.argv[2]))
