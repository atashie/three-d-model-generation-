# Subject selection (S0 intake + S1 selection) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `tdmg select`: a deterministic command that takes an image, the user's own
words, and explicit point controls. It writes a subject mask, a cutout, a preview to
review, and a provenance record. This is the first step of Phase 1 (R1), and it also
prepares inputs for the R4 generators.

**Architecture:** one module, `src/tdmg/selection.py`, with pure functions: load the
image (S0), build the mask (S1), and write the outputs. A thin Typer command in
`src/tdmg/cli.py` calls them. Thresholds come from a new rules file,
`rules/perception.yaml`, with evidence in
`research/verification/2026-11-10-subject-selection/`. Tests use synthetic images built
in code. The owner's real images are checked only locally.

**Tech Stack:** Python 3.13, numpy, OpenCV (`connectedComponents`), Pillow (EXIF
orientation, PNG I/O), pydantic, Typer, pytest. All are already core dependencies.

**Status:** written 2026-11-10; not started.

**Conventions for the implementer:**
- Each task's code shows new imports next to the code that needs them. Move them into
  the import block at the top of the file, because ruff flags imports below code (E402).
- Call `Image.fromarray(arr)` without a mode. Pillow infers L, RGB or RGBA from the
  array shape, and the `mode` argument is deprecated.
- **Checked during planning** (scratch prototype, 2026-11-10, Pillow 13.0.0, OpenCV 5.0.0):
  - the fixture coordinates and the tolerance-30 and tolerance-80 outcomes in Task 4;
  - byte-identical PNG output across runs;
  - EXIF orientation read from PNG;
  - the Roadie count in Task 8.

---

## Decisions this plan rests on

1. **Instructions are recorded, not interpreted.** The user's text is stored verbatim,
   and every record says `machine_interpreted: false`. Code applies only explicit
   controls: `--remove-at X,Y`, `--keep-at X,Y`, `--tolerance`, `--alpha-min`, or a
   corrected `--mask`. A phrase grammar or an opt-in LLM proposer can come later, and
   would produce the same controls. This was the recommendation the owner accepted by
   saying "proceed".
2. **The owner's images are not committed** until the owner confirms the rights to them.
   (Oddie appears to be a commercial game character.) The tests use synthetic images
   that copy the measured structure. The real images run in a local check (Task 8),
   which records only hashes and counts.
3. **The design comes from measurement**, not from priors. See
   `research/verification/2026-11-10-subject-selection/README.md`:
   - Roadie's "grey" disc is opaque, so existing transparency does not isolate the bird.
   - Colour alone splits the bird into feet and body.
   - "Flood-remove the disc at a point, then keep the piece at a point" leaves the bird as
     one piece at tolerances 20 to 40. It splits at 60.
   - Oddie is one piece at every alpha cutoff.
4. **The tool reports facts, not verdicts.** `status` is one of `empty`, `one_piece` or
   `multiple_pieces`. Whether the right subject was chosen is the user's call, made from
   the preview. Geometry checks cannot decide it.

## Behaviour contract (what the tests pin down)

- **Coordinates:** pixel `(x, y)`, with the origin at the top-left pixel, x to the right and
  y down, as in image viewers. They are measured after EXIF orientation.
- **Mask steps:**
  - Start from `alpha >= alpha_min`.
  - Each `--remove-at` takes the colour of its seed pixel. It removes the
    **4-connected** region of currently selected pixels within Euclidean RGB distance
    `tolerance` of that colour. Steps apply in the order given.
  - `--keep-at` keeps the union of the **8-connected** pieces that contain the keep
    points. Holes are counted with 4-connectivity, the standard counterpart to 8.
- **Errors (exit code 2, nothing written):**
  - a point outside the image;
  - a point on a pixel that is not selected;
  - a non-binary or wrong-size mask;
  - `--mask` combined with `--remove-at` or `--keep-at`;
  - an output folder that is not empty.
- **Warnings (written to the record):**
  - instructions given without any control or mask;
  - more than one piece;
  - user-mask pixels that are transparent in the image.
- **Outputs:** in the `--out` folder: `mask.png` (8-bit, 0 or 255), `cutout.png` (RGBA:
  the original colour where selected, all zeros elsewhere), `preview.png` (the original
  and the result side by side, over a checkerboard, with removed pixels tinted magenta),
  and `selection.json`.
- **Identity:**
  - `selection_id` is the SHA-256 of canonical JSON. It covers the algorithm version, the
    pixel hash, the resolved controls, the user-mask pixel hash and the instructions.
  - Running the same thing twice gives byte-identical files, within one pinned
    environment.
  - The record stores the input's basename only, never its full path.

---

### Task 1: Rules and units for selection thresholds

**Files:**
- Modify: `src/tdmg/rules.py` (the `UNITS` set, about line 31)
- Create: `rules/perception.yaml`
- Test: `tests/test_rules.py` (existing tests cover locators and hypothesis status)

**Step 1: Write the failing test.** Add this to `tests/test_rules.py`:

```python
def test_selection_rules_exist_with_their_units():
    assert RULES["perception.alpha.min_opaque"].unit == "alpha8"
    assert RULES["perception.flood.color_tolerance"].unit == "rgb8_distance"
```

**Step 2: Run it and check that it fails.**
Run: `uv run pytest tests/test_rules.py -k selection_rules -v`. Expected: FAIL with `KeyError`.

**Step 3: Implement.** In `src/tdmg/rules.py`, extend the units set:

```python
UNITS = {"mm", "mm2", "deg", "px", "x_nozzle", "triangles", "bool", "alpha8", "rgb8_distance"}
```

