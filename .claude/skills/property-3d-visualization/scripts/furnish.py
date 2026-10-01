"""Place the approved furniture layout in Blender, from the same JSON that layout_check.py validated.

    exec(open("<skill>/scripts/materials.py").read())      # material factories used below
    exec(open("<skill>/scripts/furnish.py").read())
    furnish("<project>/03_design/layout_v1.json")

Each item is an empty `FUR_<id>` at the layout position/rotation (front = local +Y) with its parts
parented under it, in COL_Furniture_Proposed.
  * If the item has "asset" (a .blend, .glb/.gltf, .fbx or .obj file, e.g. a Poly Haven or
    Sketchfab download), that model is imported, centred, set on the floor and scaled uniformly to
    the item's width. A depth/height mismatch over 5 % is reported: pick a model whose proportions
    match the real product instead of stretching it.
  * Otherwise a parametric stand-in with the item's exact dimensions is built (soft bevels,
    cushions, legs, shelves...). Good for layout review and lighting; replace hero pieces with real
    assets before final client renders.
Lamps (floor_lamp, bedside table lamps) get a 2700 K practical light inside the shade.
"""

import json
import math
import os
import random

import bpy
import bmesh
from mathutils import Vector

_RNG = random.Random(7)


# ---------------------------------------------------------------- materials

# name -> (factory in materials.py, default colour, extra kwargs). A layout's "palette" can override the
# colour of any entry, e.g. {"palette": {"MAT_Sofa": [0.55, 0.50, 0.43]}}, so a style is data, not code.
PALETTE = {
    "MAT_Sofa": ("fabric", (0.42, 0.40, 0.36), {"sheen": 0.6}),
    "MAT_Armchair": ("fabric", (0.30, 0.34, 0.30), {"sheen": 0.6}),
    "MAT_Rug": ("fabric", (0.72, 0.68, 0.60), {"sheen": 0.3, "roughness": 0.95, "weave_scale": 150}),
    "MAT_Linen": ("fabric", (0.82, 0.80, 0.76), {"sheen": 0.3, "weave_scale": 600}),
    "MAT_Sheet": ("fabric", (0.86, 0.85, 0.82), {"sheen": 0.2, "weave_scale": 700}),
    "MAT_Throw": ("fabric", (0.60, 0.42, 0.30), {"sheen": 0.5, "roughness": 0.9, "weave_scale": 120}),
    "MAT_Cushion_A": ("fabric", (0.55, 0.32, 0.22), {"sheen": 0.5}),
    "MAT_Cushion_B": ("fabric", (0.40, 0.45, 0.36), {"sheen": 0.5}),
    "MAT_Shade": ("fabric", (0.90, 0.87, 0.80), {"sheen": 0.2}),
    "MAT_Sheer": ("sheer", (0.93, 0.91, 0.87), {}),
    "MAT_Oak": ("solid", (0.46, 0.32, 0.20), {"roughness": 0.45, "coat": 0.2}),
    "MAT_Lacquer": ("solid", (0.80, 0.79, 0.76), {"roughness": 0.3, "coat": 0.3}),
    "MAT_Metal_Black": ("solid", (0.03, 0.03, 0.03), {"roughness": 0.35, "metallic": 1.0}),
    "MAT_Brass": ("brushed_metal", (0.80, 0.62, 0.35), {"roughness": 0.3}),
    "MAT_Screen": ("solid", (0.01, 0.01, 0.012), {"roughness": 0.08}),
    "MAT_Books": ("solid", (0.45, 0.40, 0.35), {"roughness": 0.6}),
    "MAT_Kitchen_Front": ("solid", (0.58, 0.57, 0.52), {"roughness": 0.55}),
    "MAT_Worktop": ("solid", (0.50, 0.36, 0.24), {"roughness": 0.35, "coat": 0.3}),
    "MAT_Plinth": ("solid", (0.12, 0.12, 0.12), {"roughness": 0.6}),
    "MAT_Steel": ("brushed_metal", (0.70, 0.70, 0.68), {"roughness": 0.3}),
    "MAT_Print": ("print", (0.62, 0.36, 0.24), {}),
    "MAT_Ceramic": ("solid", (0.85, 0.83, 0.78), {"roughness": 0.25}),
    "MAT_Cushion_C": ("fabric", (0.10, 0.16, 0.30), {"sheen": 0.5}),
    "MAT_Leaf": ("solid", (0.14, 0.27, 0.11), {"roughness": 0.45}),
    "MAT_Soil": ("solid", (0.10, 0.07, 0.05), {"roughness": 0.95}),
}
_OVERRIDES = {}


