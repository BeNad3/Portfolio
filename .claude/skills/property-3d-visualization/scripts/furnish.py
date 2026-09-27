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

def _mat(name):
    """Named furniture materials; built once with the factories from materials.py."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    g = globals()
    if "fabric" not in g:
        raise RuntimeError("exec materials.py before furnish.py")
    palette = {
        "MAT_Sofa": lambda: g["fabric"](name, (0.42, 0.40, 0.36), sheen=0.6),
        "MAT_Armchair": lambda: g["fabric"](name, (0.30, 0.34, 0.30), sheen=0.6),
        "MAT_Rug": lambda: g["fabric"](name, (0.72, 0.68, 0.60), sheen=0.3, roughness=0.95, weave_scale=150),
        "MAT_Linen": lambda: g["fabric"](name, (0.82, 0.80, 0.76), sheen=0.3),
        "MAT_Shade": lambda: g["fabric"](name, (0.90, 0.87, 0.80), sheen=0.2),
        "MAT_Oak": lambda: g["solid"](name, (0.46, 0.32, 0.20), roughness=0.45, coat=0.2),
        "MAT_Lacquer": lambda: g["solid"](name, (0.80, 0.79, 0.76), roughness=0.3, coat=0.3),
        "MAT_Metal_Black": lambda: g["solid"](name, (0.03, 0.03, 0.03), roughness=0.35, metallic=1.0),
        "MAT_Brass": lambda: g["brushed_metal"](name, (0.80, 0.62, 0.35), roughness=0.3),
        "MAT_Screen": lambda: g["solid"](name, (0.01, 0.01, 0.012), roughness=0.08),
        "MAT_Books": lambda: g["solid"](name, (0.45, 0.40, 0.35), roughness=0.6),
    }
    return palette.get(name, lambda: g["solid"](name, (0.6, 0.6, 0.6)))()


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


def _jitter(o, rot=0.03, scale=0.02):
    """Small imperfections: nothing in a lived-in room is perfectly aligned."""
    o.rotation_euler = [a + _RNG.uniform(-rot, rot) for a in o.rotation_euler]
    o.scale = [s * (1 + _RNG.uniform(-scale, scale)) for s in o.scale]


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
        c = box(p, f"{p.name}_seat{i}", (cw - 0.01, d - back_t - 0.02, 0.14), (x, back_t / 2, leg + 0.18 + 0.07), mat, 0.05)
        _jitter(c, 0.01, 0.01)
        b = box(p, f"{p.name}_backcush{i}", (cw - 0.02, 0.16, 0.40), (x, -d / 2 + back_t + 0.07, leg + 0.18 + 0.14 + 0.19),
                mat, 0.06, rot=(math.radians(-12), 0, 0))
        _jitter(b, 0.03, 0.02)


def build_coffee_table(p, w, d, h, round_top=False):
    top = 0.03
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
    frame_h = max(0.25, h - 0.22)
    box(p, f"{p.name}_frame", (w + 0.06, d + 0.04, frame_h), (0, 0, frame_h / 2), "MAT_Oak", 0.01)
    box(p, f"{p.name}_mattress", (w, d - 0.04, 0.22), (0, 0.0, frame_h + 0.11), "MAT_Linen", 0.05)
    box(p, f"{p.name}_head", (w + 0.1, 0.08, 1.05), (0, -d / 2 - 0.02, 0.525), "MAT_Armchair", 0.03)
    duvet = box(p, f"{p.name}_duvet", (w + 0.08, d * 0.72, 0.07), (0, d * 0.14, frame_h + 0.22 + 0.03), "MAT_Linen", 0.035)
    _jitter(duvet, 0.005, 0.01)
    fold = box(p, f"{p.name}_fold", (w + 0.08, 0.22, 0.08), (0, -d * 0.22 + 0.11, frame_h + 0.22 + 0.05), "MAT_Linen", 0.04)
    _jitter(fold, 0.01, 0.01)
    for sx in (-1, 1):
        pl = box(p, f"{p.name}_pillow", (w / 2 - 0.1, 0.45, 0.14), (sx * w / 4, -d / 2 + 0.3, frame_h + 0.22 + 0.08),
                 "MAT_Linen", 0.06, rot=(math.radians(-18), 0, 0))
        _jitter(pl, 0.04, 0.03)


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


BUILDERS = {
    "sofa": build_sofa, "armchair": build_armchair, "coffee_table": build_coffee_table, "rug": build_rug,
    "tv_unit": build_tv_unit, "floor_lamp": build_floor_lamp, "bed": build_bed,
    "bedside_table": build_bedside_table, "wardrobe": build_wardrobe, "bookcase": build_bookcase,
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
    report = {"placed": [], "asset_warnings": {}, "proxy": []}
    for it in layout["items"]:
        w, d, h = it["size"]
        root = bpy.data.objects.new(f"FUR_{it['id']}", None)
        col.objects.link(root)
        root.location = (*it["center"], it.get("elevation", 0.0))
        root.rotation_euler = (0, 0, math.radians(it.get("rotation_deg", 0.0)))
        root["type"] = it["type"]
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
