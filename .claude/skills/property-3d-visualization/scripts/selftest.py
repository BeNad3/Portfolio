"""Regression test for every script in this skill, on the bundled example apartment.

    python selftest.py            # needs Pillow + numpy; Blender tests also need `bpy`
                                  # (pip install bpy on Python 3.11, or: blender -b -P selftest.py)

Checks behaviour, not just "it runs": good inputs pass, broken inputs are rejected, measurements
recover known values. Run it after editing any script. Exit code 0 = all passed.
"""

import json
import math
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
DOSSIER = os.path.join(SKILL, "templates", "property_dossier.example.json")
LAYOUT = os.path.join(SKILL, "templates", "layout.example.json")
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def tool(script, *args):
    """Run a CLI script with this interpreter; return (exit code, parsed JSON or text)."""
    p = subprocess.run([sys.executable, os.path.join(HERE, script), *args], capture_output=True, text=True)
    out = p.stdout
    try:
        out = json.loads(out[out.index("{"):])
    except ValueError:
        pass
    return p.returncode, out


def test_layout(tmp):
    code, rep = tool("layout_check.py", "--dossier", DOSSIER, "--layout", LAYOUT, "--out", os.path.join(tmp, "l.png"))
    check("layout: example layout has no errors", code == 0 and rep["errors"] == 0, f"{rep['warnings']} warnings")
    check("layout: bedside sockets flagged", sum("socket" in i["message"] for i in rep["issues"]) == 2)
    check("layout: route width measured", rep["routes"] and all(r["min_clear_width_m"] >= 0.9 for r in rep["routes"]))
    bad = json.load(open(LAYOUT))
    items = {i["id"]: i for i in bad["items"]}
    items["CTABLE"]["center"] = [1.30, 2.0]
    items["ARM1"]["center"] = [1.45, 3.60]
    bad["items"].append({"id": "BOOK", "type": "bookcase", "room": "R1", "center": [2.3, 0.3],
                         "size": [1.0, 0.35, 2.0], "rotation_deg": 0})
    path = os.path.join(tmp, "bad.json")
    json.dump(bad, open(path, "w"))
    code, rep = tool("layout_check.py", "--dossier", DOSSIER, "--layout", path)
    msgs = " | ".join(i["message"] for i in rep["issues"])
    check("layout: broken layout rejected", code == 2)
    for needle in ("front clearance", "swing of door D1", "blocks window WIN1", "no walkable route"):
        check(f"layout: detects '{needle}'", needle in msgs)


def test_image_tools(tmp):
    import numpy as np
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (900, 600), (200, 196, 190))
    d = ImageDraw.Draw(img)
    d.polygon([(0, 450), (900, 420), (900, 600), (0, 600)], fill=(150, 110, 80))
    d.rectangle([150, 120, 420, 380], fill=(235, 240, 250))
    d.line([(600, 0), (600, 430)], fill=(170, 166, 160), width=3)
    a = os.path.join(tmp, "a.png")
    img.save(a)
    shifted = os.path.join(tmp, "b.png")
    img.transform(img.size, Image.AFFINE, (1, 0, -40, 0, 1, -25)).save(shifted)

    code, rep = tool("photo_match_overlay.py", "--photo", a, "--render", a, "--out", os.path.join(tmp, "m1.png"))
    check("overlay: identical images pass", rep["verdict"] == "pass", f"edge_match {rep['edge_match']}")
    code, rep = tool("photo_match_overlay.py", "--photo", a, "--render", shifted, "--out", os.path.join(tmp, "m2.png"))
    check("overlay: misaligned camera fails", rep["verdict"] == "fail", f"edge_match {rep['edge_match']}")

    lin = (np.asarray(img, float) / 255) ** 2.2 * 0.5 * np.array([1.06, 1.0, 0.94])
    Image.fromarray((np.clip(lin, 0, 1) ** (1 / 2.2) * 255 + 0.5).astype("uint8")).save(shifted)
    region = ["--region", "0.70,0.05,0.95,0.60"]
    code, rep = tool("look_match.py", "--photo", a, "--render", a, *region)
    check("look: identical images match", rep["verdict"] == "match")
    code, rep = tool("look_match.py", "--photo", a, "--render", shifted, *region)
    check("look: darker render -> about +1 stop", abs(rep["exposure_stops"] - 1.0) < 0.1, f"{rep['exposure_stops']}")
    check("look: warmer render -> lower white balance", "LOWER" in rep["white_balance_advice"])

    code, _ = tool("finish.py", "--src", a, "--out", os.path.join(tmp, "f.jpg"))
    f = np.asarray(Image.open(os.path.join(tmp, "f.jpg")), float)
    o = np.asarray(img, float)
    centre = np.abs(f[250:350, 400:500] - o[250:350, 400:500]).mean()
    corner = f[:40, :40].mean() - o[:40, :40].mean()
    check("finish: subtle in the centre, vignetted corners", code == 0 and centre < 6 and corner < -3,
          f"centre diff {centre:.1f}, corner {corner:+.1f}")


