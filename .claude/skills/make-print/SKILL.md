---
name: make-print
description: Use when the owner shares an image (a photo, a drawing or a generated image) to turn into a printable file, or asks to continue, print, confirm or finish a print job in jobs/. Walks the owner through tdmg job new, the selection and color reviews, building and slicing, the print, the print confirmation and tdmg finish, with the owner's own words at every confirmation.
---

# Make a print from an image

This is the conversation you follow when the owner wants to turn an image into a
printable file. The owner is a data scientist who is new to 3D printing. Use plain
words and short sentences. Explain each 3D-printing term the first time you use it.

The code decides what is printable. You run the commands, show the owner what they
made, ask the questions, and record the owner's answers. You do not decide for the
owner.

Background, if you need it: `docs/guide/pipeline-and-gate.md` (sections "Jobs",
"Finishing a print" and "Checking the library") and `docs/plans/2026-11-16-restructure-design.md`
(sections 3 to 5).

## Hard rules: never

- **Never record words the owner did not give.** A confirmation (`--owner-said`) and the
  purge permission (`--purge-owner-said`) hold only words the owner wrote or said in this
  conversation, or words they gave earlier and repeat or point to now.
- **Never paraphrase.** Copy the owner's words exactly, with their spelling and
  punctuation. No summary, no "the owner approved". If you are not sure which words
  are the answer, ask.
- **Never purge without the separate purge permission.** A print confirmation is not
  permission to delete the job.
- **Never call something printed that was not.** A slice is not a print, and a PRINTABLE
  verdict is not a print. Only the owner can tell you that they printed it.
- **Never commit source images or private files**, and never commit anything without
  the owner's OK. `jobs/`, `prints/*/source/` and `prints/*/private/` are git-ignored.
  Never use `git add -f` or `git add -A`.
- **Never use `--accept-not-certified` on your own.** Only after you explain what is not
  certified and why, and the owner chooses it in their own words.
- **Never edit `job.yaml` by hand**, or any file in `jobs/` or `prints/`. Change a job
  only with `tdmg job set`, `tdmg job run` and `tdmg job confirm`. You may read the files.