def _mat(name):
    """Named furniture materials; built once with the factories from materials.py."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    g = globals()
    if "fabric" not in g:
        raise RuntimeError("exec materials.py before furnish.py")
    factory, color, kw = PALETTE.get(name, ("solid", (0.6, 0.6, 0.6), {}))
    color = tuple(_OVERRIDES.get(name, color))
    if factory == "sheer":
        return _sheer(name, color)
    if factory == "print":
        return _print(name, color)
    return g[factory](name, color, **kw)


def _sheer(name, color):
    """Sheer linen curtain: translucent, lets daylight through, soft sheen."""
    mat = globals()["fabric"](name, color, sheen=0.4, roughness=0.9)
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    for key in ("Transmission Weight", "Transmission"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 0.55
            break
    bsdf.inputs["Roughness"].default_value = 0.9
    return mat


def _print(name, color):
    """Abstract art print: two earthy colour fields with soft organic edges (no text, no real artwork)."""
    g = globals()
    mat, nt, bsdf = g["_fresh"](name)
    uv = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 1.6
    noise.inputs["Detail"].default_value = 2.0
    nt.links.new(uv.outputs["Generated"], noise.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.46
    ramp.color_ramp.elements[0].color = (0.86, 0.82, 0.74, 1)
    ramp.color_ramp.elements[1].position = 0.50
    ramp.color_ramp.elements[1].color = (*color, 1)
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.85
    return mat


# ---------------------------------------------------------------- primitives (item-local coords)

def _obj(name, mesh, parent, mat, bevel=0.0):
    o = bpy.data.objects.new(name, mesh)
    parent.users_collection[0].objects.link(o)
    o.parent = parent
    o.data.materials.append(_mat(mat))
    if bevel:
        mod = o.modifiers.new("Bevel", "BEVEL")
        mod.width = bevel
        mod.segments = 3
        mod.limit_method = "ANGLE"
    for p in o.data.polygons:
        p.use_smooth = True
    return o


def box(parent, name, size, loc, mat, bevel=0.004, rot=(0, 0, 0)):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    bm.to_mesh(me)
    bm.free()
    o = _obj(name, me, parent, mat, bevel)
    o.location = loc
    o.rotation_euler = rot
    _box_uv(o)
    return o


def cyl(parent, name, r, h, loc, mat, segs=32, r_top=None, cap=True):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=cap, cap_tris=False, segments=segs,
                          radius1=r, radius2=r if r_top is None else r_top, depth=h)
    bm.to_mesh(me)
    bm.free()
    o = _obj(name, me, parent, mat)
    o.location = loc
    return o


def _box_uv(o):
    me = o.data
    uv = me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        n = poly.normal
        ax = max(range(3), key=lambda i: abs(n[i]))
        for li in poly.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = (co.y, co.z) if ax == 0 else ((co.x, co.z) if ax == 1 else (co.x, co.y))


def _soft(o, level=2):
    """Soft furnishings (cushions, pillows, duvets, mattresses) are never boxes: round them off."""
    mod = o.modifiers.new("Soft", "SUBSURF")
    mod.levels = mod.render_levels = level
    return o


def _jitter(o, rot=0.03, scale=0.02):
    """Small imperfections: nothing in a lived-in room is perfectly aligned."""
    o.rotation_euler = [a + _RNG.uniform(-rot, rot) for a in o.rotation_euler]
    o.scale = [s * (1 + _RNG.uniform(-scale, scale)) for s in o.scale]


def _pillow(parent, name, w, d, t, loc, mat, rot=(0, 0, 0), n=14):
    """Puffy pillow / cushion: thickness peaks in the middle and pinches to a seam at the edges."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    grid = {}
    for side in (1, -1):
        for i in range(n + 1):
            for j in range(n + 1):
                u, v = 2 * i / n - 1, 2 * j / n - 1
                f = max(0.0, (1 - abs(u) ** 3) * (1 - abs(v) ** 3)) ** 0.5
                edge = i in (0, n) or j in (0, n)
                key = (0, i, j) if edge else (side, i, j)
                if key not in grid:
                    # edges bow inwards a little, like a stuffed cover pulling on its seam
                    pinch = 1 - 0.06 * (1 - abs(v) ** 2) if i in (0, n) else 1.0
                    pinch_y = 1 - 0.06 * (1 - abs(u) ** 2) if j in (0, n) else 1.0
                    grid[key] = bm.verts.new((u * w / 2 * pinch, v * d / 2 * pinch_y, side * t / 2 * f))
    for side in (1, -1):
        for i in range(n):
            for j in range(n):
                q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
                vs = [grid.get((side, a, b)) or grid[(0, a, b)] for a, b in q]
                bm.faces.new(vs if side > 0 else vs[::-1])
    bm.to_mesh(me)
    bm.free()
    o = _obj(name, me, parent, mat)
    o.location = loc
    o.rotation_euler = rot
    _box_uv(o)
    _soft(o, 1)
    _wrinkle(o, 0.004)
    return o


def _wrinkle(o, strength=0.006, scale=0.12):
    """Fabric is never perfectly smooth: low-amplitude noise displacement after the subdivision."""
    tex = bpy.data.textures.get("TEX_Wrinkle") or bpy.data.textures.new("TEX_Wrinkle", "CLOUDS")
    tex.noise_scale = scale
    mod = o.modifiers.new("Wrinkle", "DISPLACE")
    mod.texture = tex
    mod.strength = strength
    mod.mid_level = 0.5
    return o


