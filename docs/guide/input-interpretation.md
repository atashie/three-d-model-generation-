# Tell the pipeline what the image means

**Status:** explicit selection is implemented as `tdmg select` (2026-11-10). No language
interpreter exists. Your words are stored verbatim, and code applies only the explicit
controls described below. Selection is the first stage; tracing and geometry (the rest
of R1) are not built yet. This feature came from the owner's Roadie example on 2026-11-09.

An image can contain the subject, a background, a frame, labels and shadows. The
user needs an optional field: **What should become the 3D model?** Store the user's
words exactly. A suitable Roadie instruction is:

> Use only the roadrunner bird. Ignore the grey circular background.

Do not infer additional requests such as adding a base, changing the pose, filling
spaces between limbs, or making a flat sign. Those are separate job choices.

## How to use it

```bash
uv run tdmg select roadie.png --out runs/roadie \
  --instructions "Use only the roadrunner bird. Ignore the grey circular background." \
  --remove-at 60,396 --keep-at 470,470
```

- **Points** are pixel positions `X,Y`, counted from the top-left pixel, with x going
  right and y going down, as image viewers show them. Any EXIF rotation is applied
  first.
- **`--remove-at X,Y`** removes the region of similar colour around that pixel: the
  connected area within `--tolerance` of its colour (default `perception.flood.color_tolerance`).
  Points apply in order. Repeat the flag for several regions.
- **`--keep-at X,Y`** keeps only the connected piece or pieces under these points.
- **`--alpha-min`** sets how opaque a pixel must be to count (default
  `perception.alpha.min_opaque`). It matters only for images with soft, partly
  transparent edges.
- **`--mask FILE`** replaces the point controls with a corrected black-and-white mask
  (white keeps, black drops) of the same size. The simplest way to correct a selection
  is to edit the `mask.png` from an earlier run and pass it back.
- **The output folder** must be new or empty. It receives:
  - `mask.png`;
  - `cutout.png`: the subject on transparency, the prepared input for later stages;
  - `preview.png`: before and after side by side, with removed parts tinted magenta;
  - `selection.json`: hashes, settings, your words, and `machine_interpreted: false`.

  A folder without `selection.json` is incomplete. Do not use it.

**Look at `preview.png` before going on.** The tool reports facts: one piece, several
pieces, or nothing selected. Whether the right subject was chosen is your judgement.
The checks that come later cannot decide it.

**Inputs it refuses:** 16-bit greyscale and floating-point images (export them as 8-bit),
multi-frame files such as animated GIFs (export one frame), and unreadable or truncated
files. A 16-bit colour PNG is read by Pillow as 8-bit, keeping the high byte. No colour
management is applied: embedded ICC profiles are ignored, and CMYK uses Pillow's
conversion formula.

## Planned interaction

1. Accept the image, interpretation text, and normal job settings (print type and
   dimensions). An explicit mask can also be supplied. **Done** for selection.
2. Resolve instructions into subject selection and exclusions. Show what is being
   kept and removed. If a statement cannot be acted on, report that explicitly.
   **Done for explicit controls.** Text without controls is reported as not applied.
   Automatic language-to-selection is not built.
3. Display an editable cutout preview, including interior gaps between legs and
   beneath wings. The user can correct selection before generation. **Done:**
   `preview.png`, plus `--mask` for corrections.
4. Send the prepared image to the generator, together with supported generation
   instructions if the backend offers them. Do not claim text support for an
   image-only backend. The TripoSR experiment has no text-conditioning input, so
   the Roadie exclusion must affect its input pixels or mask. **Not built.**
   `cutout.png` is the prepared image to send.
5. Preserve the original image and text, the resolved selection, preparation
   settings, mask, preview, prepared image and hashes in the run record. **Done.**
   The cache identity (`selection_id`) covers the algorithm version, input pixels,
   controls, user mask and instructions, so changed instructions or masks get a new
   identity. `mask_pixels_sha256` identifies the mask alone.

## Implementation boundary

Accepting text and understanding arbitrary text are separate capabilities. The
default runtime still makes no LLM calls. The current implementation pairs the text
with explicit user selection (points and masks). The automatic language-to-selection
method is an open implementation choice. Any LLM-based proposal stays behind the
plan's explicit opt-in and cannot bypass geometry checks. Recording a description
alone does not mean it has been applied.

Foreground processing belongs before every generator, including a manually used
MakerLab service. A correctly isolated image gives a generator that lacks a prompt
field the intended subject. It does not guarantee faithful unseen geometry.

## Acceptance cases

- **Roadie:** bird included, the opaque circular background excluded, and the spaces
  between appendages excluded. Existing outer transparency is insufficient. **Met on
  2026-11-10 and confirmed by the owner;** see
  `research/verification/2026-11-10-subject-selection/README.md`.
  - **Correction to an earlier version of this page:** Roadie has no dark outline
    that colour can separate from the disc. The edge pixels sit at a median of 27.7
    RGB units from the disc colour.
  - So `--tolerance` trades kept edge fringe against splitting: at 60 the bird
    breaks into pieces.
  - The preview decides.
- **Oddie:** preserve its leaves, feet and outline; do not mistake thin intended
  parts for removable background. **Met:** its own transparency selects one piece,
  including the thin leaf tip.
- **Frame explicitly requested:** keep a border or background when the user asks. Do
  not hard-code removal of every circular shape or grey region. **Met:** nothing is
  removed without `--remove-at`.
- **Ambiguous subject:** two plausible subjects require selection, not a guess.
  **Met:** the tool reports `multiple_pieces` with a warning; `--keep-at` chooses.
- **Unsupported instruction:** report it before generation rather than claiming
  success based on retained text. **Met:** text without controls gives a
  "not machine-interpreted" warning.
- **Replay:** the same recorded mask and settings can be reused; changed
  instructions or masks invalidate the appropriate downstream cache. **Met within one
  environment:** repeated runs give byte-identical files, and changes give a new
  `selection_id`.

Subject agreement and printability remain distinct. A perfect manifold sphere
with a bird embossed on it can be the wrong object. A faithful bird can still have
thin, disconnected or unsupported geometry. Both need inspection.

## Known limits

- **Memory:** in review measurements at 4000 × 4000 pixels, peak memory was about
  0.6 GB for the selection and 0.5 GB for writing the outputs. Larger photos have not
  been measured.
- **Rare decoder errors:** some malformed files raise Pillow's own error messages
  instead of a `tdmg` error.
- **Error naming:** error messages name the library fields (`alpha_min`) rather than
  the command-line flags (`--alpha-min`).
- **Identity is strict:** a value given explicitly and the same value taken from the
  rule default give different `selection_id`s. This can cause extra recomputation but
  never stale reuse.
