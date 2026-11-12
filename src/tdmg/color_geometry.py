"""Per-color regions in model mm for colored flat geometry (R2 step 2).

docs/plans/2026-11-12-color-geometry.md, Decisions 3-5 (with the amendments after Task 1
and after the Task 3 quality review):

- Decision 3: each color c of the fine label map (tdmg.smoothing.smooth_labels) is
  vectorized as mask_outline(fine == c) scaled by 1/s about the origin, which puts it in
  the pixel-cell coordinates of tdmg.flat (x right, y down, image pixel (column x, row y)
  the cell [x, x + 1] x [y, y + 1]). tdmg.flat.apply_transform then takes it to model mm
  (x_mm = (x - x0) * scale, y_mm = (y1 - y) * scale), and it is clipped to the silhouette
  S. Task 1 measured plain float64 overlays on the approved plans (zero overlap, gaps of
  at most 7e-12 mm^2), so there is no simplification, no fixed grid and no coverage
  function here.
- Decision 4: every palette color except the base is an inlay; the base's top is S minus
  the union of the inlays, which is the base color's own fine region inside S, to
  float64 rounding.
- Decision 5, as replaced by the owner's decision ("Match preview", 2026-11-12): the
  inlays are not cleaned. Opening each color on its own and giving the trimmings to the
  base drew base-colored hairlines between touching colors (1.0-21.3 mm^2 on the four
  approved plans). So each inlay is exactly its fine region clipped to S, as in the
  approved preview. Parts narrower than the width the caller passes
  (flat.sliver.opening_width) are only reported, with tdmg.flat.thin_regions; the slicer
  checks in step 4 judge whether they print.

Pure: no I/O, no extrusion, no record. The caller builds S (the cleaned R1 silhouette)
and passes the rule value.
"""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon

from tdmg.flat import apply_transform, mask_outline, order_key, polygon_parts, thin_regions
from tdmg.smoothing import SmoothingError, check_supersample

STATUSES = ("inlay", "vanished_in_fine", "outside_silhouette")
TRANSFORM_KEYS = ("scale_mm_per_px", "x0_px", "y1_px")  # what apply_transform reads


class ColorGeometryError(ValueError):
    """Invalid input to the color geometry. Nothing is built."""


@dataclass(frozen=True, eq=False)
class ColorRegions:
    """Per-color polygons in model mm, expected to partition S to float64 rounding.

    Not checked here: the tests assert it, and C1.partition (plan Task 4) gates it.

    inlays: palette index -> its fine region clipped to S, as polygons sorted by
      tdmg.flat.order_key, only for colors with area inside S; never the base.
    base_top: the polygons of S minus the union of all inlay polygons, sorted the same
      way.
    report: JSON-safe; see color_regions.
    warnings: one line per non-inlay color, and one if the base is not in the fine map.
    """

    inlays: dict[int, list[Polygon]]
    base_top: list[Polygon]
    report: dict
    warnings: list[str]


def _supersample(value) -> int:
    try:
        return check_supersample(value)
    except SmoothingError as exc:
        raise ColorGeometryError(str(exc)) from None


def _fine(fine) -> np.ndarray:
    a = np.asarray(fine)
    if a.ndim != 2:
        raise ColorGeometryError(f"fine must be two-dimensional, got shape {a.shape}")
    if a.dtype == np.bool_ or not np.issubdtype(a.dtype, np.integer):
        raise ColorGeometryError(f"fine must be an integer array, got {a.dtype}")
    if a.size == 0:
        raise ColorGeometryError(f"fine is empty (shape {a.shape})")
    if int(a.min()) < 0:
        raise ColorGeometryError(f"fine labels must be palette indices of at least 0, "
                                 f"got {int(a.min())}")
    return a


def fine_regions_px(fine, supersample, labels=None) -> dict[int, shapely.Geometry]:
    """Each label's region of the fine map, in image pixel units.

    fine: a 2-D integer array (bool refused) of palette indices (>= 0), as
    smooth_labels returns. supersample: its factor s, an int >= 1 (bool refused).
    labels: the labels to vectorize (ints >= 0, bool refused), or None for all. For each
    of them present in fine, in ascending order: mask_outline(fine == c) scaled by 1/s
    about the origin (fine pixel (row i, column j) is the cell [j/s, (j+1)/s] x
    [i/s, (i+1)/s]). Keys are Python ints.
    """
    a = _fine(fine)
    s = _supersample(supersample)
    present = [int(c) for c in np.unique(a)]
    if labels is not None:
        wanted = {_int("labels", c, 0) for c in labels}
        present = [c for c in present if c in wanted]
    return {c: affinity.scale(mask_outline(a == c), 1 / s, 1 / s, origin=(0, 0))
            for c in present}