- **Never delete or overwrite an existing job.** If the name is taken, pick another.
- **Never run `tdmg finish` on a dirty git tree** (see step 10).
- **Never generate images.** Image generation is outside the pipeline (CLAUDE.md rule 1).
- **Never change `rules/`, thresholds or checks to make a verdict pass** (see "When
  something fails").

## How to run the commands

- **Use the Bash tool (Git Bash) for every command, never PowerShell.** The quoting
  below is bash quoting.
- **Start every command that carries the owner's words with `MSYS_NO_PATHCONV=1`.**
  Without it, Git Bash turns words that start with `/` into a Windows path (measured on
  the PC: `/yes` became `C:/Program Files/Git/yes`).
- **Give file paths in Windows form with forward slashes**, for example
  `C:/Users/arikt/Desktop/roadie.png`, for `--image` and `select.mask`.
- **Put the owner's words in bash single quotes:** `--owner-said 'THEIR EXACT WORDS'`.
  Inside single quotes nothing is expanded (`$`, `` ` ``, `"`, `!` and `\` stay as they
  are). Write a `'` in their words as `'\''`. For example, *it's good* becomes
  `--owner-said 'it'\''s good'`.
- **A backslash** in their words may not survive the Windows command line. Check the
  read-back.

### Check the read-back

Each command that records words prints them back (`job new` in `job.yaml`, `job set`,
`job confirm`, and `finish --dry-run` for the purge words). Compare the read-back with
the owner's words, character by character.

- The read-back is ASCII-escaped: a curly apostrophe shows as `\u2019`, an accented
  letter as its `\u` code. That is the same text. Do not "correct" the owner's words to
  match.
- **If a read-back differs:** tell the owner. For a confirmation, record it again with the
  right words: entries are only ever added, and finish uses the latest current entry with
  the same route and face (or `--confirmation N`). Never finish on a wrong entry. For
  `job new`, the origin fields can only be set when the job is made: tell the owner, and
  ask whether to start again under a new name. For the purge words, use the dry run's
  echo before the real run (step 10).

## The slicer folders

The pinned slicers are in `artifacts/tools/`. Use the same two folders in every
`job run`, `job status`, `job confirm` and `finish` of a job. The PrusaSlicer folder is
part of the slice stage's input key, so a command without it shows the slice as stale.
Run these two checks once at the start:

```bash
uv run python scripts/setup_orcaslicer.py --verify-only artifacts/tools/orcaslicer-2.5.0
uv run python scripts/setup_prusaslicer.py --verify-only artifacts/tools/prusaslicer-2.9.7
```

If one fails, stop and tell the owner: the slice stage cannot run without them.

## Step 1: the owner shares the image

1. Ask for the image file's full path on disk (PNG or JPEG). If the owner pasted the
   image into the chat, ask them to save it as a file and give you the path.
2. Open the image with the Read tool so that you can see it.
3. Ask where the image came from: a photo, a drawing, or a generated image.
4. For a generated image, ask what the owner knows of its origin: the prompt; the
   generator and its version; the settings; any reference images given to it; which
   candidate they chose; any edits made after generation. Record only what the owner
   tells you. Leave out the flag for anything they do not know: it stays `unknown`. Do
   not guess from the image.
5. Ask what should become the model, in their words (for example "only the bird, not the
   grey circle"). This is a record; code does not read it.

**Waits for the owner:** the path, the origin, and what should become the model.

## Step 2: choose the kind of print and a job name

1. Explain the choices. Today only the `flat-icon` class can be made:
   - **single color** (recipe R1): one flat shape in one filament, an STL file;
   - **multicolor** (recipe R2, `--colors`): one body per color, a 3MF file for the
     AMS (the automatic filament changer), or a glue-together version.
   Figurines and flexis are planned, not ready.
2. Ask for a job name: lowercase letters, digits and hyphens, for example `roadie-drop`.
   Each variant is its own job (for example `roadie-drop` with the outline dropped and
   `roadie-keep` with it kept), even from the same image. If `job new` says the job or a
   library entry already exists, ask for another name.

**Waits for the owner:** single color or multicolor, and the name.

## Step 3: start the job

Use only the flags for which the owner gave an answer. For a single-color print, leave
out `--colors`. For a photo or drawing, leave out the generated-image flags.

```bash
MSYS_NO_PATHCONV=1 uv run tdmg job new NAME --class flat-icon --colors --image C:/PATH/TO/IMAGE.png --origin generated --prompt 'THEIR PROMPT' --generator 'THEIR GENERATOR' --generator-version 'THEIR VERSION' --settings 'THEIR SETTINGS' --references 'THEIR REFERENCES' --chosen 'THEIR CHOICE' --edits 'THEIR EDITS'
MSYS_NO_PATHCONV=1 uv run tdmg job new NAME --class flat-icon --image C:/PATH/TO/IMAGE.png --origin photo
```

This copies the image to `jobs/NAME/source/` (git-ignored) and writes `jobs/NAME/job.yaml`.
Nothing runs yet. Read the `source:` part of `job.yaml` back (see "Check the read-back").
If it exits 2, tell the owner the message in plain words.

Then record what should become the model. `job set` reads each value as YAML, so the
words go in YAML double quotes, inside the bash single quotes. In the words, write `"`
as `\"`, and `'` as `'\''` as usual:

```bash
MSYS_NO_PATHCONV=1 uv run tdmg job set NAME 'select.instructions="THEIR WORDS"'
```

Without the YAML quotes, words with a colon are refused. Check the read-back.

## Step 4: the selection (what becomes the model)

1. Look at the image and suggest the controls. Points are pixel positions `[X, Y]` from
   the top-left corner (x to the right, y down):
   - `select.remove_at`: remove the region of similar color at each point (a background,
     a frame);
   - `select.keep_at`: keep only the piece or pieces under these points;
   - `select.tolerance`: how different a color may be and still be removed (leave it
     unset for the rule's default).

   See `docs/guide/input-interpretation.md`. Tell the owner which points you would use
   and why, and ask: "Shall I try these points?"
2. When they agree, set them and run:

   ```bash
   uv run tdmg job set NAME "select.remove_at=[[60, 396]]" "select.keep_at=[[470, 470]]"
   uv run tdmg job run NAME --slicer-dir artifacts/tools/orcaslicer-2.5.0 --prusaslicer-dir artifacts/tools/prusaslicer-2.9.7
   ```

   The run does the selection, then stops because the size is not set yet. That is
   expected.
3. Open `jobs/NAME/select/preview.png` with the Read tool. Give the owner its absolute
   path so they can open it too.
4. Ask: "Is this the subject? Is anything missing, or anything extra?"
5. If it is wrong, change the controls and run again:
   - move or add points, or change the tolerance, with `tdmg job set`;
   - or use a corrected mask. The owner copies `jobs/NAME/select/mask.png` to a folder
     outside the repository (their Desktop, say), edits the copy (white keeps, black
     drops) and gives you its path. Then, on its own:

     ```bash
     uv run tdmg job set NAME select.mask=C:/PATH/TO/MASK.png
     ```

     `select.mask=none` removes it again.
6. When the owner says the selection is right, record their words exactly:

   ```bash
   MSYS_NO_PATHCONV=1 uv run tdmg job confirm NAME --subject selection --owner-said 'THEIR EXACT WORDS' --prusaslicer-dir artifacts/tools/prusaslicer-2.9.7
   ```

**Waits for the owner:** that the preview is right, in their words.

## Step 5: the size

Ask for the width of the model in millimetres, and its thickness. The width is the size
across; the thickness is how tall it stands on the print bed. If a value is refused,
tell the owner the limit the message gives; do not pick a value for them.

For a single-color job (R1), then go to step 7:

```bash
uv run tdmg job set NAME flat.width_mm=60 flat.thickness_mm=3
```

For a multicolor job (R2), set only the width now. The thickness comes after the colors
are confirmed, so nothing is built from colors the owner has not seen:

```bash
uv run tdmg job set NAME colors.width_mm=60
```

**Waits for the owner:** the width and the thickness.

## Step 6: the colors (multicolor only)

1. Run:

   ```bash
   uv run tdmg job run NAME --slicer-dir artifacts/tools/orcaslicer-2.5.0 --prusaslicer-dir artifacts/tools/prusaslicer-2.9.7
   ```

   It makes the color plan and stops, because the thickness is not set.
2. Open `jobs/NAME/colors/regions.png` with the Read tool and give the owner its absolute
   path. It shows the image, the extracted colors with their numbers, any flags, and the
   final regions.
3. Explain the choices. Each one is the owner's decision, never a side effect of cleanup.
   Say what the default is and what each option changes:
   - **Outlines** (`colors.outlines`): `drop` (the default) gives the drawn outline's
     pixels to the nearest other color; `keep` prints the outline as an even band
     (`colors.outline_width_mm`, default from the rules). A plan with the outline kept has
     no glue version. `colors.outline_color` is `auto`, `none` or a list of color numbers.
   - **Merges** (`colors.merge`): fold one color into another, for example a shade into
     its main color. The code flags likely shade pairs but never merges them itself.
   - **Number of colors** (`colors.colors`): at most the printer's palette (4 on the A1's
     AMS lite). `colors.extract` is how many colors are found before merges.
   - **Edges** (`colors.edges`): `smooth` (default), `furry` or `exact`.
   - **Base** (`colors.base`): `auto` (the largest color) or a color number.
4. If the plan is not ready (more colors than allowed), the status says so. Ask the
   owner which colors to merge. Set what they choose and run again:

   ```bash
   uv run tdmg job set NAME "colors.merge=[[4, 1]]" colors.outlines=keep
   uv run tdmg job run NAME --slicer-dir artifacts/tools/orcaslicer-2.5.0 --prusaslicer-dir artifacts/tools/prusaslicer-2.9.7
   ```

5. When the owner says the colors are right, record their words exactly:

   ```bash
   MSYS_NO_PATHCONV=1 uv run tdmg job confirm NAME --subject colors --owner-said 'THEIR EXACT WORDS' --prusaslicer-dir artifacts/tools/prusaslicer-2.9.7
   ```

6. Set the thickness:

   ```bash
   uv run tdmg job set NAME colored_flat.thickness_mm=3
   ```

**Waits for the owner:** each style choice, and that the colors are right, in their words.

## Step 7: build and slice

```bash
uv run tdmg job run NAME --slicer-dir artifacts/tools/orcaslicer-2.5.0 --prusaslicer-dir artifacts/tools/prusaslicer-2.9.7
uv run tdmg job status NAME --prusaslicer-dir artifacts/tools/prusaslicer-2.9.7
```

The run builds the model, checks it, and slices it with the pinned OrcaSlicer (and
PrusaSlicer). Slicing turns the model into the printer's layer-by-layer instructions
(G-code). The status lists each stage, the verdicts, and what waits for the owner.

Show the owner what was built:
- single color: `jobs/NAME/flat/outline.png`;
- multicolor: `jobs/NAME/colored_flat/top.png` (compare it with `colors/regions.png`),
  and `parts.png` for the glue version.

## Step 8: explain the verdict and how to print

1. Explain the verdict in plain words:
   - **PRINTABLE**: every check the recipe requires passed. It is not a promise; it means
     the code found no problem it knows how to measure.
   - **NOT CERTIFIED**: a check failed or could not be measured. Name each reason from
     the status or from `slice/slice.json`. Then see "When something fails".
   - Say which warnings there are, and what is not checked at all (for example the glue
     gap of a glue print is still untested).
2. Give the print instructions that the status prints after "to print". In short:
   - **Which file:** single color: `jobs/NAME/flat/model.stl`. Multicolor on the AMS:
     `jobs/NAME/colored_flat/model.3mf`, with the filament for each color as listed.
   - **Which face:** for multicolor, the status says which face is PRINTABLE and which
     one tdmg chose. The owner prefers face down when it is PRINTABLE. "Face down" means
     the colored face lies on the bed.
   - **How to turn it in Bambu Studio:** `model.3mf` opens face up. For face down, select
     the model, press R (Rotate), and turn it 180 degrees about X. This is a turn, not a
     mirror, so the picture reads correctly when the print is turned back over.
   - The owner slices in Bambu Studio and prints from there. tdmg's own G-code is for
     checking only; it is not for printing.
3. Give absolute paths to every file the owner needs.

**Waits for the owner:** the print. They tell you when they have printed it and how it
came out.

## Step 9: the owner prints, then confirm the print

1. Ask the owner: Did you print it? Which file? For multicolor: on the AMS or the glue
   version, face up or face down? How did it come out, in your words?
2. Do not record anything until the owner says they printed it. If they printed a
   different file or face than the one tdmg chose, say so and ask whether that is what
   they did.
3. Record their words exactly. For a single-color print:

   ```bash
   MSYS_NO_PATHCONV=1 uv run tdmg job confirm NAME --subject print --owner-said 'THEIR EXACT WORDS' --prusaslicer-dir artifacts/tools/prusaslicer-2.9.7
   ```

   For a multicolor print on the AMS, with the face they printed (never guessed from the
   slice):

   ```bash
   MSYS_NO_PATHCONV=1 uv run tdmg job confirm NAME --subject print --route ams --face down --owner-said 'THEIR EXACT WORDS' --prusaslicer-dir artifacts/tools/prusaslicer-2.9.7
   ```

   For the glue version, use `--route glue` and no `--face`.
4. If the owner gave the words on an earlier day, add the date they gave them (their
   local date), for example `--date 2026-11-16`.
5. If the verdict is not PRINTABLE, the confirm is refused unless
   `--accept-not-certified` is given. Use it only if the owner, after you explained what
   is not certified, says in their words that they printed it anyway (or choose to).

**Waits for the owner:** that they printed it, the route and the face, and their words.

## Step 10: finish

`tdmg finish` copies the print into the library (`prints/NAME/`), proves that it
rebuilds from the library's own files, and then deletes the working folder `jobs/NAME/`.

1. Ask: **may the design be public?** Explain:
   - This repository is public on GitHub. The printable file is a copy of the owner's
     image in another form.
   - `yes`: the printable files go to `prints/NAME/files/` and are committed.
     `no`: they go to `prints/NAME/private/`, which git ignores; then they exist only on
     this disk. The source image is never committed either way.
   - Either way, `card.md`, `job.yaml` and `provenance.json` are always tracked, so they
     become public once pushed. They hold the owner's words, any prompt and other origin
     details, the instructions, and the image's SHA-256 hash.
2. Run `git status`. The tree must be clean, except `jobs/` and `prints/`, which finish
   does not check (an uncommitted `prints/OTHER` does not block it). If anything else is
   changed, show the owner `git status` and ask before you commit anything. Never stash
   or discard changes to get past the check.
3. Do a dry run with the owner's public answer (`yes` or `no`) in place of `ANSWER`:

   ```bash
   uv run tdmg finish NAME --public ANSWER --dry-run --slicer-dir artifacts/tools/orcaslicer-2.5.0 --prusaslicer-dir artifacts/tools/prusaslicer-2.9.7
   ```

   It checks the job, stages it in a temporary folder, rebuilds it and compares the
   files. Then it removes what it staged and says what a real run would publish and
   delete. Nothing else is changed.
4. Show the owner what it says will be published and deleted. Point out any file it
   names that the library does not keep (notes, for example).
5. Ask for the **purge permission**, on its own: "May I delete `jobs/NAME/`, the working
   data listed above? The library keeps the printable file, the card, the job record and
   the source image." Wait for their own words.
6. Run the dry run again with their words. It prints the words back as `purge.json` will
   hold them. Check the read-back:

   ```bash
   MSYS_NO_PATHCONV=1 uv run tdmg finish NAME --public ANSWER --dry-run --purge-owner-said 'THEIR EXACT WORDS' --slicer-dir artifacts/tools/orcaslicer-2.5.0 --prusaslicer-dir artifacts/tools/prusaslicer-2.9.7
   ```

7. Run the real finish with the same words. It prints them again before it records them:

   ```bash
   MSYS_NO_PATHCONV=1 uv run tdmg finish NAME --public ANSWER --purge-owner-said 'THEIR EXACT WORDS' --slicer-dir artifacts/tools/orcaslicer-2.5.0 --prusaslicer-dir artifacts/tools/prusaslicer-2.9.7
   ```

   If several print confirmations differ in route or face, finish asks which one. Ask
   the owner, then give `--confirmation N` (the number in `tdmg job status`).
8. Check the library entry:

   ```bash
   uv run tdmg library check NAME
   ```

   On this machine the source is present, so a note "source unavailable" means it is
   missing: tell the owner. Exit 1 (damaged or incomplete): stop and tell the owner.
9. Show the owner `prints/NAME/card.md`. Before any commit, list what would be added:

   ```bash
   git status --short --untracked-files=all prints/NAME
   ```

   Check that no `source/` or `private/` path is listed. Ask the owner. With their OK,
   run `git add prints/NAME` (only that folder) and commit. Do not push unless they ask.

If a finish stops part way (a crash, a closed window), run the same command again. It
continues where it stopped. `tdmg library check` says when an entry is incomplete.

**Waits for the owner:** public yes or no, the purge permission in their words, and the
OK to commit.

## When something fails

- **A stage fails, or a command exits 2:** tell the owner the message in plain words.
  Fix inputs (a point, a size, a mask) with `tdmg job set`.
- **The verdict is NOT CERTIFIED:** name each failed or unknown check and what it means
  for the print. Offer the options that stay inside the pipeline:
  - change a choice the owner controls (size, thickness, face, outlines, merges, edges)
    and run again;
  - make a variant as a new job;
  - stop here.

  Printing a NOT CERTIFIED file is the owner's choice, after you explain the risk. If a
  rule seems wrong, say so and leave the change to a separate, reviewed piece of work.
- **A confirmation is stale:** a file it covers changed (for example after a new
  `job set`). Show the owner the new preview and ask them to confirm again.
- **The rebuild differs at finish (exit 1):** stop. Nothing was published or deleted.
  Tell the owner what differs. Do not retry with changes, and do not purge. The owner's
  print confirmation covers the file they printed only.

## Not jobs yet

Calibration strips are not jobs yet. Use `tdmg strip` (see the guide):

```bash
uv run tdmg strip OUT --slicer-dir artifacts/tools/orcaslicer-2.5.0
```
