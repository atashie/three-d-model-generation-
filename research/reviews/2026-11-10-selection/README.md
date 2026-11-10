# Independent review of `tdmg select`, 2026-11-10

Ran the installed OpenAI Codex CLI (0.167.0) with `codex exec --sandbox read-only
--ephemeral` on commits `c015619..27d5423`. The full response is in
[review.txt](review.txt). Codex ran 45 filesystem-free tests and in-memory probes.
Its read-only sandbox blocked the full suite.

Each subagent task had already passed a spec review and a code-quality review. Every
finding below was checked against the code or docs before it was handled.

1. **Mutable state could change provenance:** confirmed. Fixed in `33cbb52`:
   - `Intake` stores a read-only pixel copy;
   - `Selection` keeps a JSON snapshot, and `write_selection` builds the identity and
     record only from it;
   - tests mutate a selection after construction.
2. **Concurrent writers could overwrite each other:** confirmed by reading the code.
   Fixed in `33cbb52`:
   - the folder is created exclusively when new;
   - PNGs are created with exclusive mode;
   - the temporary record name is unique;
   - two simulated races are tested.
3. **Pillow's size guard escaped the CLI:** confirmed. `DecompressionBombError` now
   becomes a `SelectionError` (`33cbb52`). This is tested in the library and the CLI.
4. **Non-binary RGB masks were accepted through luminance rounding:** confirmed. Masks
   are now validated on their decoded channels with no rounding. Unsupported modes are
   refused (`33cbb52`).
5. **The guide overstated preservation of the original image:** confirmed. Only its
   name and hashes are recorded. The guide now says "partly done" and that replay needs
   the source image.
6. **The plan's embedded YAML kept the corrected overclaim, and its status was stale:**
   confirmed. The plan is now marked executed, with execution notes. The embedded claim
   is marked superseded, and the plan says the code and rules are the source of truth.
7. **The memory figures had no reproducible record:** confirmed. Added
   `measure_memory.py` and `memory.txt` to the verification record. The guide now
   cites those measured values and states what tracemalloc does not count.

After the fixes: 251 tests pass and ruff is clean. The golden `selection_id` is
unchanged. Codex did not re-review the fixes.