def _int(name: str, value, low: int, high: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ColorGeometryError(f"{name} must be an integer, got {value!r}")
    value = int(value)
    if value < low or (high is not None and value >= high):
        bound = f"in [{low}, {high})" if high is not None else f"at least {low}"
        raise ColorGeometryError(f"{name} must be {bound}, got {value}")
    return value


def _positive(name: str, value) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ColorGeometryError(f"{name} must be a number, got {value!r}")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ColorGeometryError(f"{name} must be a finite number above 0, got {value}")
    return value


def _transform(transform) -> dict:
    if not isinstance(transform, dict) or any(k not in transform for k in TRANSFORM_KEYS):
        raise ColorGeometryError(f"transform must be tdmg.flat.to_model's dict with "
                                 f"{', '.join(TRANSFORM_KEYS)}")
    for key in TRANSFORM_KEYS:
        value = transform[key]
        if (isinstance(value, bool) or not isinstance(value, numbers.Real)
                or not math.isfinite(value)):
            raise ColorGeometryError(f"transform {key} must be a finite number, "
                                     f"got {value!r}")
    if transform["scale_mm_per_px"] <= 0:
        raise ColorGeometryError(f"transform scale_mm_per_px must be above 0, got "
                                 f"{transform['scale_mm_per_px']}")
    return transform


def _silhouette(silhouette):
    if not isinstance(silhouette, (Polygon, MultiPolygon)):
        raise ColorGeometryError(f"silhouette must be a Polygon or MultiPolygon, got "
                                 f"{type(silhouette).__name__}")
    if silhouette.is_empty or not silhouette.area > 0:
        raise ColorGeometryError("silhouette is empty (no area)")
    if not silhouette.is_valid:
        raise ColorGeometryError(f"silhouette is not valid: "
                                 f"{shapely.is_valid_reason(silhouette)}")
    return silhouette


def _polygonal(geom) -> list[Polygon]:
    """geom's polygons of positive area.

    Overlays can return lines and points where boundaries touch; they have no area and
    are dropped.
    """
    return [p for p in polygon_parts(geom)[0] if p.area > 0]


def _filaments(n: int) -> str:
    return "1 filament remains" if n == 1 else f"{n} filaments remain"


def _warning(index: int, status: str, filaments: int) -> str:
    if status == "vanished_in_fine":
        what = "not in the fine label map, so nothing of it is printed"
    else:
        what = "no area inside the silhouette, so nothing of it is printed"
    return f"color {index}: {status}: {what}; {_filaments(filaments)}"


def color_regions(fine, supersample, transform, silhouette, *, n_colors, base_index,
                  thin_width_mm) -> ColorRegions:
    """Per-color inlay polygons and the base top in model mm, clipped to the silhouette.

    fine, supersample: the fine label map and its factor (fine_regions_px).
    transform: tdmg.flat.to_model's dict. silhouette: S, a valid Polygon or MultiPolygon
    in mm with area > 0 (the cleaned R1 shape). n_colors: the palette size, an int >= 1;
    every fine label must be below it. base_index: the base color, an int in
    [0, n_colors). thin_width_mm: finite, > 0 (the caller passes
    flat.sliver.opening_width); used only to report thin parts. Bools are refused for
    every number. ColorGeometryError names the bad argument.

    For each palette index c except the base, the inlay is the positive-area polygons of
    c's fine region in mm intersected with S. Nothing is cleaned (module docstring). The
    base color is not vectorized: its top is S minus the union of the inlays.

    report: {"colors": [per palette index except the base, ascending: {"index",
    "status", "area_mm2", "parts", "thin"}], "base": {"index", "present_in_fine",
    "area_mm2" (of base_top)}, "base_thin", "silhouette_area_mm2"}. status is one of
    STATUSES: "vanished_in_fine" (not in fine), "outside_silhouette" (in fine, no area
    inside S) or "inlay". "thin" and "base_thin" are tdmg.flat.thin_regions of the
    color's polygons and of base_top at thin_width_mm: information only, never a warning.
    warnings: one line per non-inlay color and one if the base is not in fine, each
    ending with the number of filaments the AMS output will use (the base plus each
    inlay color).
    """
    a = _fine(fine)
    s = _supersample(supersample)
    n_colors = _int("n_colors", n_colors, 1)
    base_index = _int("base_index", base_index, 0, n_colors)
    if int(a.max()) >= n_colors:
        raise ColorGeometryError(f"fine has label {int(a.max())}, not below n_colors "
                                 f"{n_colors}")
    thin_width_mm = _positive("thin_width_mm", thin_width_mm)
    transform = _transform(transform)
    silhouette = _silhouette(silhouette)

    others = [c for c in range(n_colors) if c != base_index]
    regions_px = fine_regions_px(a, s, labels=others)
    inlays: dict[int, list[Polygon]] = {}
    statuses = {}
    for c in others:
        if c not in regions_px:
            statuses[c] = "vanished_in_fine"
            continue
        parts = _polygonal(shapely.intersection(
            apply_transform(regions_px[c], transform), silhouette))
        if parts:
            inlays[c] = sorted(parts, key=order_key)
            statuses[c] = "inlay"
        else:
            statuses[c] = "outside_silhouette"

    entries = []
    for c in others:
        parts = inlays.get(c, [])
        entries.append({"index": c, "status": statuses[c],
                        "area_mm2": float(sum(p.area for p in parts)),
                        "parts": len(parts), "thin": thin_regions(parts, thin_width_mm)})

    all_inlays = [p for polys in inlays.values() for p in polys]
    if all_inlays:
        base = shapely.difference(silhouette, shapely.union_all(all_inlays))
    else:
        base = silhouette
    base_top = sorted(_polygonal(base), key=order_key)
    base_area = float(sum(p.area for p in base_top))
    base_present = bool((a == base_index).any())
    report = {"colors": entries,
              "base": {"index": base_index, "present_in_fine": base_present,
                       "area_mm2": base_area},
              "base_thin": thin_regions(base_top, thin_width_mm),
              "silhouette_area_mm2": float(silhouette.area)}
    filaments = 1 + len(inlays)  # the base and one per inlay color (the AMS bodies)
    warnings = []
    if not base_present:
        warnings.append(f"base color {base_index}: not in the fine label map; it is the "
                        f"body under the inlays, and its top shows only where no inlay "
                        f"covers the silhouette ({base_area:.6g} mm^2); "
                        f"{_filaments(filaments)}")
    warnings += [_warning(e["index"], e["status"], filaments)
                 for e in entries if e["status"] != "inlay"]
    return ColorRegions(inlays, base_top, report, warnings)
