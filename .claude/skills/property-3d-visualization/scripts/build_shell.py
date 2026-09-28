"""Build a measured architectural shell in Blender from a property dossier JSON.

Runs two ways:
  * Headless:     blender -b -P build_shell.py -- dossier.json [--out scene.blend] [--clay-render DIR [--engine CYCLES|WORKBENCH]]
  * Blender MCP:  exec(open("<skill>/scripts/build_shell.py").read()); build("<project>/01_analysis/property_dossier.json")

Units are metres. Plan coordinates: +X right, +Y up on the floor-plan sheet, Z up.
Everything the script creates is named with a prefix (GEO_, CUT_, MAT_, CAM_, REF_) and placed in
COL_* collections so later design and lighting passes never touch the locked architecture by accident.

The shell is geometry only: walls with real openings, floors, ceilings, fixed elements (radiators,
outlets, columns...) and one camera per source photo. Materials are neutral clay placeholders
named MAT_<surface> so the look-dev pass can replace them one by one.
"""

import json
import math
import os
import sys

import bpy  # must precede bmesh when running as the standalone bpy module
import bmesh
from mathutils import Vector

CLAY = {
    "MAT_Wall": (0.80, 0.80, 0.80, 1.0),
    "MAT_Floor": (0.55, 0.55, 0.55, 1.0),
    "MAT_Ceiling": (0.85, 0.85, 0.85, 1.0),
    "MAT_Fixed": (0.65, 0.62, 0.60, 1.0),
    "MAT_Glass": (0.90, 0.95, 1.00, 1.0),
}


# ---------------------------------------------------------------- helpers

def _collection(name, parent=None):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(col)
    return col


def _material(name):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = CLAY.get(name, (0.7, 0.7, 0.7, 1.0))
        bsdf.inputs["Roughness"].default_value = 0.85
        if name == "MAT_Glass":
            bsdf.inputs["Roughness"].default_value = 0.0
            bsdf.inputs["IOR"].default_value = 1.52
            bsdf.inputs["Transmission Weight"].default_value = 1.0
    return mat


def _link(obj, col):
    for c in obj.users_collection:
        c.objects.unlink(obj)
    col.objects.link(obj)


def _box(name, size, location, rot_z, col, mat):
    """Axis-aligned box of size (length, thickness, height) centred on location, rotated about Z."""
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    col.objects.link(obj)
    obj.location = Vector(location)
    obj.rotation_euler = (0.0, 0.0, rot_z)
    if mat:
        obj.data.materials.append(mat)
    return obj


def _apply_boolean(target, cutter, operation):
    mod = target.modifiers.new(name=f"BOOL_{cutter.name}", type="BOOLEAN")
    mod.operation = operation
    mod.solver = "EXACT"
    mod.object = cutter
    with bpy.context.temp_override(object=target, active_object=target, selected_objects=[target]):
        bpy.ops.object.modifier_apply(modifier=mod.name)


def world_box_uv(obj):
    """Real-world-scale box-mapping UVs (1 UV unit = 1 m) so PBR textures keep true size."""
    mesh = obj.data
    uv = mesh.uv_layers.get("UVMap") or mesh.uv_layers.new(name="UVMap")
    mw = obj.matrix_world
    nmat = mw.to_3x3().inverted().transposed()
    for poly in mesh.polygons:
        n = (nmat @ poly.normal).normalized()
        ax = max(range(3), key=lambda i: abs(n[i]))
        for li in poly.loop_indices:
            co = mw @ mesh.vertices[mesh.loops[li].vertex_index].co
            if ax == 2:
                uv.data[li].uv = (co.x, co.y)
            elif ax == 0:
                uv.data[li].uv = (co.y, co.z)
            else:
                uv.data[li].uv = (co.x, co.z)


def _wall_frame(wall):
    a, b = Vector((*wall["a"], 0.0)), Vector((*wall["b"], 0.0))
    d = b - a
    length = d.length
    if length < 1e-6:
        raise ValueError(f"wall {wall['id']} has zero length")
    u = d / length                     # along the wall, a -> b
    left = Vector((-u.y, u.x, 0.0))    # left-hand normal when walking a -> b
    return a, u, left, length


def _wall_centerline_shift(wall):
    """'align' says which face the a->b line traces: center, left or right face of the wall."""
    t = wall["thickness"]
    return {"center": 0.0, "left": -t / 2.0, "right": t / 2.0}[wall.get("align", "center")]


def _polygon_object(name, pts, z, col, mat, flip=False):
    mesh = bpy.data.meshes.new(name)
    verts = [(x, y, z) for x, y in pts]
    face = list(range(len(verts)))
    if flip:
        face.reverse()
    mesh.from_pydata(verts, [], [face])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    col.objects.link(obj)
    obj.data.materials.append(mat)
    return obj


