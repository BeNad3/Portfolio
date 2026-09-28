---
name: property-3d-visualization
description: >-
  End-to-end pipeline that turns real property photos + a floor plan (+ measurements) into an accurate
  3D reconstruction in Blender, a functional interior redesign, and photorealistic renders that read as
  real-estate photography. Use whenever the user supplies photos, a floor plan, or dimensions of a house
  or apartment and wants it analysed, reconstructed, redesigned, virtually staged, or rendered: "here
  are the photos and the plan", "reconstruct this apartment", "redesign this living room", "make it look
  like a real photo", "virtual staging", "home staging 3D", "rénovation / aménagement / rendu 3D". This
  skill is the orchestrator: it sets the order and the gates, and chain-loads archviz, arch-render,
  blender-*, real-estate-content-production, comfyui-*, upscale-for-print and n8n-* for each step.
---

# Property 3D Visualization

**Real photos + floor plan → spatial analysis → accurate 3D reconstruction → intelligent redesign →
photorealistic images.**

The priority order never changes: **accuracy of the existing property first, aesthetics second.**
The work is not "make a pretty room". It is "show this real room, correctly measured, with a better
interior". Anything that changes walls, openings, ceiling height, fixed elements or proportions is
a failure, however good it looks.

## Operating rules

1. **Analyse before designing.** No furniture, material or style proposal before the Property Dossier
   (Step 1) exists and the user has seen its open questions.
2. **Every fact has an evidence tag:** `measured` (user-supplied number), `plan` (read from the drawing),
   `photo` (seen in a photo), `derived` (computed from other facts), `inferred` (a standard used as a
   fallback), `unknown`. Never upgrade a tag silently. `inferred` values are listed back to the user.
3. **Do not invent architecture.** An element that is not on the plan and not in a photo is not built.
   If a render needs it (the far side of a room nobody photographed), ask or leave it out of frame.
4. **Stop on contradictions.** When plan and photos disagree (a window on the photo, not on the plan),
   record it in `conflicts`, ask one grouped question, and do not pick a side yourself.
5. **Geometry before look.** No material, light or AI pass may be used to hide a geometry error. Fix
   the model, never the picture.
6. **Honest output.** Redesigns are labelled as visualisations. Real-estate channels get the disclosure
   rules from `real-estate-content-production` (virtual staging disclosure, keep the originals).

## Project layout

Create this once per property; every later step reads and writes here.

```
<project>/
  00_input/        photos/, plan/ (PDF + PNG export), measurements.txt, brief.md (user's design wishes)
  01_analysis/     property_dossier.json, analysis_report.md, photo_notes/, conflicts.md
  02_blender/      shell.blend -> existing.blend -> design_vN.blend, clay/, qa/
  03_design/       design_brief.md, layout_vN.png (top view), ffe_schedule.md, staging_ledger.md
  04_renders/      raw EXR/PNG per camera and version, passes/
  05_final/        graded + upscaled deliverables, originals paired, disclosure text, alt text
```

## Step 1 — Analyse the property (no design yet)

Read `references/analysis-guide.md` for the method, standard dimensions and camera estimation.

1. **Inventory sources.** List each photo (file, room, what it shows, EXIF focal length, time of day)
   and each drawing (scale, north arrow, legible dimensions, levels).
2. **Scale the plan.** Find the scale from a written dimension or a scale bar, never from assumptions.
   Check it on a second dimension; a mismatch over 2 % is a conflict.
3. **Read the plan:** rooms, wall lines and thicknesses, every door (width, swing, hinge side), every
   window, openings, stairs, columns, shafts, radiators or fixed kitchen/bath elements if drawn.
4. **Read each photo:** which room and from where (see camera estimation), which walls and openings are
   visible, window sill/head heights, radiators, outlets, switches, vents, lights, beams, skirting,
   cornices, flooring (type, board size, direction), wall and ceiling finish, existing furniture with
   approximate sizes scaled from a door or a known object, light direction and quality.
