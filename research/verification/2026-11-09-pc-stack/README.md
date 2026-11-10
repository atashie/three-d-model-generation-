# PC stack verification, 2026-11-09

## Machine and environment

Measured with PowerShell CIM, Get-Volume, and uv:

- Windows 11 Pro, 10.0.26200, x64.
- Intel Core i9-12900K: 16 cores, 24 logical processors.
- OS-visible RAM: 68,378,660,864 bytes (63.68 GiB).
- C: volume: 3,999,686,193,152 bytes; 1,574,305,878,016 bytes free before installation.
- uv 0.11.29 (901092ee1, x86_64-pc-windows-msvc).
- Python 3.13.1, existing local CPython; the Mac used 3.13.15.

## Core results

`uv sync` succeeded. `uv run pytest`: **133 passed** in 31.13 seconds.
`uv run ruff check .` and `uv run python scripts/gen_docs.py --check` passed.
See `pytest.txt` and `core-freeze.txt` for the test output and installed versions.

`uv build --wheel` succeeded. Installed the wheel in `artifacts/wheeltest`,
changed directory to the system temporary directory, and ran its Python with
`-m tdmg.cli rules`: all 26 rules loaded outside the checkout.
CI now includes `windows-latest`; its wheel check selects `Scripts/python.exe`
on Windows and `bin/python` elsewhere. The GitHub run is not yet verified.

## Original smoke scripts

The original scripts remain unchanged. Outputs are under ignored `artifacts/`.
Run the flat chain with `uv run python research/verification/2026-11-08-stack-smoke/flat_chain_smoke.py artifacts/pc-flat`;
the other scripts are in the same directory.

- Flat chain: one polygon after filtering, hole retained, watertight, consistent
  winding, positive volume; trimesh/manifold3d volume both 2756.2 mm³; genus 1.
  Both lib3mf objects passed its read-back manifold test. CAD tag volume 2341.1 mm³.
- Half-pixel experiment: high-resolution error -1.00% raw / +0.17% buffered;
  low-resolution -10.07% / +1.95%. These match the Mac's reported measurements.
- Two separate `det3mf.py` processes produced SHA-256
  `9dce4727d7273e9547d7c36c63add62cc5659e4a3760a649af23bd9fd56c643f`.
  This establishes Windows repeatability, not cross-platform byte equality.
- The flat script's STL repeatability check passed within its process.
- The original optional smoke script was attempted; native import failure
  prevents completing its functional checks. `check_optional.py` isolates each
  import and reruns the original unbuffered, recording exit status and output.

The prototype defects documented in the Mac report remain Phase 1 work.

## Optional packages

Installed separately with binary wheels only, leaving the core environment intact:

```powershell
uv venv artifacts/pc-optional --python 3.13
uv pip install --python artifacts/pc-optional/Scripts/python.exe --only-binary :all: pymeshlab open3d 'rembg[cpu]' onnxruntime bpy orca123d meshlib pymeshfix libigl point-cloud-utils trimesh
artifacts/pc-optional/Scripts/python.exe research/verification/2026-11-09-pc-stack/check_optional.py
```

| Package | Installed | Isolated import |
|---|---|---|
| pymeshlab | 2025.7.post1 | Process exit 3221225477 (0xC0000005) |
| open3d | 0.20.0 | DLL initialization failure |
| rembg | 2.0.87 | Process exit 3221225477 |
| onnxruntime | 1.31.1 | Process exit 3221225477 |
| bpy | 5.2.3 | DLL initialization failure |
| orca123d | 0.1.2 | Pass |
| meshlib | 3.1.4.297 | `meshlib.mrmeshpy` passes |
| pymeshfix | 0.18.1 | Pass |
| libigl | 2.6.3 | Pass |
| point-cloud-utils | 0.34.0 | Pass, with SyntaxWarnings |

See `optional-freeze.txt`, `optional-install.txt`, and `optional-results.json`.
The PowerShell install log wraps uv's stderr in a NativeCommandError despite
uv reporting successful installation; actual imports were checked separately.
Native failure causes are not established. These results apply to this environment,
not all Windows versions. No background-removal model was downloaded or executed.

## Next dependency

The CPU generation preflight is recorded in
[`CPU-PREFLIGHT.md`](../../experiments/2026-11-g3-local-vs-hosted/CPU-PREFLIGHT.md).
**Subsequent update:** the isolated Python 3.11 CPU trial is complete; see
[`RESULTS-PC.md`](../../experiments/2026-11-g3-local-vs-hosted/RESULTS-PC.md).
ONNX Runtime/rembg imports and background-removal inference succeeded in that
different environment; this does not explain or invalidate the original 3.13
import failures. Phase 1 has not started and no backend has been selected.