def _drape(parent, name, w, d, z, drop, mat, y0=0.0, foot=True, head=False, thick=0.03, r=0.06,
           folds_per_m=5.0, res=0.03):
    """Duvet / throw lying on a w x d top surface at height z and hanging `drop` over the sides
    (and the foot at +Y). Built from a flat sheet: the excess beyond each edge rolls over a radius r
    and falls, corners gather into a fold, the hanging part ripples. Local origin = top centre."""
    W = w + 2 * drop
    D = d + (drop if foot else 0) + (drop if head else 0)
    nx, ny = max(8, int(W / res)), max(8, int(D / res))
    ymin = -d / 2 - (drop if head else 0)

    def roll(e):
        if e <= 0:
            return 0.0, 0.0
        if e < r * math.pi / 2:
            a = e / r
            return r * math.sin(a), r * (1 - math.cos(a))
        return r, r + (e - r * math.pi / 2)

    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    vs = []
    for j in range(ny + 1):
        row = []
        b = ymin + D * j / ny
        for i in range(nx + 1):
            a = -W / 2 + W * i / nx
            ex = max(0.0, abs(a) - w / 2)
            ey = max(0.0, b - d / 2) if foot else 0.0
            if head:
                ey = max(ey, -d / 2 - b)
            ox, dx = roll(ex)
            oy, dy = roll(ey)
            hang = max(dx, dy)
            corner = min(ex, ey)
            x = math.copysign(min(abs(a), w / 2) + ox + 0.25 * corner, a)
            y = (min(max(b, -d / 2), d / 2) + math.copysign(oy + 0.25 * corner, b)) if ey > 0 else b
            # ripples grow with the hanging length, along the edge the cloth falls from
            ripple = 0.015 * min(1.0, hang / 0.15)
            if ex > ey:
                x += math.copysign(ripple * math.sin(2 * math.pi * folds_per_m * b), a)
            elif ey > 0:
                y += math.copysign(ripple * math.sin(2 * math.pi * folds_per_m * a + 1.3), b)
            row.append(bm.verts.new((x, y + y0, -hang)))
        vs.append(row)
    for j in range(ny):
        for i in range(nx):
            bm.faces.new((vs[j][i], vs[j][i + 1], vs[j + 1][i + 1], vs[j + 1][i]))
    bm.to_mesh(me)
    bm.free()
    o = _obj(name, me, parent, mat)
    o.location = (0, 0, z)
    uv = me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        for li in poly.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = (co.x, co.y - co.z)
    sol = o.modifiers.new("Thick", "SOLIDIFY")
    sol.thickness = thick
    sol.offset = 1.0
    _soft(o, 1)
    _wrinkle(o, 0.006)
    return o


def practical(parent, name, loc, watts=25.0, kelvin=2700, radius=0.04):
    ld = bpy.data.lights.new(name, "POINT")
    ld.energy = watts
    ld.shadow_soft_size = radius
    if hasattr(ld, "use_temperature"):
        ld.use_temperature = True
        ld.temperature = kelvin
    else:
        ld.color = (1.0, 0.72, 0.42)
    o = bpy.data.objects.new(name, ld)
    parent.users_collection[0].objects.link(o)
    o.parent = parent
    o.location = loc
    return o


# ---------------------------------------------------------------- parametric stand-ins
# Local frame: origin at the item's floor centre, +Y = front, -Y = back, Z up.

def build_sofa(p, w, d, h, mat="MAT_Sofa", seats=3):
    arm, leg, back_t = 0.18, 0.12, 0.22
    for sx in (-1, 1):
        for sy in (-1, 1):
            cyl(p, f"{p.name}_leg", 0.02, leg, (sx * (w / 2 - 0.06), sy * (d / 2 - 0.06), leg / 2), "MAT_Oak", 12)
    # Parts overlap but never share a face plane: coincident faces render as black patches or
    # flicker in Cycles. The base tucks 1 cm into each arm and sits 1 cm back from the arm fronts.
    box(p, f"{p.name}_base", (w - 2 * arm + 0.02, d - 0.03, 0.18), (0, -0.005, leg + 0.09), mat, 0.03)
    for sx in (-1, 1):
        box(p, f"{p.name}_arm", (arm, d, 0.62 - leg), (sx * (w / 2 - arm / 2), 0, leg + (0.62 - leg) / 2), mat, 0.05)
    box(p, f"{p.name}_back", (w - 2 * arm + 0.02, back_t - 0.01, h - leg), (0, -d / 2 + back_t / 2, leg + (h - leg) / 2), mat, 0.05)
    inner = w - 2 * arm
    cw = inner / seats
    for i in range(seats):
        x = -inner / 2 + cw * (i + 0.5)
        c = _soft(box(p, f"{p.name}_seat{i}", (cw - 0.01, d - back_t - 0.02, 0.14), (x, back_t / 2, leg + 0.18 + 0.07), mat, 0.03))
        _jitter(c, 0.01, 0.01)
        b = _soft(box(p, f"{p.name}_backcush{i}", (cw - 0.02, 0.16, 0.40), (x, -d / 2 + back_t + 0.07, leg + 0.18 + 0.14 + 0.19),
                      mat, 0.04, rot=(math.radians(-12), 0, 0)))
        _jitter(b, 0.03, 0.02)


