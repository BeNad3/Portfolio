"""Check a proposed furniture layout against the real apartment before anything is rendered.

    python layout_check.py --dossier 01_analysis/property_dossier.json \
        --layout 03_design/layout_v1.json --out 03_design/layout_v1.png

Reads the locked architecture from the dossier (rooms, walls, openings, fixed elements) and a
layout JSON (see templates/layout.example.json), then checks:

  * every item sits inside a room and items do not collide (rugs excepted);
  * door swings are clear;
  * each item's functional clearance zone (in front of a sofa, around a bed, behind dining
    chairs, in front of a wardrobe...) is free;
  * radiators keep a free zone in front, windows are not blocked by tall furniture;
  * lamps, TV, desk are within cable reach (1.5 m) of a socket recorded in the dossier;
  * the TV sits at a sensible distance for its size ("screen_in", default 55) and the main seat faces it;
  * the widest walking route between every pair of doors, and its narrowest point.

Writes a dimensioned top view (the drawing the client approves) and prints a JSON report.
Exit code 0 = no errors (warnings allowed), 2 = errors. Pure Python + Pillow, no Blender needed.
The grid is 2.5 cm; overlaps under ~0.01 m² are ignored as drawing noise.
"""

import argparse
import heapq
import json
import math
import sys

from PIL import Image, ImageDraw

CELL = 0.025          # m
MIN_OVERLAP = 16      # cells (= 0.01 m²)

# type -> clearance zones: (side, depth_m, allowed types inside, severity)
# side: front (+Y local), back, left, right, all
ZONES = {
    "sofa":         [("front", 0.40, {"rug"}, "error")],
    "armchair":     [("front", 0.40, {"rug"}, "error")],
    "bed":          [("left", 0.60, {"rug", "bedside_table"}, "error"),
                     ("right", 0.60, {"rug", "bedside_table"}, "error"),
                     ("front", 0.70, {"rug", "bench"}, "error")],
    "dining_table": [("all", 0.75, {"rug", "chair"}, "error")],
    "desk":         [("front", 0.90, {"rug", "chair"}, "error")],
    "wardrobe":     [("front", 0.90, {"rug"}, "error")],
    "sideboard":    [("front", 0.60, {"rug"}, "warning")],
    "bookcase":     [("front", 0.60, {"rug"}, "warning")],
    "tv_unit":      [("front", 0.60, {"rug", "coffee_table"}, "warning")],
    "kitchen_run":  [("front", 1.00, {"rug"}, "error")],
}
NON_BLOCKING = {"rug", "ceiling_light", "wall_art", "curtain"}
POWERED = {"tv_unit", "floor_lamp", "bedside_table", "desk", "table_lamp"}   # override per item: "powered": true/false
CABLE_REACH = 1.5     # m from the item's footprint to a socket before an extension lead or new socket is needed
SEATING = {"sofa", "armchair"}
TALL = 1.0            # m: taller items must not stand in front of windows


# ---------------------------------------------------------------- geometry

def rect_corners(cx, cy, w, d, rot_deg):
    r = math.radians(rot_deg)
    c, s = math.cos(r), math.sin(r)
    pts = []
    for lx, ly in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)):
        pts.append((cx + lx * c - ly * s, cy + lx * s + ly * c))
    return pts


