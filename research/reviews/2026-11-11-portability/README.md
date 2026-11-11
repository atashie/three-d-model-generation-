# Independent critical review of F6.portability (PrusaSlicer), 2026-11-11

The owner asked for a Codex critical review after each step's documentation audit. I ran
the installed OpenAI Codex CLI (0.167.0) with `codex exec --sandbox read-only --ephemeral`
on commits `8233345..c40340d`. Its final response is in [review.txt](review.txt).

Codex re-hashed both installed slicers and the recorded outputs, and checked the six
explicit settings against the hash-checked profiles. It ran read-only Python
reproductions on the real owner G-code. Its sandbox blocked `uv` and pytest.

Before this, the portability work had a subagent spec and quality review and fixes after
each. I checked every finding below against the code or the PrusaSlicer source before
handling it.

1. **High: layer comments alone could PASS.** Confirmed by reading: `gcode_layers`
   counted `;LAYER_CHANGE` and `;Z:` lines and never looked at motion, so a G-code cut
   after its last `;Z:`, or holding only those comments, passed.
   - **Fix:** `gcode_layers` now reads the motion PrusaSlicer writes (G90, M82, G92 E0,
     G28, G0/G1 words) and refuses anything else: M83, G91, arcs, G10/G11, G92 on other
     axes, malformed or repeated words, X/Y/Z with more than 3 decimals, extrusion before
     the first layer or before the modes and position are set. `F6.portability` FAILs
     unless the file ends with `; prusaslicer_config = end` (true of all 14 real
     PrusaSlicer files), every layer has an extruding move, and every extruding move is
     at its layer's height within `COMMANDED_Z_TOL_MM` (twice the 3-decimal rounding).
   - **Fake:** `tests/fake_prusa.py` now writes the measured form (absolute E rising,
     a Z move per layer, the closing block) and can truncate, drop a layer's extrusion or
     move a layer's Z. The fake-slicer tests cover each case.
   - **Real output:** `mutations_portability.py` → `mutations.txt` in
     `research/verification/2026-11-11-prusaslicer-windows/` repeats Codex's mutations on
     the real Roadie and Oddie G-code. The originals PASS; all 16 mutations FAIL, including
     the comment-only and cut files with the closing line put back.
   - **Scope, stated in the code and docs:** this shows plastic is laid on every layer to
     the top. It does not show each layer is fully printed; F3 judges that for the
     OrcaSlicer G-code only.
2. **Medium: the volume bound missed admesh's zeroed normals.** Confirmed in the
   PrusaSlicer 2.9.7 source (`stl_normalize_vector` in
   `bundled_deps/admesh/admesh/stl.h` zeroes a normal shorter than 1e-12, so that facet's
   volume term is 0) and by Codex's 1e-6 mm cube.
   - **Fix:** a facet that may be zeroed (`|C| - eta < ADMESH_NORMAL_CUTOFF`) adds its
     whole exact term to the bound.
   - **Checked while fixing:** `get_volume` takes the height from the facet's *stored*
     normal. The import repair (`stl_fix_normal_values`, before `stl_calculate_volume` in
     `trianglemesh_repair_on_import`) overwrites every stored normal with the recomputed
     one, so the derivation's assumption holds. The docstring now says so.
   - **Tests:** six cubes straddling the cutoff and Codex's centred cube. With the fix
     disabled, two of them fail; with it, all pass. The owner models' bounds are
     unchanged (no facet near the cutoff).
3. **Low: "every setting explicit" overstated.** Confirmed in the real G-code: PrusaSlicer
   used 20% infill, elephant-foot compensation 0 and the Arachne perimeter generator,
   where the OrcaSlicer A1 run used 15%, 0.075 mm and classic.
   - **Fix:** the code, the setup script, `PORTABILITY_MEANING` and the docs now say that
     the bed, nozzle, layer and filament settings are explicit and the rest are
     PrusaSlicer's defaults. The research record's Settings section is corrected by an
     addendum; the original text is kept.

**Remaining limit Codex noted, not changed:** `slice_id` identifies the request (inputs,
pins, settings, algorithm), not the result. A run stopped by a timeout and one that
finishes share it. That is the design for every id in this repo; the record holds the
result.

**Version:** `slice-4` was never pushed, so these fixes stay within it, as earlier
unpushed revisions did; the comment at `SLICE_ALGORITHM_VERSION` lists them. The owner
models' slice_ids are therefore unchanged.