def _signed_area(pts):
    return 0.5 * sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))


# ---------------------------------------------------------------- builders

def build_walls(d, cols):
    levels = {lv["id"]: lv for lv in d["levels"]}
    walls_by_id, out = {}, []
    for w in d["walls"]:
        lv = levels[w.get("level", d["levels"][0]["id"])]
        h = w.get("height") or lv["ceiling_height"]
        a, u, left, length = _wall_frame(w)
        ext = w["thickness"] / 2.0 if w.get("extend_ends", True) else 0.0
        centre = a + u * (length / 2.0) + left * _wall_centerline_shift(w)
        centre.z = lv["elevation"] + h / 2.0
        obj = _box(f"GEO_Wall_{w['id']}", (length + 2 * ext, w["thickness"], h), centre,
                   math.atan2(u.y, u.x), cols["walls"], _material("MAT_Wall"))
        obj["evidence"] = w.get("evidence", "unknown")
        walls_by_id[w["id"]] = (w, obj, lv)
        out.append(obj)
    return walls_by_id, out


def cut_openings(d, walls_by_id, cols):
    glass = _material("MAT_Glass")
    for op in d.get("openings", []):
        w, wall_obj, lv = walls_by_id[op["wall"]]
        a, u, left, _ = _wall_frame(w)
        along = op["offset"] + op["width"] / 2.0
        centre = a + u * along + left * _wall_centerline_shift(w)
        sill, head = op.get("sill", 0.0), op["head"]
        centre.z = lv["elevation"] + (sill + head) / 2.0
        rot = math.atan2(u.y, u.x)
        cutter = _box(f"CUT_{op['id']}", (op["width"], w["thickness"] + 0.2, head - sill),
                      centre, rot, cols["cutters"], None)
        _apply_boolean(wall_obj, cutter, "DIFFERENCE")
        cutter.hide_render = True
        cutter.hide_set(True)
        if op["type"] == "window" or op.get("glazed"):     # glazed doors get glass too
            pane = _box(f"GEO_Glass_{op['id']}", (op["width"], 0.008, head - sill), centre, rot,
                        cols["openings"], glass)
            pane["evidence"] = op.get("evidence", "unknown")


def build_rooms(d, cols):
    levels = {lv["id"]: lv for lv in d["levels"]}
    for r in d.get("rooms", []):
        lv = levels[r.get("level", d["levels"][0]["id"])]
        pts = [tuple(p) for p in r["polygon"]]
        ccw = _signed_area(pts) > 0
        z0 = lv["elevation"]
        ch = r.get("ceiling_height") or lv["ceiling_height"]
        floor = _polygon_object(f"GEO_Floor_{r['id']}", pts, z0, cols["floors"],
                                _material("MAT_Floor"), flip=not ccw)
        ceil = _polygon_object(f"GEO_Ceiling_{r['id']}", pts, z0 + ch, cols["ceilings"],
                               _material("MAT_Ceiling"), flip=ccw)
        for o in (floor, ceil):
            o["room"] = r.get("name", r["id"])
            world_box_uv(o)


def build_fixed(d, walls_by_id, cols):
    mat = _material("MAT_Fixed")
    for f in d.get("fixed_elements", []):
        if "wall" in f:
            w, _, lv = walls_by_id[f["wall"]]
            a, u, left, _ = _wall_frame(w)
            side = 1.0 if f.get("side", "left") == "left" else -1.0
            face = _wall_centerline_shift(w) + side * w["thickness"] / 2.0
            centre = a + u * (f["offset"] + f["width"] / 2.0) + left * (face + side * f["depth"] / 2.0)
            rot = math.atan2(u.y, u.x)
        else:
            lv = next(l for l in d["levels"] if l["id"] == f.get("level", d["levels"][0]["id"]))
            centre = Vector((*f["position"], 0.0))
            rot = math.radians(f.get("rotation_deg", 0.0))
        centre.z = lv["elevation"] + f.get("elevation", 0.0) + f["height"] / 2.0
        obj = _box(f"GEO_{f['type'].title()}_{f['id']}", (f["width"], f["depth"], f["height"]),
                   centre, rot, cols["fixed"], mat)
        obj["evidence"] = f.get("evidence", "unknown")


