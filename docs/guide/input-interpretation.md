# Tell the pipeline what the image means

**Status: planned, not implemented.** Added from the owner's Roadie example on
2026-11-09. The repository currently has foundations and experiment scripts, not
a production image intake/generation command.

An image can contain the subject, a background, a frame, labels and shadows. The
user needs an optional field: **What should become the 3D model?** Store the user's
words exactly. A suitable Roadie instruction is:

> Use only the roadrunner bird. Ignore the grey circular background.

Do not infer additional requests such as adding a base, changing the pose, filling
spaces between limbs, or making a flat sign. Those are separate job choices.

## Planned interaction

1. Accept the image, interpretation text, and normal job settings (print type and
   dimensions). An explicit crop or mask can also be supplied.
2. Resolve instructions into subject selection and exclusions. Show what is being
   kept and removed. If a statement cannot be acted on, report that explicitly;
   ask a targeted question only when the selection remains ambiguous.
3. Display an editable cutout preview, including interior gaps between legs and
   beneath wings. The user can correct selection before generation. A CLI can save
   the preview and accept a corrected mask path; this does not require a web UI.
4. Send the prepared image to the generator, together with supported generation
   instructions if the backend offers them. Do not claim text support for an
   image-only backend. The TripoSR experiment has no text-conditioning input, so
   the Roadie exclusion must affect its input pixels/mask.
5. Preserve the original image/text, resolved subject/exclusions, preparation
   settings, mask, preview, prepared image and hashes in the run record. The cache
   identity includes these inputs; changing interpretation must not reuse a stale
   generation. Preserve unresolved/unsupported instructions in the report.

## Implementation boundary

Accepting text and understanding arbitrary text are separate capabilities. The
default runtime still makes no LLM calls. Initial implementation can pair the text
with explicit user selection (crop/mask and background controls). The automatic
language-to-selection method is an open implementation choice; any LLM-based
proposal stays behind the plan's explicit opt-in and cannot bypass geometry checks.
Recording a description alone does not mean it has been applied.

Foreground processing belongs before every generator, including a manually used
MakerLab service. A correctly isolated image gives a generator that lacks a prompt
field the intended subject. It does not guarantee faithful unseen geometry.

## Acceptance cases

- **Roadie:** bird included, opaque circular background excluded; keep the dark
  outline and spaces between appendages. Existing outer transparency is insufficient.
- **Oddie:** preserve its leaves, feet and outline; do not mistake thin intended
  parts for removable background.
- **Frame explicitly requested:** keep a border/background when the user asks;
  do not hard-code removal of every circular shape or grey region.
- **Ambiguous subject:** two plausible subjects require selection, not a guess.
- **Unsupported instruction:** report it before generation rather than claiming
  success based on retained text.
- **Replay:** the same recorded mask/settings can be reused; changed instructions
  or masks invalidate the appropriate downstream cache.

Subject agreement and printability remain distinct. A perfect manifold sphere
with a bird embossed on it can be the wrong object. A faithful bird can still have
thin, disconnected or unsupported geometry. Both need inspection.