Create `rules/perception.yaml`:

```yaml
# Subject selection (stage S1). Our own defaults, chosen from software measurements on two
# owner images. kind stays hypothesis (validation untested) until wider tests support them.
- id: perception.alpha.min_opaque
  kind: hypothesis
  summary: A pixel counts as opaque image content if its 8-bit alpha is at least this.
  unit: alpha8
  default: 128
  range: [1, 255]
  evidence:
    - ref: research/verification/2026-11-10-subject-selection/README.md
      locator: "Oddie is one 8-connected piece at every alpha cutoff tested"
      provenance: primary
      validation: untested
      claim: On Oddie, cutoffs 1 to 255 all give one piece and change its area by 2.2%. 128 counts a pixel when it is at least half covered. Measured in software on one image; not a general result.
  notes: Adjustable with --alpha-min. It matters only for images with partly transparent pixels.

- id: perception.flood.color_tolerance
  kind: hypothesis
  summary: Euclidean distance in 8-bit RGB within which a pixel joins the colour region grown from a --remove-at point.
  unit: rgb8_distance
  default: 30
  range: [0, 441.7]
  evidence:
    - ref: research/verification/2026-11-10-subject-selection/README.md
      locator: "At tolerances 20, 30 and 40 the bird stays one piece; at 60 it splits."
      provenance: primary
      validation: untested
      claim: On Roadie, removing the disc from one seed left the bird as one piece at 20, 30 and 40 and split it at 60. 30 is the middle of the range that worked. Measured in software on one image; not a general result.
  notes: Adjustable with --tolerance. Lower values keep more of an anti-aliased fringe, and higher values can cut thin dark lines. Check the preview.
```

**Step 4: Run the tests and regenerate the docs.**
Run: `uv run pytest tests/test_rules.py -v`, then `uv run python scripts/gen_docs.py`, then
`uv run pytest tests/test_docs.py -q`. Expected: all PASS. `docs/reference/rules.md` now
lists both rules.

**Step 5: Commit.**
```bash
git add src/tdmg/rules.py rules/perception.yaml tests/test_rules.py docs/reference/rules.md
git commit -m "Add subject-selection threshold rules with measured evidence"
```

### Task 2: Synthetic fixtures

**Files:**
- Create: `tests/selection_fixtures.py`
- Test: `tests/test_selection.py` (new)

The fixtures copy the measured structure of the owner's images without copying the
images themselves.

**Step 1: Write the fixture builders and their sanity test.**

`tests/selection_fixtures.py`:

```python
"""Synthetic images that copy the measured structure of the owner's test images.

See research/verification/2026-11-10-subject-selection/README.md. All return HxWx4 uint8 RGBA.
"""

import cv2
import numpy as np

DISC = (57, 46, 40)           # Roadie's measured disc colour
RED = (230, 20, 20)
WHITE = (240, 240, 240)
DARK_LINE = (20, 10, 5)       # about 62 RGB units from DISC: kept at tolerance 30, cut at 80

DISC_SEED = (30, 100)         # x, y inside the disc, away from the bird
BIRD_SEED = (100, 80)         # x, y on the bird's body
GAP_BETWEEN_LEGS = (100, 130)
RING_POINT = (100, 5)         # on the thin ring outside the disc


def roadie_like() -> np.ndarray:
    """Opaque disc on a transparent canvas, a thin separate ring outside it, and a red bird.

    The bird's shoes are joined to its legs only through a dark outline, so a high
    tolerance cuts the feet off, as measured on the real image at tolerance 60.
    """
    img = np.zeros((200, 200, 4), np.uint8)
    cv2.circle(img, (100, 100), 95, (*WHITE, 255), 1)
    cv2.circle(img, (100, 100), 90, (*DISC, 255), -1)
    cv2.ellipse(img, (100, 80), (35, 20), 0, 0, 360, (*RED, 255), -1)
    cv2.line(img, (85, 95), (70, 134), (*RED, 255), 3)
    cv2.line(img, (115, 95), (130, 134), (*RED, 255), 3)
    for cx in (70, 130):
        cv2.ellipse(img, (cx, 143), (10, 6), 0, 0, 360, (*WHITE, 255), -1)
        cv2.ellipse(img, (cx, 143), (11, 7), 0, 0, 360, (*DARK_LINE, 255), 2)
    return img


def soft_blob() -> np.ndarray:
    """One round body with a thin stroke on top and soft alpha edges, like Oddie."""
    alpha = np.zeros((120, 120), np.uint8)
    cv2.circle(alpha, (60, 75), 30, 255, -1)
    cv2.line(alpha, (60, 45), (60, 10), 255, 3)
    alpha = cv2.GaussianBlur(alpha, (5, 5), 0)
    img = np.zeros((120, 120, 4), np.uint8)
    img[..., :3] = (80, 112, 144)
    img[..., 3] = alpha
    return img


STROKE_POINT = (60, 20)       # on the thin stroke, away from its blurred tip


def two_subjects() -> np.ndarray:
    img = np.zeros((60, 120, 4), np.uint8)
    cv2.circle(img, (30, 30), 20, (*RED, 255), -1)
    cv2.circle(img, (90, 30), 20, (*RED, 255), -1)
    return img


def empty() -> np.ndarray:
    return np.zeros((10, 10, 4), np.uint8)
```

Add the sanity test to a new `tests/test_selection.py`:

