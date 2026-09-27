# Step 1 — Property analysis guide

Goal: a Property Dossier where every number has a source. This file covers how to extract facts
from plans and photos, how to estimate what is not written, and how to report what stays unknown.

## 1. Evidence ladder (strongest first)

1. `measured`: a number the user measured (laser, tape) or wrote on a sketch.
2. `plan`: a dimension written on the plan, or measured on a correctly scaled plan.
3. `photo`: seen in a photo; a size scaled from a known reference in the same plane.
4. `derived`: computed from other facts (e.g. room width = wall-to-wall on the plan minus thickness).
5. `inferred`: a standard value (tables below) used because nothing better exists. **Always listed
   back to the user.**
6. `unknown`: not determinable. The element is not built or not shown until resolved.

When two sources disagree beyond tolerance (2 % or 3 cm for rooms, 1 cm for openings), record a
conflict with both values and their sources. Measured beats plan beats photo, but ask before you
override a plan with a photo estimate.

## 2. Reading the floor plan

- **Scale:** from a written dimension (best: the longest one), cross-checked on a second dimension
  in the other axis. A scale bar is second-best. Never trust a PDF's printed "1:100" alone: exports
  get resized.
- **Dimension conventions:** French/European plans often write interior clear dimensions per room and
  overall exterior dimensions; check which one before building. Wall thicknesses: read them, then check
  them against the difference between exterior and interior dimensions.
- **Openings:** position along the wall (to the rough opening, not the frame), width, door swing and
  hinge side from the arc, sliding doors, window type symbols. Heights are rarely on plans: sill and
  head come from photos, elevations or measurements.
- **Plan annotations:** `HSP` (hauteur sous plafond) = ceiling height; `Ht` / `All.` = sill heights;
  room areas (m²) are a checksum: compute the area from your polygon and compare (±3 %).
- **North arrow** → `project.north_deg`. No arrow → orientation is `unknown`; ask (or derive it from
  the address and street layout, labelled `derived`).
- Export a PNG of the plan (300 dpi) for the Blender underlay and record `m_per_px` and the pixel of
  plan origin.

## 3. Reading the photos

For every photo write a note in `01_analysis/photo_notes/<photo>.md`:

- Room, and camera position/direction on the plan (see §4).
- Every visible wall, opening, fixed element; which plan element each one corresponds to.
- Heights you can scale: sill, window head, door head, radiator top, worktop, skirting.
- Finishes: floor (material, board width, laying direction, pattern), walls, ceiling, joinery, metal.
- Existing furniture with approximate size (scaled, see below) and whether it stays.
- Light: sun patches and shadow direction (→ time and orientation check), overcast vs direct,
  colour temperature of practical lights, blown-out windows (exposure).
- Photo defects to *not* copy into the model: lens distortion (wide/ultra-wide phone lens), converging
  verticals, HDR halos.

### Scaling objects in a photo

Only scale against a reference **in the same plane and at the same depth** (a door in the same wall as
the radiator, not a door three metres behind it). Useful references: the door leaf (plan width), the
window (plan width), floor boards or tiles (count × module), a standard socket plate (8 × 8 cm), a
standard A4 sheet. Label the result `photo` with the reference used.

## 4. Camera estimation for each photo

1. **Focal length:** read EXIF `FocalLengthIn35mmFilm`. Without EXIF: phone main lens ≈ 24–26 mm,
   phone ultra-wide ≈ 13–16 mm, phone 2×/3× ≈ 48–77 mm; real-estate DSLR usually 16–24 mm.
   Ultra-wide phone photos have strong barrel distortion near the edges: undistort (or ignore edge
   lines) before matching.
2. **Camera height:** the horizon line (the height where horizontal lines parallel to the floor stop
   converging up or down, i.e. where the vanishing point of floor-parallel lines sits) is at the
   camera's eye height. Find the horizon on a wall of known height (e.g. a door of 2.04 m): the ratio
   along that wall gives the camera height. Phone photos are usually 1.3–1.6 m; real-estate shots ~1.2–1.5 m.
3. **Position and direction:** two visible room corners plus the focal length pin the camera. In
   practice: place the camera at the estimate, set the photo as the camera background
   (`build_shell.py` does this), and adjust in Blender until the room corners and ceiling line match.
   **fSpy** (free, desktop) solves the camera from 2–3 vanishing points and imports into Blender:
   use it for any photo where the manual match takes more than a few iterations.
4. **Check** with `scripts/photo_match_overlay.py`. A camera that cannot be matched while the plan
   says it should be means a measurement error: find it, don't force the camera.

## 5. Standard dimensions (for `inferred` only)

Use only when nothing better exists, and label them `inferred`. These are common European/French
values; adapt to the country of the property.

| Element | Typical value |
|---|---|
| Ceiling height, post-1950 apartment | 2.50 m (2.40–2.60) |
| Ceiling height, Haussmann / pre-1914 | 2.80–3.30 m (lower on top floors) |
| Interior door leaf (FR) | 0.63 / 0.73 / 0.83 / 0.93 m wide × 2.04 m |
| Door rough opening | leaf + ~0.07 m wide, ~2.10–2.18 m high |
| Entrance door | 0.90–1.00 m leaf |
| Window sill, living/bedroom | 0.85–1.00 m (0.0 for French doors) |
| Window head | 2.10–2.25 m |
| Interior partition | 0.07 m (plasterboard 72/48) or 0.10 m |
| Load-bearing / façade wall | 0.18–0.30 m (older buildings 0.40–0.60 m) |
| Skirting board | 0.07–0.10 m high |
| Socket height | 0.25–0.30 m (kitchen worktop sockets ~1.10 m) |
| Switch height | 1.00–1.10 m, 0.10–0.20 m from door frame |
| Panel radiator | 0.30–0.90 m high, 0.06–0.12 m deep, bottom 0.10–0.15 m above floor |
| Kitchen worktop | 0.90 m high, 0.60–0.65 m deep; wall units bottom at ~1.45–1.50 m |
| Bathroom washbasin | rim 0.85 m |

## 6. Dossier completeness check

Before closing Step 1, every item below is either filled or listed in `unknowns`:

- [ ] Plan scale verified twice; orientation known.
- [ ] Every room: polygon, ceiling height, floor finish.
- [ ] Every wall: line, thickness, height.
- [ ] Every opening: wall, offset, width, sill, head, type, swing.
- [ ] Every fixed element visible in photos: radiators, sockets, switches, lights, vents, beams, columns, built-ins.
- [ ] Every photo: matched to a room, camera estimate with evidence.
- [ ] Light: window orientations, photo conditions, practical lights.
- [ ] Circulation: adjacency and clear paths.
- [ ] Conflicts: none unresolved, or the user has decided each.