def build_coffee_table(p, w, d, h, round_top=None):
    """Rectangular on four legs, or round (w == d) on three legs."""
    top = 0.03
    if round_top is None:
        round_top = abs(w - d) < 1e-6
    if round_top:
        cyl(p, f"{p.name}_top", w / 2, top, (0, 0, h - top / 2), "MAT_Oak", 64)
        for k in range(3):
            a = 2 * math.pi * k / 3
            cyl(p, f"{p.name}_leg", 0.018, h - top, (math.cos(a) * w * 0.32, math.sin(a) * w * 0.32, (h - top) / 2),
                "MAT_Oak", 12)
        return
    box(p, f"{p.name}_top", (w, d, top), (0, 0, h - top / 2), "MAT_Oak", 0.006)
    for sx in (-1, 1):
        for sy in (-1, 1):
            cyl(p, f"{p.name}_leg", 0.018, h - top, (sx * (w / 2 - 0.08), sy * (d / 2 - 0.08), (h - top) / 2), "MAT_Metal_Black", 12)


def build_rug(p, w, d, h):
    box(p, f"{p.name}_rug", (w, d, max(h, 0.008)), (0, 0, max(h, 0.008) / 2), "MAT_Rug", 0.004)


def build_tv_unit(p, w, d, h):
    box(p, f"{p.name}_body", (w, d, h - 0.08), (0, 0, 0.08 + (h - 0.08) / 2), "MAT_Lacquer", 0.004)
    for sx in (-1, 1):
        cyl(p, f"{p.name}_foot", 0.015, 0.08, (sx * (w / 2 - 0.1), 0, 0.04), "MAT_Metal_Black", 12)
    for i in range(1, 3):
        box(p, f"{p.name}_gap", (0.003, 0.004, h - 0.12), (-w / 2 + w * i / 3, d / 2, 0.08 + (h - 0.08) / 2), "MAT_Metal_Black", 0)
    tv_w, tv_h = 1.23, 0.71                                  # 55" screen
    box(p, f"{p.name}_tv", (tv_w, 0.03, tv_h), (0, -0.02, h + 0.06 + tv_h / 2), "MAT_Screen", 0.003)
    box(p, f"{p.name}_tvstand", (0.30, 0.20, 0.06), (0, -0.02, h + 0.03), "MAT_Metal_Black", 0.004)


def build_armchair(p, w, d, h):
    build_sofa(p, w, d, h, mat="MAT_Armchair", seats=1)


def build_floor_lamp(p, w, d, h):
    cyl(p, f"{p.name}_base", 0.14, 0.02, (0, 0, 0.01), "MAT_Metal_Black")
    cyl(p, f"{p.name}_pole", 0.012, h - 0.3, (0, 0, (h - 0.3) / 2), "MAT_Brass", 12)
    cyl(p, f"{p.name}_shade", min(w, d) / 2, 0.30, (0, 0, h - 0.15), "MAT_Shade", 48, r_top=min(w, d) / 2 * 0.8, cap=False)
    practical(p, f"{p.name}_light", (0, 0, h - 0.18), watts=40)


def build_bed(p, w, d, h):
    """Upholstered headboard, oak frame, mattress, a duvet draping over sides and foot with the top
    turned back, two pillow pairs and a throw across the foot (MAT_Throw)."""
    frame_h = max(0.25, h - 0.22)
    mat_top = frame_h + 0.22
    box(p, f"{p.name}_frame", (w + 0.06, d + 0.04, frame_h), (0, 0, frame_h / 2), "MAT_Oak", 0.01)
    box(p, f"{p.name}_mattress", (w, d - 0.04, 0.22), (0, 0.0, frame_h + 0.11), "MAT_Sheet", 0.05)
    box(p, f"{p.name}_head", (w + 0.1, 0.08, 1.05), (0, -d / 2 - 0.02, 0.525), "MAT_Armchair", 0.03)
    drop = min(0.32, mat_top - 0.08)
    cover = d * 0.74                                       # duvet turned back below the pillows
    _drape(p, f"{p.name}_duvet", w, cover, mat_top, drop, "MAT_Linen", y0=d / 2 - 0.02 - cover / 2,
           thick=0.045, r=0.07)
    fold = _soft(box(p, f"{p.name}_fold", (w + 0.1, 0.16, 0.07),
                     (0, d / 2 - 0.02 - cover - 0.05, mat_top + 0.035), "MAT_Linen", 0.03))
    _jitter(fold, 0.006, 0.01)
    throw_d = min(0.55, d * 0.28)
    _drape(p, f"{p.name}_throw", w + 0.24, throw_d, mat_top + 0.05, drop - 0.06, "MAT_Throw",
           y0=d / 2 - 0.02 - throw_d / 2 - 0.12, foot=False, thick=0.012, r=0.09, folds_per_m=7.0)
    for sx in (-1, 1):
        back = _pillow(p, f"{p.name}_pillow", w / 2 - 0.08, 0.50, 0.16,
                       (sx * w / 4, -d / 2 + 0.24, mat_top + 0.14), "MAT_Linen",
                       rot=(math.radians(-32), 0, sx * 0.02))
        _jitter(back, 0.03, 0.02)
        front = _pillow(p, f"{p.name}_pillow2", w / 2 - 0.14, 0.40, 0.13,
                        (sx * w / 4, -d / 2 + 0.42, mat_top + 0.10), "MAT_Sheet",
                        rot=(math.radians(-22), 0, -sx * 0.03))
        _jitter(front, 0.03, 0.02)