```python
import numpy as np
from selection_fixtures import (BIRD_SEED, DISC_SEED, RING_POINT, STROKE_POINT,
                                roadie_like, soft_blob)


def _at(img, p):
    x, y = p
    return img[y, x]


def test_fixtures_have_the_structure_they_claim():
    r = roadie_like()
    assert _at(r, DISC_SEED)[3] == 255 and tuple(_at(r, DISC_SEED)[:3]) == (57, 46, 40)
    assert tuple(_at(r, BIRD_SEED)[:3]) == (230, 20, 20)
    assert _at(r, RING_POINT)[3] == 255
    s = soft_blob()
    assert 0 < np.count_nonzero((s[..., 3] > 0) & (s[..., 3] < 255))   # soft edges exist
    assert _at(s, STROKE_POINT)[3] >= 128
```

**Step 2: Run it.** Run: `uv run pytest tests/test_selection.py -v`. Expected: PASS.
These are fixture checks, so there is no failing step. If one fails, fix the fixture
coordinates, not the assertion.

**Step 3: Commit.**
```bash
git add tests/selection_fixtures.py tests/test_selection.py
git commit -m "Add synthetic subject-selection fixtures"
```

### Task 3: S0 intake (`load_image`)

**Files:**
- Create: `src/tdmg/selection.py`
- Test: `tests/test_selection.py`

**Step 1: Write the failing tests.**

```python
from PIL import Image

from tdmg.selection import load_image


def _save(tmp_path, rgba, name="in.png", exif=None):
    p = tmp_path / name
    im = Image.fromarray(rgba)
    im.save(p, exif=exif) if exif is not None else im.save(p)
    return p


def test_load_image_hashes_and_keeps_rgba(tmp_path):
    p = _save(tmp_path, roadie_like())
    a = load_image(p)
    assert a.rgba.shape == (200, 200, 4) and a.rgba.dtype == np.uint8
    assert len(a.file_sha256) == 64 and len(a.pixels_sha256) == 64
    assert a.source_name == "in.png" and a.exif_transposed is False
    assert load_image(p).pixels_sha256 == a.pixels_sha256


def test_load_image_applies_exif_orientation(tmp_path):
    exif = Image.Exif()
    exif[0x0112] = 6                       # rotate 90 degrees clockwise to display
    p = _save(tmp_path, np.zeros((10, 20, 4), np.uint8), exif=exif)
    a = load_image(p)
    assert a.rgba.shape[:2] == (20, 10) and a.exif_transposed is True
```

**Step 2: Run them and check that they fail.**
Run: `uv run pytest tests/test_selection.py -v`. Expected: FAIL with `ModuleNotFoundError: tdmg.selection`.

**Step 3: Implement.** Create `src/tdmg/selection.py` with the module docstring and intake:

```python
"""S0 intake and S1 subject selection (docs/plans/2026-11-10-subject-selection.md).

Deterministic: the same image and controls give the same mask, byte for byte, within one
pinned environment. Code does not interpret language. The user's instructions are stored
verbatim and reported as not machine-interpreted. Only explicit controls change the mask.

Coordinates are pixel (x, y): origin at the top-left pixel, x right, y down, after EXIF
orientation. A --remove-at region grows through 4-connected neighbours, so it cannot leak
through a diagonal gap. Foreground pieces use 8-connectivity and holes 4-connectivity,
the standard dual pair.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

ORIENTATION_TAG = 0x0112   # EXIF Orientation; 1 means "as stored"


class SelectionError(ValueError):
    """A control or input cannot be applied as given. Nothing is written."""


@dataclass(frozen=True)
class Intake:
    rgba: np.ndarray          # H x W x 4 uint8, after EXIF orientation
    file_sha256: str
    pixels_sha256: str
    exif_transposed: bool
    source_name: str


def pixels_sha256(arr: np.ndarray) -> str:
    """Hash of shape and pixel bytes, independent of file encoding."""
    a = np.ascontiguousarray(arr)
    return hashlib.sha256(repr((a.shape, str(a.dtype))).encode() + a.tobytes()).hexdigest()


def load_image(path: str | Path) -> Intake:
    path = Path(path)
    data = path.read_bytes()
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        orientation = im.getexif().get(ORIENTATION_TAG, 1)
        oriented = ImageOps.exif_transpose(im)
        rgba = np.asarray(oriented.convert("RGBA")).copy()
    return Intake(rgba=rgba, file_sha256=hashlib.sha256(data).hexdigest(),
                  pixels_sha256=pixels_sha256(rgba), exif_transposed=orientation != 1,
                  source_name=path.name)
```

**Step 4: Run the tests and check that they pass.**
Run: `uv run pytest tests/test_selection.py -v`. Expected: PASS. If Pillow does not
write EXIF to PNG on this version, use `Image.Exif` with JPEG for that one test (alpha is
lost, which is fine for a shape check), and record the change in the commit message.

**Step 5: Commit.**
```bash
git add src/tdmg/selection.py tests/test_selection.py
git commit -m "Add S0 image intake with EXIF orientation and pixel hashing"
```

### Task 4: S1 mask from explicit controls (`select_subject`)

**Files:**
- Modify: `src/tdmg/selection.py`
- Test: `tests/test_selection.py`

**Step 1: Write the failing tests.**