5. **Cross-reference.** Match each photo to a plan position; check that what the photo shows agrees
   with the plan (count of windows, door positions, room proportions). Record agreements and conflicts.
6. **Light and orientation.** North arrow → orientation of each window → which rooms get sun when.
   Confirm with shadows and sun patches in the photos.
7. **Circulation.** Room adjacency through doors, the main paths (entry → living → kitchen → bedrooms),
   and the clear widths along them.
8. **Write** `01_analysis/property_dossier.json` (schema: `templates/property_dossier.example.json`)
   and `analysis_report.md` with: a room table (dimensions, area, height, evidence), a per-photo camera
   table, fixed elements, finishes, light, circulation, **Unknowns**, **Conflicts**.
9. **Gate:** show the user the report's Unknowns and Conflicts as one grouped question. Proceed when
   answered, or with the user's explicit OK to use the listed `inferred` values.

## Step 2 — Reconstruct the existing space in Blender

Chain-load `blender-pro-workflow` (order), `blender-modeling`, `archviz`, `realistic-style`.
Needs the Blender MCP (`references/tooling-setup.md`).

1. **Build the shell from the dossier**, never freehand:
   ```python
   exec(open("<skills>/property-3d-visualization/scripts/build_shell.py").read())
   build("<project>/01_analysis/property_dossier.json", clear=True)
   ```
   It creates walls with real openings, floors, ceilings, fixed elements, a plan underlay, one camera
   per photo, and the collections `COL_Architecture_LOCKED`, `COL_Furniture_Existing`,
   `COL_Furniture_Proposed`, `COL_Lighting`. It refuses a dossier whose openings do not fit their walls.
   Headless alternative: `blender -b -P build_shell.py -- dossier.json --out shell.blend --clay-render clay/`.
2. **Plan check:** top orthographic view over `REF_FloorPlan`; walls and openings must sit on the drawing.
3. **Photo-match every camera** (the key accuracy gate). Mark correspondences, then solve:
   - Make a gridded copy of the photo and read 6-10 points whose 3D position the dossier knows: room
     corners at floor and ceiling (`"H"` = ceiling height), door/window jambs at the floor line. Add
     `{"line": [[x,y,z],[x,y,z]], "px": [u,v]}` items for pixels on a skirting line whose ends are not
     visible: they pin the near walls, which corner points alone leave loose.
   ```bash
   python <skills>/property-3d-visualization/scripts/solve_camera.py --dossier 01_analysis/property_dossier.json \
     --camera P1 --room Z1 --points 02_blender/qa/points_P1.json --free-ceiling --mask 0.76,0.84,1,1 \
     --out 02_blender/qa/solve_P1.png --write
   ```
   It fits position, heading, lens and vertical principal shift (horizontal shift fixed at 0), refines on
   the photo's edges, and rejects implausible cameras (lens outside 40-130 deg, height outside 0.8-2.0 m).
   **Read the sheet, not only the score:** a model line that was not marked but falls on the photo
   (e.g. an unmarked skirting) is the real proof; a tight fit with an odd answer (ceiling 2.75 m, camera at
   knee height) means a misread point. Ceiling heights that agree across photos upgrade an inferred
   height to photo-derived. Fully automatic edge matching (no `--points`) latches onto strong window
   frames on real photos; use it only on renders or as refinement. A photo that cannot be matched is a
   **conflict** (record it, ask for a measurement), never a reason to bend the model. With a solved
   camera, heights can be *measured*: back-project a pixel onto the known wall plane (window head,
   transom, socket height, ceiling outlets). Then confirm on a clay render:
   ```bash
   python <skills>/property-3d-visualization/scripts/photo_match_overlay.py \
     --photo 00_input/photos/living_01.jpg --render 02_blender/clay/clay_CAM_P1.png --out 02_blender/qa/P1.png
   ```
   Target `edge_match >= 0.75` **and** a visual check of the sheet: wall corners, ceiling line, window
   and door edges on the photo's lines. If the camera cannot be matched, the geometry is wrong: go back
   to the dossier, fix the measurement, rebuild. Record each camera's final values in the dossier.