def build_bedside_table(p, w, d, h):
    box(p, f"{p.name}_body", (w, d, h - 0.1), (0, 0, 0.1 + (h - 0.1) / 2), "MAT_Oak", 0.005)
    for sx in (-1, 1):
        for sy in (-1, 1):
            cyl(p, f"{p.name}_leg", 0.012, 0.1, (sx * (w / 2 - 0.04), sy * (d / 2 - 0.04), 0.05), "MAT_Oak", 10)
    box(p, f"{p.name}_drawer", (w - 0.04, 0.004, 0.003), (0, d / 2, h - 0.12), "MAT_Metal_Black", 0)
    cyl(p, f"{p.name}_lampbase", 0.06, 0.28, (0.05, -0.02, h + 0.14), "MAT_Lacquer", 24)
    cyl(p, f"{p.name}_lampshade", 0.13, 0.18, (0.05, -0.02, h + 0.36), "MAT_Shade", 40, r_top=0.10, cap=False)
    practical(p, f"{p.name}_light", (0.05, -0.02, h + 0.34), watts=15)


def build_wardrobe(p, w, d, h):
    box(p, f"{p.name}_body", (w, d, h), (0, 0, h / 2), "MAT_Lacquer", 0.004)
    doors = max(2, round(w / 0.5))
    for i in range(1, doors):
        box(p, f"{p.name}_gap", (0.003, 0.004, h - 0.04), (-w / 2 + w * i / doors, d / 2, h / 2), "MAT_Metal_Black", 0)
    for i in range(doors):
        x = -w / 2 + w * (i + 0.5) / doors + (0.18 if i % 2 == 0 else -0.18) * (w / doors) / 0.5
        box(p, f"{p.name}_handle", (0.012, 0.025, 0.30), (x, d / 2 + 0.012, 1.05), "MAT_Brass", 0.003)


def build_bookcase(p, w, d, h):
    t = 0.02
    for sx in (-1, 1):
        box(p, f"{p.name}_side", (t, d, h), (sx * (w / 2 - t / 2), 0, h / 2), "MAT_Oak", 0.002)
    box(p, f"{p.name}_backpanel", (w, 0.008, h), (0, -d / 2 + 0.004, h / 2), "MAT_Oak", 0)
    n = max(2, int(h / 0.35))
    for i in range(n + 1):
        z = min(h - t / 2, t / 2 + i * (h - t) / n)
        box(p, f"{p.name}_shelf", (w - 2 * t, d, t), (0, 0, z), "MAT_Oak", 0.002)
        if i < n:
            x = -w / 2 + t + 0.02
            while x < w / 2 - t - 0.05 and _RNG.random() < 0.93:
                bw = _RNG.uniform(0.02, 0.05)
                bh = _RNG.uniform(0.18, 0.30)
                box(p, f"{p.name}_book", (bw, d * 0.8, bh), (x + bw / 2, 0, z + t / 2 + bh / 2), "MAT_Books", 0.002)
                x += bw + 0.002


def build_dining_table(p, w, d, h, round_top=None):
    """Round (w == d) pedestal table or rectangular table on four legs."""
    top = 0.03
    if round_top is None:
        round_top = abs(w - d) < 1e-6
    if round_top:
        cyl(p, f"{p.name}_top", w / 2, top, (0, 0, h - top / 2), "MAT_Oak", 64)
        cyl(p, f"{p.name}_column", 0.04, h - top - 0.02, (0, 0, (h - top) / 2), "MAT_Metal_Black", 24)
        cyl(p, f"{p.name}_foot", min(w, 0.9) * 0.28, 0.02, (0, 0, 0.01), "MAT_Metal_Black", 48)
    else:
        box(p, f"{p.name}_top", (w, d, top), (0, 0, h - top / 2), "MAT_Oak", 0.004)
        for sx in (-1, 1):
            for sy in (-1, 1):
                box(p, f"{p.name}_leg", (0.04, 0.04, h - top), (sx * (w / 2 - 0.06), sy * (d / 2 - 0.06), (h - top) / 2),
                    "MAT_Oak", 0.003)


