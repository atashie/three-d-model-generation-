"""Gate check results and the F1 topology checks (docs/PLAN.md section 4, "Gate contract").

Each check returns PASS, FAIL or UNKNOWN with what it measured, the threshold and the
rules-registry id that sets it. The F1 checks read the raw face array of an exactly
merged mesh. They never call trimesh properties or methods that repair, merge or drop
faces, so a defect in the file is a defect in the result.

Known behaviour, by design:
- Zero area means an exactly zero cross product. No tolerance is applied. If a cross
  product overflows, that face's area cannot be decided and the check is UNKNOWN.
- The vertex-link test accepts a 2-cycle link. A closed two-triangle "pillow" (one
  triangle in both windings) passes it; no_duplicate_faces and positive_volume catch it.
- positive_volume judges each connected shell on its own, so a correct inward-facing
  cavity shell has negative volume and FAILs. This is conservative; revisit when a
  recipe needs enclosed voids.
- Vertices that no face uses are counted as unused_vertices, not as bad vertex links.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import cache
from typing import Literal

import numpy as np
import trimesh

from tdmg.rules import load_rules

Status = Literal["PASS", "FAIL", "UNKNOWN"]
VOLUME_DECIMALS = 6  # rounding of reported body volumes only; decisions use the raw value
F1_ORDER = ("F1.finite", "F1.no_degenerate_faces", "F1.no_duplicate_faces",
            "F1.edge_manifold", "F1.consistent_orientation", "F1.vertex_manifold",
            "F1.positive_volume")  # the ids topology_checks returns, in its order
F1_CHECK_IDS = frozenset(F1_ORDER)


@dataclass(frozen=True)
class CheckResult:
    id: str  # e.g. "F1.edge_manifold"
    status: Status
    measured: object  # JSON-serialisable
    threshold: object | None
    rule: str | None  # rules-registry id, when a rule sets the threshold
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@cache
def _rule_default(rule_id: str) -> object:
    return load_rules()[rule_id].default


def _result(id_: str, ok: bool, measured: object, rule: str | None = None,
            note: str = "") -> CheckResult:
    threshold = _rule_default(rule) if rule else None
    return CheckResult(id_, "PASS" if ok else "FAIL", measured, threshold, rule, note)


def merge_exact(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Unify only exactly equal coordinates (STL stores corners). No snapping or repair."""
    # Ported from research/experiments/2026-11-g3-local-vs-hosted/inspect_makerlab.py
    # (lines 19-20). Adding 0.0 turns -0.0 into 0.0, which compare equal as numbers.
    vertices = np.asarray(mesh.vertices, dtype=np.float64) + 0.0
    unique, inverse = np.unique(vertices, axis=0, return_inverse=True)
    faces = inverse.reshape(-1)[np.asarray(mesh.faces, dtype=np.int64)]
    return trimesh.Trimesh(unique, faces, process=False, validate=False)


def _vertex_links(faces: np.ndarray, n_vertices: int) -> tuple[int, int]:
    """Return (bad, unused): vertices whose link is not one closed cycle, and unused ones.

    The link of a vertex is the opposite edges of its incident faces. Ported from
    research/experiments/2026-11-g3-local-vs-hosted/inspect_makerlab.py (lines 22-38),
    except that a vertex no face uses (empty link) is counted as unused, not as bad.
    """
    links: list[dict[int, list[int]]] = [{} for _ in range(n_vertices)]
    for a, b, c in faces.tolist():
        for v, i, j in ((a, b, c), (b, c, a), (c, a, b)):
            links[v].setdefault(i, []).append(j)
            links[v].setdefault(j, []).append(i)
    invalid = unused = 0
    for graph in links:
        if not graph:
            unused += 1
            continue
        if any(len(n) != 2 for n in graph.values()):
            invalid += 1
            continue
        seen, stack = set(), [next(iter(graph))]
        while stack:
            node = stack.pop()
            if node not in seen:
                seen.add(node)
                stack.extend(graph[node])
        invalid += len(seen) != len(graph)
    return invalid, unused


def _signed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    """Signed volume; may be inf or nan when coordinates overflow (callers check)."""
    tri = vertices[faces]
    with np.errstate(all="ignore"):
        products = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2]))
        return float(products.sum() / 6)


