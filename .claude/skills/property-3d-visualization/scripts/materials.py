"""PBR materials for the reconstructed shell and furniture, at real-world scale.

    exec(open("<skill>/scripts/materials.py").read())
    pbr_from_folder("MAT_Floor", "/textures/oak_parquet_2k", size_m=2.0)   # Poly Haven set on disk
    plaster_paint("MAT_Wall", color=(0.86, 0.85, 0.82))
    plaster_paint("MAT_Ceiling", color=(0.90, 0.90, 0.89), bump=0.01)
    parquet("MAT_Floor", board_w=0.07, board_l=0.60, tone=(0.52, 0.36, 0.22))   # procedural fallback
    glass("MAT_Glass")

Every material is built from shader nodes looked up by type, so it works on any UI language and on
Blender 4.2 - 5.x. Textures use the world-scale UVs from build_shell.py (1 UV unit =
1 m), so `size_m` is the real-world size one texture tile covers (Poly Haven lists it per asset).

Rules baked in (see references/photoreal-recipes.md): no pure white/black albedo, roughness
variation on every surface, subtle bump everywhere.
"""

import glob
import os

import bpy


# ---------------------------------------------------------------- node helpers

def _fresh(name):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    return mat, nt, bsdf


def _inp(bsdf, *names):
    for n in names:
        if n in bsdf.inputs:
            return bsdf.inputs[n]
    raise KeyError(names)


def _uv_scaled(nt, size_m):
    uv = nt.nodes.new("ShaderNodeTexCoord")
    uv.location = (-1100, 0)
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.location = (-900, 0)
    s = 1.0 / size_m
    mp.inputs["Scale"].default_value = (s, s, s)
    nt.links.new(uv.outputs["UV"], mp.inputs["Vector"])
    return mp.outputs["Vector"]


def _noise(nt, vec, scale, detail=6.0, lo=0.0, hi=1.0, loc=(-500, 0)):
    tex = nt.nodes.new("ShaderNodeTexNoise")
    tex.location = loc
    tex.inputs["Scale"].default_value = scale
    tex.inputs["Detail"].default_value = detail
    nt.links.new(vec, tex.inputs["Vector"])
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.location = (loc[0] + 200, loc[1])
    mr.inputs["To Min"].default_value = lo
    mr.inputs["To Max"].default_value = hi
    nt.links.new(tex.outputs["Fac"], mr.inputs["Value"])
    return mr.outputs["Result"]


def _bump(nt, height, strength, distance=0.002, normal=None, loc=(0, -400)):
    b = nt.nodes.new("ShaderNodeBump")
    b.location = loc
    b.inputs["Strength"].default_value = strength
    b.inputs["Distance"].default_value = distance
    nt.links.new(height, b.inputs["Height"])
    if normal is not None:
        nt.links.new(normal, b.inputs["Normal"])
    return b.outputs["Normal"]


# ---------------------------------------------------------------- image-based (Poly Haven)

MAP_PATTERNS = {
    "color": ("_diff_", "_diffuse", "_albedo", "_basecolor", "_col_", "_color"),
    "rough": ("_rough_", "_roughness"),
    "normal": ("_nor_gl_", "_normal_gl", "_nor_", "_normal"),
    "disp": ("_disp_", "_displacement", "_height"),
    "arm": ("_arm_",),
    "metal": ("_metal_", "_metallic"),
}


def find_maps(folder):
    files = sorted(glob.glob(os.path.join(folder, "*")))
    maps = {}
    for key, pats in MAP_PATTERNS.items():
        for f in files:
            low = os.path.basename(f).lower()
            if key == "normal" and "_nor_dx" in low:
                continue                          # DirectX normal: wrong green channel for Blender
            if any(p in low for p in pats) and low.rsplit(".", 1)[-1] in ("jpg", "jpeg", "png", "exr", "tif", "tiff"):
                maps.setdefault(key, f)
    return maps


