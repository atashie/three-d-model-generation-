# Principles

The full statement, with the reasons behind each principle, is in [the plan, section 2](../PLAN.md#2-principles). In short:

1. **No LLM decides anything at run time.** Code does. An LLM may propose parameters in an optional mode, and its output faces the same checks.
2. **Machine learning is fenced.** Background removal, depth estimation and photo-to-3D are not deterministic. Their outputs are recorded with model identity and settings, cached, and replayed, so everything after them can be reproduced exactly.
3. **Reproducible within a stated envelope.** The same inputs in the same pinned environment give byte-identical files. Across machines we promise the same geometry within tolerances.
4. **Every number has a source and a status.** See [rules](../reference/rules.md). A rule records what kind of claim it is, where its evidence comes from, and whether anyone has shown that it works.
5. **Checks are precise.** Each check states exactly what it measures and how.
6. **Your printer is the final judge.** Calibration prints override general rules for your A1, but never override file-format requirements.
7. **3MF first.**