4. **Detail the architecture that the photos show:** `scripts/add_details.py` builds window/glazed-door
   frames (with `transom`, `mullions`, `leaf_width` from the dossier) and skirting per room (interrupted at
   doors). Model by hand what it does not cover: door leaves and casings, cornices, radiators with the
   right model, switches, ceiling lights, beams. Real dimensions, 1–3 mm bevels on visible edges.
   Wall ends must not poke through neighbouring wall faces (a 2 cm step shows as a seam in renders).
5. **Model existing furniture** (`COL_Furniture_Existing`) at its estimated size when the user wants
   to keep it, or when a "before" image is requested.
6. **Gate:** clay renders from all photo cameras + the overlay sheets, shown to the user. Save `existing.blend`.

## Step 3 — Redesign to the user's brief

Read `references/design-rules.md` (clearances, sizes, lighting layers). Chain-load
`furniture`/FF&E guidance in `arch-render` (`references/furniture-styling-object-curation.md`),
`set-dressing`, and for real-estate use `real-estate-content-production`.

1. Restate the brief: style, budget tier, what must stay, who lives there (without fair-housing
   targeting language), how each room is used.
2. **List the locks** (from the dossier): walls, openings, ceiling, radiators, sockets, fixed kitchen
   and bath elements, flooring unless the brief changes it. A changed finish (paint, floor) is allowed
   only if the brief asks for it, and is recorded as a proposal.
3. **Plan first:** write 1–2 layouts as `03_design/layout_vN.json` (schema:
   `templates/layout.example.json`) and run the checker, which also draws the top view the client approves:
   ```bash
   python <skills>/property-3d-visualization/scripts/layout_check.py \
     --dossier 01_analysis/property_dossier.json --layout 03_design/layout_v1.json --out 03_design/layout_v1.png
   ```
   It enforces `design-rules.md` against the real architecture: items inside rooms and not colliding,
   door swings clear (needs `swing_side`/`hinge` in the dossier), sofa/bed/table/wardrobe clearances,
   radiators and windows not blocked, and the widest route between every pair of doors (target ≥ 0.90 m,
   error < 0.80 m), lamps/TV/desk within 1.5 m of a real socket, TV distance for its screen size and
   the main seat facing it. **No render of a layout with errors.** Warnings are shown to the user as
   decisions (e.g. a socket warning: extension lead, move the item, or new socket as electrical work).
4. Get the layout approved, then place it with the same JSON:
   `exec(materials.py); exec(furnish.py); furnish("03_design/layout_v1.json")`. Items with an `asset`
   (Poly Haven / Sketchfab download) are imported and scaled to the layout width, with a warning if
   their proportions differ from the real product; items without one get dimension-exact stand-ins
   (fine for review and lighting, replaced by real models before client renders). Before rendering from a
   photo camera, check it is not inside a proposed item: photographers stand in corners where kitchens and
   wardrobes go. If it is, add a new level real-estate view in free space instead (and label it as a view
   without a source photo).
5. Write `ffe_schedule.md` (item, size, material, colour, placement, evidence/reference) and, for
   staging, `staging_ledger.md` (template in `real-estate-content-production`).

## Step 4 — Photorealistic visualisation

Read `references/photoreal-recipes.md` (the render recipe). Chain-load `blender-materials`,
`blender-lighting`, `blender-cameras`, `blender-rendering`, `lookdev`, `compositing`,
`reference-look-calibration`, `lighting-direction`, `qa-review`.

1. **Cameras:** the photo cameras first (true before/after pairs), then new real-estate views only
   where the model is fully known. 24–28 mm full-frame equivalent, camera 1.2–1.5 m high, level, vertical
   lines kept vertical with lens shift, never wider than 20 mm.
2. **Materials** (`scripts/materials.py`): `pbr_from_folder()` for Poly Haven / vendor texture sets at
   their real tile size (the shell has 1 UV unit = 1 m); procedural `plaster_paint`, `parquet`, `fabric`,
   `glass`, `solid`, `brushed_metal` as fallbacks; `default_shell_look()` for a neutral start. Match
   kept finishes to the photos. Roughness variation on every surface, no perfect materials.
