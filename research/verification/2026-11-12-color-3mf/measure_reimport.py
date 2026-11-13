"""Re-import of the real model.3mf files (plan docs/plans/2026-11-12-color-3mf.md, Task 5).

Copies `model.3mf` from each owner-plan run in artifacts/colored-runs/ into OUT as
`<plan>.3mf`, then runs the same OrcaSlicer (plain) and PrusaSlicer runs as Task 1, with the
functions of measure_import.py, and prints a short summary per plan.

Usage (from the repo root, Windows):
    uv run python research/verification/2026-11-12-color-3mf/measure_reimport.py OUT

Research code: not part of the package, not tested.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import measure_import as mi

RUNS = mi.REPO / "artifacts/colored-runs"


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    copied = {}
    for run in sorted(p for p in RUNS.iterdir() if (p / "model.3mf").is_file()):
        dst = out / f"{run.name}.3mf"
        shutil.copyfile(run / "model.3mf", dst)
        palette = json.loads((run / "palette.json").read_text("utf-8"))
        copied[run.name] = {"sha256": mi.sha(dst), "bytes": dst.stat().st_size,
                            "palette_model_3mf_sha256": palette["model_3mf_sha256"],
                            "shells": [(s["body"], s["hex"]) for s in palette["shells"]]}
        if copied[run.name]["sha256"] != palette["model_3mf_sha256"]:
            raise SystemExit(f"{run.name}: model.3mf does not match palette.json")
    (out / "inputs.json").write_text(json.dumps(copied, indent=1), encoding="utf-8")
    print(json.dumps(copied, indent=1))
    mi.orca(out, "plain")
    mi.prusa(out)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