def point_in_poly(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


class Grid:
    def __init__(self, xmin, ymin, xmax, ymax):
        self.x0, self.y0 = xmin, ymin
        self.nx = int(math.ceil((xmax - xmin) / CELL)) + 1
        self.ny = int(math.ceil((ymax - ymin) / CELL)) + 1

    def centre(self, i, j):
        return self.x0 + (i + 0.5) * CELL, self.y0 + (j + 0.5) * CELL

    def cells(self, poly=None, test=None, bbox=None):
        """Cells whose centre is inside `poly` or satisfies `test(x, y)` within `bbox`."""
        if poly is not None:
            xs, ys = [p[0] for p in poly], [p[1] for p in poly]
            bbox = (min(xs), min(ys), max(xs), max(ys))
            test = lambda x, y: point_in_poly(x, y, poly)  # noqa: E731
        i0 = max(0, int((bbox[0] - self.x0) / CELL) - 1)
        i1 = min(self.nx - 1, int((bbox[2] - self.x0) / CELL) + 1)
        j0 = max(0, int((bbox[1] - self.y0) / CELL) - 1)
        j1 = min(self.ny - 1, int((bbox[3] - self.y0) / CELL) + 1)
        out = set()
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                if test(*self.centre(i, j)):
                    out.add((i, j))
        return out


def wall_frame(w):
    ax, ay = w["a"]
    bx, by = w["b"]
    L = math.hypot(bx - ax, by - ay)
    u = ((bx - ax) / L, (by - ay) / L)
    left = (-u[1], u[0])
    shift = {"center": 0.0, "left": -w["thickness"] / 2, "right": w["thickness"] / 2}[w.get("align", "center")]
    return (ax + left[0] * shift, ay + left[1] * shift), u, left, L


def zone_rect(item, side, depth):
    """Clearance zone polygon on one side of an item (item front = local +Y)."""
    w, d = item["size"][0], item["size"][1]
    cx, cy = item["center"]
    r = math.radians(item.get("rotation_deg", 0.0))
    c, s = math.cos(r), math.sin(r)
    loc = {
        "front": (0, d / 2 + depth / 2, w, depth),
        "back": (0, -d / 2 - depth / 2, w, depth),
        "left": (-w / 2 - depth / 2, 0, depth, d),
        "right": (w / 2 + depth / 2, 0, depth, d),
    }[side]
    lx, ly, zw, zd = loc
    return rect_corners(cx + lx * c - ly * s, cy + lx * s + ly * c, zw, zd, item.get("rotation_deg", 0.0))


# ---------------------------------------------------------------- checks

def run(dossier, layout):
    rooms = {r["id"]: r for r in dossier["rooms"]}
    walls = {w["id"]: w for w in dossier["walls"]}
    xs = [p[0] for w in dossier["walls"] for p in (w["a"], w["b"])]
    ys = [p[1] for w in dossier["walls"] for p in (w["a"], w["b"])]
    g = Grid(min(xs) - 0.5, min(ys) - 0.5, max(xs) + 0.5, max(ys) + 0.5)
    issues = []

    def issue(sev, item, msg):
        issues.append({"severity": sev, "item": item, "message": msg})

    floor = {rid: g.cells(poly=[tuple(p) for p in r["polygon"]]) for rid, r in rooms.items()}
    all_floor = set().union(*floor.values())

    # door openings: walkable cells through the wall, swing sectors, route endpoints
    door_cells, swings, endpoints = set(), [], []
    for op in dossier.get("openings", []):
        if op["type"] not in ("door", "opening"):
            continue
        w = walls[op["wall"]]
        (ax, ay), u, left, _ = wall_frame(w)
        t = w["thickness"]
        s0, s1 = op["offset"], op["offset"] + op["width"]
        mid = (s0 + s1) / 2
        cx, cy = ax + u[0] * mid, ay + u[1] * mid
        door_cells |= g.cells(poly=rect_corners(cx, cy, op["width"], t + 0.1,
                                                math.degrees(math.atan2(u[1], u[0]))))
        for sgn in (1, -1):
            px = cx + left[0] * sgn * (t / 2 + 0.35)
            py = cy + left[1] * sgn * (t / 2 + 0.35)
            c = (int((px - g.x0) / CELL), int((py - g.y0) / CELL))
            room_here = next((rid for rid, f in floor.items() if c in f), None)
            if room_here:
                endpoints.append((op["id"], room_here, (px, py)))
        if op["type"] == "door":
            if "swing_side" not in op or "hinge" not in op:
                issue("warning", op["id"], "door swing unknown in dossier (swing_side/hinge): swing not checked")
                continue
            sgn = 1 if op["swing_side"] == "left" else -1
            hs = s0 if op["hinge"] == "a" else s1
            hx = ax + u[0] * hs + left[0] * sgn * t / 2
            hy = ay + u[1] * hs + left[1] * sgn * t / 2
            closed = u if op["hinge"] == "a" else (-u[0], -u[1])
            opened = (left[0] * sgn, left[1] * sgn)
            R = op["width"]

            def in_sector(x, y, hx=hx, hy=hy, closed=closed, opened=opened, R=R):
                dx, dy = x - hx, y - hy
                return (dx * dx + dy * dy <= R * R and dx * closed[0] + dy * closed[1] >= 0
                        and dx * opened[0] + dy * opened[1] >= 0)
            cells = g.cells(test=in_sector, bbox=(hx - R, hy - R, hx + R, hy + R))
            swings.append((op["id"], cells, (hx, hy, R, closed, opened)))

    # items
    items = layout["items"]
    item_cells = {}
    for it in items:
        poly = rect_corners(*it["center"], it["size"][0], it["size"][1], it.get("rotation_deg", 0.0))
        cells = g.cells(poly=poly)
        item_cells[it["id"]] = cells
        room = rooms.get(it.get("room"))
        if room is None:
            issue("error", it["id"], f"unknown room {it.get('room')}")
        outside = len(cells - floor.get(it.get("room"), set()))
        if outside > MIN_OVERLAP:
            issue("error", it["id"], f"extends outside room {it.get('room')} by ~{outside * CELL * CELL:.2f} m²")

    blocking = [it for it in items if it["type"] not in NON_BLOCKING]
    for i, a in enumerate(blocking):
        for b in blocking[i + 1:]:
            n = len(item_cells[a["id"]] & item_cells[b["id"]])
            if n > MIN_OVERLAP and b["id"] not in a.get("allow_overlap", []) and a["id"] not in b.get("allow_overlap", []):
                issue("error", a["id"], f"collides with {b['id']} (~{n * CELL * CELL:.2f} m²)")

    for did, cells, _ in swings:
        for it in blocking:
            n = len(cells & item_cells[it["id"]])
            if n > MIN_OVERLAP:
                issue("error", it["id"], f"blocks the swing of door {did}")

    zones_drawn = []
    by_id = {it["id"]: it for it in items}
    for it in items:
        for side, depth, allowed, sev in ZONES.get(it["type"], []):
            sides = ("front", "back", "left", "right") if side == "all" else (side,)
            for sd in sides:
                zpoly = zone_rect(it, sd, depth)
                zones_drawn.append(zpoly)
                zc = g.cells(poly=zpoly)
                if len(zc - all_floor - door_cells) > MIN_OVERLAP * 4:
                    issue(sev, it["id"], f"{sd} clearance {depth:.2f} m runs into a wall")
                for other in blocking:
                    if other is it or other["type"] in allowed:
                        continue
                    if len(zc & item_cells[other["id"]]) > MIN_OVERLAP:
                        issue(sev, it["id"], f"{other['id']} ({other['type']}) inside its {sd} clearance of {depth:.2f} m")

    # radiators and windows
    for fe in dossier.get("fixed_elements", []):
        if fe["type"] != "radiator" or "wall" not in fe:
            continue
        w = walls[fe["wall"]]
        (ax, ay), u, left, _ = wall_frame(w)
        sgn = 1 if fe.get("side", "left") == "left" else -1
        mid = fe["offset"] + fe["width"] / 2
        for depth, tall_only, sev in ((0.15, False, "warning"), (0.50, True, "error")):
            off = w["thickness"] / 2 + fe["depth"] + depth / 2
            zc = g.cells(poly=rect_corners(ax + u[0] * mid + left[0] * sgn * off, ay + u[1] * mid + left[1] * sgn * off,
                                           fe["width"], depth, math.degrees(math.atan2(u[1], u[0]))))
            for it in blocking:
                if tall_only and it["size"][2] <= TALL:
                    continue
                if len(zc & item_cells[it["id"]]) > MIN_OVERLAP:
                    what = "tall item in front of" if tall_only else f"within {depth:.2f} m of"
                    issue(sev, it["id"], f"{what} radiator {fe['id']}")
    for op in dossier.get("openings", []):
        if op["type"] != "window":
            continue
        w = walls[op["wall"]]
        (ax, ay), u, left, _ = wall_frame(w)
        mid = op["offset"] + op["width"] / 2
        for sgn in (1, -1):
            off = w["thickness"] / 2 + 0.15
            zc = g.cells(poly=rect_corners(ax + u[0] * mid + left[0] * sgn * off, ay + u[1] * mid + left[1] * sgn * off,
                                           op["width"], 0.30, math.degrees(math.atan2(u[1], u[0]))))
            for it in blocking:
                if it["size"][2] > max(TALL, op.get("sill", 0.9)) and len(zc & item_cells[it["id"]]) > MIN_OVERLAP:
                    issue("error", it["id"], f"tall item blocks window {op['id']}")

    # sockets: powered items within cable reach of a real socket (from the dossier)
    sockets = []
    for fe in dossier.get("fixed_elements", []):
        if fe["type"] in ("outlet", "socket") and "wall" in fe:
            w = walls[fe["wall"]]
            (ax, ay), u, left, _ = wall_frame(w)
            sgn = 1 if fe.get("side", "left") == "left" else -1
            mid = fe["offset"] + fe["width"] / 2
            off = w["thickness"] / 2
            sockets.append((fe["id"], (ax + u[0] * mid + left[0] * sgn * off, ay + u[1] * mid + left[1] * sgn * off)))
    powered = [it for it in items if it.get("powered", it["type"] in POWERED)]
    if powered and not sockets:
        issue("warning", "sockets", "no sockets recorded in the dossier: socket reach not checked")
    for it in powered if sockets else []:
        dist, sid = min((footprint_distance(it, p), sid) for sid, p in sockets)
        if dist > CABLE_REACH:
            issue("warning", it["id"], f"nearest socket {sid} is {dist:.1f} m away (> {CABLE_REACH} m): "
                                       "extension lead, relocate, or propose a new socket as electrical work")

    # TV viewing distance and orientation from the seating in the same room
    for tv in [it for it in items if it["type"] == "tv_unit"]:
        diag = tv.get("screen_in", 55) * 0.0254
        seats = [it for it in items if it["type"] in SEATING and it.get("room") == tv.get("room")]
        if not seats:
            continue
        seat = max(seats, key=lambda it: it["size"][0])                 # main seat = widest
        dx, dy = tv["center"][0] - seat["center"][0], tv["center"][1] - seat["center"][1]
        dist = math.hypot(dx, dy)
        lo, hi = 1.0 * diag, 2.5 * diag
        if not lo <= dist <= hi:
            issue("warning", tv["id"], f"{seat['id']} to TV {dist:.2f} m for a {tv.get('screen_in', 55)}\" screen "
                                       f"(comfortable {1.2 * diag:.1f}-{1.6 * diag:.1f} m, acceptable {lo:.1f}-{hi:.1f} m)")
        r = math.radians(seat.get("rotation_deg", 0.0))
        front = (-math.sin(r), math.cos(r))
        cos_a = (front[0] * dx + front[1] * dy) / max(dist, 1e-6)
        if cos_a < math.cos(math.radians(35)):
            issue("warning", tv["id"], f"{seat['id']} does not face the TV ({math.degrees(math.acos(max(-1, min(1, cos_a)))):.0f} deg off axis)")

    # circulation: widest route between door endpoints
    walk = (all_floor | door_cells)
    obstacle_cells = set().union(*(item_cells[it["id"]] for it in blocking)) if blocking else set()
    walk -= obstacle_cells
    dist = clearance_field(g, walk)
    near_door = set()
    for op in dossier.get("openings", []):
        if op["type"] in ("door", "opening"):
            w = walls[op["wall"]]
            (ax, ay), u, _, _ = wall_frame(w)
            mid = op["offset"] + op["width"] / 2
            cx, cy = ax + u[0] * mid, ay + u[1] * mid
            rr = op["width"] / 2 + w["thickness"] / 2 + 0.15
            near_door |= g.cells(test=lambda x, y, cx=cx, cy=cy, rr=rr: (x - cx) ** 2 + (y - cy) ** 2 <= rr * rr,
                                 bbox=(cx - rr, cy - rr, cx + rr, cy + rr))
    routes = []
    for i in range(len(endpoints)):
        for j in range(i + 1, len(endpoints)):
            (da, ra, pa), (db, rb, pb) = endpoints[i], endpoints[j]
            if da == db:
                continue
            name = f"{da}({ra})->{db}({rb})"
            res = widest_path(g, walk, dist, near_door, pa, pb)
            if res is None:
                issue("error", name, "no walkable route (blocked by furniture)")
                continue
            width, path, pinch = res
            sev = "error" if width < 0.80 else ("warning" if width < 0.90 else None)
            routes.append({"route": name, "min_clear_width_m": round(width, 2), "pinch": pinch, "path": path})
            if sev:
                issue(sev, name, f"route narrows to {width:.2f} m (target 0.90, minimum 0.80) near {pinch}")

    return g, issues, routes, item_cells, swings, zones_drawn


def footprint_distance(item, p):
    """Distance from point p to the item's rectangular footprint (0 if inside)."""
    r = math.radians(item.get("rotation_deg", 0.0))
    dx, dy = p[0] - item["center"][0], p[1] - item["center"][1]
    lx = dx * math.cos(r) + dy * math.sin(r)
    ly = -dx * math.sin(r) + dy * math.cos(r)
    ex = max(abs(lx) - item["size"][0] / 2, 0.0)
    ey = max(abs(ly) - item["size"][1] / 2, 0.0)
    return math.hypot(ex, ey)


def clearance_field(g, walk):
    """Distance (m) from each walkable cell to the nearest non-walkable cell (8-neighbour chamfer)."""
    INF = float("inf")
    dist = {c: INF for c in walk}
    heap = []
    steps = [(1, 0, 1), (-1, 0, 1), (0, 1, 1), (0, -1, 1), (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]
    for (i, j) in walk:
        for di, dj, _ in steps[:4]:
            if (i + di, j + dj) not in walk:
                dist[(i, j)] = 0.5 * CELL
                heapq.heappush(heap, (dist[(i, j)], i, j))
                break
    while heap:
        dcur, i, j = heapq.heappop(heap)
        if dcur > dist[(i, j)]:
            continue
        for di, dj, w in steps:
            n = (i + di, j + dj)
            if n in dist and dcur + w * CELL < dist[n]:
                dist[n] = dcur + w * CELL
                heapq.heappush(heap, (dist[n], *n))
    return dist


def widest_path(g, walk, dist, ignore, pa, pb):
    """Maximise the minimum clearance along the route (door throats ignored for the bottleneck)."""
    def cell(p):
        return int((p[0] - g.x0) / CELL), int((p[1] - g.y0) / CELL)
    s, t = cell(pa), cell(pb)
    if s not in walk or t not in walk:
        return None
    best = {s: float("inf")}
    prev = {}
    heap = [(-float("inf"), s)]
    while heap:
        nb, c = heapq.heappop(heap)
        nb = -nb
        if c == t:
            break
        if nb < best.get(c, -1):
            continue
        i, j = c
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            n = (i + di, j + dj)
            if n not in walk:
                continue
            b = nb if n in ignore else min(nb, dist[n])
            if b > best.get(n, -1):
                best[n] = b
                prev[n] = c
                heapq.heappush(heap, (-b, n))
    if t not in best:
        return None
    bottleneck = best[t]
    # second pass: the shortest route that keeps that bottleneck (the maximin route alone wanders)
    ok = lambda c: c in ignore or dist[c] >= bottleneck - 1e-9  # noqa: E731
    cost, prev = {s: 0.0}, {}
    heap = [(0.0, s)]
    while heap:
        d0, c = heapq.heappop(heap)
        if c == t:
            break
        if d0 > cost[c]:
            continue
        i, j = c
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            n = (i + di, j + dj)
            if n not in walk or not ok(n):
                continue
            nd = d0 + math.hypot(di, dj)
            if nd < cost.get(n, float("inf")):
                cost[n] = nd
                prev[n] = c
                heapq.heappush(heap, (nd, n))
    path, c = [t], t
    while c != s:
        c = prev[c]
        path.append(c)
    path.reverse()
    width = 2 * bottleneck
    pinch_cell = min((c for c in path if c not in ignore), key=lambda c: dist[c], default=path[0])
    px, py = g.centre(*pinch_cell)
    return width, [g.centre(*c) for c in path[::4]], [round(px, 2), round(py, 2)]


# ---------------------------------------------------------------- drawing

def draw(dossier, layout, g, issues, routes, item_cells, swings, zones, out, px_per_m=100):
    W, H = int(g.nx * CELL * px_per_m), int(g.ny * CELL * px_per_m)
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    def P(x, y):
        return ((x - g.x0) * px_per_m, H - (y - g.y0) * px_per_m)

    for r in dossier["rooms"]:
        d.polygon([P(*p) for p in r["polygon"]], fill=(246, 244, 240))
    for z in zones:
        d.polygon([P(*p) for p in z], outline=(150, 190, 230))
    for w in dossier["walls"]:
        (ax, ay), u, left, L = wall_frame(w)
        t = w["thickness"]
        ext = t / 2 if w.get("extend_ends", True) else 0
        poly = rect_corners(ax + u[0] * L / 2, ay + u[1] * L / 2, L + 2 * ext, t, math.degrees(math.atan2(u[1], u[0])))
        d.polygon([P(*p) for p in poly], fill=(60, 60, 60))
    for op in dossier.get("openings", []):
        w = next(x for x in dossier["walls"] if x["id"] == op["wall"])
        (ax, ay), u, _, _ = wall_frame(w)
        mid = op["offset"] + op["width"] / 2
        poly = rect_corners(ax + u[0] * mid, ay + u[1] * mid, op["width"], w["thickness"] + 0.01,
                            math.degrees(math.atan2(u[1], u[0])))
        d.polygon([P(*p) for p in poly], fill=(160, 200, 240) if op["type"] == "window" else (255, 255, 255))
    for _, _, (hx, hy, R, closed, opened) in swings:
        pts = [P(hx, hy)]
        a0, a1 = math.atan2(closed[1], closed[0]), math.atan2(opened[1], opened[0])
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        for k in range(17):
            a = a0 + da * k / 16
            pts.append(P(hx + R * math.cos(a), hy + R * math.sin(a)))
        d.line(pts + [P(hx, hy)], fill=(120, 120, 120), width=2)
    for fe in dossier.get("fixed_elements", []):
        if fe["type"] == "radiator" and "wall" in fe:
            w = next(x for x in dossier["walls"] if x["id"] == fe["wall"])
            (ax, ay), u, left, _ = wall_frame(w)
            sgn = 1 if fe.get("side", "left") == "left" else -1
            mid = fe["offset"] + fe["width"] / 2
            off = w["thickness"] / 2 + fe["depth"] / 2
            poly = rect_corners(ax + u[0] * mid + left[0] * sgn * off, ay + u[1] * mid + left[1] * sgn * off,
                                fe["width"], fe["depth"], math.degrees(math.atan2(u[1], u[0])))
            d.polygon([P(*p) for p in poly], fill=(230, 120, 60))
    bad = {i["item"] for i in issues if i["severity"] == "error"}
    for it in sorted(layout["items"], key=lambda i: i["type"] != "rug"):
        poly = rect_corners(*it["center"], it["size"][0], it["size"][1], it.get("rotation_deg", 0.0))
        fill = (235, 225, 205) if it["type"] == "rug" else ((240, 150, 150) if it["id"] in bad else (205, 215, 200))
        d.polygon([P(*p) for p in poly], fill=fill, outline=(40, 40, 40))
        fx, fy = zone_rect(it, "front", 0.0)[0], zone_rect(it, "front", 0.0)[1]
        d.line([P(*fx), P(*fy)], fill=(40, 40, 40), width=3)       # front edge marker
        cx, cy = P(*it["center"])
        d.text((cx - 20, cy - 6), it["id"], fill=(0, 0, 0))
    for r in routes:
        col = (200, 40, 40) if r["min_clear_width_m"] < 0.8 else ((220, 150, 0) if r["min_clear_width_m"] < 0.9 else (40, 150, 70))
        d.line([P(*p) for p in r["path"]], fill=col, width=2)
        px, py = P(*r["pinch"])
        d.ellipse([px - 5, py - 5, px + 5, py + 5], outline=col, width=2)
        d.text((px + 7, py - 7), f"{r['min_clear_width_m']:.2f} m", fill=col)
    img.save(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dossier", required=True)
    ap.add_argument("--layout", required=True)
    ap.add_argument("--out", help="top-view PNG")
    args = ap.parse_args(argv)
    dossier = json.load(open(args.dossier, encoding="utf-8"))
    layout = json.load(open(args.layout, encoding="utf-8"))
    g, issues, routes, item_cells, swings, zones = run(dossier, layout)
    if args.out:
        draw(dossier, layout, g, issues, routes, item_cells, swings, zones, args.out)
    report = {
        "errors": sum(i["severity"] == "error" for i in issues),
        "warnings": sum(i["severity"] == "warning" for i in issues),
        "issues": issues,
        "routes": [{k: v for k, v in r.items() if k != "path"} for r in routes],
        "drawing": args.out,
    }
    print(json.dumps(report, indent=2))
    return 2 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