3. **Light:** Poly Haven HDRI + sun placed from the real orientation, latitude and chosen date/time;
   window portals; practical lights at 2700–3000 K. Match exposure and white balance to the photos by
   measurement, not by eye: render the photo camera, then
   `python scripts/look_match.py --photo <photo> --render <render> --region x0,y0,x1,y1` on a kept
   wall/ceiling. It returns the exposure correction in stops and the white-balance direction
   (render too warm → lower `white_balance_temperature`); repeat until the verdict is `match`.
4. **Render:** Cycles, AgX, 1024+ samples with denoise, passes for comp; then
   `scripts/finish.py --src raw.png --out final.jpg` for the camera traits (gentle contrast curve,
   edge chromatic aberration, vignetting, mid-tone grain), strength ≤ 1 for real estate.
5. **Daylight shots: practical lamps off** unless the photos show them on; 2700 K lamps in a sunny shot
   read as a pink cast. Re-measure look_match after furnishing (warm rugs/furniture shift the bounce light).
6. **Imperfection pass:** cushions dented, throws folded unevenly, books leaning, slight rug curl,
   fingerprints on glass, micro-scratches on floors, cables where devices are. Plausible, not messy.
7. **Optional AI finishing** (`references/ai-finishing.md`, `comfyui-*`): low-denoise, structure-locked
   pass for realism only, then `upscale-for-print`. Every AI output is compared with the raw render;
   any architectural drift rejects it.
8. **QA gate** (`generated-media-qa`, `qa-review` and the checklist in `references/photoreal-recipes.md`):
   geometry identical to the clay pass, scale of furniture, verticals, light direction matches the
   windows, no floating objects, no AI artefacts, disclosure label present where needed.
9. **Deliver** to `05_final/`: images, paired originals, disclosure text, alt text, and a short report
   of what is real, what is proposed, and what was inferred.

## Maintaining the tools

After editing any script, run `python scripts/selftest.py` (Pillow + numpy; the Blender half needs
`bpy`, e.g. `pip install bpy` on Python 3.11). It checks behaviour on the bundled example: good inputs
pass, broken layouts/dossiers/cameras are rejected, and measurements recover known values.

## Automation

For repeatable agency runs (intake form → dossier draft → Blender render job → QA → client delivery),
read `references/automation-n8n.md` and chain-load `n8n-workflow-patterns`, `n8n-mcp-tools-expert`.
Human approval gates stay in the automated flow: dossier questions, layout approval, final QA.

## Skill map

| Need | Skill |
|---|---|
| Archviz standards (scale, lens, lighting) | `archviz`, `realistic-style` |
| Plan-preserving reconstruction, evidence matrix, room prompts, FF&E | `arch-render` (`2d-to-3d-reconstruction.md`, `core-policies.md`, `furniture-styling-object-curation.md`, `architectural-camera-director.md`) |
| Blender order / modeling / UVs | `blender-pro-workflow`, `blender-modeling`, `blender-uv-texturing`, `scene-assembly` |
| Materials, lights, cameras, render | `blender-materials`, `blender-lighting`, `blender-cameras`, `blender-rendering`, `lookdev`, `lighting-direction` |
| Matching the look of the real photos | `reference-look-calibration`, `color-correction` |
| Grade and finish | `compositing`, `still-image-retouching-finishing` |
| Honest staging, disclosure, MLS/portal rules | `real-estate-content-production` |
| Local AI edit / staging / realism pass | `comfyui-workflow`, `comfyui-core`, `qwen-image-edit`, `prompt-engineering`, `model-compatibility`, `comfyui-troubleshooting` |
| Final upscale | `upscale-for-print` |
| Output QA, stuck quality loops | `generated-media-qa`, `qa-review`, `quality-refinement-autoloop` |
| Automation | `using-n8n-mcp-skills` and the other `n8n-*` skills |