```python
import pytest

from tdmg.rules import load_rules
from tdmg.selection import SelectionError, SelectionSpec, select_subject
from selection_fixtures import GAP_BETWEEN_LEGS, two_subjects, empty


def _intake(rgba):
    from tdmg.selection import Intake, pixels_sha256
    return Intake(rgba, "f" * 64, pixels_sha256(rgba), False, "x.png")


def _m(sel, p):
    x, y = p
    return bool(sel.mask[y, x])


def test_roadie_like_remove_disc_then_keep_bird():
    sel = select_subject(_intake(roadie_like()),
                         SelectionSpec(remove_at=((30, 100),), keep_at=((100, 80),)))
    assert _m(sel, BIRD_SEED) and not _m(sel, DISC_SEED)
    assert not _m(sel, GAP_BETWEEN_LEGS) and not _m(sel, RING_POINT)
    assert _m(sel, (70, 143)) and _m(sel, (130, 143))          # both shoes kept
    assert sel.result["status"] == "one_piece"


def test_high_tolerance_cuts_the_feet_off():
    sel = select_subject(_intake(roadie_like()), SelectionSpec(
        remove_at=((30, 100),), keep_at=((100, 80),), color_tolerance=80))
    assert not _m(sel, (70, 143))
    assert sel.steps[-1]["pieces_before"] > 2


def test_frame_is_kept_when_not_removed():
    sel = select_subject(_intake(roadie_like()), SelectionSpec())
    assert _m(sel, DISC_SEED) and sel.result["status"] == "multiple_pieces"


def test_defaults_come_from_the_rules_registry():
    rules = load_rules()
    sel = select_subject(_intake(roadie_like()), SelectionSpec())
    c = sel.controls
    assert c["alpha_min"] == {"value": rules["perception.alpha.min_opaque"].default,
                              "rule": "perception.alpha.min_opaque"}
    assert c["color_tolerance"]["rule"] == "perception.flood.color_tolerance"
    explicit = select_subject(_intake(roadie_like()), SelectionSpec(color_tolerance=12))
    assert explicit.controls["color_tolerance"] == {"value": 12.0, "rule": None}


def test_soft_edges_keep_the_thin_stroke():
    sel = select_subject(_intake(soft_blob()), SelectionSpec())
    assert _m(sel, STROKE_POINT) and sel.result["status"] == "one_piece"


def test_two_subjects_need_a_keep_point():
    sel = select_subject(_intake(two_subjects()), SelectionSpec())
    assert sel.result["status"] == "multiple_pieces"
    assert any("--keep-at" in w for w in sel.result["warnings"])
    one = select_subject(_intake(two_subjects()), SelectionSpec(keep_at=((30, 30),)))
    assert one.result["status"] == "one_piece" and not one.mask[30, 90]


def test_empty_image_does_not_crash():
    sel = select_subject(_intake(empty()), SelectionSpec())
    assert sel.result["status"] == "empty" and sel.result["selected_px"] == 0


def test_instructions_alone_are_reported_as_not_applied():
    sel = select_subject(_intake(two_subjects()), SelectionSpec(instructions="only the left one"))
    assert sel.interpretation == {"text": "only the left one", "machine_interpreted": False}
    assert any("not machine-interpreted" in w for w in sel.result["warnings"])


def test_holes_are_counted():
    img = two_subjects()
    img[28:33, 28:33, 3] = 0                     # a 5x5 hole inside the left circle
    sel = select_subject(_intake(img), SelectionSpec(keep_at=((15, 30),)))
    assert sel.result["holes_px"] == [25]


@pytest.mark.parametrize("spec", [
    SelectionSpec(remove_at=((500, 5),)),                      # outside the image
    SelectionSpec(remove_at=((0, 0),)),                        # transparent pixel
    SelectionSpec(remove_at=((30, 100),), keep_at=((30, 100),)),  # keep a removed pixel
])
def test_unusable_points_raise(spec):
    with pytest.raises(SelectionError):
        select_subject(_intake(roadie_like()), spec)
```

**Step 2: Run them and check that they fail.**
Run: `uv run pytest tests/test_selection.py -v`. Expected: FAIL with `ImportError` for `SelectionSpec`.

**Step 3: Implement.** Append to `src/tdmg/selection.py` and extend the imports:

```python
import cv2
from pydantic import BaseModel, ConfigDict, Field

from tdmg.rules import load_rules

ALGORITHM_VERSION = "selection-1"
ALPHA_RULE = "perception.alpha.min_opaque"
TOLERANCE_RULE = "perception.flood.color_tolerance"
NOT_INTERPRETED = ("instructions recorded verbatim but not machine-interpreted; "
                   "no control or mask applied them")

Point = tuple[int, int]


class SelectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    instructions: str | None = None
    alpha_min: int | None = Field(default=None, ge=1, le=255)
    color_tolerance: float | None = Field(default=None, ge=0)
    remove_at: tuple[Point, ...] = ()
    keep_at: tuple[Point, ...] = ()


@dataclass
class Selection:
    mask: np.ndarray                     # H x W bool
    controls: dict
    steps: list[dict]
    result: dict
    interpretation: dict


def _resolve(spec: SelectionSpec) -> dict:
    rules = load_rules()
    def pick(value, rule_id, cast):
        if value is not None:
            return {"value": cast(value), "rule": None}
        return {"value": cast(rules[rule_id].default), "rule": rule_id}
    return {"alpha_min": pick(spec.alpha_min, ALPHA_RULE, int),
            "color_tolerance": pick(spec.color_tolerance, TOLERANCE_RULE, float),
            "remove_at": [list(p) for p in spec.remove_at],
            "keep_at": [list(p) for p in spec.keep_at]}


def _selected_point(mask: np.ndarray, p: Point, what: str) -> tuple[int, int]:
    x, y = p
    h, w = mask.shape
    if not (0 <= x < w and 0 <= y < h):
        raise SelectionError(f"{what} point {x},{y} is outside the {w}x{h} image")
    if not mask[y, x]:
        raise SelectionError(f"{what} point {x},{y} is not in the current selection "
                             "(transparent, or already removed)")
    return x, y


def _piece_areas(mask: np.ndarray) -> list[int]:
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return sorted((int(a) for a in stats[1:, cv2.CC_STAT_AREA]), reverse=True)


def _hole_areas(mask: np.ndarray) -> list[int]:
    n, lab = cv2.connectedComponents((~mask).astype(np.uint8), connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist())
    counts = np.bincount(lab.ravel(), minlength=n)
    return sorted((int(counts[i]) for i in range(1, n) if i not in border), reverse=True)


def _result(mask: np.ndarray, warnings: list[str]) -> dict:
    pieces = _piece_areas(mask)
    if not pieces:
        status = "empty"
    elif len(pieces) == 1:
        status = "one_piece"
    else:
        status = "multiple_pieces"
        warnings.append(f"{len(pieces)} separate pieces; choose with --keep-at, or expect "
                        "separate bodies downstream")
    return {"status": status, "selected_px": int(mask.sum()), "pieces_px": pieces,
            "holes_px": _hole_areas(mask), "warnings": warnings}


def select_subject(intake: Intake, spec: SelectionSpec) -> Selection:
    controls = _resolve(spec)
    rgb = intake.rgba[..., :3].astype(np.int32)
    mask = intake.rgba[..., 3] >= controls["alpha_min"]["value"]
    steps = [{"op": "alpha", "selected_px": int(mask.sum())}]
    tol2 = controls["color_tolerance"]["value"] ** 2
    for p in spec.remove_at:
        x, y = _selected_point(mask, p, "remove_at")
        seed = rgb[y, x]
        near = mask & (((rgb - seed) ** 2).sum(axis=-1) <= tol2)
        _, lab = cv2.connectedComponents(near.astype(np.uint8), connectivity=4)
        region = lab == lab[y, x]
        mask &= ~region
        steps.append({"op": "remove_at", "point": [x, y], "seed_rgb": seed.tolist(),
                      "removed_px": int(region.sum())})
    if spec.keep_at:
        n, lab = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
        labels = sorted({int(lab[y, x]) for x, y in
                         (_selected_point(mask, p, "keep_at") for p in spec.keep_at)})
        mask = np.isin(lab, labels)
        steps.append({"op": "keep_at", "points": controls["keep_at"], "pieces_before": n - 1,
                      "pieces_kept": len(labels), "selected_px": int(mask.sum())})
    warnings = []
    if spec.instructions and not (spec.remove_at or spec.keep_at):
        warnings.append(NOT_INTERPRETED)
    return Selection(mask=mask, controls=controls, steps=steps,
                     result=_result(mask, warnings),
                     interpretation={"text": spec.instructions, "machine_interpreted": False})
```

Note: an explicit `--alpha-min` or `--tolerance` without seeds also leaves the
not-interpreted warning. Those are general settings, not a selection.

**Step 4: Run the tests and check that they pass.**
Run: `uv run pytest tests/test_selection.py -v`. Expected: all PASS. If
`test_high_tolerance_cuts_the_feet_off` fails, print the step record and check the
fixture's `DARK_LINE` distance before changing any assertion.

**Step 5: Commit.**
```bash
git add src/tdmg/selection.py tests/test_selection.py
git commit -m "Add deterministic S1 subject selection from explicit point controls"
```

### Task 5: Corrected user mask (`select_from_mask`)

**Files:**
- Modify: `src/tdmg/selection.py`
- Test: `tests/test_selection.py`

**Step 1: Write the failing tests.**

```python
from tdmg.selection import load_mask, select_from_mask


def _mask_file(tmp_path, arr, name="m.png"):
    p = tmp_path / name
    Image.fromarray(arr).save(p)
    return p


def test_user_mask_replaces_controls(tmp_path):
    m = np.zeros((200, 200), np.uint8)
    m[60:100, 65:135] = 255
    m[0, 0] = 255                                   # a transparent pixel in the image
    sel = select_from_mask(_intake(roadie_like()), load_mask(_mask_file(tmp_path, m), (200, 200)),
                           SelectionSpec(instructions="just the body"))
    assert sel.controls["source"] == "user_mask" and sel.mask.sum() == 40 * 70 + 1
    assert any("transparent" in w for w in sel.result["warnings"])
    assert not any("not machine-interpreted" in w for w in sel.result["warnings"])


def test_bad_user_masks_raise(tmp_path):
    grey = np.full((200, 200), 100, np.uint8)
    with pytest.raises(SelectionError, match="0 and 255"):
        load_mask(_mask_file(tmp_path, grey), (200, 200))
    with pytest.raises(SelectionError, match="size"):
        load_mask(_mask_file(tmp_path, np.zeros((5, 5), np.uint8), "s.png"), (200, 200))
    with pytest.raises(SelectionError, match="either"):
        select_from_mask(_intake(roadie_like()), np.zeros((200, 200), bool),
                         SelectionSpec(remove_at=((30, 100),)))
```

**Step 2: Run them and check that they fail.** Expected: `ImportError`.

**Step 3: Implement.**

