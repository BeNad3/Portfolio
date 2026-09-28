"""Architectural details the photos show and the plan does not: window/door frames and skirting.

    exec(open("<skill>/scripts/materials.py").read())
    exec(open("<skill>/scripts/add_details.py").read())
    add_details("<project>/01_analysis/property_dossier.json")

Reads the same dossier as build_shell.py.
  * Frames: every window and glazed door gets a frame (default 7 x 7 cm profile, white) in the middle
    of the wall. Optional per opening: "transom": height of a horizontal bar (m above floor),
    "mullions": list of positions along the opening (m from its start) for vertical bars,
    "mullion_above_transom": true to stop mullions at the transom (casements over fixed glazing).
    A glazed door with "leaf_width" gets a mullion between the leaf and the fixed sidelight.
  * Skirting: along every room edge that lies on a wall, interrupted at doors and floor-level openings.
    Per room in the dossier: "skirting": {"height": 0.05, "material": "MAT_Skirting_Oak"} or false.
Everything goes to COL_Details (locked architecture, not furniture).
"""

import json
import math

import bpy
import bmesh
from mathutils import Vector


def _col(name="COL_Details"):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        parent = bpy.data.collections.get("COL_Architecture_LOCKED") or bpy.context.scene.collection
        parent.children.link(col)
    return col


def _box(name, size, loc, rot_z, mat):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    _col().objects.link(o)
    o.location = loc
    o.rotation_euler = (0, 0, rot_z)
    o.data.materials.append(mat)
    mod = o.modifiers.new("Bevel", "BEVEL")
    mod.width = 0.002
    mod.segments = 2
    return o


def _frame_of(w):
    a, b = Vector((*w["a"], 0)), Vector((*w["b"], 0))
    L = (b - a).length
    u = (b - a) / L
    left = Vector((-u.y, u.x, 0))
    shift = {"center": 0.0, "left": -w["thickness"] / 2, "right": w["thickness"] / 2}[w.get("align", "center")]
    return a + left * shift, u, left, L


def _get_mat(name, factory):
    return bpy.data.materials.get(name) or factory()


def add_frames(d, profile=0.07, depth=0.07, mat=None):
    g = globals()
    mat = mat or _get_mat("MAT_Frame_White", lambda: g["solid"]("MAT_Frame_White", (0.88, 0.88, 0.86), roughness=0.3))
    walls = {w["id"]: w for w in d["walls"]}
    z0 = d["levels"][0]["elevation"]
    made = 0
    for op in d.get("openings", []):
        if not (op["type"] == "window" or op.get("glazed")):
            continue
        a, u, left, _ = _frame_of(walls[op["wall"]])
        rot = math.atan2(u.y, u.x)
        s0, W = op["offset"], op["width"]
        sill, head = op.get("sill", 0.0), op["head"]
        H = head - sill

        def piece(tag, along, zc, w, h):
            nonlocal made
            p = a + u * along
            _box(f"DET_Frame_{op['id']}_{tag}", (w, depth, h), Vector((p.x, p.y, z0 + zc)), rot, mat)
            made += 1
        piece("L", s0 + profile / 2, sill + H / 2, profile, H)
        piece("R", s0 + W - profile / 2, sill + H / 2, profile, H)
        piece("T", s0 + W / 2, head - profile / 2, W, profile)
        piece("B", s0 + W / 2, sill + profile / 2, W, profile)
        if op.get("transom"):
            piece("TR", s0 + W / 2, op["transom"], W, profile)
        mullions = list(op.get("mullions", []))
        if op.get("leaf_width"):
            mullions.append(op["leaf_width"] if op.get("hinge", "a") == "a" else W - op["leaf_width"])
        for i, m in enumerate(mullions):
            lo = op["transom"] if op.get("mullion_above_transom") and op.get("transom") else sill
            piece(f"M{i}", s0 + m, (lo + head) / 2, profile, head - lo)
    return made


def _on_wall(p, q, walls):
    mid = (p + q) / 2
    for w in walls:
        a, u, left, L = _frame_of(w)
        t = max(0.0, min(L, (mid - a).dot(u)))
        if ((a + u * t) - mid).length <= w["thickness"] / 2 + 0.04:
            return w
    return None


def add_skirting(d, height=0.05, thick=0.012):
    g = globals()
    walls = d["walls"]
    by_id = {w["id"]: w for w in walls}
    z0 = d["levels"][0]["elevation"]
    made = 0
    for r in d.get("rooms", []):
        spec = r.get("skirting", {})
        if spec is False:
            continue
        h = spec.get("height", height)
        mat = _get_mat(spec.get("material", "MAT_Skirting_Oak"),
                       lambda: g["solid"](spec.get("material", "MAT_Skirting_Oak"), (0.62, 0.48, 0.34), roughness=0.4, coat=0.2))
        poly = [Vector((*p, 0)) for p in r["polygon"]]
        cw = sum((q.x - p.x) * (q.y + p.y) for p, q in zip(poly, poly[1:] + poly[:1])) > 0
        for i in range(len(poly)):
            p, q = poly[i - 1], poly[i]
            w = _on_wall(p, q, walls)
            if w is None:
                continue
            e = q - p
            L = e.length
            ue = e / L
            inward = Vector((-ue.y, ue.x, 0)) * (-1 if cw else 1)
            # intervals along this edge taken by doors / floor-level openings in that wall
            cuts = []
            for op in d.get("openings", []):
                if op["wall"] != w["id"] or op.get("sill", 0.0) > 0.05:
                    continue
                a, u, _, _ = _frame_of(by_id[op["wall"]])
                t0 = ((a + u * op["offset"]) - p).dot(ue)
                t1 = ((a + u * (op["offset"] + op["width"])) - p).dot(ue)
                cuts.append((min(t0, t1), max(t0, t1)))
            segs, cur = [], 0.0
            for c0, c1 in sorted(cuts):
                if c1 <= 0 or c0 >= L:
                    continue
                if c0 > cur:
                    segs.append((cur, c0))
                cur = max(cur, c1)
            if cur < L:
                segs.append((cur, L))
            for j, (t0, t1) in enumerate(segs):
                if t1 - t0 < 0.03:
                    continue
                c = p + ue * ((t0 + t1) / 2) + inward * (thick / 2)
                _box(f"DET_Skirting_{r['id']}_{i}_{j}", (t1 - t0, thick, h), Vector((c.x, c.y, z0 + h / 2)),
                     math.atan2(ue.y, ue.x), mat)
                made += 1
    return made


def add_details(dossier):
    if isinstance(dossier, str):
        with open(dossier, encoding="utf-8") as fh:
            dossier = json.load(fh)
    if "solid" not in globals():
        raise RuntimeError("exec materials.py before add_details.py")
    n_f = add_frames(dossier)
    n_s = add_skirting(dossier)
    print(f"details: {n_f} frame pieces, {n_s} skirting pieces")
    return n_f, n_s
