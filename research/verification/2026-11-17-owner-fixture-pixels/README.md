# Owner selection pixel hashes, 2026-11-17

Restructure plan (`docs/plans/2026-11-16-restructure.md`), Task 11 review fix. The
question: what are the pixel hashes of the owner's two selections, so that
`tests/conftest.py` can check a selection rebuilt from a library entry or a job without
comparing PNG file bytes? PNG bytes depend on the Pillow and zlib versions
(`src/tdmg/selection.py`, write_selection: "PNG bytes depend on the Pillow and zlib
versions"); decoded pixels do not.

## What was measured

- **Files:** `artifacts/selection-runs/roadie-tol30/` and `artifacts/selection-runs/oddie/`
  (git-ignored). These are the selections of the color-palette Task 1 record
  (`research/verification/2026-11-11-color-palette/results.txt`). Their file SHA-256:

  | File | SHA-256 |
  |---|---|
  | `roadie-tol30/mask.png` | `0bf6bdc6d26f2a42d858c4b49ad1cde9f23ec248ee674b2a9e7ddd60b31c0065` |
  | `roadie-tol30/cutout.png` | `7729c18cb7dd69d56de2b9512a6ff8ed8c0d86af59487777a9950b60ac94efb4` |
  | `oddie/mask.png` | `421bddd781ddadb70f9aa1c0f85e8b8fa8a2775815abc4018dc990468db462fe` |
  | `oddie/cutout.png` | `5a7bfc486f86401153378f1ede3ac27dbb86365afe6fc655675c8d44afd1d7a3` |

  The first 16 hex digits of each agree with the `mask sha256` and `cutout sha256` of
  results.txt.
- **Hash:** `tdmg.selection.pixels_sha256` (SHA-256 of the array's shape and dtype, then
  its bytes) of:
  - mask: `np.array(Image.open("mask.png"))`, a (H, W) uint8 array;
  - cutout: `np.array(Image.open("cutout.png").convert("RGBA"))`, a (H, W, 4) uint8
    array.
- **Machine:** the Windows PC (Windows 11 Pro 10.0.26200, x64), Python 3.13.1, Pillow
  13.0.0, numpy 2.5.4, zlib 1.3.1. **Date:** 2026-11-17. **Code:** commit `7641942`.

## Command

From the repo root, `uv run python measure.py` with this script (kept in the
scratchpad, not in the repo):

```python
import json
import numpy as np
from PIL import Image
from tdmg.selection import pixels_sha256
for name in ("roadie-tol30", "oddie"):
    d = f"artifacts/selection-runs/{name}"
    rec = json.load(open(f"{d}/selection.json", encoding="utf-8"))
    mask = np.array(Image.open(f"{d}/mask.png"))
    cut = np.array(Image.open(f"{d}/cutout.png").convert("RGBA"))
    print(name, mask.shape, mask.dtype, cut.shape, cut.dtype)
    print("  mask.png pixels", pixels_sha256(mask))
    print("  cutout.png pixels", pixels_sha256(cut))
    print("  selection.json mask_pixels_sha256", rec["mask_pixels_sha256"])
    print("  pixels_sha256(mask.png == 255)", pixels_sha256(mask == 255))
```

## Results

Output shapes: roadie-tol30 mask (792, 836) uint8, cutout (792, 836, 4) uint8; oddie
mask (1013, 1024) uint8, cutout (1013, 1024, 4) uint8.

| Selection | mask.png pixels | cutout.png pixels |
|---|---|---|
| roadie-tol30 | `3f7f5786d273637cdeb92a6aeafec6ee5606f1602d61de3522349ba6a2680427` | `0c5e0cfb7aded0adcac38a4624b1eefbbd8b841c06c8bcac5d27273c38e18a94` |
| oddie | `f36a0d679503eec6235eff49482573e90caf175990fe54ffed7c68c1e7cc757c` | `a846daabf615f7365f45f9cc14df47ecd9d754e51b7e4408a45ba9152d0ed2f6` |

Cross-checks:
- `pixels_sha256(mask.png == 255)` equals each `selection.json`'s `mask_pixels_sha256`
  (roadie-tol30 `794ffb01…56b2`, oddie `6a4ba0fb…9939`).
- The first 16 hex digits of the cutout pixel hashes agree with the `cutout pixels
  sha256` lines in `research/verification/2026-11-11-color-palette/outline-shade.txt`
  (`0c5e0cfb7aded0ad`, `a846daabf615f736`).

## Use

`tests/conftest.py` reads the Results table. A selection rebuilt from a library entry
or a job must have these pixel hashes, as well as the `selection_id` recorded in
band-survival.txt. The legacy folders, which are copied, are still checked by file bytes
against results.txt.