```python
def load_mask(path: str | Path, shape: tuple[int, int]) -> np.ndarray:
    """A corrected mask: 8-bit or 1-bit, only 0 and 255, same size as the oriented image."""
    with Image.open(path) as im:
        im.load()
        arr = np.asarray(im.convert("L"))
    if arr.shape != tuple(shape):
        raise SelectionError(f"mask size {arr.shape[1]}x{arr.shape[0]} does not match image "
                             f"size {shape[1]}x{shape[0]}")
    if not np.isin(arr, (0, 255)).all():
        raise SelectionError("mask must contain only 0 and 255 (black = drop, white = keep)")
    return arr == 255


def select_from_mask(intake: Intake, mask: np.ndarray, spec: SelectionSpec) -> Selection:
    if spec.remove_at or spec.keep_at:
        raise SelectionError("use either --mask or --remove-at/--keep-at, not both")
    controls = _resolve(spec)
    controls.update(source="user_mask", user_mask_sha256=pixels_sha256(mask))
    warnings = []
    transparent = int((mask & (intake.rgba[..., 3] < controls["alpha_min"]["value"])).sum())
    if transparent:
        warnings.append(f"{transparent} selected pixels are transparent in the image")
    return Selection(mask=mask.copy(), controls=controls,
                     steps=[{"op": "user_mask", "selected_px": int(mask.sum())}],
                     result=_result(mask, warnings),
                     interpretation={"text": spec.instructions, "machine_interpreted": False})
```

Also add `controls["source"] = "controls"` in `select_subject` right after `_resolve`, and
add an assertion `assert sel.controls["source"] == "controls"` to
`test_roadie_like_remove_disc_then_keep_bird`.

**Step 4: Run the tests.** Expected: all PASS.

**Step 5: Commit.**
```bash
git add src/tdmg/selection.py tests/test_selection.py
git commit -m "Accept a corrected binary mask as the selection source"
```

### Task 6: Outputs, record and identity (`write_selection`)

**Files:**
- Modify: `src/tdmg/selection.py`
- Test: `tests/test_selection.py`

**Step 1: Write the failing tests.**

```python
import json

from tdmg.selection import write_selection

SPEC = SelectionSpec(instructions="Use only the bird.", remove_at=((30, 100),),
                     keep_at=((100, 80),))


def _run(tmp_path, name, spec=SPEC):
    sel = select_subject(_intake(roadie_like()), spec)
    return write_selection(_intake(roadie_like()), sel, tmp_path / name)


def test_outputs_and_record(tmp_path):
    rec = _run(tmp_path, "a")
    out = tmp_path / "a"
    assert sorted(p.name for p in out.iterdir()) == [
        "cutout.png", "mask.png", "preview.png", "selection.json"]
    mask = np.asarray(Image.open(out / "mask.png"))
    assert set(np.unique(mask)) <= {0, 255}
    cut = np.asarray(Image.open(out / "cutout.png"))
    assert (cut[mask == 0] == 0).all() and (cut[mask == 255][:, 3] == 255).all()
    on_disk = json.loads((out / "selection.json").read_text(encoding="utf-8"))
    assert on_disk == rec
    assert rec["input"]["name"] == "x.png" and "path" not in rec["input"]
    assert rec["interpretation"]["machine_interpreted"] is False
    assert set(rec["outputs"]) == {"mask.png", "cutout.png", "preview.png"}


def test_replay_is_byte_identical_and_changes_invalidate(tmp_path):
    a, b = _run(tmp_path, "a"), _run(tmp_path, "b")
    for name in ("mask.png", "cutout.png", "preview.png", "selection.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    tol = _run(tmp_path, "c", SPEC.model_copy(update={"color_tolerance": 12.0}))
    text = _run(tmp_path, "d", SPEC.model_copy(update={"instructions": "the bird"}))
    assert len({a["selection_id"], tol["selection_id"], text["selection_id"]}) == 3
    assert text["mask_pixels_sha256"] == a["mask_pixels_sha256"]


def test_refuses_to_overwrite(tmp_path):
    _run(tmp_path, "a")
    with pytest.raises(SelectionError, match="not empty"):
        _run(tmp_path, "a")
```

**Step 2: Run them and check that they fail.** Expected: `ImportError`.

**Step 3: Implement.**

```python
import json

from tdmg import __version__

RECORD_SCHEMA = "tdmg.selection/1"
# Preview display only; these are not thresholds.
CHECKER_CELL_PX = 8
CHECKER_SHADES = (200, 235)
REMOVED_TINT = np.array([255, 0, 255])


def _checker(h: int, w: int) -> np.ndarray:
    yy, xx = np.indices((h, w))
    cell = ((yy // CHECKER_CELL_PX + xx // CHECKER_CELL_PX) % 2).astype(bool)
    return np.where(cell[..., None], CHECKER_SHADES[0], CHECKER_SHADES[1]).astype(np.float64)


def _over(rgba: np.ndarray, under: np.ndarray) -> np.ndarray:
    a = rgba[..., 3:4] / 255.0
    return rgba[..., :3] * a + under * (1 - a)


def _preview(rgba: np.ndarray, mask: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    bg = _checker(h, w)
    left = _over(rgba.astype(np.float64), bg)
    right = bg.copy()
    right[mask] = rgba[..., :3][mask]
    removed = ~mask & (rgba[..., 3] > 0)
    right[removed] = 0.5 * left[removed] + 0.5 * REMOVED_TINT
    return np.rint(np.concatenate([left, right], axis=1)).astype(np.uint8)


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _write_png(arr: np.ndarray, path: Path) -> str:
    Image.fromarray(arr).save(path, format="PNG")    # mode inferred: L, RGB or RGBA
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_selection(intake: Intake, sel: Selection, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()):
        raise SelectionError(f"output folder {out} is not empty; choose a new one")
    out.mkdir(parents=True, exist_ok=True)
    mask8 = np.where(sel.mask, 255, 0).astype(np.uint8)
    cutout = np.where(sel.mask[..., None], intake.rgba, 0).astype(np.uint8)
    cutout[..., 3] = mask8
    outputs = {"mask.png": _write_png(mask8, out / "mask.png"),
               "cutout.png": _write_png(cutout, out / "cutout.png"),
               "preview.png": _write_png(_preview(intake.rgba, sel.mask), out / "preview.png")}
    h, w = sel.mask.shape
    identity = {"algorithm": ALGORITHM_VERSION, "input_pixels_sha256": intake.pixels_sha256,
                "controls": sel.controls, "instructions": sel.interpretation["text"]}
    record = {
        "schema": RECORD_SCHEMA, "tdmg_version": __version__, "algorithm": ALGORITHM_VERSION,
        "selection_id": hashlib.sha256(_canonical(identity)).hexdigest(),
        "input": {"name": intake.source_name, "file_sha256": intake.file_sha256,
                  "pixels_sha256": intake.pixels_sha256, "width": w, "height": h,
                  "exif_transposed": intake.exif_transposed},
        "interpretation": sel.interpretation, "controls": sel.controls, "steps": sel.steps,
        "result": sel.result, "mask_pixels_sha256": pixels_sha256(sel.mask),
        "outputs": outputs,
        "review": "Open preview.png and confirm the subject before generating geometry.",
    }
    (out / "selection.json").write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return record
```

