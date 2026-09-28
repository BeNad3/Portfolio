"""Solve the camera of a real photo against the reconstructed room (automatic photo-match).

    python solve_camera.py --dossier 01_analysis/property_dossier.json --camera P1 \
        --mask 0.77,0.83,1,1 --out 02_blender/qa/solve_P1.png [--free-ceiling] [--write]

Projects the room's structural edges (floor and ceiling lines, wall corners, door/window frames on
the walls of the room the camera stands in) through a pinhole camera and minimises their distance to
the edges found in the photo. Solves position, heading, pitch, roll, horizontal field of view and
principal-point offset (real-estate photos are usually vertical-corrected, i.e. shifted, not tilted),
starting from the dossier's camera estimate. `--free-ceiling` also solves the ceiling height: when
several photos agree, it turns an inferred ceiling height into a photo-derived one.

  * Photo borders: black letterbox bars (screenshots) are detected and ignored; `--mask x0,y0,x1,y1`
    (0-1, repeatable) hides watermarks or furniture.
  * Output: JSON (camera in plan coordinates + Blender lens/shift/rotation, residual in px, share of
    model edges within 3 px of a photo edge) and a sheet with the solved edges drawn over the photo.
  * `--write` stores the solved camera in the dossier (evidence "solved"). Run build_shell.py again and
    confirm with photo_match_overlay.py on a clay render: the solver is a tool, the render is the gate.

Assumes a rectilinear (lens-corrected) photo. Strongly distorted fisheye/phone ultra-wide images must be
undistorted first. Needs numpy, scipy, Pillow.
"""

import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from scipy import ndimage, optimize

CAP = 25.0            # px: residual cap (edges further than this count as "missing")


# ---------------------------------------------------------------- photo side

def content_box(img):
    """Crop letterbox bars: rows/columns that are almost uniformly black."""
    a = np.asarray(img.convert("L"), dtype=np.float32)
    rows = np.where(a.mean(axis=1) > 12)[0]
    cols = np.where(a.mean(axis=0) > 12)[0]
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def edge_distance(img, masks, keep_frac=0.10):
    grey = ImageOps.autocontrast(img.convert("L").filter(ImageFilter.GaussianBlur(1.5)))
    g = np.asarray(grey, dtype=np.float32)
    gx = ndimage.sobel(g, axis=1)
    gy = ndimage.sobel(g, axis=0)
    mag = np.hypot(gx, gy)
    h, w = mag.shape
    valid = np.ones_like(mag, dtype=bool)
    b = 3
    valid[:b, :] = valid[-b:, :] = valid[:, :b] = valid[:, -b:] = False
    for x0, y0, x1, y1 in masks:
        valid[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)] = False
    thr = np.quantile(mag[valid], 1 - keep_frac)
    edges = (mag >= thr) & valid
    # thin to local maxima along the gradient so thick soft edges do not dominate
    dist = ndimage.distance_transform_edt(~edges)
    return dist, valid, edges


# ---------------------------------------------------------------- model side

def _wall_frame(w):
    (ax, ay), (bx, by) = w["a"], w["b"]
    L = math.hypot(bx - ax, by - ay)
    u = np.array([(bx - ax) / L, (by - ay) / L])
    left = np.array([-u[1], u[0]])
    shift = {"center": 0.0, "left": -w["thickness"] / 2, "right": w["thickness"] / 2}[w.get("align", "center")]
    return np.array([ax, ay]) + left * shift, u, left, L


def _in_poly(p, poly):
    x, y = p
    inside = False
    for i in range(len(poly)):
        (x0, y0), (x1, y1) = poly[i - 1], poly[i]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


def _dist_to_seg(p, a, b):
    ab = b - a
    t = np.clip(np.dot(p - a, ab) / max(np.dot(ab, ab), 1e-12), 0, 1)
    return np.linalg.norm(p - (a + t * ab))