def build_chair(p, w, d, h):
    """Dining chair; front (+Y) is where the sitter's knees point."""
    seat_h, seat_t = 0.45, 0.03
    for sx in (-1, 1):
        for sy in (-1, 1):
            cyl(p, f"{p.name}_leg", 0.013, seat_h - seat_t, (sx * (w / 2 - 0.04), sy * (d / 2 - 0.04), (seat_h - seat_t) / 2),
                "MAT_Oak", 12)
    box(p, f"{p.name}_seat", (w, d, seat_t), (0, 0, seat_h - seat_t / 2), "MAT_Oak", 0.006)
    box(p, f"{p.name}_back", (w - 0.04, 0.02, h - seat_h - 0.05), (0, -d / 2 + 0.02, seat_h + (h - seat_h) / 2 + 0.02),
        "MAT_Oak", 0.005, rot=(math.radians(-8), 0, 0))


def build_kitchen_run(p, w, d, h, module=0.6):
    """Base cabinets: recessed plinth, carcass, fronts with 3 mm gaps and bar handles, 4 cm worktop.
    Appliances from the layout item (distances measured from the run's left end, facing its front):
    "sink_at", "hob_at" (with a built-in oven below unless "oven": false)."""
    plinth, wt = 0.10, 0.04
    body_h = h - plinth - wt
    box(p, f"{p.name}_plinth", (w, d - 0.06, plinth), (0, -0.03, plinth / 2), "MAT_Plinth", 0.0)
    box(p, f"{p.name}_carcass", (w, d - 0.03, body_h), (0, -0.015, plinth + body_h / 2), "MAT_Kitchen_Front", 0.0)
    n = max(1, round(w / module))
    fw = w / n
    for i in range(n):
        x = -w / 2 + fw * (i + 0.5)
        box(p, f"{p.name}_front", (fw - 0.003, 0.019, body_h - 0.003), (x, d / 2 - 0.02, plinth + body_h / 2),
            "MAT_Kitchen_Front", 0.001)
        box(p, f"{p.name}_handle", (fw * 0.5, 0.012, 0.012), (x, d / 2 - 0.004, plinth + body_h - 0.06), "MAT_Steel", 0.002)
    box(p, f"{p.name}_worktop", (w, d + 0.02, wt), (0, 0.01, h - wt / 2), "MAT_Worktop", 0.003)
    spec = {k: p[k] for k in ("sink_at", "hob_at", "oven") if k in p}
    if "sink_at" in spec:
        x = -w / 2 + spec["sink_at"]
        box(p, f"{p.name}_sink", (0.50, 0.40, 0.012), (x, 0.03, h + 0.001), "MAT_Steel", 0.004)
        box(p, f"{p.name}_basin", (0.44, 0.34, 0.012), (x, 0.03, h + 0.003), "MAT_Plinth", 0.01)
        cyl(p, f"{p.name}_tap", 0.02, 0.28, (x, -0.20, h + 0.14), "MAT_Steel", 16)
        spout = cyl(p, f"{p.name}_spout", 0.011, 0.20, (x, -0.11, h + 0.27), "MAT_Steel", 12)
        spout.rotation_euler = (math.radians(90), 0, 0)
    if "hob_at" in spec:
        x = -w / 2 + spec["hob_at"]
        box(p, f"{p.name}_hob", (0.58, 0.50, 0.006), (x, 0.02, h + 0.003), "MAT_Screen", 0.002)
        if spec.get("oven", True):
            box(p, f"{p.name}_oven", (0.56, 0.02, 0.46), (x, d / 2 - 0.005, plinth + body_h - 0.30), "MAT_Screen", 0.002)
            box(p, f"{p.name}_ovenbar", (0.45, 0.02, 0.015), (x, d / 2 + 0.015, plinth + body_h - 0.08), "MAT_Steel", 0.002)


def build_wall_units(p, w, d, h, module=0.6):
    """Wall cabinets (place with "elevation" = underside height, typically 1.45 m); optional "hood_at"
    (distance from the left end) adds a slim extractor under the units."""
    box(p, f"{p.name}_carcass", (w, d - 0.02, h), (0, -0.01, h / 2), "MAT_Kitchen_Front", 0.0)
    n = max(1, round(w / module))
    fw = w / n
    for i in range(n):
        x = -w / 2 + fw * (i + 0.5)
        box(p, f"{p.name}_front", (fw - 0.003, 0.019, h - 0.003), (x, d / 2 - 0.01, h / 2), "MAT_Kitchen_Front", 0.001)
        box(p, f"{p.name}_handle", (fw * 0.5, 0.012, 0.012), (x, d / 2 + 0.006, 0.05), "MAT_Steel", 0.002)
    if "hood_at" in p:
        box(p, f"{p.name}_hood", (0.60, d, 0.05), (-w / 2 + p["hood_at"], 0.0, -0.025), "MAT_Steel", 0.003)


