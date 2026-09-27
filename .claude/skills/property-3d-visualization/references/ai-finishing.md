# Optional AI finishing, staging and upscaling (ComfyUI, local)

AI passes come **after** a correct Blender render, never instead of one. They may add realism
(micro-texture, fabric softness, natural light falloff) but must not move a single architectural
edge. Every AI output is compared with its source render and rejected on drift.

## When to use which path

| Goal | Path |
|---|---|
| Redesign with accurate geometry (default) | Blender render (Steps 2–4) → optional realism pass → upscale |
| Quick honest virtual staging of a real photo (empty room, same camera) | ComfyUI inpaint on the **floor/furniture zone only** of the real photo, mask excludes walls, windows, radiators, ceiling |
| Declutter a real photo | Inpaint removal of movable objects only (`real-estate-content-production` rules: never remove defects) |
| Material/colour variant of an approved render | Qwen Image Edit (`qwen-image-edit`) with explicit "preserve" list, or re-render in Blender (preferred) |

## Realism pass (structure-locked img2img)

Built with `comfyui-workflow` / `comfyui-core`; models per `model-compatibility`.

1. Input: the Blender beauty render + its depth (Z/mist pass) + a line map (Canny on the clay render).
2. SDXL or Flux img2img with ControlNet **depth + canny** (strength 0.6–0.9), **denoise 0.15–0.30**.
   Above ~0.35 architecture starts drifting.
3. Prompt describes the *photo*, not the design: "professional real-estate photograph, interior,
   natural daylight, 24 mm, f/8, subtle film grain, true colours". Negative: "extra window, changed
   wall, distorted perspective, warped lines, text, watermark, people, fisheye, oversaturated".
4. Fixed seed per camera for consistency across a set.
5. **Drift check:** run `scripts/photo_match_overlay.py --photo <blender_render> --render <ai_output>`
   (edge_match should stay ≥ 0.9), then visually compare windows, door frames, radiators, sockets.
   Colour check with `color-correction`. Any drift → lower denoise or reject.

## Honest virtual staging of a real photo

Follow `real-estate-content-production` strictly: staging ledger, allowed changes = movable
furniture and decor only, locked = everything built in, label "Virtually staged", keep the original.
Scale furniture using the dossier (room size from plan, camera from the matched Blender camera):
the best result is to render the furniture in Blender from the matched camera with a shadow catcher
and composite it onto the real photo. That is geometrically exact, unlike a pure inpaint.

## Upscaling (`upscale-for-print`)

```bash
python .claude/skills/upscale-for-print/scripts/upscale_for_print.py --src 05_final/P1.png --pixels 6000x4000
```

- Upscale only the final, approved image; prefer rendering at the target size when time allows (native
  detail beats reconstructed detail).
- Real-ESRGAN x4plus for photoreal. Check 100 % crops on straight edges (window frames, skirting)
  and on text; reject haloing or invented texture on flat walls.
- Deliver the upscale as "enhanced resolution" in the delivery note if the channel requires disclosure
  of AI processing.

## Tooling note

`artokun/comfyui-mcp` (vendored skills: `comfyui-core`, `qwen-image-edit`, `color-correction`,
`prompt-engineering`, `model-compatibility`, `comfyui-troubleshooting`) is **no longer maintained and
will be archived on 2026-10-09**; its author points to the official **Comfy MCP / Comfy Agent**
(comfy.org/mcp). The skills' knowledge (node wiring, model files, colour measurement) stays valid;
use the official server for execution going forward. `comfyui-workflow` generates importable
workflow JSON and needs no MCP at all.