def model_segments(d, room, H):
    """3D line segments (pairs of points) the photo should show from inside `room`."""
    poly = [tuple(p) for p in room["polygon"]]
    segs = []
    for i in range(len(poly)):
        a, b = np.array(poly[i - 1]), np.array(poly[i])
        mid = (a + b) / 2
        on_wall = any(_dist_to_seg(mid, *(lambda f: (f[0], f[0] + f[1] * f[3]))(_wall_frame(w)))
                      <= w["thickness"] / 2 + 0.04 for w in d["walls"])
        segs.append(((a[0], a[1], 0.0), (b[0], b[1], 0.0)))            # floor line (or floor finish change)
        if on_wall:
            segs.append(((a[0], a[1], H), (b[0], b[1], H)))            # ceiling line only along real walls
    for (x, y) in poly:
        segs.append(((x, y, 0.0), (x, y, H)))                          # corners / wall ends
    walls = {w["id"]: w for w in d["walls"]}
    for op in d.get("openings", []):
        w = walls[op["wall"]]
        a, u, left, _ = _wall_frame(w)
        mid = a + u * (op["offset"] + op["width"] / 2)
        for sgn in (1, -1):
            face = mid + left * sgn * (w["thickness"] / 2)
            if not _in_poly(face + left * sgn * 0.05, poly):
                continue
            p0 = a + u * op["offset"] + left * sgn * (w["thickness"] / 2)
            p1 = p0 + u * op["width"]
            s, hd = op.get("sill", 0.0), min(op["head"], H)
            segs += [((*p0, s), (*p0, hd)), ((*p1, s), (*p1, hd)), ((*p0, hd), (*p1, hd))]
            if s > 0.03:
                segs.append(((*p0, s), (*p1, s)))
    return np.array(segs, dtype=np.float64)


# ---------------------------------------------------------------- camera

def basis(yaw, pitch, roll):
    """yaw: heading CCW from plan +X; pitch: up positive; roll: clockwise positive."""
    f = np.array([math.cos(yaw) * math.cos(pitch), math.sin(yaw) * math.cos(pitch), math.sin(pitch)])
    r = np.cross(f, [0.0, 0.0, 1.0])
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    c, s = math.cos(roll), math.sin(roll)
    return f, r * c - u * s, r * s + u * c