def test_blender(tmp):
    try:
        import bpy
        from mathutils import Vector
    except ImportError:
        print("SKIP  Blender tests (no bpy in this interpreter)")
        return
    ns = {}
    exec(open(os.path.join(HERE, "build_shell.py")).read().split("if __name__")[0], ns)
    dossier = json.load(open(DOSSIER))
    broken = json.loads(json.dumps(dossier))
    broken["openings"][0]["offset"] = 7.5
    try:
        ns["build"](broken, clear=True)
        check("shell: impossible opening rejected", False)
    except ValueError:
        check("shell: impossible opening rejected", True)
    rep = ns["build"](dossier, clear=True)
    check("shell: builds example", rep["walls"] == 5 and rep["openings"] == 4)
    wall = bpy.data.objects["GEO_Wall_W1"]
    dims = wall.dimensions
    check("shell: wall W1 is 8.60 x 0.20 x 2.50 m", abs(dims.x - 8.6) < 1e-3 and abs(dims.y - 0.2) < 1e-3 and abs(dims.z - 2.5) < 1e-3)
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    hit = bpy.context.scene.ray_cast(deps, Vector((2.3, 2.0, 1.5)), Vector((0, -1, 0)))
    check("shell: window WIN1 is a real opening", hit[4] is not None and hit[4].name.startswith("GEO_Glass"))
    hit = bpy.context.scene.ray_cast(deps, Vector((2.3, 2.0, 0.5)), Vector((0, -1, 0)))
    check("shell: wall below the sill is solid", hit[4] is not None and hit[4].name in ("GEO_Wall_W1", "GEO_Radiator_RAD1"))

    exec(open(os.path.join(HERE, "materials.py")).read(), ns)
    ns["default_shell_look"]()
    exec(open(os.path.join(HERE, "furnish.py")).read(), ns)
    frep = ns["furnish"](LAYOUT)
    layout = json.load(open(LAYOUT))
    check("furnish: every layout item placed", len(frep["placed"]) == len(layout["items"]))
    bpy.context.view_layer.update()
    sofa = bpy.data.objects["FUR_SOFA"]
    pts = [o.matrix_world @ Vector(c) for o in sofa.children for c in o.bound_box]
    ext = [max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3)]
    check("furnish: sofa footprint matches layout (0.95 x 2.20 m, rotated)",
          abs(ext[0] - 0.95) < 0.05 and abs(ext[1] - 2.20) < 0.05, f"{ext[0]:.2f} x {ext[1]:.2f}")

    exec(open(os.path.join(HERE, "photoreal_setup.py")).read().split("if __name__")[0], ns)
    az, el = ns["solar_position"](48.85, 2.35, "2026-06-21T12:00")
    check("light: Paris solstice noon sun ~64.6 deg high, due south", abs(el - 64.6) < 0.5 and abs(az - 184) < 3,
          f"az {az:.1f} el {el:.1f}")
    ns["setup_daylight"](48.85, 2.35, "2026-03-20T13:30", north_deg=0)
    ns["add_window_portals"]()
    ns["orient_portals_inward"]()
    bpy.context.view_layer.update()
    inward = all((o.matrix_world.to_3x3() @ Vector((0, 0, -1))).y > 0.9
                 for o in bpy.data.objects if o.name.startswith("LGT_Portal_"))
    check("light: window portals face into the rooms", inward)
    ns["realestate_camera"]("CAM_P1", fstop=8.0, height=1.35)
    cam = bpy.data.objects["CAM_P1"]
    bpy.context.view_layer.update()
    up = cam.matrix_world.to_3x3() @ Vector((0, 1, 0))
    fwd = cam.matrix_world.to_3x3() @ Vector((0, 0, -1))
    check("camera: level (verticals stay vertical), same heading", up.z > 0.9999 and fwd.x < -0.7 and fwd.y < -0.5,
          f"up.z {up.z:.5f}, shift_y {cam.data.shift_y:.3f}")
    ns["render_preset"]("preview", width=240, exposure=0.8, white_balance_k=6800)
    s = bpy.context.scene
    s.cycles.samples = 4
    s.render.filepath = os.path.join(tmp, "tiny.png")
    bpy.ops.render.render(write_still=True)
    check("render: furnished scene renders", os.path.exists(s.render.filepath))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        test_layout(tmp)
        test_image_tools(tmp)
        test_blender(tmp)
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed" + (f"; FAILED: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