def build_cameras(d, cols, base_dir):
    for c in d.get("cameras", []):
        cam_data = bpy.data.cameras.new(f"CAM_{c['id']}")
        cam_data.sensor_width = c.get("sensor_mm", 36.0)
        cam_data.sensor_fit = "AUTO"
        cam_data.lens = c["focal_mm_35eq"]
        cam_data.shift_x = c.get("shift_x", 0.0)
        cam_data.shift_y = c.get("shift_y", 0.0)
        cam_data.clip_start = 0.05
        cam = bpy.data.objects.new(f"CAM_{c['id']}", cam_data)
        cols["cameras"].objects.link(cam)
        cam.location = Vector(c["position"])
        direction = Vector(c["look_at"]) - cam.location
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        solved = c.get("blender")                     # exact values from solve_camera.py
        if solved:
            cam.location = Vector(solved["location"])
            cam.rotation_euler = [math.radians(a) for a in solved["rotation_euler_deg"]]
            cam_data.lens = solved["lens_mm"]
            cam_data.sensor_width = solved["sensor_width_mm"]
            cam_data.sensor_fit = solved["sensor_fit"]
            cam_data.shift_x = solved["shift_x"]
            cam_data.shift_y = solved["shift_y"]
            cam["solved_resolution"] = solved["resolution"]
        cam["photo"] = c.get("photo", "")
        cam["evidence"] = c.get("evidence", "estimated")
        photo = os.path.join(base_dir, c["photo"]) if c.get("photo") else None
        if photo and os.path.exists(photo):
            img = bpy.data.images.load(photo, check_existing=True)
            cam_data.show_background_images = True
            bg = cam_data.background_images.new()
            bg.image = img
            bg.alpha = 0.5
            cam["photo_px"] = list(img.size)


def build_plan_underlay(d, cols, base_dir):
    u = d.get("plan_underlay")
    if not u:
        return
    path = os.path.join(base_dir, u["image"])
    if not os.path.exists(path):
        print(f"shell:plan_underlay_missing {path}")
        return
    img = bpy.data.images.load(path, check_existing=True)
    w_px, h_px = img.size
    m_per_px = u["m_per_px"]
    empty = bpy.data.objects.new("REF_FloorPlan", None)
    empty.empty_display_type = "IMAGE"
    empty.data = img
    empty.empty_display_size = max(w_px, h_px) * m_per_px
    empty.empty_image_offset = (0.0, -1.0)      # anchor image top-left at the object origin
    ox, oy = u.get("origin_px", (0, 0))          # pixel of plan (0,0) measured from image top-left
    empty.location = (-ox * m_per_px, oy * m_per_px, -0.001)
    empty.color[3] = u.get("opacity", 0.5)
    empty.use_empty_image_alpha = True
    empty.hide_render = True
    cols["reference"].objects.link(empty)


def validate(d):
    """Cheap consistency gate: every opening fits inside its wall and below its ceiling."""
    problems = []
    walls = {w["id"]: w for w in d["walls"]}
    levels = {lv["id"]: lv for lv in d["levels"]}
    for op in d.get("openings", []):
        w = walls.get(op["wall"])
        if w is None:
            problems.append(f"{op['id']}: unknown wall {op['wall']}")
            continue
        length = (Vector(w["b"]) - Vector(w["a"])).length
        if op["offset"] < 0 or op["offset"] + op["width"] > length + 1e-6:
            problems.append(f"{op['id']}: spans {op['offset']:.2f}-{op['offset'] + op['width']:.2f} m "
                            f"on wall {w['id']} of length {length:.2f} m")
        ceiling = w.get("height") or levels[w.get("level", d["levels"][0]["id"])]["ceiling_height"]
        if op["head"] > ceiling + 1e-6:
            problems.append(f"{op['id']}: head {op['head']} m above wall height {ceiling} m")
        if op.get("sill", 0.0) >= op["head"]:
            problems.append(f"{op['id']}: sill >= head")
    return problems


# ---------------------------------------------------------------- entry points

def build(dossier, clear=False):
    """Build the shell. `dossier` is a path or an already-parsed dict. Returns a report dict."""
    base_dir = ""
    if isinstance(dossier, str):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(dossier)))  # project root
        with open(dossier, encoding="utf-8") as fh:
            dossier = json.load(fh)
    base_dir = dossier.get("project", {}).get("root", base_dir)

    problems = validate(dossier)
    if problems:
        raise ValueError("dossier failed validation:\n  " + "\n  ".join(problems))

    if clear:
        bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0

    root = _collection("COL_Architecture_LOCKED")
    cols = {
        "walls": _collection("COL_Walls", root),
        "openings": _collection("COL_Openings", root),
        "floors": _collection("COL_Floors", root),
        "ceilings": _collection("COL_Ceilings", root),
        "fixed": _collection("COL_Fixed_Elements", root),
        "cutters": _collection("COL_Cutters", root),
        "cameras": _collection("COL_Cameras"),
        "reference": _collection("COL_Reference"),
    }
    _collection("COL_Furniture_Existing")
    _collection("COL_Furniture_Proposed")
    _collection("COL_Lighting")

    walls_by_id, wall_objs = build_walls(dossier, cols)
    cut_openings(dossier, walls_by_id, cols)
    for o in wall_objs:
        world_box_uv(o)
    build_rooms(dossier, cols)
    build_fixed(dossier, walls_by_id, cols)
    build_cameras(dossier, cols, base_dir)
    build_plan_underlay(dossier, cols, base_dir)

    report = {
        "walls": len(dossier["walls"]),
        "openings": len(dossier.get("openings", [])),
        "rooms": len(dossier.get("rooms", [])),
        "fixed_elements": len(dossier.get("fixed_elements", [])),
        "cameras": [c["id"] for c in dossier.get("cameras", [])],
    }
    print("shell:built " + json.dumps(report))
    return report


