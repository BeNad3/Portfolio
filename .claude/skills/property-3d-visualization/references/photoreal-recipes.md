# Step 4 — Photoreal recipe: from locked model to "real photograph"

Order matters (from `blender-pro-workflow`): camera → light → materials → detail → render → grade.
Change one variable per iteration and compare against the real photo of the same camera.

## 1. Light (scripts/photoreal_setup.py)

```python
exec(open("<skill>/scripts/photoreal_setup.py").read())
setup_daylight(lat, lon, "2026-04-15T12:30", north_deg=dossier["project"]["north_deg"],
               hdri="<polyhaven>.exr", hdri_sun_azimuth_deg=<from HDRI>)   # or omit hdri → sky texture
add_window_portals()                         # also stops glass from blocking the sun
orient_portals_inward(room_centre_xyz)
add_practical("LGT_Pendant_R1", (2.6, 2.1, 2.1), watts=40, kelvin=2700)
render_preset("preview", exposure=1.0, white_balance_k=7500)
```

- **Time of day:** pick one that flatters *and* is honest for the orientation (a north-facing room
  never gets sun patches). For before/after pairs, use the time the photo was taken (EXIF) so the
  light matches.
- **HDRI (Poly Haven via Blender MCP):** `search_polyhaven_assets(asset_type="hdris", categories="outdoor,urban")`,
  `download_polyhaven_asset(..., resolution="4k")`. Choose a sky matching the view out of the
  windows (urban street, trees, overcast). A clear HDRI with a separate sun lamp gives the most
  control; align the HDRI sun with `hdri_sun_azimuth_deg`.
- **View through the window:** the real view matters for honesty. Use a backplate photo of the actual
  view (from the photos) on a plane 5–30 m outside, emission ≈ exposure-matched. Never invent a
  park or a sea view.
- **White balance:** raise `white_balance_k` until a white wall reads neutral in the render (typically
  7000–9000 K for skylit rooms, ~3000 K when practicals dominate at night). Verify with the
  `color-correction` skill's measurements rather than by eye.
- **Artificial lights:** IES profiles for spots when available; lampshade materials with translucency
  so the shade glows; never an invisible light with no fixture.

## 2. Materials (PBR, real scale)

The shell's UVs are 1 unit = 1 m, so a texture authored for 1 m × 1 m maps at true size; for a
2 m texture set the Mapping node scale to 0.5.

| Surface | Base setup | Imperfection layer |
|---|---|---|
| Painted plaster wall | albedo 0.75–0.85 (never 1.0), roughness 0.85–0.9 | noise bump 0.02–0.05, subtle roughness noise, slightly darker near floor (AO/dirt) |
| Ceiling | albedo 0.85, roughness 0.9 | very faint roller texture |
| Oak parquet / strip | Poly Haven wood floor set, board size from dossier | per-board hue/roughness variation (random per island), varnish coat: clearcoat 0.3–0.5, roughness 0.25–0.4, micro-scratches in coat roughness |
| Tiles | albedo map + grout recessed (displacement or normal) | grout darker, slight lippage via random per-tile normal tilt |
| Fabric (sofa, curtains) | sheen 0.3–0.6, roughness 0.8–0.95, weave normal map | seams, creases, pilling noise, slightly worn armrests |
| Leather | roughness 0.35–0.55, fine grain normal | creases at seat, lighter wear on edges |
| Brushed metal | metallic 1, roughness 0.3–0.45, anisotropy 0.5–0.8 | fingerprints on handles (roughness map) |
| Chrome / polished | metallic 1, roughness 0.05–0.12 | faint smudges |
| Window glass | transmission 1, IOR 1.52, roughness 0, **real thickness** (2 panes ~4 mm) | dust/fingerprint roughness map at 2–5 %; `visible_shadow=False` |
| Mirror | metallic 1, roughness 0.02 | slight edge darkening |
| Plants | Poly Haven / scanned, translucency 0.2–0.3 | a few imperfect leaves |

Rules: every surface gets roughness variation; nothing is pure black or pure white; colours follow the
photo (use `reference-look-calibration` to measure the existing floor/walls and match them); bevel
every visible hard edge 1–3 mm (Bevel modifier, or the Bevel shader node for cheap rounding).

## 3. Camera (real-estate photography look)

```python
realestate_camera("CAM_P1", fstop=8.0, height=1.35)   # level + lens shift, keeps matched focal length
```

- 20–28 mm full-frame equivalent; 24 mm is the default interior. Never fisheye, never stretched corners.
- Camera 1.2–1.5 m high (lower for kitchens/bathrooms over worktops: ~1.1 m), perfectly level;
  verticals kept vertical with shift_y. This one rule separates "real-estate photo" from "3D render".
- f/5.6–8 at 3–4 m focus: almost everything sharp, with a very slight softening far away. No
  shallow-DOF bokeh on wide room shots; macro detail shots can use f/2.8.
- Composition: one-point perspective straight on a wall, or two-point from a corner. Show two walls
  and the ceiling line; keep 1/3 floor.

## 4. Render and finish

- `render_preset("final")`: Cycles 1024 samples, adaptive 0.01, OIDN/OptiX denoise, AgX (Base Contrast),
  passes Z/normal/mist/crypto for the comp. 3000 px for web, 6000 px (or upscale) for print.
- Finish with `scripts/finish.py` (version-independent, works on Blender, ComfyUI or upscaled outputs):
  gentle S-curve → edge chromatic aberration (~1 px per 1000 px width) → vignette ~10 % → mid-tone
  grain ~1 %. Glare on light sources and lens distortion, if wanted, in the Blender compositor
  (`compositing`). Everything subtle: the goal is "a good camera", not "an effect".
- Keep the linear EXR, deliver PNG/JPEG (sRGB).

## 5. "Does it look like a photo?" checklist

- [ ] Geometry pixel-identical to the approved clay pass from the same camera.
- [ ] Verticals vertical, horizon level, no stretched corners.
- [ ] Light direction and sun patches consistent with window orientation and chosen time.
- [ ] Contact shadows under every object (nothing floats); rugs lie flat with thickness.
- [ ] No coincident faces: overlapping parts never share a face plane (it renders as black patches or
      flicker in Cycles). Offset by ≥ 5 mm. Trace a suspicious pixel with `scene.ray_cast` to find the object.
- [ ] Furniture scale checked against doors (2.04 m), worktops (0.90 m), seat height (0.45 m).
- [ ] No pure blacks, no clipped highlights except light sources and windows; windows not blown to white unless the photos are.
- [ ] Materials: roughness variation everywhere; wood grain direction and scale plausible; fabric has sheen and creases; glass has reflections and faint dust.
- [ ] Imperfections present but tidy (lived-in, not dirty).
- [ ] Colours match the real finishes that are kept (measured, not guessed).
- [ ] Nothing in the image contradicts the dossier (no extra window, no moved radiator, no missing socket).
- [ ] Disclosure label applied where the channel needs one.