def pbr_from_folder(name, folder, size_m=1.0, bump_strength=0.3, roughness_gain=1.0, tint=None):
    """Material from a texture set on disk (Poly Haven naming, also most PBR vendors).
    `size_m` = real-world width one tile covers. Returns the material."""
    maps = find_maps(folder)
    if "color" not in maps:
        raise FileNotFoundError(f"no albedo/diffuse map in {folder}")
    mat, nt, bsdf = _fresh(name)
    vec = _uv_scaled(nt, size_m)

    def img(path, noncolor, loc):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.location = loc
        n.image = bpy.data.images.load(path, check_existing=True)
        if noncolor:
            n.image.colorspace_settings.name = "Non-Color"
        nt.links.new(vec, n.inputs["Vector"])
        return n

    col = img(maps["color"], False, (-500, 300))
    color_out = col.outputs["Color"]
    if tint:
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 1.0
        mix.inputs[7].default_value = (*tint, 1.0)            # B colour input
        nt.links.new(color_out, mix.inputs[6])                # A colour input
        color_out = mix.outputs[2]
    nt.links.new(color_out, _inp(bsdf, "Base Color"))

    rough_src = None
    if "rough" in maps:
        rough_src = img(maps["rough"], True, (-500, 0)).outputs["Color"]
    elif "arm" in maps:
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        a = img(maps["arm"], True, (-700, 0))
        nt.links.new(a.outputs["Color"], sep.inputs["Color"])
        rough_src = sep.outputs[1]
        nt.links.new(sep.outputs[2], _inp(bsdf, "Metallic"))
    if rough_src is not None:
        g = nt.nodes.new("ShaderNodeMath")
        g.operation = "MULTIPLY"
        g.inputs[1].default_value = roughness_gain
        nt.links.new(rough_src, g.inputs[0])
        nt.links.new(g.outputs[0], _inp(bsdf, "Roughness"))
    if "metal" in maps:
        nt.links.new(img(maps["metal"], True, (-500, -150)).outputs["Color"], _inp(bsdf, "Metallic"))

    normal = None
    if "normal" in maps:
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (-200, -300)
        nt.links.new(img(maps["normal"], True, (-500, -300)).outputs["Color"], nm.inputs["Color"])
        normal = nm.outputs["Normal"]
    if "disp" in maps:
        normal = _bump(nt, img(maps["disp"], True, (-500, -500)).outputs["Color"],
                       bump_strength, distance=0.003, normal=normal)
    if normal is not None:
        nt.links.new(normal, _inp(bsdf, "Normal"))
    mat["source"] = folder
    mat["tile_size_m"] = size_m
    return mat


# ---------------------------------------------------------------- procedural fallbacks

def plaster_paint(name, color=(0.86, 0.85, 0.82), roughness=0.88, bump=0.02):
    """Matte painted plaster: slight roller texture, roughness variation, never pure white."""
    mat, nt, bsdf = _fresh(name)
    vec = _uv_scaled(nt, 1.0)
    base = nt.nodes.new("ShaderNodeRGB")
    base.outputs[0].default_value = (*[min(c, 0.9) for c in color], 1.0)
    var = _noise(nt, vec, 3.0, 4.0, 0.96, 1.0, loc=(-500, 250))
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs["Factor"].default_value = 1.0
    nt.links.new(base.outputs[0], mul.inputs[6])
    comb = nt.nodes.new("ShaderNodeCombineColor")
    for k in range(3):
        nt.links.new(var, comb.inputs[k])
    nt.links.new(comb.outputs[0], mul.inputs[7])
    nt.links.new(mul.outputs[2], _inp(bsdf, "Base Color"))
    nt.links.new(_noise(nt, vec, 12.0, 8.0, roughness - 0.06, roughness, loc=(-500, 0)), _inp(bsdf, "Roughness"))
    fine = _noise(nt, vec, 180.0, 10.0, loc=(-500, -300))
    nt.links.new(_bump(nt, fine, bump), _inp(bsdf, "Normal"))
    return mat


def parquet(name, board_w=0.07, board_l=0.60, tone=(0.50, 0.34, 0.20), varnish=0.35, along_x=True, variation=0.2):
    """Procedural strip parquet: staggered boards with per-board tone variation, grain along the
    board, bevelled joints and a satin varnish coat. Use real textures when available."""
    mat, nt, bsdf = _fresh(name)
    uv = nt.nodes.new("ShaderNodeTexCoord")
    vec = uv.outputs["UV"]
    if not along_x:
        rot = nt.nodes.new("ShaderNodeMapping")
        rot.inputs["Rotation"].default_value[2] = 1.5708
        nt.links.new(vec, rot.inputs["Vector"])
        vec = rot.outputs["Vector"]
    brick = nt.nodes.new("ShaderNodeTexBrick")
    brick.location = (-700, 200)
    brick.offset = 0.37
    brick.offset_frequency = 1
    brick.inputs["Scale"].default_value = 1.0
    brick.inputs["Brick Width"].default_value = board_l
    brick.inputs["Row Height"].default_value = board_w
    brick.inputs["Mortar Size"].default_value = 0.0012
    brick.inputs["Mortar Smooth"].default_value = 0.6
    brick.inputs["Bias"].default_value = 0.0
    lo = tuple(c * (1 - variation) for c in tone)                 # board-to-board tone spread
    hi = tuple(min(0.9, c * (1 + 0.75 * variation)) for c in tone)
    brick.inputs["Color1"].default_value = (*lo, 1.0)
    brick.inputs["Color2"].default_value = (*hi, 1.0)
    brick.inputs["Mortar"].default_value = (*(c * 0.35 for c in tone), 1.0)
    nt.links.new(vec, brick.inputs["Vector"])
    # grain: stretched noise along the board direction
    stretch = nt.nodes.new("ShaderNodeMapping")
    stretch.inputs["Scale"].default_value = (4.0, 90.0, 1.0)
    nt.links.new(vec, stretch.inputs["Vector"])
    grain = _noise(nt, stretch.outputs["Vector"], 1.0, 12.0, 0.82, 1.08, loc=(-700, -100))
    comb = nt.nodes.new("ShaderNodeCombineColor")
    for k in range(3):
        nt.links.new(grain, comb.inputs[k])
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs["Factor"].default_value = 1.0
    nt.links.new(brick.outputs["Color"], mul.inputs[6])
    nt.links.new(comb.outputs[0], mul.inputs[7])
    nt.links.new(mul.outputs[2], _inp(bsdf, "Base Color"))
    # varnished wood: low roughness with scuffs, stronger in traffic noise
    nt.links.new(_noise(nt, vec, 6.0, 8.0, 0.28, 0.45, loc=(-500, -300)), _inp(bsdf, "Roughness"))
    try:
        _inp(bsdf, "Coat Weight", "Coat").default_value = varnish
        _inp(bsdf, "Coat Roughness").default_value = 0.12
    except KeyError:
        pass
    joints = nt.nodes.new("ShaderNodeMath")
    joints.operation = "SUBTRACT"
    joints.inputs[0].default_value = 1.0
    nt.links.new(brick.outputs["Fac"], joints.inputs[1])
    nt.links.new(_bump(nt, joints.outputs[0], 0.4, distance=0.0015), _inp(bsdf, "Normal"))
    return mat