The user-mask hash is already in `controls`, so `selection_id` covers it.

**Step 4: Run the tests.** Expected: all PASS. If the PNG bytes differ between runs,
investigate before weakening the test. Pillow PNG output is expected to contain no
timestamp. That expectation is what the test measures.

**Step 5: Commit.**
```bash
git add src/tdmg/selection.py tests/test_selection.py
git commit -m "Write mask, cutout, preview and a hashed selection record"
```

### Task 7: `tdmg select` command

**Files:**
- Modify: `src/tdmg/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write the failing tests.** Append to `tests/test_cli.py`:

```python
def test_select_writes_a_reviewable_selection(tmp_path):
    import numpy as np
    from PIL import Image
    from selection_fixtures import roadie_like

    img = tmp_path / "roadie_like.png"
    Image.fromarray(roadie_like()).save(img)
    out = tmp_path / "sel"
    result = runner.invoke(app, ["select", str(img), "--out", str(out),
                                 "--instructions", "Use only the bird.",
                                 "--remove-at", "30,100", "--keep-at", "100,80"])
    assert result.exit_code == 0, result.output
    assert "one_piece" in result.output and "preview.png" in result.output
    assert (out / "selection.json").is_file()
    assert np.asarray(Image.open(out / "mask.png")).max() == 255


def test_select_rejects_bad_points(tmp_path):
    import numpy as np
    from PIL import Image

    img = tmp_path / "e.png"
    Image.fromarray(np.zeros((4, 4, 4), np.uint8)).save(img)
    bad = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "o"),
                              "--remove-at", "a,b"])
    assert bad.exit_code == 2
    off = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "o2"),
                              "--keep-at", "9,9"])
    assert off.exit_code == 2 and "outside" in off.output
    assert not (tmp_path / "o2").exists()
```

**Step 2: Run them and check that they fail.**
Run: `uv run pytest tests/test_cli.py -v`. Expected: FAIL, because there is no `select` command.

**Step 3: Implement.** In `src/tdmg/cli.py`, update the module docstring to say that
Phase 1 starts with `select`, then add:

```python
from pathlib import Path

from tdmg.selection import (SelectionError, SelectionSpec, load_image, load_mask,
                            select_from_mask, select_subject, write_selection)


def _points(values: list[str] | None, flag: str) -> tuple[tuple[int, int], ...]:
    out = []
    for v in values or []:
        try:
            x, y = (int(s) for s in v.split(","))
        except ValueError:
            raise typer.BadParameter(f"{flag} expects X,Y in pixels, got {v!r}") from None
        out.append((x, y))
    return tuple(out)


@app.command()
def select(
    image: Path = typer.Argument(..., exists=True, dir_okay=False, help="PNG or JPEG input."),
    out: Path = typer.Option(..., "--out", help="New or empty folder for the outputs."),
    instructions: str | None = typer.Option(
        None, help="What should become the model, in your words. Stored verbatim; "
                   "code does not interpret it."),
    remove_at: list[str] | None = typer.Option(
        None, "--remove-at", help="X,Y: remove the colour region at this pixel. Repeatable."),
    keep_at: list[str] | None = typer.Option(
        None, "--keep-at", help="X,Y: keep only the piece(s) at these pixels. Repeatable."),
    tolerance: float | None = typer.Option(
        None, "--tolerance", help="RGB distance for --remove-at. Default from rules."),
    alpha_min: int | None = typer.Option(
        None, "--alpha-min", help="Lowest alpha (1-255) counted as opaque. Default from rules."),
    mask: Path | None = typer.Option(
        None, "--mask", exists=True, dir_okay=False,
        help="Corrected black/white mask; replaces --remove-at/--keep-at."),
) -> None:
    """Select the subject: write mask, cutout, preview and selection.json for review."""
    spec = SelectionSpec(instructions=instructions, alpha_min=alpha_min,
                         color_tolerance=tolerance,
                         remove_at=_points(remove_at, "--remove-at"),
                         keep_at=_points(keep_at, "--keep-at"))
    try:
        intake = load_image(image)
        if mask is not None:
            sel = select_from_mask(intake, load_mask(mask, intake.rgba.shape[:2]), spec)
        else:
            sel = select_subject(intake, spec)
        rec = write_selection(intake, sel, out)
    except SelectionError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    r = rec["result"]
    typer.echo(f"status {r['status']}: {r['selected_px']} px in {len(r['pieces_px'])} piece(s), "
               f"{len(r['holes_px'])} hole(s)")
    for w in r["warnings"]:
        typer.echo(f"warning: {w}")
    typer.echo(f"wrote {out / 'preview.png'} - check the subject before going on")