def topology_checks(mesh: trimesh.Trimesh) -> list[CheckResult]:
    """F1 on an exactly merged mesh."""
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64).reshape(-1, 3)
    ids = F1_ORDER
    rules = {"F1.edge_manifold": "format.3mf.edge_manifold",
             "F1.consistent_orientation": "format.3mf.consistent_orientation",
             "F1.vertex_manifold": "gate.topology.vertex_manifold"}
    if len(faces) == 0:
        # No surface encloses no solid: a definite FAIL, not a lack of information.
        return [_result(i, False, {"faces": 0}, rules.get(i), "mesh has no faces")
                for i in ids]

    results = []
    nonfinite = int(np.count_nonzero(~np.isfinite(vertices).all(axis=1)))
    finite = nonfinite == 0
    results.append(_result("F1.finite", finite, {"nonfinite_vertices": nonfinite}))

    repeated = int(np.count_nonzero((faces[:, 0] == faces[:, 1]) | (faces[:, 1] == faces[:, 2])
                                    | (faces[:, 2] == faces[:, 0])))
    if finite:
        tri = vertices[faces]
        with np.errstate(all="ignore"):
            cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        undecided = ~np.isfinite(cross).all(axis=1)
        zero = int(np.count_nonzero(~cross.any(axis=1) & ~undecided))
        n_undecided = int(np.count_nonzero(undecided))
        measured = {"repeated_index": repeated, "zero_area": zero}
        if n_undecided == 0:
            results.append(_result("F1.no_degenerate_faces", repeated == 0 and zero == 0,
                                   measured))
        else:
            measured["undecided_area"] = n_undecided
            results.append(CheckResult(
                "F1.no_degenerate_faces", "FAIL" if repeated or zero else "UNKNOWN",
                measured, None, None, "coordinates too large for exact area"))
    else:
        results.append(CheckResult(
            "F1.no_degenerate_faces", "FAIL" if repeated else "UNKNOWN",
            {"repeated_index": repeated, "zero_area": None}, None, None,
            "areas not computed: coordinates are not finite"))

    duplicates = len(faces) - len(np.unique(np.sort(faces, axis=1), axis=0))
    results.append(_result("F1.no_duplicate_faces", duplicates == 0,
                           {"duplicate_faces": int(duplicates)}))

    directed = faces[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
    _, edge_counts = np.unique(np.sort(directed, axis=1), axis=0, return_counts=True)
    boundary = int(np.count_nonzero(edge_counts == 1))
    overfull = int(np.count_nonzero(edge_counts > 2))
    results.append(_result("F1.edge_manifold", boundary == 0 and overfull == 0,
                           {"boundary_edges": boundary, "overfull_edges": overfull},
                           rules["F1.edge_manifold"]))

    # Every directed edge once, and its reverse once. Directed edges are taken together
    # with the reversed copies; a pair is good only if both directions occur exactly once.
    uniq, counts = np.unique(directed, axis=0, return_counts=True)
    count_of = {(int(a), int(b)): int(n) for (a, b), n in zip(uniq, counts, strict=True)}
    bad = sum(1 for (a, b), n in count_of.items() if n != 1 or count_of.get((b, a)) != 1)
    results.append(_result("F1.consistent_orientation", bad == 0,
                           {"bad_directed_edges": bad},
                           rules["F1.consistent_orientation"]))

    bad_vertices, unused = _vertex_links(faces, len(vertices))
    results.append(_result("F1.vertex_manifold", bad_vertices == 0,
                           {"bad_vertices": bad_vertices, "unused_vertices": unused},
                           rules["F1.vertex_manifold"]))

    results.append(_positive_volume(vertices, faces, finite))
    return results


def _positive_volume(vertices: np.ndarray, faces: np.ndarray, finite: bool) -> CheckResult:
    if not finite:
        return CheckResult("F1.positive_volume", "UNKNOWN", {"body_volumes": None}, None,
                           None, "volumes not computed: coordinates are not finite")
    plain = trimesh.Trimesh(vertices, faces, process=False, validate=False)
    # split computes face normals internally, which overflow for huge coordinates;
    # grouping faces into bodies depends only on shared edges, not on those normals.
    with np.errstate(all="ignore"):
        bodies = plain.split(only_watertight=False, repair=False)
    if sum(len(b.faces) for b in bodies) != len(faces):
        return CheckResult("F1.positive_volume", "UNKNOWN", {"body_volumes": None}, None,
                           None, "split into bodies did not account for every face")
    volumes = [_signed_volume(np.asarray(b.vertices), np.asarray(b.faces)) for b in bodies]
    nonfinite = sum(1 for v in volumes if not np.isfinite(v))
    if nonfinite:
        return CheckResult("F1.positive_volume", "FAIL",
                           {"body_volumes": None, "nonfinite_volumes": nonfinite}, None, None,
                           "coordinates too large for exact volume")
    return _result("F1.positive_volume", all(v > 0 for v in volumes),
                   {"body_volumes": [round(v, VOLUME_DECIMALS) for v in volumes]})


def verdict(results: list[CheckResult], required: set[str]) -> str:
    """'PRINTABLE' only if every required check is present and PASS; else 'NOT CERTIFIED'."""
    if not required:
        raise ValueError("verdict needs at least one required check")
    for check in required:
        found = [r for r in results if r.id == check]
        if not found or any(r.status != "PASS" for r in found):
            return "NOT CERTIFIED"
    return "PRINTABLE"