def build_appliance(p, w, d, h):
    """Freestanding white appliance (washing machine / dryer) with a round door."""
    box(p, f"{p.name}_body", (w, d, h), (0, 0, h / 2), "MAT_Ceramic", 0.01)
    door = cyl(p, f"{p.name}_door", 0.17, 0.03, (0, d / 2, h * 0.45), "MAT_Screen", 48)
    door.rotation_euler = (math.radians(90), 0, 0)


def build_tall_unit(p, w, d, h):
    """Tall housing (fridge column): carcass, two fronts, bar handles."""
    plinth = 0.10
    box(p, f"{p.name}_plinth", (w, d - 0.06, plinth), (0, -0.03, plinth / 2), "MAT_Plinth", 0.0)
    box(p, f"{p.name}_carcass", (w, d - 0.03, h - plinth), (0, -0.015, plinth + (h - plinth) / 2), "MAT_Kitchen_Front", 0.0)
    split = plinth + (h - plinth) * 0.55
    for name, z0, z1 in (("low", plinth, split), ("high", split, h)):
        box(p, f"{p.name}_front_{name}", (w - 0.003, 0.019, z1 - z0 - 0.003), (0, d / 2 - 0.02, (z0 + z1) / 2),
            "MAT_Kitchen_Front", 0.001)
    box(p, f"{p.name}_handle", (0.012, 0.012, 0.35), (w / 2 - 0.06, d / 2 - 0.004, split + 0.25), "MAT_Steel", 0.002)
    box(p, f"{p.name}_handle2", (0.012, 0.012, 0.35), (w / 2 - 0.06, d / 2 - 0.004, split - 0.25), "MAT_Steel", 0.002)


def build_plant(p, w, d, h, blades=11):
    """Snake plant (Sansevieria) in a ceramic pot: upright tapered blades, slightly irregular.
    Item size = pot diameter x pot diameter x total height."""
    pot_h = min(0.35, h * 0.35)
    r = min(w, d) / 2
    cyl(p, f"{p.name}_pot", r, pot_h, (0, 0, pot_h / 2), "MAT_Ceramic", 40, r_top=r * 1.05)
    cyl(p, f"{p.name}_soil", r * 0.95, 0.01, (0, 0, pot_h - 0.02), "MAT_Soil", 32)
    for k in range(blades):
        bh = (h - pot_h) * _RNG.uniform(0.55, 1.0)
        bw = _RNG.uniform(0.035, 0.06)
        me = bpy.data.meshes.new(f"{p.name}_blade")
        me.from_pydata([(-bw / 2, 0, 0), (bw / 2, 0, 0), (bw * 0.1, 0, bh), (-bw * 0.1, 0, bh)], [], [(0, 1, 2, 3)])
        o = _obj(f"{p.name}_blade", me, p, "MAT_Leaf")
        o.modifiers.new("Thickness", "SOLIDIFY").thickness = 0.003
        a = 2 * math.pi * k / blades + _RNG.uniform(-0.3, 0.3)
        rr = r * _RNG.uniform(0.1, 0.6)
        o.location = (math.cos(a) * rr, math.sin(a) * rr, pot_h - 0.02)
        o.rotation_euler = (_RNG.uniform(-0.12, 0.12), _RNG.uniform(-0.12, 0.12), _RNG.uniform(0, math.pi))


def build_curtain(p, w, d, h, folds_per_m=6.0):
    """Sheer curtain panel with sinusoidal folds on a thin rod; item width = curtain width, height = rod height.
    Place with front (+Y) facing into the room, a few cm in front of the window wall."""
    amp = max(0.02, d / 2 - 0.01)
    nx, nz = max(8, int(w * 60)), 6
    me = bpy.data.meshes.new(f"{p.name}_sheer")
    verts, faces = [], []
    for j in range(nz + 1):
        z = 0.02 + (h - 0.06) * j / nz
        for i in range(nx + 1):
            x = -w / 2 + w * i / nx
            verts.append((x, amp * math.sin(2 * math.pi * folds_per_m * (x + w / 2)), z))
    for j in range(nz):
        for i in range(nx):
            a = j * (nx + 1) + i
            faces.append((a, a + 1, a + nx + 2, a + nx + 1))
    me.from_pydata(verts, [], faces)
    o = _obj(f"{p.name}_sheer", me, p, "MAT_Sheer")
    sol = o.modifiers.new("Thickness", "SOLIDIFY")
    sol.thickness = 0.002
    cyl(p, f"{p.name}_rod", 0.01, w + 0.1, (0, 0, h - 0.02), "MAT_Metal_Black", 12).rotation_euler = (0, math.pi / 2, 0)


def build_wall_art(p, w, d, h):
    """Framed abstract print; place with "elevation" = bottom edge height, front facing into the room."""
    frame = 0.025
    box(p, f"{p.name}_frame", (w, max(d, 0.02), h), (0, 0, h / 2), "MAT_Oak", 0.002)
    box(p, f"{p.name}_print", (w - 2 * frame, 0.004, h - 2 * frame), (0, max(d, 0.02) / 2, h / 2), "MAT_Print", 0.0)