def fabric(name, color=(0.55, 0.53, 0.50), sheen=0.5, roughness=0.9, weave_scale=400.0):
    mat, nt, bsdf = _fresh(name)
    vec = _uv_scaled(nt, 1.0)
    _inp(bsdf, "Base Color").default_value = (*color, 1.0)
    nt.links.new(_noise(nt, vec, 25.0, 4.0, roughness - 0.08, roughness, loc=(-500, 0)), _inp(bsdf, "Roughness"))
    try:
        _inp(bsdf, "Sheen Weight", "Sheen").default_value = sheen
        _inp(bsdf, "Sheen Roughness").default_value = 0.5
    except KeyError:
        pass
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.location = (-500, -300)
    wave.inputs["Scale"].default_value = weave_scale
    nt.links.new(vec, wave.inputs["Vector"])
    nt.links.new(_bump(nt, wave.outputs["Fac"], 0.08, distance=0.0005), _inp(bsdf, "Normal"))
    return mat


def solid(name, color, roughness=0.5, metallic=0.0, coat=0.0):
    """Painted wood, lacquer, plastic, ceramics: plain PBR with a little roughness noise."""
    mat, nt, bsdf = _fresh(name)
    vec = _uv_scaled(nt, 1.0)
    _inp(bsdf, "Base Color").default_value = (*color, 1.0)
    _inp(bsdf, "Metallic").default_value = metallic
    nt.links.new(_noise(nt, vec, 8.0, 6.0, roughness * 0.85, min(1.0, roughness * 1.15), loc=(-500, 0)),
                 _inp(bsdf, "Roughness"))
    if coat:
        try:
            _inp(bsdf, "Coat Weight", "Coat").default_value = coat
        except KeyError:
            pass
    return mat


def brushed_metal(name, color=(0.62, 0.62, 0.60), roughness=0.35, anisotropy=0.6):
    mat = solid(name, color, roughness, metallic=1.0)
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    try:
        _inp(bsdf, "Anisotropic").default_value = anisotropy
    except KeyError:
        pass
    return mat


def glass(name, ior=1.52, dust=0.03):
    """Clear window glass with a faint dust/fingerprint roughness layer."""
    mat, nt, bsdf = _fresh(name)
    vec = _uv_scaled(nt, 1.0)
    _inp(bsdf, "Base Color").default_value = (0.97, 0.98, 0.98, 1.0)
    _inp(bsdf, "IOR").default_value = ior
    _inp(bsdf, "Transmission Weight", "Transmission").default_value = 1.0
    nt.links.new(_noise(nt, vec, 30.0, 6.0, 0.0, dust, loc=(-500, 0)), _inp(bsdf, "Roughness"))
    return mat


def emissive(name, color=(1.0, 0.85, 0.65), strength=5.0):
    mat, nt, bsdf = _fresh(name)
    _inp(bsdf, "Emission Color", "Emission").default_value = (*color, 1.0)
    _inp(bsdf, "Emission Strength").default_value = strength
    return mat


def default_shell_look():
    """Neutral, realistic finishes for the shell when the dossier gives no better evidence."""
    plaster_paint("MAT_Wall", color=(0.84, 0.83, 0.80))
    plaster_paint("MAT_Ceiling", color=(0.88, 0.88, 0.87), bump=0.008)
    parquet("MAT_Floor")
    glass("MAT_Glass")
    solid("MAT_Fixed", (0.86, 0.86, 0.84), roughness=0.35, coat=0.2)   # painted steel radiators