def project(params, pts, size):
    x, y, z, yaw, pitch, roll, hfov, dx, dy = params[:9]
    w, h = size
    f, r, u = basis(yaw, pitch, roll)
    v = pts - np.array([x, y, z])
    depth = v @ f
    fpx = (w / 2) / math.tan(hfov / 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        px = w / 2 + dx + fpx * (v @ r) / depth
        py = h / 2 + dy - fpx * (v @ u) / depth
    return px, py, depth


def sample_segments(segs, n=40):
    t = np.linspace(0, 1, n)[None, :, None]
    return (segs[:, None, 0, :] * (1 - t) + segs[:, None, 1, :] * t).reshape(-1, 3)


def cost(params, pts, dist, valid, edges_yx, size, room_poly):
    """Symmetric chamfer: model edges -> nearest photo edge AND photo edges -> nearest model edge.
    One-sided costs are degenerate: the solver would aim the camera where few model edges are visible."""
    px, py, depth = project(params, pts, size)
    w, h = size
    ok = (depth > 0.05) & (px >= 0) & (px < w - 1) & (py >= 0) & (py < h - 1)
    ix, iy = px[ok].astype(int), py[ok].astype(int)
    vis = valid[iy, ix]
    if vis.sum() < 100:
        return 1e3
    r = np.minimum(dist[iy[vis], ix[vis]], CAP)
    m2p = np.mean(np.sqrt(r * r + 4.0) - 2.0)
    model = np.zeros((h, w), dtype=bool)
    model[iy, ix] = True
    dmodel = ndimage.distance_transform_edt(~model)
    q = np.minimum(dmodel[edges_yx[0], edges_yx[1]], CAP)
    p2m = np.mean(np.sqrt(q * q + 4.0) - 2.0)
    c = m2p + p2m
    if not _in_poly((params[0], params[1]), room_poly):   # the camera stands inside the room
        c += 50
    return c


# ---------------------------------------------------------------- main

def solve(d, cam, photo_path, masks, free_ceiling, work_width=480):
    img = ImageOps.exif_transpose(Image.open(photo_path)).convert("RGB")
    box = content_box(img)
    img = img.crop(box)
    size = img.size
    k = work_width / size[0]                                  # solve on a downscaled copy (fast EDTs)
    small = img.resize((work_width, round(size[1] * k)), Image.LANCZOS)
    ssize = small.size
    dist, valid, edges = edge_distance(small, masks)
    eyx = np.nonzero(edges)
    lv = d["levels"][0]
    H0 = lv["ceiling_height"]
    pos = np.array(cam["position"], float)
    room = next(r for r in d["rooms"] if _in_poly(pos[:2], [tuple(p) for p in r["polygon"]]))
    poly = [tuple(p) for p in room["polygon"]]
    look = np.array(cam["look_at"], float) - pos
    yaw0 = math.atan2(look[1], look[0])
    hfov0 = 2 * math.atan(36 / (2 * cam.get("focal_mm_35eq", 20)))

    def f_of(H):
        pts = sample_segments(model_segments(d, room, H), 120)
        return lambda p: cost(p, pts, dist, valid, eyx, ssize, poly)

    best = None
    f0 = f_of(H0)
    for dyaw in (0.0, -0.3, 0.3):
        for hf in (hfov0, math.radians(75), math.radians(95)):
            x0 = np.array([pos[0], pos[1], pos[2], yaw0 + dyaw, 0.0, 0.0, hf, 0.0, 0.0])
            res = optimize.minimize(f0, x0, method="Powell", options={"maxiter": 4000, "xtol": 1e-4, "ftol": 1e-5})
            if best is None or res.fun < best.fun:
                best = res
    params, H = best.x, H0
    if free_ceiling:
        def fH(p):
            if not 2.2 <= p[9] <= 3.3:
                return 1e3
            return f_of(p[9])(p[:9])
        r2 = optimize.minimize(fH, np.append(params, H0), method="Powell",
                               options={"maxiter": 6000, "xtol": 1e-4, "ftol": 1e-5})
        params, H = r2.x[:9], float(r2.x[9])

    # refine at double resolution: sharper edges break the dolly/zoom ambiguity of the coarse pass
    k2 = min(1.0, 2 * k)
    big = img.resize((round(size[0] * k2), round(size[1] * k2)), Image.LANCZOS)
    bdist, bvalid, bedges = edge_distance(big, masks)
    beyx = np.nonzero(bedges)
    pts_b = sample_segments(model_segments(d, room, H), 240)
    p_b = params.copy()
    p_b[7:9] *= k2 / k
    fb = lambda p: cost(p, pts_b, bdist, bvalid, beyx, big.size, poly)  # noqa: E731
    p_b = optimize.minimize(fb, p_b, method="Powell", options={"maxiter": 3000, "xtol": 1e-5, "ftol": 1e-6}).x

    # quality at full resolution
    params = p_b.copy()
    params[7:9] /= k2
    fdist, fvalid, _ = edge_distance(img, masks)
    segs = model_segments(d, room, H)
    pts = sample_segments(segs, 200)
    px, py, depth = project(params, pts, size)
    ok = (depth > 0.05) & (px >= 0) & (px < size[0] - 1) & (py >= 0) & (py < size[1] - 1)
    ix, iy = px[ok].astype(int), py[ok].astype(int)
    vis = fvalid[iy, ix]
    r = fdist[iy[vis], ix[vis]]
    return img, box, size, params, H, segs, {
        "median_px": round(float(np.median(r)), 2),
        "within_3px": round(float(np.mean(r <= 3)), 3),
        "visible_model_share": round(float(vis.sum()) / len(pts), 3),
        "room": room["id"],
    }


def to_blender(params, size):
    x, y, z, yaw, pitch, roll, hfov, dx, dy = params
    w, h = size
    f, r, u = basis(yaw, pitch, roll)
    m = np.column_stack([r, u, -f])                       # Blender camera: X right, Y up, looks -Z
    # rotation matrix -> XYZ Euler
    sy = -m[2, 0]
    ry = math.asin(max(-1, min(1, sy)))
    rx = math.atan2(m[2, 1], m[2, 2])
    rz = math.atan2(m[1, 0], m[0, 0])
    lens = 36 / (2 * math.tan(hfov / 2))
    big = max(w, h)
    return {"location": [round(x, 4), round(y, 4), round(z, 4)],
            "rotation_euler_deg": [round(math.degrees(v), 3) for v in (rx, ry, rz)],
            "lens_mm": round(lens, 3), "sensor_width_mm": 36.0, "sensor_fit": "HORIZONTAL",
            "shift_x": round(-dx / big, 5), "shift_y": round(dy / big, 5),
            "resolution": [w, h]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dossier", required=True)
    ap.add_argument("--camera", required=True)
    ap.add_argument("--mask", action="append", default=[], help="x0,y0,x1,y1 in 0-1 of the cropped photo")
    ap.add_argument("--free-ceiling", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--write", action="store_true", help="store the solved camera in the dossier")
    args = ap.parse_args(argv)

    dpath = os.path.abspath(args.dossier)
    d = json.load(open(dpath, encoding="utf-8"))
    root = d.get("project", {}).get("root", os.path.dirname(os.path.dirname(dpath)))
    cam = next(c for c in d["cameras"] if c["id"] == args.camera)
    masks = [tuple(float(v) for v in m.split(",")) for m in args.mask]
    img, box, size, params, H, segs, q = solve(d, cam, os.path.join(root, cam["photo"]), masks, args.free_ceiling)
    x, y, z, yaw, pitch, roll, hfov, dx, dy = params
    out = {
        "camera": args.camera,
        "position": [round(float(x), 3), round(float(y), 3), round(float(z), 3)],
        "heading_deg": round(math.degrees(yaw), 2), "pitch_deg": round(math.degrees(pitch), 2),
        "roll_deg": round(math.degrees(roll), 2), "hfov_deg": round(math.degrees(hfov), 2),
        "focal_mm_35eq": round(36 / (2 * math.tan(hfov / 2)), 2),
        "principal_offset_px": [round(float(dx), 1), round(float(dy), 1)],
        "ceiling_height": round(H, 3), "ceiling_solved": args.free_ceiling,
        "photo_crop_box": list(box), "quality": q, "blender": to_blender(params, size),
        "verdict": "good" if q["median_px"] <= 3.0 and q["within_3px"] >= 0.6 and q["visible_model_share"] >= 0.25 else "check",
    }
    if args.out:
        sheet = img.copy()
        dr = ImageDraw.Draw(sheet)
        for s in segs:
            p = sample_segments(s[None], 60)
            px, py, dep = project(params, p, size)
            pts = [(a, b) for a, b, c in zip(px, py, dep) if c > 0.05 and -2000 < a < 4000 and -2000 < b < 4000]
            if len(pts) > 1:
                dr.line(pts, fill=(255, 30, 30), width=2)
        for m in masks:
            dr.rectangle([m[0] * size[0], m[1] * size[1], m[2] * size[0], m[3] * size[1]], outline=(255, 200, 0), width=2)
        sheet.save(args.out)
        out["sheet"] = args.out
    if args.write:
        cam.update({"position": out["position"], "heading_deg": out["heading_deg"], "pitch_deg": out["pitch_deg"],
                    "roll_deg": out["roll_deg"], "focal_mm_35eq": out["focal_mm_35eq"],
                    "blender": out["blender"],
                    "evidence": f"solved from photo edges: median {q['median_px']} px, {q['within_3px'] * 100:.0f}% within 3 px"})
        f, _, _ = basis(yaw, pitch, roll)
        cam["look_at"] = [round(float(v), 3) for v in np.array([x, y, z]) + f * 3.0]
        json.dump(d, open(dpath, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2))
    return 0 if out["verdict"] == "good" else 2


if __name__ == "__main__":
    sys.exit(main())
