# Portfolio — property visualisation studio

Besides the portfolio site (`index.html`, `styles.css`), this repo carries a Claude Code skill set
for turning real property photos + floor plans into accurate 3D reconstructions, redesigns and
photorealistic renders.

## Start here

For any job involving photos, a floor plan or dimensions of a house/apartment, load the
**`property-3d-visualization`** skill first. It is the orchestrator: it sets the order
(analyse → reconstruct → redesign → render) and the gates, and chains the other skills.

Non-negotiables:
- Accuracy of the existing property comes first, aesthetics second.
- Every fact in the dossier carries an evidence tag; `inferred` values are shown to the user.
- Never invent architecture. Stop and ask on plan/photo conflicts.
- Photo-match gate (`scripts/photo_match_overlay.py`) before any look-dev; layout gate
  (`scripts/layout_check.py`, zero errors) before any furnished render.
- Redesigns and staging are labelled as visualisations (`real-estate-content-production`).

## Layout

- `.claude/skills/property-3d-visualization/`: orchestrator skill, tested scripts
  (`build_shell.py`, `solve_camera.py`, `photo_match_overlay.py`, `layout_check.py`, `materials.py`, `furnish.py`,
  `photoreal_setup.py`, `look_match.py`, `finish.py`), dossier and layout templates, references.
  After editing any script run `scripts/selftest.py` (25 behaviour checks on the example apartment).
- `.claude/skills/*`: curated third-party skills (Blender, archviz, arch-render, real-estate,
  ComfyUI, upscaling, n8n). Sources, commits and licenses: `.claude/third_party/NOTICE.md`.
- `.mcp.json`: Blender MCP, ComfyUI MCP and n8n-mcp for use on a machine running those apps.
- Client projects live outside this repo (they contain private photos and addresses).
