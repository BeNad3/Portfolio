# Tooling setup (on the machine that runs Blender / ComfyUI / n8n)

These tools run locally, next to the apps they control. The project's `.mcp.json` declares them, so
Claude Code on your machine picks them up on start (approve them when asked).

| Tool | Install | Needed for |
|---|---|---|
| Blender 4.2+ (5.x tested) | blender.org | Steps 2–4 |
| Blender MCP (`mcp-for-blender`, formerly `blender-mcp`) | `uv` installed, then `uvx mcp-for-blender install-addon`; in Blender: Preferences → Add-ons → enable **MCP for Blender**; viewport `N` panel → **Start MCP Server** | Claude driving Blender, Poly Haven HDRIs/textures/models, Sketchfab |
| Poly Haven | built into the Blender MCP addon: enable Poly Haven in its panel | HDRIs, PBR textures, furniture/props (CC0) |
| fSpy (optional) | fspy.io + its Blender importer | solving the camera of difficult photos |
| ComfyUI | comfy.org (desktop) or source install, GPU with ≥ 12 GB VRAM for SDXL/Flux | optional AI finishing / staging |
| ComfyUI MCP | official Comfy MCP (comfy.org/mcp). `artokun/comfyui-mcp` still works (`npx -y comfyui-mcp`) but is unmaintained from 2026-10-09 | Claude driving ComfyUI |
| Real-ESRGAN via spandrel | `pip install spandrel torch pillow numpy` | final upscale (`upscale-for-print`) |
| n8n + n8n-mcp | n8n self-hosted (`n8n-self-hosting`), `npx n8n-mcp` with `N8N_API_URL` / `N8N_API_KEY` env vars | automation |

Headless render workers need only Blender (or `pip install bpy` for Python 3.11) and Pillow;
`build_shell.py` and `photoreal_setup.py` run without a display. The clay pass defaults to Cycles
because Workbench needs an OpenGL/EGL context.

Security (from the Blender MCP README): the MCP can run arbitrary Python inside Blender. Save your
work before long sessions and only connect it to a Blender instance you are using for this project.