def build_cushion(p, w, d, h):
    """Scatter cushion leaning back: size = (width, thickness, height) of the cushion standing up."""
    c = _pillow(p, f"{p.name}_cushion", w, h, max(d, 0.12), (0, 0, h / 2), p.get("mat", "MAT_Cushion_A"),
                rot=(math.radians(105), 0, 0))
    _jitter(c, 0.05, 0.04)


def build_pendant(p, w, d, h, ceiling=2.55):
    """Pendant fixture on a ceiling outlet: canopy, cord and a shade whose bottom is at the item's elevation.
    (Light off in daylight shots; the fixture is what shows.)"""
    base = p.location.z
    cord = max(0.05, ceiling - base - h)
    cyl(p, f"{p.name}_canopy", 0.05, 0.02, (0, 0, ceiling - base - 0.01), "MAT_Ceramic", 24)
    cyl(p, f"{p.name}_cord", 0.003, cord, (0, 0, h + cord / 2), "MAT_Metal_Black", 8)
    cyl(p, f"{p.name}_shade", w / 2, h, (0, 0, h / 2), "MAT_Ceramic", 48, r_top=w * 0.12, cap=False)
    practical(p, f"{p.name}_light", (0, 0, h * 0.4), watts=40)


BUILDERS = {
    "sofa": build_sofa, "armchair": build_armchair, "coffee_table": build_coffee_table, "rug": build_rug,
    "tv_unit": build_tv_unit, "floor_lamp": build_floor_lamp, "bed": build_bed,
    "bedside_table": build_bedside_table, "wardrobe": build_wardrobe, "bookcase": build_bookcase,
    "dining_table": build_dining_table, "chair": build_chair, "kitchen_run": build_kitchen_run,
    "tall_unit": build_tall_unit, "curtain": build_curtain, "wall_art": build_wall_art,
    "cushion": build_cushion, "pendant": build_pendant, "plant": build_plant,
    "wall_units": build_wall_units, "appliance": build_appliance,
}


# ---------------------------------------------------------------- real assets

def import_asset(path, parent, w, d, h):
    ext = os.path.splitext(path)[1].lower()
    before = set(bpy.data.objects)
    if ext == ".blend":
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = list(src.objects)
        for o in dst.objects:
            if o is not None:
                parent.users_collection[0].objects.link(o)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    else:
        raise ValueError(f"unsupported asset {path}")
    new = [o for o in bpy.data.objects if o not in before and o.type in ("MESH", "EMPTY", "LIGHT")]
    roots = [o for o in new if o.parent is None or o.parent not in new]
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in new if o.type == "MESH" for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    dims = hi - lo
    s = w / dims.x if dims.x > 1e-6 else 1.0
    offset = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    for r in roots:
        r.location = (r.location - offset) * s
        r.scale = r.scale * s
        r.parent = parent
    warn = []
    for label, real, want in (("depth", dims.y * s, d), ("height", dims.z * s, h)):
        if want and abs(real - want) / want > 0.05:
            warn.append(f"{label} {real:.2f} m vs layout {want:.2f} m")
    return warn


# ---------------------------------------------------------------- entry point

def furnish(layout, clear_previous=True):
    if isinstance(layout, str):
        with open(layout, encoding="utf-8") as fh:
            layout = json.load(fh)
    col = bpy.data.collections.get("COL_Furniture_Proposed")
    if col is None:
        col = bpy.data.collections.new("COL_Furniture_Proposed")
        bpy.context.scene.collection.children.link(col)
    if clear_previous:
        for o in list(col.all_objects):
            bpy.data.objects.remove(o, do_unlink=True)
    _OVERRIDES.clear()
    _OVERRIDES.update(layout.get("palette", {}))       # style = colours per material, from the layout file
    report = {"placed": [], "asset_warnings": {}, "proxy": []}
    for it in layout["items"]:
        w, d, h = it["size"]
        root = bpy.data.objects.new(f"FUR_{it['id']}", None)
        col.objects.link(root)
        root.location = (*it["center"], it.get("elevation", 0.0))
        root.rotation_euler = (0, 0, math.radians(it.get("rotation_deg", 0.0)))
        root["type"] = it["type"]
        if it.get("material"):
            root["mat"] = it["material"]
        for key in ("sink_at", "hob_at", "oven", "hood_at"):   # appliance positions for kitchen builders
            if key in it:
                root[key] = it[key]
        if it.get("asset"):
            warn = import_asset(it["asset"], root, w, d, h)
            if warn:
                report["asset_warnings"][it["id"]] = warn
        else:
            BUILDERS.get(it["type"], lambda p, w, d, h: box(p, f"{p.name}_box", (w, d, h), (0, 0, h / 2), "MAT_Lacquer"))(root, w, d, h)
            report["proxy"].append(it["id"])
        report["placed"].append(it["id"])
    print("furnish:" + json.dumps(report))
    return report