```

An out-of-range `--alpha-min` or a negative `--tolerance` makes pydantic raise
`ValidationError` while the spec is built. It must also exit with code 2. Wrap the
`spec = SelectionSpec(...)` statement like this, with
`from pydantic import ValidationError` at the top of `cli.py`:

```python
    try:
        spec = SelectionSpec(...)   # the same arguments as above
    except ValidationError as e:
        typer.echo(f"error: {e.errors()[0]['loc'][0]}: {e.errors()[0]['msg']}", err=True)
        raise typer.Exit(2) from None
```

Add this test:

```python
def test_select_rejects_out_of_range_alpha(tmp_path):
    import numpy as np
    from PIL import Image

    img = tmp_path / "e.png"
    Image.fromarray(np.zeros((4, 4, 4), np.uint8)).save(img)
    r = runner.invoke(app, ["select", str(img), "--out", str(tmp_path / "o"), "--alpha-min", "0"])
    assert r.exit_code == 2 and "alpha_min" in r.output
```

**Step 4: Run the tests.** Run: `uv run pytest -q`, then `uv run ruff check .`. Expected:
all PASS and lint clean. Confirm by hand that `uv run tdmg select --help` lists every option.

**Step 5: Commit.**
```bash
git add src/tdmg/cli.py tests/test_cli.py
git commit -m "Add tdmg select command"
```

### Task 8: Local run on the owner's images (not in CI)

**Files:**
- Modify: `research/verification/2026-11-10-subject-selection/README.md` (append a dated
  section; do not rewrite the earlier measurements)
- Outputs: `artifacts/selection-runs/` (git-ignored; check with `git check-ignore`)

**Step 1: Run Roadie with the owner's words.**
```bash
uv run tdmg select "C:/Users/arikt/Downloads/three-d-test/roadie.png" \
  --out artifacts/selection-runs/roadie-tol30 \
  --instructions "Use only the roadrunner bird. Ignore the grey circular background." \
  --remove-at 60,396 --keep-at 470,470
```
`470,470` is a red body pixel, RGB (249, 5, 7). The planning prototype checked it; it did
not use the disc point `418,330`, which an earlier draft had wrong. Expected: `one_piece`
with exactly 74,768 px. The planning prototype gave this count at tolerance 30, and it
matches the measurement table.

**Step 2: Run the comparisons.** Run the same command at `--tolerance 20` and
`--tolerance 40` into new folders. Then run Oddie with only `--instructions`, and expect
the not-interpreted warning and `one_piece`. Run each Roadie command twice into separate
folders and compare the `selection.json` and PNG hashes.

**Step 3: Inspect the previews visually.** Check:
- the beak edge, which looked thin at tolerance 40;
- that the gaps between the legs are removed;
- that both shoes are kept.

Show the previews to the owner. The owner decides whether the bird is right, and that
decision is recorded.

**Step 4: Record the results.** Append the commands, input hashes, `selection_id`s,
pixel counts, the repeatability result and the owner's verdict to the README. Commit only
the README; the outputs stay in `artifacts/`.

### Task 9: Docs, status and independent review

**Files:**
- Modify: `docs/guide/input-interpretation.md`. Change the status line to say explicit
  controls are implemented as `tdmg select` and no language interpreter exists. Add a
  "How to use it" section with the Roadie command and the coordinate convention. Correct
  the Roadie acceptance case: the measured "dark outline" is not separable from the disc
  by colour (fringe median 27.7 RGB units from the disc colour), so tolerance trades
  kept fringe against splitting, and the preview decides.
- Modify: `docs/PLAN.md`. Update the gate-contract paragraph and Q6 in section 13 to say
  S1 explicit controls are implemented; the language interpreter is still not built.
- Modify: `README.md`. Add `uv run tdmg select ...` to the command list.
- Modify: `docs/STATUS.md`. Update Phase 1, next steps, and the handoff.
- Create: `research/reviews/2026-11-10-selection/`. This holds the Codex review output and
  a README recording how each finding was handled.

**Step 1:** Make the doc edits. Run `uv run python scripts/gen_docs.py`, `uv run pytest -q`
and `uv run ruff check .`. Expected: all pass.

**Step 2:** Run an independent read-only Codex review of the diff since this plan's
first commit, as in `research/reviews/2026-11-09-pc/`. Verify each finding against the
code before applying it, and record how each one was handled.

**Step 3:** Commit and push. Pushing needs the owner's go-ahead in this session. Check
that CI passes on all three operating systems before calling the work verified.

---

## Out of scope for this plan

- Tracing the mask to polygons, extrusion and anything after S1. That is the next R1
  plan, and it reuses `mask.png` and the half-pixel contour rule
  `vectorize.opencv.contour_offset_px`.
- A phrase grammar or an LLM proposer for instructions.
- rembg/ONNX background removal. These imports failed on this PC, and the explicit
  controls do not need them.
- An input-pixel budget rule. Pillow's own decompression-bomb guard applies until the
  rule is added with evidence.
- Joining multiple pieces. `multiple_pieces` is reported, and R1 decides what to do with
  it.
