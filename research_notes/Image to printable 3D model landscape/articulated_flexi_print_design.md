# Articulated print-in-place ("flexi") FDM design rules, failure modes, and automatic-generation methods (state as of 2026-11-08)

Scope note. This covers consumer FDM (0.4 mm nozzle unless stated). Each finding is tagged:
**[P]** verified from a primary source (designer's own repo/page, official vendor docs, paper text or publisher abstract);
**[S]** secondary claim (vendor blog, forum, aggregator, or a model page seen only through a search snippet because the host blocked fetching);
**[U]** could not verify.
Material published before 2025 is marked **(older)**. "Per side" = radial gap; "total" = diametral gap. Many sources do not say which they mean; where unclear I say so.

Blocked hosts during research (fetch returned 402/403): makerworld.com, printables.com model pages, wiki.bambulab.com, thingiverse.com, mdpi.com, all3dp.com, myminifactory.com, dspace.mit.edu bitstreams. Their content below comes from search snippets or from Crossref/arXiv/GitHub mirrors and is labelled accordingly. The web-search budget for this session ran out near the end, so a few follow-ups (CuteFlexiMaker, Articulate-Anything licence text, Kirbs' original licence) are listed as gaps rather than guessed.

---

## 1. Flat flexi design rules (Flexi-Rex-style keychains and flat articulated animals)

### Takeaway
The only designer-published, dimensioned flat-flexi hinge spec found is DrLex's Flexi Rex "stronger links" drawing (about 0.5 mm clearance, 2.5 mm axle in a 3.6 mm hole, shackle wall at least 1.58 mm, 1.2–1.8 mm gap between body segments, 3 perimeters at 0.2 mm layers). Everything else in circulation is a 0.2–0.5 mm-per-side range from vendor blogs and model pages; the few peer-reviewed FDM studies (0.15–0.25 mm optimum for a 10 mm PLA pin; Z-axis-aligned hinges tolerate tighter gaps than XY-plane hinges; 0.1 and 0.3 mm layers both worsen release force) agree with the community range but are not flexi-specific.

### Cited Findings

**Joint types actually used in flat flexis**
- Flexi Rex lineage (older): zheng3's *Flexy Rex* (July 2015) made the body flexible with "a thin spine connecting the model sliced into thin plates" (a living-hinge/spine approach); Kirbs' *Flexi Rex* (8 Sept 2016) was "redesigned from scratch… with a shackle construction instead of the flexible spine" because the spine version "proved too fragile for being handled by kids"; DrLex's "stronger links" (30 Dec 2017) thickened the shackles **[P]** — [DrLex0/print3D-FlexiRex README, History](https://github.com/DrLex0/print3D-FlexiRex)
- The Flexi Rex hinge is a captive pin-in-loop ("shackle" around an "axle"): the drawing labels Ø axle, Ø hole, shackle width/thickness, axle length and inter-segment gap **[P]** — [Hinge_dimensions.png in DrLex0/print3D-FlexiRex](https://github.com/DrLex0/print3D-FlexiRex/blob/master/images/Hinge_dimensions.png)
- Flexifier (image-to-flexi generator) offers two joint types, `normal` (pin hinge) and `ball` **[P]** — [Lucandia/Flexifier streamlit_app.py](https://github.com/Lucandia/Flexifier/blob/main/streamlit_app.py)
- BOSL2's print-in-place knuckle hinge replaces the pin with "interlocking cones" at 45° (a cone-pin hinge), and separately offers `living_hinge_mask()` and snap-lock modules **[P]** — [BOSL2 wiki hinges.scad](https://github.com/BelfrySCAD/BOSL2/wiki/hinges.scad)
- CuteFlexi Studio (2026 browser generator) uses "a knob on the rear segment [that] sits in a socket ring on the front one… 45° lips above and below stop it lifting or pulling out" and "horizontal cone-pin hinges" for wings **[P]** — [ais80/cuteflexi-studio README](https://github.com/ais80/cuteflexi-studio)

**Clearance values (mm)**
- Flexi Rex (DrLex): "Clearance: about 0.5mm" (vertical, between axle top and shackle), Ø axle 2.5 mm in Ø hole 3.6 mm (i.e. 1.1 mm total / 0.55 mm radial), "Distance to next part: between 1.2 and 1.8mm", "Center of axle to next part: about 2.3mm" **[P]** — [Hinge_dimensions.png](https://github.com/DrLex0/print3D-FlexiRex/blob/master/images/Hinge_dimensions.png)
- DrLex: "You won't gain any flexibility by providing more clearance than needed, the model will only become weaker." **[P]** — [README, Hinge Design](https://github.com/DrLex0/print3D-FlexiRex)
- Flexifier hard-codes `hor_tolerance = 0.8` and `vert_tolerance = 0.8` (mm) for its pin hinge, with `pin_diam = (hinge_diam - vert_tolerance)/3`; its OpenSCAD `uni_ball` module defaults `tolerance = 0.4` **[P]** — [streamlit_app.py](https://github.com/Lucandia/Flexifier/blob/main/streamlit_app.py)
- Prusa KB: "An Original Prusa will be accurate to at least 0.2 mm" and "An initial good measurement for movable parts is at least 0.3 mm"; it stresses no universal value exists **[P]** — [Prusa KB, Modeling with 3D printing in mind](https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135)
- Peer-reviewed FDM pin joints (PLA, d = 10 mm, printed assembled, no supports): "lowest resistance at a clearance in the range t = 0.15–0.25 [mm]" (published 28 Sept 2025) **[P, abstract via Crossref]** — [Technologies 13(10):436, doi 10.3390/technologies13100436](https://doi.org/10.3390/technologies13100436)
- Peer-reviewed FDM hinge farm study (PLA, print farm, 2023): "forces necessary to initially release and move the joints begins to rise until complete fusion of bushing and hinge axis"; "Hinge axes aligned with the Z-axis allowed tighter critical clearances than axes aligned in the XY-plane" with less scatter **[P, abstract]** — [Frohn-Sörensen, Mouratidis, Engel, Procedia CIRP 120:129–134](https://italg.wiwi.uni-siegen.de/en/?p=2994); DOI record [10.1016/j.procir.2023.08.024](https://doi.org/10.1016/j.procir.2023.08.024)
- Make: magazine test (older, Nov 2014): a print-in-place robot with "just over 0.3 mm between the limb parts" fused on most printers; only "few printers… could print this design flawlessly with stock settings" **[S]** — [Make: Print-in-Place, the Additive Holy Grail](https://makezine.com/2014/11/10/print-in-place-the-additive-holy-grail/)
- UMD Terrapin Works comparison (2023, PLA, 0.2 mm profiles): no 0.05 or 0.1 mm "negative tolerance" disks spun on either a Bambu P1P or Prusa MK3; 0.15 mm spun only partially on the "faster" profiles; 0.2–0.3 mm spun on MK3 (both 0.2 mm profiles) and on the P1P "Standard" profile, but the P1P "Strength" profile fused everything up to 0.25 mm, attributed to "the excessive size of the Z seams" **[P, PDF text]** — [P1P vs MK3 Report 2023](https://terrapinworks.umd.edu/sites/terrapinworks.umd.edu/files/P1P%20vs%20MK3%20Report%202023.pdf)
- Bambu forum (Nov 2024): users report print-in-place hinges working at 0.15 mm on default A1 settings and ~0.1 mm after dropping flow to 97% and nozzle temp 220→210 °C; one poster treats 0.2 mm as the pass mark **[S]** — [Bambu forum: Print In Place Hinge Tolerances](https://forum.bambulab.com/t/print-in-place-hinge-tolerances/111715)
- Vendor blog (Sovol, 8 Aug 2026): PLA radial clearance "tight" 0.15–0.20, "standard" 0.20–0.30, "loose" 0.30–0.40; PETG +0.05–0.10 per side; start at 0.25 mm per side; adjust in 0.05 mm steps **[S]** — [Sovol: Print-in-Place 3D Printing](https://www.sovol3d.com/blogs/news/print-in-place-3d-printing-how-to-design-hinges-joints-and-moving-parts-that-actually-work)
- Vendor blog (JLC3DP, 27 Aug 2026): 0.2–0.3 mm per side (0.4–0.6 total) for FDM 0.4 mm nozzle; PETG 0.25–0.35 per side; a 0.25 mm gap "is not reliably reproduced with a 0.6 nozzle" **[S]** — [JLC3DP: 3D Printed Articulated Animals](https://jlc3dp.com/blog/3d-printed-articulated-animals-design)
- Model pages seen via search snippets: one Printables flexi uses "0.4 mm on each side of the joint = 0.8 mm total"; MakerWorld Flexi Mini T-Rex is "tuned for PLA", warns "TPU may fuse joints", and says not to rotate the model on the bed because it is "optimized for bridging and joint clearance" **[S]** — [MakerWorld flexi trex listing](https://makerworld.com/de/models/2734085-flexi-trex)

**Minimum link thickness / engagement**
- Flexi Rex: "Shackle thickness: at least 1.58mm", "shackle width: 3 mm", "axle length: 4 mm" at 100 % scale (13 mm body thickness) **[P]** — [Hinge_dimensions.png](https://github.com/DrLex0/print3D-FlexiRex/blob/master/images/Hinge_dimensions.png); default thickness 13 mm from [Cenwulf/FlexiRex-Fusion README](https://github.com/Cenwulf/FlexiRex-Fusion)
- Cenwulf's parametric Flexi Rex: `joint_axle_offset` exists to keep the shackle wall "usually at least two extrusion widths to maintain printability and structural integrity"; min overall scale "~0.54 (7/13) with a 0.4 mm nozzle… ~0.31 (4/13) with a 0.2 mm nozzle", with joint rescaling; `joint_scale_factor` max ≈ 1.2 before the shackle cut-out bisects small segments **[P]** — [Cenwulf/FlexiRex-Fusion](https://github.com/Cenwulf/FlexiRex-Fusion)
- CuteFlexi Studio strength floors: "Neck at least 3 mm wide, socket wall 2.6 mm, lips at least 0.9 mm, and a socket mouth at least 0.7 mm narrower than the knob" (design-rule assertions, not yet print-validated) **[P]** — [ais80/cuteflexi-studio](https://github.com/ais80/cuteflexi-studio)
- Prusa KB perimeter widths: 1 perimeter ≈ 0.45 mm, 2 ≈ 0.9, 3 ≈ 1.35, 4 ≈ 1.8 mm; "Walls thinner than one nozzle perimeter are not printable." **[P]** — [Prusa KB](https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135)
- JLC3DP: structural wall 1.2–1.6 mm, stressed joint wall 1.6–2.0 mm, pins/snap features > 1.5 mm **[S]** — [JLC3DP](https://jlc3dp.com/blog/3d-printed-articulated-animals-design)

**First layer / elephant foot**
- PrusaSlicer EFC: "Values around 0.2 mm usually work well for the default 0.4 mm nozzle"; affects only the first layer; a brim that fails to connect means EFC is set too high **[P]** — [Prusa KB Elephant foot compensation](https://help.prusa3d.com/article/elephant-foot-compensation_114487)
- Prusa KB: fillets on bottom edges create steep overhangs; "use chamfer instead if a perfect part finish is a priority" **[P]** — [Prusa KB Modeling](https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135)
- Sovol: 0.5–1.0 mm × 45° bottom chamfer on pin and socket as elephant-foot relief; EFC 0.1–0.2 mm; "Fused at first layer only → elephant's foot" **[S]** — [Sovol](https://www.sovol3d.com/blogs/news/print-in-place-3d-printing-how-to-design-hinges-joints-and-moving-parts-that-actually-work)
- JLC3DP: "0.15–0.20 of first-layer spread per side can consume a 0.4 total gap"; raise moving features off the plate or orient so the tightest joint is not on layer one **[S]** — [JLC3DP](https://jlc3dp.com/blog/3d-printed-articulated-animals-design)
- Bambu Studio has its own EFC page (content not retrievable; page exists) **[U]** — [Bambu wiki elephant-foot](https://wiki.bambulab.com/en/software/bambu-studio/parameter/elephant-foot)

**Layer height, perimeters, infill, orientation**
- DrLex recommended settings at 100 %: "0.2 mm layers, 3 perimeters, 15% infill, solid infill threshold 8 mm², 5 top layers and 4 bottom layers, no supports and no raft"; "If you scale up the model, you should also scale up the number of perimeters and/or their width"; too much infill makes the head heavy and the Rex "faceplant" **[P]** — [README, Recommended Print Settings](https://github.com/DrLex0/print3D-FlexiRex)
- Flexi Factory (Dan Sopala) listings: "No Supports (adding supports will hinder functionality)", 15–20 % infill, three walls, PLA; split files exist to "scale it up to max out your build plate" **[S]** — [MyMiniFactory Flexi Factory Dragonfly](https://www.myminifactory.com/object/3d-print-flexi-factory-print-in-place-dragonfly-330679)
- Frohn-Sörensen 2023: 0.1 mm layers "might lead to increased release forces", 0.3 mm layers "led to increased forces during the hinges' motion" **[P, abstract]** — [Siegen page](https://italg.wiwi.uni-siegen.de/en/?p=2994)
- Sovol: layer 0.16–0.20 mm, Arachne wall generator ("Classic can drop thin gaps"), inner-then-outer wall order, 3–4 perimeters on pins **[S]**; JLC3DP: 0.12–0.16 for small joints, 0.16–0.20 general **[S]**
- Other dragon listings via snippets: 0.16 mm / 3 perimeters / 5 % infill; 0.15–0.16 mm / 15 % / Arachne **[S]** — search result summary of [cgtrader](https://www.cgtrader.com/3d-print-models/games-toys/toys/mesh-mayhem-articulated-dragon-007) and [Printables 1335739](https://www.printables.com/model/1335739-dragon-action-figure)

**Break-in**
- DrLex: "This should move freely right after you take it off the build plate… If you need to use force to free the hinges, you still have some optimization work to do on your printing technique." **[P]** — [README](https://github.com/DrLex0/print3D-FlexiRex)
- Designer pages (snippets): "gently wiggling them to free them"; "work each articulated joint back and forth"; "the joints will also loosen normally… through repeated use" **[S]** — [Thangs Flexi Otter](https://thangs.com/m/1031356), [MakerWorld Flexi Bugs Beetle](https://makerworld.com/en/models/1284118-flexi-bugs-beetle)
- Sovol: let the print cool to room temperature first, then gentle force by hand or padded pliers **[S]** — [Sovol](https://www.sovol3d.com/blogs/news/print-in-place-3d-printing-how-to-design-hinges-joints-and-moving-parts-that-actually-work)

**Scaling (designer-stated limits, all snippets)**
- Flexi Otter "safe to scale to 85%"; Flexi Mickey "~80% depending on printer tolerance"; Flexi Clownette "Do not Downscale more than 20%… use at least 3 walls on the joints"; Flexi Snail "Minimum recommended downscale is 40%"; a generic set warns below 60 % joints "may become too tight and fuse"; one designer suggests scaling a stiff part "down by 1–2%" **[S]** — [MakerWorld Flexi Mickey Mouse](https://makerworld.com/en/models/2731850-flexi-mickey-mouse), [MMF Flexi Clownette](https://www.myminifactory.com/object/3d-print-flexi-clownette-330794), [MMF Flexi Snail](https://www.myminifactory.com/object/3d-print-flexi-snail-615642)
- Prusa forum: for stuck hinges, "scaling the model up 1–2%" or printing cooler **[S]** — [Prusa forum: Print in place hinges don't swivel](https://forum.prusa3d.com/forum/original-prusa-i3-mk3s-mk3-how-do-i-print-this-printing-help/print-in-place-hinges-dont-swivel)

### Inferences
- The one dimensioned flat-flexi spec (Flexi Rex) uses ~0.5 mm clearance — roughly double the 0.2–0.3 mm "per side" figures vendors quote — and its author explicitly says extra clearance only weakens the link. A generator should therefore treat clearance as a per-printer input with a conservative default near 0.4–0.5 mm for pin-in-loop hinges, not 0.2 mm.
- The Flexi Rex ratios are reusable as parameters: hole Ø ≈ 1.44 × axle Ø; shackle wall ≥ 1.58 mm ≈ 3.5 perimeters at 0.45 mm; inter-segment gap 1.2–1.8 mm ≈ 2.4–3.6× the hinge clearance (the body gap must exceed the hinge gap so segments never touch before the hinge binds).
- Two independent sources (Frohn-Sörensen 2023; UMD 2023) implicate layer-by-layer effects (Z seam blobs, layer height) rather than XY accuracy alone as the cause of fusion; a generator can mitigate by placing hinge axes vertical (Z) where the design allows and by exposing a Z-seam allowance.
- Min scale is nozzle-bound: Cenwulf's ~0.54 at 0.4 mm vs ~0.31 at 0.2 mm nozzle implies the limiting feature is shackle wall ≥ 2 extrusion widths, so a generator should compute min scale from `2 × extrusion_width / shackle_wall` rather than a fixed percentage.

### Gaps
- Kirbs' original Flexi Rex page (Thingiverse thing:1759297) could not be fetched; its licence and any design notes are unverified (DrLex states the whole lineage is CC BY-SA).
- No Prusa Knowledge Base or Bambu Wiki article specific to print-in-place/flexi joints was found; Prusa's only numeric guidance is the 0.3 mm "movable parts" line above.
- Flexi Factory, McGybeer and Cinderwing3D publish print settings but no dimensioned joint specs; none of their pages state clearance values.
- Living-hinge (thin-spine) rules for flexis: only historical mention (zheng3) and BOSL2's `living_hinge_mask` defaults (hinge gap = layer height, 0.2 mm) were found; no flexi-specific living-hinge thickness data.
- The Frohn-Sörensen full text (gap values in mm, printer models) was not accessible.

---

## 2. Fully 3D print-in-place articulated figures (ball-and-socket dragons etc.) and material choice

### Takeaway
No designer of the popular articulated dragons publishes socket geometry; the dimensioned ball-joint evidence is a 2012 SIGGRAPH Asia paper (SLS/PolyJet, not FDM: 0.2 mm gap fused, 0.3 mm worked, 5 mm minimum ball radius) and two 2026 code generators that assert rules (45° lips, socket mouth ≥ 0.7 mm narrower than the knob, neck ≥ 3 mm) without print validation. Clearance is absolute and does not scale with the model; PLA is the consensus material, PETG needs ~0.05–0.10 mm more per side, and TPU is reported to fuse in tight joints.

### Cited Findings

**Ball-and-socket geometry**
- Calì et al. 2012 (older; SLS and PolyJet, not FDM): generic joint = "cage-in-socket" ball joint; friction added by slightly enlarging two bands on the cage that rest in grooves of the socket; tolerance set 0.2–0.6 mm; "a gap of 0.2mm is too small as it causes the bands and socket to fuse together. With a 0.3mm gap the joint is easy to manipulate whilst maintaining good friction"; even 0.6 mm still holds poses; "the minimum size for producing functional joints was 5mm in radius for both printing processes"; band thickness set 2–12 mm; PolyJet thin bands "snap" under force, SLS more elastic **[P, PDF text]** — [JointFit low-res PDF](https://reality.tf.fau.de/projects/jointfit/jointfit-lowres.pdf); project page [JointFit](https://reality.tf.fau.de/projects/jointfit/jointfit.html)
- Calì et al.: tolerances "may be derived from known material parameters… [but] one and the same process may lead to different results, as individual printers may vary. Thus, we leave determination of joint dimensions to a calibration process that we run on each printer before model generation" (three calibration sets: tolerance, band thickness, outer radius) **[P]** — same PDF
- CuteFlexi Studio (2026): knob-in-socket-ring with "45° lips above and below… No surface is steeper than 45°, so no supports"; floors: neck ≥ 3 mm, socket wall 2.6 mm, lips ≥ 0.9 mm, socket mouth ≥ 0.7 mm narrower than knob; 25 test slices checked "no extrusion runs inside any hinge air gap"; "nothing has been printed yet" **[P]** — [ais80/cuteflexi-studio](https://github.com/ais80/cuteflexi-studio)
- PrintPal Flexi Model Creator: Saturn-shaped cutter (ring → socket, sphere → ball), auto-sized "slightly larger than the model's cross-section", scale 50–300 %; recommends "0.1–0.15 mm gap between joint parts" and 0.2 mm layers with 2–3 walls **[S, vendor tool page]** — [printpal.io flexi-model-creator](https://printpal.io/tools/flexi-model-creator)
- Sovol: captive ball-and-socket joints "use chamfered contact surfaces and overhangs of 45° or steeper"; horizontal hinge axes should use a "45° teardrop profile so the socket top bridges without drooping"; no ball numbers given **[S]** — [Sovol](https://www.sovol3d.com/blogs/news/print-in-place-3d-printing-how-to-design-hinges-joints-and-moving-parts-that-actually-work)
- Vendor snippets: socket radius "at least 5.03 cm for a 5.00 cm ball" (≈0.3 mm radial); 0.2–0.3 mm friction fit vs 0.4–0.5 mm free-sliding **[S]** — [Flashforge action-figure guide](https://www.flashforge.com/pt/blogs/news/how-to-3d-print-action-figures), [Qidi dragon guide](https://qidi3d.com/en-br/blogs/news/3d-print-articulated-dragons-guide)
- Cinderwing3D Crystal Dragon instructions (paywalled; snippet): "3 walls, 10–25% infill" **[S]** — [Thangs Crystal Dragon instructions](https://thangs.com/designer/Cinderwing3D/3d-model/Crystal%20Dragon-1060509/instructions)

**Overhangs, bridging, supports inside joints**
- Prusa KB: "A 3D printer can cleanly print overhanging structures with an angle between 45 and 60 degrees"; Nextruder printers with 360° cooling up to 75°; "short horizontal bridges can be printed without supports"; smaller nozzles reduce the angle **[P]** — [Prusa KB Modeling](https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135)
- Flexi Factory: "adding supports will hinder functionality" **[S]** — [MMF listing](https://www.myminifactory.com/object/3d-print-flexi-factory-print-in-place-dragonfly-330679)
- Sovol: "Support blockers over all moving voids. Avoid internal supports"; external bridge flow 0.90–0.95 **[S]**; JLC3DP: support interfaces inside gaps "lock joints permanently" **[S]**

**Scaling behaviour**
- Clearance scales with the model: "0.6 clearance at 50% scale becomes 0.3 (below minimum)… 1.6 wall becomes 0.8"; recommendation: scale visual details but "hold clearance, wall, connector, and retention dimensions constant or redesign them" **[S]** — [JLC3DP](https://jlc3dp.com/blog/3d-printed-articulated-animals-design)
- "If you scale your model, remember that the clearances scale too." **[S]** — [CLV Maker Center guide (PDF)](https://files.lasvegasnevada.gov/files/CLVMakerCenter-AssemblyGuide.pdf)
- At 150 % "the gap grows, the segments get heavier, and the joints go loose" **[S]** — search summary of [Qidi guide](https://kr.qidi3d.com/blogs/news/3d-print-articulated-dragons-guide)
- Cenwulf's parametric Rex decouples `scale_factor` from `joint_scale_factor`/`joint_axle_offset` precisely so joint walls can be held at ≥ 2 extrusion widths when the body is scaled **[P]** — [Cenwulf/FlexiRex-Fusion](https://github.com/Cenwulf/FlexiRex-Fusion)

**Printer-class tolerance**
- UMD 2023: both Bambu P1P and Prusa MK3 "consistently fall within ±0.2mm" dimensionally; print-in-place disks needed ≥ 0.2 mm on good profiles, and a single profile change (P1P "Strength") fused parts up to 0.25 mm via Z-seam size **[P]** — [UMD report](https://terrapinworks.umd.edu/sites/terrapinworks.umd.edu/files/P1P%20vs%20MK3%20Report%202023.pdf)
- Make: 2014 (older): "few printers… could print this design flawlessly with stock settings" at ~0.3 mm **[S]** — [Make:](https://makezine.com/2014/11/10/print-in-place-the-additive-holy-grail/)
- Bambu forum: tuned A1 reaches ~0.1 mm; default ~0.15 mm **[S]** — [forum thread](https://forum.bambulab.com/t/print-in-place-hinge-tolerances/111715)

**Failure modes**
- Fused joints: gap below printer capability, first-layer spread, supports in joints, down-scaling **[S]** — [JLC3DP](https://jlc3dp.com/blog/3d-printed-articulated-animals-design); Z-seam blobs **[P]** — [UMD](https://terrapinworks.umd.edu/sites/terrapinworks.umd.edu/files/P1P%20vs%20MK3%20Report%202023.pdf); "Fused full height → over-extrusion or clearance too tight" **[S]** — [Sovol](https://www.sovol3d.com/blogs/news/print-in-place-3d-printing-how-to-design-hinges-joints-and-moving-parts-that-actually-work)
- Snapped links: Kirbs' Rex "one of the links broke after some rough handling" → thicker shackles **[P]** — [DrLex README](https://github.com/DrLex0/print3D-FlexiRex); thin friction bands "snapped and broke" when twisted (PolyJet) **[P]** — [Calì PDF](https://reality.tf.fau.de/projects/jointfit/jointfit-lowres.pdf); "Pin breaks on break-free → weak Z adhesion or sharp corner; fix 3–4 walls, 0.5 mm × 45° chamfers" **[S]** — Sovol
- Sagging bridges / grinding; PETG stringing locking joints **[S]** — Sovol
- Balance failure: head-heavy Rex "faceplants" if infill too high; DrLex moved feet forward (2022) **[P]** — [DrLex README](https://github.com/DrLex0/print3D-FlexiRex)
- Slicer-level fusing: Bambu Studio users report print-in-place parts fusing when gaps are very small and hole compensation makes it worse **[S]** — [Bambu forum: Slicer fusing parts with small gaps](https://forum.bambulab.com/t/slicer-fusing-parts-with-small-gaps/251065)

**Materials**
- DrLex: photos printed in ABS "but pretty much any material should work. You could print it in a flexible filament… but plain PLA is probably easiest" **[P]** — [README](https://github.com/DrLex0/print3D-FlexiRex)
- Flexi Factory: "PLA works great" **[S]**; Flexi Mini T-Rex: "TPU may fuse joints" **[S]** — [MakerWorld](https://makerworld.com/de/models/2734085-flexi-trex)
- Sovol: PLA "crisp bridges, low stringing… brittle under impact, weaker in fatigue for flexural living hinges"; PETG tougher but "prone to stringing and oozing", needs +0.05–0.10 mm per side and drying; TPU not covered **[S]**
- JLC3DP: PETG 0.25–0.35 per side; TPU "suited for bendable designs, but tight captive joints are harder to print" **[S]**
- Prusa KB: PETG and flexible filaments are weaker at bridging and overhangs **[P, via search of help.prusa3d.com]** — [Prusa KB PETG](https://help.prusa3d.com/article/petg_2059), [Flexible materials](https://help.prusa3d.com/article/flexible-materials_2057)
- Bambu forum: PETG flex parts "past a certain point it just snaps instead of deforming like PLA" **[S]** — [forum thread](https://forum.bambulab.com/t/experimenting-with-a-new-way-to-flex/126203)
- A Printables PIP hinge designer: "PLA is too brittle for that design, so PETG or ASA" (load-bearing hinge, not a toy) **[S]** — [Printables 120636](https://www.printables.com/model/120636-print-in-place-hinge-petgasa-high-strength-300-lr)

### Inferences
- For FDM ball joints, the Calì 0.3 mm result is a floor, not a target: it was obtained on SLS/PolyJet with ~0.1 mm resolution; FDM evidence (UMD, forum) says 0.2–0.3 mm works only on well-tuned machines, so a generator default of ~0.35–0.4 mm radial for captive balls with a user-calibrated override is the defensible choice. PrintPal's 0.1–0.15 mm recommendation is an outlier unsupported by any other source.
- Minimum ball size: Calì's 5 mm radius minimum (10 mm ball) on finer processes suggests FDM balls below ~8–10 mm diameter are risky; the 2025 Technologies study also used d = 10 mm pins. Generators should floor joint diameter rather than scale it linearly with the mesh.
- Socket retention needs an undercut (mouth narrower than ball) that is itself an overhang; the 45°-lip approach (CuteFlexi, Sovol) is the only support-free construction described, so socket openings should be designed as 45° chamfered lips, with the opening half-angle derived from `asin((ball_r - lip)/ball_r)`.

### Gaps
- No primary source gives FDM ball-and-socket numbers (ball Ø, socket opening angle, radial clearance) from a validated print; CuteFlexi's floors are unprinted assertions.
- Cinderwing3D, McGybeer and Flexi Factory publish no joint geometry; their pages are paywalled or blocked.
- No peer-reviewed FDM ball-joint clearance study in 2022–2026 was found (searches returned only the 2021 pin-joint and 2025 rotational-joint papers).
- TPU-specific articulated-joint data: only anecdotal "may fuse"/"harder" claims.

---

## 3. Parametric / code generators (OpenSCAD, Python, browser, Blender)

### Takeaway
There is no mature open-source Python library for articulated print-in-place figures. The closest fits are Flexifier (CadQuery + Streamlit, GPL/AGPL, 2023–2025, image → flat flexi with hard-coded 0.8 mm tolerances), BOSL2 (OpenSCAD, BSD-2-Clause, actively maintained, print-in-place cone-pin knuckle hinge with `gap` and `$slop`), and two 2026 experiments (tusosos/articulated-toys, MIT, Python CLI with `--clearance` and waist-detection segmentation; ais80/cuteflexi-studio, browser, no licence). Blender add-ons are paid and under-documented.

### Cited Findings

| Tool | Type / kernel | Licence | Activity (GitHub API, 2026-11-08) | Exposed parameters | Source |
|---|---|---|---|---|---|
| BOSL2 `hinges.scad` | OpenSCAD library | BSD-2-Clause | 2,453 stars; pushed 2026-11-08 | `knuckle_hinge(length, segs, offset, …)`: `gap` (default 0.2), `knuckle_diam` (4), `pin_diam` (1.75; PIP default knuckle−1), `in_place` (45° cones, angle settable), `teardrop`, `clearance` (raise pin hole ~1–2 layers), `$slop` (pin hole + 2×slop); `living_hinge_mask(l, thick, layerheight=0.2, foldangle=90, hingegap=layerheight)`; `snap_lock/snap_socket` | [hinges.scad wiki](https://github.com/BelfrySCAD/BOSL2/wiki/hinges.scad) **[P]**; [repo](https://github.com/BelfrySCAD/BOSL2) **[P]** |
| BOSL2 `$slop` | constant | — | — | default 0.0; calibration part with holes at 0.00–0.25 in 0.05 steps; examples 0.15, 0.17, 0.2 | [constants.scad wiki](https://github.com/BelfrySCAD/BOSL2/wiki/constants.scad) **[P]** |
| Flexifier | Python 3, CadQuery, Streamlit web app + OpenSCAD snippet | GitHub API: AGPL-3.0; README: code GPL-3.0, models CC BY-NC-SA 4.0 (discrepancy) | 38 stars, 21 forks; created 2023-06-14; pushed 2025-02-07 | Input png/jpg/svg; output stl/step; model height (0–100 mm, default 10); per-hinge: type `normal`/`ball`, hinge thickness (0.1–20), joint external diameter, image cut thickness/length, X/Y position, rotation, "expose ball joint"; **tolerances hard-coded**: `hor_tolerance=0.8`, `vert_tolerance=0.8`, ball `tolerance=0.4` | [repo](https://github.com/Lucandia/Flexifier), [streamlit_app.py](https://github.com/Lucandia/Flexifier/blob/main/streamlit_app.py) **[P]**; Printables page blocked (403) |
| Cenwulf FlexiRex-Fusion | Autodesk Fusion parametric (not scriptable) | CC BY-SA 4.0 | 2 stars; pushed 2025-10-21 | `scale_factor`, `joint_scale_factor` (≤~1.2), `joint_axle_offset`, `thickness_offset` | [repo](https://github.com/Cenwulf/FlexiRex-Fusion) **[P]** |
| tusosos/articulated-toys | Python CLI ("Manus Agent Skill"); numpy-stl, trimesh, shapely, manifold3d | MIT | 4 stars; pushed 2026-02-23 | `generate_articulated.py --preset` (13 creatures, hook-and-axle joints, wings/legs via ball-socket); `articulate_model.py --input --segments --joint-size --clearance --method waist` converts any STL/OBJ/3MF; "Auto-scaling joints" | [repo](https://github.com/tusosos/articulated-toys) **[P]** (README partially fetched; main-branch README 404, master worked) |
| ais80/cuteflexi-studio | Browser; manifold-3d WASM; 3MF export; Python slicer check | **No licence** ("all rights are reserved by default") | pushed 2026-10-19 | printer presets (Bambu A1/A1 mini/P1/X1, Snapmaker U1, generic 220 mm) with "recommended air gap"; strength floors; hinged wings; AMS colour workflows; "nothing has been printed yet" | [repo](https://github.com/ais80/cuteflexi-studio) **[P]** |
| Seglectic/HinGen | Browser; Manifold WASM; STL | MIT | pushed 2026-11-08 | leaf width/thickness, knuckle count, clearance ("good starting point is 0.4 mm"), screw holes, gussets; print-in-place butt hinge | [repo](https://github.com/Seglectic/HinGen) **[P]** |
| HarkonenBade/parametric_hinge | OpenSCAD | MIT | pushed 2022-08-06 (older) | "print in place capable hinge"; README one line | [repo](https://github.com/HarkonenBade/parametric_hinge) **[P]** |
| Pan-Chera/Multi-Agent-CAD | LLM agent pipeline → build123d; STEP/STL/GLB/URDF | MIT | — | natural-language brief; claims "print-in-place mechanisms with separate bodies and functional clearances"; no numeric clearances; "Validate generated geometry and joints before manufacturing" | [README](https://github.com/Pan-Chera/Multi-Agent-CAD) **[P]** |
| Flexi Graphic Generator | OpenSCAD on MakerWorld (SVG → flexi sheet) | not seen | — | SVG upload; single-line label | [MakerWorld 1841003](https://makerworld.com/models/1841003) **[S]** |
| ChainMaker / EasyLink / Magic Snake Builder | OpenSCAD / Fusion / OpenSCAD (ball-and-socket snake; "not really any sane way to make this Customizer-able") | not seen | — | link count or target length; bed size | [MakerWorld 3090086](https://makerworld.com/fr/models/3090086-chain-maker-parametric-cuban-classic-chains), [MakerWorld 3217758](https://makerworld.com/zh-tw/models/3217758-easylink-simple-parametric-chain-generator), [MMF 76304](https://www.myminifactory.com/object/3d-print-76304) **[S]** |
| PrintPal Flexi / Articulated Model Creator | Browser SaaS; ball-and-socket Saturn cutters; STL in/out | proprietary; placement free, export $10/mo | — | cut axis, position, scale 50–300 %, rotation; no clearance control | [printpal.io](https://printpal.io/tools/flexi-model-creator) **[S]** |
| JointLab (Blender) | Blender 4.0–5.2 extension | GPL (paid, $65/seat, v1.0 Early Access) | "4 months ago"; 20+ sales | joint types/parameters not documented on page | [Superhive docs](https://superhivemarket.com/products/jointlab-/docs) **[S]** |
| SlicerJoint Pro (Blender) | add-on | not seen | v1.1.0 | "Improved Articulated Mode… cleaner print-in-place workflows" | [BlenderArtists](https://blenderartists.org/t/slicerjoint-pro-v1-1-0/1651012) **[S]** |
| Flexi Joint Cutter | STL negative volume for Boolean subtraction | not seen | — | none (fixed cutter) | [Cults3D](https://cults3d.com/:3913105) **[S]** |
| 3D Joint Generator (Graffinity3D) | Blender geometry-nodes add-on, $12.99 | not seen | — | not print-in-place specific | [Gumroad](https://graffinity3d.gumroad.com/l/jointgenerator) **[S]** |
| Kinergy | Grasshopper/Rhino-era research tool (UIST 2022) for print-in-place springs/gears | open source per authors; licence not retrievable | — | kinetic units (spring, transmission, lock) | [Kinergy project](https://makeabilitylab.cs.washington.edu/project/kinergy) **[S]** |

- CadQuery/build123d: no articulated-joint or hinge library was found; Printago's pre-installed `bd_warehouse` is a parts library without hinges **[S]** — [Printago docs](https://docs.printago.io/docs/parts/cadquery/libraries); build123d itself has assembly "joints" for positioning, not printable joint geometry **[U — not verified in docs]**
- Flexifier's README publishes a reusable OpenSCAD pattern: `difference(){ linear_extrude(...) import(svg); diff_hinge(...) }` then `uni_hinge(...)` to add the pin back — i.e. the "cut slot, add captive pin" idiom **[P]** — [Flexifier README](https://github.com/Lucandia/Flexifier)

### Inferences
- For a deterministic Python CLI, the realistic path is to borrow idioms rather than import a library: Flexifier (CadQuery pin-in-slot with 0.8 mm tolerance), BOSL2 (cone-pin knuckle with `gap` + `$slop` + teardrop), and tusosos (trimesh/manifold3d segmentation + `--clearance`). All three are permissively or copyleft licensed (BSD-2 / GPL-AGPL / MIT); AGPL on Flexifier matters if the generator is offered as a web service.
- Every generator exposes clearance as a single scalar; none separates XY from Z clearance, first-layer relief, or Z-seam allowance even though the FDM evidence (Frohn-Sörensen, UMD) says those differ. That is the gap a "tolerance profile" (Section 6) should fill.
- None of the 2026 generators (cuteflexi-studio, articulated-toys, Multi-Agent-CAD, HinGen) reports physical validation of its default clearances; treat their numbers as hypotheses.

### Gaps
- Flexifier licence ambiguity (API SPDX AGPL-3.0 vs README GPL-3.0) is unresolved; check the LICENSE file before reuse.
- tusosos/articulated-toys default clearance value, joint geometry details and SKILL.md were not retrievable (404 on guessed paths; GitHub API rate-limited).
- No star/commit data for Flexi Graphic Generator, ChainMaker, Magic Snake Builder, JointLab (not on GitHub).
- CuteFlexiMaker (a MakerWorld crowdfunded flexi-pet builder referenced by cuteflexi-studio) could not be researched (search budget exhausted).

---

## 4. Academic work on automatically articulating a static shape for print-in-place fabrication

### Takeaway
The two foundational systems are both from 2012 (Bächer et al., SIGGRAPH; Calì et al., SIGGRAPH Asia): both take a rigged/skinned mesh, place friction joints automatically (medial axis / rig joints), carve them with CSG and print as one piece — but on PolyJet/SLS/Objet-class machines, and neither released code. Since then the literature has moved to tolerance modelling of FDM non-assembly joints (2021, 2023, 2025), spring/kinematic mechanisms (Kinergy 2022, All-in-One Print 2023) and fabrication-aware text-to-3D (2024–2025); no 2024–2026 paper on automatic print-in-place joint synthesis for FDM figures was found.

### Cited Findings
- **Bächer, Bickel, James, Pfister 2012 (older), ACM TOG 31(4), SIGGRAPH.** Input: skinned mesh; "we first extract a set of potential joint locations… estimate mechanical friction joints that satisfy inter-joint non-penetration and other fabrication constraints… place joint centers on an approximate medial axis… and maximize each joint's minimal cross-sectional area"; printed "as single, assembled pieces" **[P, Crossref abstract]** — [doi 10.1145/2185520.2185543](https://doi.org/10.1145/2185520.2185543); project page [Harvard VCG](https://vcg.seas.harvard.edu/publications/20120101-fabricating-articulated-characters-from-skinned-meshes); code not mentioned on project page or ISTA record ("No fulltext has been uploaded") — [ISTA record](https://research-explorer.ista.ac.at/record/2101); Harvard lists it as a licensable technology — [Harvard OTD](https://otd.harvard.edu/explore-innovation/technologies/method-to-fabricate-articulated-characters-from-skinned-meshes)
- **Calì, Calian, Amati, Kleinberger, Steed, Kautz, Weyrich 2012 (older), ACM TOG 31(6), SIGGRAPH Asia.** Takes "an appropriately rigged 3D model, automatically fits novel 3D-printable and posable joints, and provides an interface for specifying rotational constraints"; generic cage-in-socket ball joint template inserted at each rig joint (skipping "virtual nodes" with >2 bones), scaled to surrounding geometry; four constraint pins at 45° define rotation limits via slerp; limb vs attachment joints; printed on EOS FORMIGA P100 (SLS) and Objet PolyJet; per-printer calibration sets; numeric results in Section 2 above; no code release mentioned **[P]** — [PDF](https://reality.tf.fau.de/projects/jointfit/jointfit-lowres.pdf), [DOI](https://doi.org/10.1145/2366145.2366149)
- **Luo, Baran, Rusinkiewicz, Matusik 2012 (older), "Chopper: Partitioning Models into 3D-printable Parts", TOG 31(6)** — partitioning for build volume, not articulation; bibliographic only **[S]** — [SIGGRAPH history](https://history.siggraph.org/?p=102394)
- **Coros et al. 2013 (older), "Computational Design of Mechanical Characters", TOG 32(4)**: sketch motion curves → planar linkage mechanisms + gear trains, 3D-printed **[S]** — [Disney Research](https://studios.disneyresearch.com/2013/07/21/computational-design-of-mechanical-characters/); **Thomaszewski et al. 2014** linkage-based characters; **Megaro et al. 2015**, "Interactive Design of 3D-Printable Robotic Creatures", TOG 34(6) (servo robots, fabrication blueprints) **[S]** — [Disney Research](https://studios.disneyresearch.com/2015/11/04/interactive-design-of-3d-printable-robotic-creatures/). These are linkage/robot design, not print-in-place friction joints.
- **Schächtl, Schleich, Wartzack 2021 (older), Applied Sciences 11(4):1860**: FDM non-assembly mechanisms have "comparatively large joint clearances and geometric deviations depending on machine-specific process parameters"; ML models predict deviations, multi-body simulation evaluates clearance-affected joints; planar 8-bar example; goal "Print first time right" **[P, Crossref abstract]** — [doi 10.3390/app11041860](https://doi.org/10.3390/app11041860)
- **Processes 9(6):925, 2021 (older)**: Taguchi L27 with infill density, imposed shaft–hole clearance and layer thickness; GA-ANN minimum "absolute relative clearance" 0.0386, validated within 4 %; rational function to map designed → obtained clearance **[P, Crossref abstract]** — [doi 10.3390/pr9060925](https://doi.org/10.3390/pr9060925)
- **He, Su, Peng, Lipton, Froehlich 2022 (older), Kinergy, UIST 2022**: print-in-place helical/spiral springs, gears, compliant locks; open-source code announced **[S]** — [Kinergy PDF](https://makeabilitylab.cs.washington.edu/media/publications/He_KinergyCreating3DPrintableMotionUsingEmbeddedKineticEnergy_UIST2022.pdf)
- **Li et al. 2023 (older), All-in-One Print, CHI 2023, DOI 10.1145/3544548.3581440**: "Arch-printing and Support-bridges" method converts solid models into printable kinematic mechanisms (rotate, slide, screw; multi-stable states) output as G-code for FDM; design tool provided **[S, abstract via aggregator]** — [MIT DSpace record](https://dspace.mit.edu/handle/1721.1/150631); bitstream fetch failed
- **Frohn-Sörensen, Mouratidis, Engel 2023, Procedia CIRP 120**: statistical hinge study on a public print farm; Z-aligned axes tolerate tighter clearance; layer height effects **[P, abstract]** — [Siegen](https://italg.wiwi.uni-siegen.de/en/?p=2994)
- **Technologies 13(10):436, 28 Sept 2025**: "Basic principles for the design of assembled rotational joints, built without support structures"; two robot models; current-draw proxy for rolling resistance; PLA d = 10 mm, best clearance 0.15–0.25 mm **[P, abstract]** — [doi 10.3390/technologies13100436](https://doi.org/10.3390/technologies13100436)
- **Fabrication-aware generation (not articulated)**: Atlas3D (arXiv 2405.18515, 2024) enforces self-supporting text-to-3D for "simulation and fabrication"; arXiv 2511.16434 (Nov 2025) optimises text-to-3D for support efficiency **[S]** — [Atlas3D](https://arxiv.org/pdf/2405.18515), [2511.16434](https://arxiv.org/pdf/2511.16434v1)
- **FAU "JointFit" project page** hosts the Calì 2012 paper (it is not new work; the page is undated but the PDF is the 2012 TOG paper) **[P]** — [FAU](https://reality.tf.fau.de/projects/jointfit/jointfit.html)

### Inferences
- The Bächer/Calì pipeline (rig → joint sites → joint template scaled to local cross-section → CSG carve → per-printer calibration) is directly re-implementable in Python with trimesh/manifold3d; the missing piece for FDM is replacing their SLS/PolyJet joint template with a support-free ball-in-45°-lipped-socket or cone-pin hinge.
- Bächer's "maximize minimal cross-sectional area" criterion is the formal version of DrLex's "provide as much material around the axle hole as possible" — a generator check should compute the minimum solid cross-section through each joint and compare it against a perimeter-based floor.
- The 2021–2025 tolerance papers all treat clearance as process-dependent and propose calibration/prediction rather than a universal value, matching the community's "print a test ladder" practice.

### Gaps
- No code was found for Bächer 2012, Calì 2012 or All-in-One Print; Kinergy's licence file could not be read.
- No SIGGRAPH/UIST/CHI 2024–2026 paper on automatic print-in-place articulated-figure synthesis was found (searches on "print-in-place" + UIST/2024/2025 returned nothing relevant); this may be a search-coverage gap rather than absence.
- Full texts of Frohn-Sörensen 2023, Processes 2021 and Technologies 2025 were not accessible (MDPI 403; Elsevier redirect), so printer models and raw gap data are missing.

---

## 5. AI articulation / rigging research and its relevance to print-in-place joint placement

### Takeaway
2025–2026 auto-rigging models (MagicArticulate, RigAnything, UniRig, Anymate, Puppeteer, Rigel3D) predict skeleton joints, hierarchy and skinning weights for arbitrary meshes — exactly the "appropriately rigged 3D model" that Bächer 2012 and Calì 2012 required as input — but no paper or tool was found that connects them to printable joint synthesis; the only automatic joint placers for print-in-place (tusosos' waist detection, Multi-Agent-CAD) are heuristics/LLM pipelines without validation.

### Cited Findings
- **MagicArticulate** (arXiv 2502.12135, 17 Feb 2025; CVPR 2025): "automatically transforms static 3D models into articulation-ready assets"; Articulation-XL benchmark "over 33k 3D models"; autoregressive skeleton generation; code Apache-2.0, 418 stars, last push 2025-09-14 **[P]** — [arXiv](https://arxiv.org/abs/2502.12135), [GitHub Seed3D/MagicArticulate](https://github.com/Seed3D/MagicArticulate)
- **RigAnything** (arXiv 2502.09615, 13 Feb 2025; SIGGRAPH 2025 per Adobe): "probabilistically generating joints and skeleton topologies and assigning skinning weights in a template-free manner", autoregressive **[P]** — [arXiv](https://arxiv.org/abs/2502.09615), [Adobe Research](https://research.adobe.com/publication/riganything-template-free-autoregressive-rigging-for-diverse-3d-assets); public code repo not found **[U]**
- **UniRig** (SIGGRAPH 2025): "Skeleton Tree Tokenization"; MIT licence; 2,078 stars; last push 2026-06-04 **[P]** — [GitHub VAST-AI-Research/UniRig](https://github.com/VAST-AI-Research/UniRig)
- **Anymate** (arXiv 2505.06227, 9 May 2025): 230K rigged assets; "three sequential modules for joint, connectivity, and skinning" **[P]** — [arXiv](https://arxiv.org/abs/2505.06227), [project](https://anymate3d.github.io); repo path not confirmed **[U]**
- **Puppeteer** (arXiv 2508.10898, 14 Aug 2025; NeurIPS 2025 Spotlight): "auto-regressive transformer that introduces a joint-based tokenization strategy… hierarchical ordering"; Apache-2.0; 444 stars; authors report lower Chamfer joint errors than MagicArticulate/UniRig and 1.6–1.9× speedups (self-reported) **[P/S]** — [arXiv](https://arxiv.org/abs/2508.10898), [GitHub Seed3D/Puppeteer](https://github.com/Seed3D/Puppeteer)
- **Rigel3D** (arXiv 2605.13129, 13 May 2026): "jointly models geometry and rig structure through coupled surface and skeleton structured latent representations" — generation of rigged meshes rather than post-hoc rigging **[P]** — [arXiv](https://arxiv.org/abs/2605.13129)
- **Articulate-Anything** (arXiv 2410.13882, Oct 2024; ICLR 2025): VLM "generate[s] code that can be compiled into an interactable digital twin for use in standard 3D simulators"; mesh retrieval; 230 stars; no licence file detected **[P]** — [arXiv](https://arxiv.org/abs/2410.13882), [GitHub vlongle/articulate-anything](https://github.com/vlongle/articulate-anything)
- **Articulate AnyMesh** (arXiv 2502.02590, Feb 2025): converts "any rigid 3D mesh into its articulated counterpart in an open-vocabulary manner" via VLMs; simulation-oriented **[P]** — [arXiv](https://arxiv.org/abs/2502.02590)
- **ArtFormer** (arXiv 2412.07237, Dec 2024; CVPR 2025): "tree of tokens… transformer to generate both the object's high-level geometry code and its kinematic relations", SDF part decoder; 44 stars; no licence file **[P]** — [arXiv](https://arxiv.org/abs/2412.07237), [GitHub](https://github.com/ShuYuMo2003/ArtFormer)
- **ArtLLM** (arXiv 2603.01142, Mar 2026), **ArtGen** (arXiv 2512.12395, Dec 2025), **GAOT** (arXiv 2512.03566, MMAsia '25): articulated-asset generation for simulation/robotics; no printability **[P/S]** — [ArtLLM](https://arxiv.org/abs/2603.01142), [ArtGen](https://arxiv.org/pdf/2512.12395), [GAOT](https://arxiv.org/html/2512.03566v1)
- **Bridge to fabrication — what exists**: Bächer 2012 and Calì 2012 both consume a rig ("takes a skinned mesh as input"; "takes an appropriately rigged 3D model") **[P]** — Crossref abstracts above. The only automatic print-in-place joint placers found are heuristic: tusosos `--method waist` ("finds natural joint locations") **[P]** — [repo](https://github.com/tusosos/articulated-toys); Multi-Agent-CAD's LLM pipeline **[P]** — [README](https://github.com/Pan-Chera/Multi-Agent-CAD). A search for rig-to-printable-figure work in 2024–2025 returned only RigNet (2020) and the 2012 papers **[S]**.

### Inferences
- A predicted rig gives three things a print-in-place generator needs: joint positions (where to cut), bone directions (hinge/ball axis), and skinning weights (which triangles belong to which rigid segment, i.e. the CSG partition). This makes UniRig/MagicArticulate/Puppeteer a drop-in replacement for the manual rig in the 2012 pipelines; the remaining work is purely geometric (joint template, clearance, support-free orientation).
- Rig joints are kinematic centres, not fabrication-safe centres; Bächer's medial-axis + maximal-cross-section adjustment should still be applied after prediction to avoid joints sitting at thin necks.
- Licensing is favourable for a pipeline: UniRig (MIT) and MagicArticulate/Puppeteer (Apache-2.0) are compatible with a commercial or open generator; Articulate-Anything and ArtFormer have no licence file and should not be depended on.

### Gaps
- No paper, preprint or tool bridging neural rigging to printable joints was found (search budget ended before a final targeted pass; confidence moderate).
- RigAnything and Anymate code locations/licences unverified.
- No evaluation exists of how well predicted skeletons align with the segment boundaries flexi designers choose by hand (e.g., Flexi Rex's ~14 segments).

---

## 6. Calibration: tolerance test prints and a codifiable per-printer "tolerance profile"

### Takeaway
Community tests converge on a clearance ladder from 0.05/0.10 to 0.30–0.40 mm in 0.05 mm steps, printed in the final orientation, with separate XY and Z gaps; official vendor guidance is limited to dimensional compensation (PrusaSlicer XY size/EFC; Bambu X-Y hole/contour compensation measured on a test print, half the error), and the 2012 SIGGRAPH Asia paper already formalised per-printer calibration sets (gap, band thickness, radius) run before model generation.

### Cited Findings
- **Prusa KB**: accuracy "at least 0.2 mm"; movable parts "at least 0.3 mm"; EFC "around 0.2 mm… for the default 0.4 mm nozzle"; XY size compensation is for "small corrections, such as tweaking the size of threads or holes", positive enlarges, skipped when multi-material painting is used; no Z equivalent **[P]** — [Modeling](https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135), [EFC](https://help.prusa3d.com/article/elephant-foot-compensation_114487), [Per-model settings](https://help.prusa3d.com/article/per-model-settings_1674)
- **Bambu wiki (official, seen only via search snippet)**: X-Y hole compensation in mm, default 0; print a test, measure holes with calipers, "take that average error, divide it by two, and enter the result"; X-Y contour compensation for outer walls; hole compensation "only changes the size of the circular hole" **[S — official page, snippet]** — [3D prints shrinkage](https://wiki.bambulab.com/en/knowledge-sharing/3d-prints-shrinkage), [XY hole/contour compensation](https://wiki.bambulab.com/en/software/bambu-studio/xy-hole-contour-compensation). Forum limitations: only closed holes; non-linear across sizes; unavailable for multi-material; worsens print-in-place gaps **[S]** — [forum 169100](https://forum.bambulab.com/t/x-y-hole-compensation-undersized-round-holes-and-outer-diameters/169100), [forum 251065](https://forum.bambulab.com/t/slicer-fusing-parts-with-small-gaps/251065)
- **BOSL2 `$slop` calibration part**: six holes at 0.00–0.25 in 0.05 steps; choose the smallest the plug fits "without much force"; default 0 **[P]** — [constants.scad](https://github.com/BelfrySCAD/BOSL2/wiki/constants.scad)
- **Multi-Type Tolerance Test (MakerWorld 137989)**: tests XY and Z, print-in-place vs assembled; PIP gaps at 0.10 and 0.15 mm "fuse by design" to show the limit; PIP "will generally need more tolerance than parts printed separately" **[S]** — [MakerWorld 137989](https://makerworld.com/en/models/137989-multi-type-tolerance-test)
- **Hinge & Tolerance Clearance Test**: five PIP hinges at 0.10/0.15/0.20/0.25/0.30 mm **[S]**; **Vertical Tolerance Test (538503)**: Z-gap test with 0.2/0.08 mm profiles **[S]** — [MakerWorld 538503](https://makerworld.com/en/models/538503-important-vertical-tolerance-test); one gauge warns "all labeled clearances… represent per-side clearance, not total" **[S]**
- **Printables hinge test with 0.01 mm steps** (MK3S+, PETG) **[S]** — [Printables 1585971](https://www.printables.com/model/1585971-scharnier-hinge-print-in-place-v2-update)
- **UMD 2023**: 0.05–0.30 mm disk ladder; results depend on profile (fast vs strength) via Z-seam size **[P]** — [UMD](https://terrapinworks.umd.edu/sites/terrapinworks.umd.edu/files/P1P%20vs%20MK3%20Report%202023.pdf)
- **Frohn-Sörensen 2023**: orientation (Z vs XY axis) and layer height (0.1, 0.3 worse) are first-order variables **[P, abstract]** — [Siegen](https://italg.wiwi.uni-siegen.de/en/?p=2994)
- **Calì 2012**: three calibration sets (gap 0.2–0.6 mm; band thickness 2–12 mm; outer radius) "run on each printer before model generation" **[P]** — [PDF](https://reality.tf.fau.de/projects/jointfit/jointfit-lowres.pdf)
- **Bambu forum**: flow 97 % and 210 °C reduced achievable PIP gap from ~0.15 to ~0.1 mm **[S]** — [forum](https://forum.bambulab.com/t/print-in-place-hinge-tolerances/111715)
- **Vendor coupons**: Sovol pins at 0.15/0.20/0.25/0.30 radial, 0.05 steps; JLC3DP ladder 0.15/0.20/0.25/0.30/0.40 per side; 0.6 mm nozzle cannot reproduce 0.25 **[S]** — [Sovol](https://www.sovol3d.com/blogs/news/print-in-place-3d-printing-how-to-design-hinges-joints-and-moving-parts-that-actually-work), [JLC3DP](https://jlc3dp.com/blog/3d-printed-articulated-animals-design)

### Inferences
- A per-printer profile that the generator consumes can be fully derived from one ladder print; fields supported by the sources above: `nozzle_d`, `layer_h`, `material`, `xy_gap_min_pip` (smallest XY ladder step that moves freely), `z_gap_min_pip` (from a vertical ladder; Multi-Type and Vertical tests), `first_layer_spread` (from a chamfer-less vs chamfered pair or EFC value), `z_seam_allowance` (profile-dependent; UMD), `hinge_axis_preference` (Z over XY; Frohn-Sörensen), `efc_mm`, `xy_hole_comp_mm`, and `min_wall = k × extrusion_width` (k ≥ 2 per Cenwulf; ≥ 3.5 per Flexi Rex). Generator checks: every PIP gap ≥ max(xy or z min, as oriented) + margin; gaps touching layer 1 get a chamfer or lift; joints below min ball/pin diameter flagged.
- The "per side vs total" labelling confusion in community tests is a real data-quality hazard; the profile should store radial values and the ladder STL should print its own convention.
- Because XY hole compensation does not act on open slots and can close PIP gaps, profiles should record it but the generator should bake clearance into geometry rather than rely on slicer compensation.

### Gaps
- No official Bambu Lab or Prusa print-in-place tolerance test model was found; all ladders are community-made.
- No published dataset maps printer model + material + profile → minimum PIP gap; the only cross-printer data points are UMD (2 printers) and Frohn-Sörensen (print farm, numbers not public).
- Z-gap (vertical clearance) numbers were not found in any primary source; only the existence of Z tests is confirmed.

---

## 7. Legal / IP note

### Takeaway
Popular flexi designs span the licensing spectrum: the Flexi Rex lineage is CC BY-SA (sell prints freely with attribution; remixes must stay BY-SA), Flexi Factory and Cinderwing3D are all-rights-reserved with paid commercial print licences ($10/month for Cinderwing; via Patreon for Flexi Factory), MakerWorld's default "Standard Digital File License" is read as personal/non-commercial with a separate Commercial License Membership, and Printables offers CC variants plus OCL/CERN-OHL. A generator that only borrows geometric rules (not meshes) is unaffected, but copying joint geometry from a specific model inherits that model's licence.

### Cited Findings
- **Flexi Rex (DrLex, and by his account the whole lineage from Kirbs)**: CC BY-SA 4.0; "I want to sell prints… do I need your explicit permission? No, but you must provide attribution"; remixes must be BY-SA; remix pages showing "Attribution or even Public Domain" licences are "irrelevant and… by definition BY-SA because that is the license of Kirbs' original model" **[P]** — [DrLex0/print3D-FlexiRex README](https://github.com/DrLex0/print3D-FlexiRex)
- **Flexi Factory (Dan Sopala)**: "ALL Flexi Factory designs are protected by Copyright Law"; selling prints or files requires permission via Patreon **[S]** — [MMF listings](https://www.myminifactory.com/object/3d-print-197808), [Patreon](https://www.patreon.com/FlexiFactory)
- **Cinderwing3D**: commercial licence to "sell prints" via Patreon, MyMiniFactory or Thangs at "$10.00 a month"; "We do not condone the sale of our product on Temu, AliExpress, or Alibaba" **[P]** — [cinderwing3d.com](https://www.cinderwing3d.com/); listings: "upon purchase, you do NOT have the right to sell commercially"; licence covers "3D PRINTS (Not Files)"; ends if subscription cancelled **[S]** — [MMF Crystal Dragon](https://www.myminifactory.com/object/3d-print-206281), [MMF Winter Dragon](https://www.myminifactory.com/it/object/3d-print-winter-dragon-258837)
- **MakerWorld**: Commercial License Membership announced 13 Feb 2025; creators need "at least 200 followers and 600 prints, and no rule violations in the past 90 days"; price $3–$300/month; 10 % platform fee; catalog "free and open for personal use" **[P]** — [Bambu Lab blog](https://blog.bambulab.com/empowering-our-creators-with-new-commercial-license-membership); Creator Membership Agreement: subscribers "may be entitled to use this Program's Models for commercial purposes or under license terms set forth by the Creator" **[S]** — [MakerWorld agreement](https://makerworld.com/en/creator-membership-agreement); the default "Standard Digital File License" is read by forum users as non-commercial/no-redistribution and is required for the Exclusive program **[S]** — [forum 257609](https://forum.bambulab.com/t/understanding-makerworlds-standard-digital-file-license/257609), [forum 103866](https://forum.bambulab.com/t/makerworld-exclusive-program-is-now-live/103866)
- **Printables**: CC licences shown with a checklist (e.g. CC BY-NC-ND marks sharing, remixing, commercial use as not allowed); OCL v1.1 and CERN OHL-S 2.0 added as options **[P]** — [Prusa blog OCL v1.1](https://blog.prusa3d.com/open-community-license-v1-1-the-new-plugin-system-more-examples-and-your-questions-answered_137202/); enforcement precedent: 3DBenchy's CC BY-ND enforced Jan 2025, then relicensed CC0 **[S]** — [Hackaday](https://hackaday.com/2025/01/09/3dbenchy-starts-enforcing-its-no-derivatives-license), [All3DP](https://all3dp.com/4/3dbenchy-is-public-domain-now)
- **Flexifier**: code GPL-3.0 (README) / AGPL-3.0 (GitHub SPDX); generated example models CC BY-NC-SA 4.0 **[P]** — [Flexifier README](https://github.com/Lucandia/Flexifier)
- **Tool licences**: BOSL2 BSD-2-Clause; tusosos/articulated-toys MIT; HinGen MIT; Multi-Agent-CAD MIT; cuteflexi-studio none (all rights reserved); UniRig MIT; MagicArticulate/Puppeteer Apache-2.0 **[P]** — GitHub API/LICENSE files cited in Sections 3 and 5

### Inferences
- Encoding published *rules* (clearances, wall floors, 45° lips) in a generator does not copy a protected expression; reusing Flexi Rex's exact shackle/axle dimensions is low-risk as the lineage is BY-SA, but any emitted model that is recognisably a Flexi Rex derivative would need BY-SA + attribution.
- Flexi Factory/Cinderwing joint geometry must not be measured and reproduced; their licences forbid file redistribution and the commercial-print licence is subscription-bound.
- If the generator is hosted as a web service, AGPL on Flexifier would require releasing modifications; prefer re-implementing the pin-in-slot idiom.

### Gaps
- Kirbs' original Thingiverse licence text not verified (Thingiverse blocked).
- Official Printables licence list page and MakerWorld Standard Digital File License text not retrievable (403); descriptions rely on blog posts and forum readings.
- Flexi Factory's exact commercial terms (Patreon tiers) not fetched.