def clay_render(out_dir, width=1600, engine="CYCLES", samples=24):
    """Geometry-check render from every CAM_ camera at the source photo's aspect ratio.

    A closed room lit only through its windows is too dark to judge geometry, so the clay pass
    lights the room evenly instead of realistically:
      * engine="CYCLES" (default, works CPU-only and on headless servers): bright world plus a soft
        area "headlamp" on each camera, removed afterwards.
      * engine="WORKBENCH": flat studio light with cavity and outlines; crisper edges, but needs an
        OpenGL/EGL context (a desktop Blender, or a GPU server with EGL installed).
    """
    scene = bpy.context.scene
    if engine.upper() == "WORKBENCH":
        scene.render.engine = "BLENDER_WORKBENCH"
        shading = scene.display.shading
        shading.light = "STUDIO"
        shading.color_type = "MATERIAL"
        shading.show_cavity = True
        shading.cavity_type = "BOTH"
        shading.show_object_outline = True
        scene.view_settings.view_transform = "Standard"
    else:
        scene.render.engine = "CYCLES"
        scene.cycles.samples = samples
        scene.cycles.use_denoising = True
        scene.view_settings.view_transform = "AgX"
        world = scene.world or bpy.data.worlds.new("World")
        scene.world = world
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs["Strength"].default_value = 3.0
    os.makedirs(out_dir, exist_ok=True)
    # Clay tones chosen for edges, not looks: floor / walls / ceiling must differ or white-on-white
    # corners vanish and the photo-match gate scores the lighting instead of the geometry. Glass is
    # hidden because its reflections add edges that do not exist in the photo.
    tones = {"MAT_Floor": 0.35, "MAT_Wall": 0.70, "MAT_Ceiling": 0.92}
    saved = {}
    for name, v in tones.items():
        m = bpy.data.materials.get(name)
        if m and m.use_nodes:
            bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if bsdf and not bsdf.inputs["Base Color"].is_linked:
                saved[name] = tuple(bsdf.inputs["Base Color"].default_value)
                bsdf.inputs["Base Color"].default_value = (v, v, v, 1.0)
    glass = [o for o in bpy.data.objects if o.name.startswith("GEO_Glass_") and not o.hide_render]
    for o in glass:
        o.hide_render = True
    for cam in [o for o in bpy.data.objects if o.type == "CAMERA" and o.name.startswith("CAM_")]:
        px = cam.get("photo_px")
        aspect = (px[0] / px[1]) if px else 1.5
        scene.render.resolution_x = width
        scene.render.resolution_y = int(round(width / aspect))
        scene.camera = cam
        lamp = None
        if scene.render.engine == "CYCLES":
            ld = bpy.data.lights.new("TMP_Headlamp", "AREA")
            ld.size, ld.energy = 1.5, 400.0
            lamp = bpy.data.objects.new("TMP_Headlamp", ld)
            scene.collection.objects.link(lamp)
            # matrix_world is stale until the depsgraph updates, so copy the local transform
            lamp.location = cam.location.copy()
            lamp.rotation_euler = cam.rotation_euler.copy()
        scene.render.filepath = os.path.join(out_dir, f"clay_{cam.name}.png")
        bpy.ops.render.render(write_still=True)
        if lamp:
            bpy.data.objects.remove(lamp)
            bpy.data.lights.remove(ld)
        print(f"shell:clay_render {scene.render.filepath}")
    for o in glass:
        o.hide_render = False
    for name, col in saved.items():
        bsdf = next(n for n in bpy.data.materials[name].node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        bsdf.inputs["Base Color"].default_value = col


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        print("usage: blender -b -P build_shell.py -- dossier.json [--out scene.blend] [--clay-render DIR]")
        sys.exit(1)
    build(argv[0], clear=True)
    if "--clay-render" in argv:
        engine = argv[argv.index("--engine") + 1] if "--engine" in argv else "CYCLES"
        clay_render(argv[argv.index("--clay-render") + 1], engine=engine)
    if "--out" in argv:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(argv[argv.index("--out") + 1]))
