"""Physically grounded lighting, camera and render setup for a reconstructed property.

Use after build_shell.py (same Blender session, or open the .blend):

    exec(open("<skill>/scripts/photoreal_setup.py").read())
    setup_daylight(lat=48.85, lon=2.35, when_utc="2026-06-21T13:00", north_deg=0)   # sky texture
    # or: setup_daylight(..., hdri="/path/to/polyhaven_4k.exr")                     # Poly Haven HDRI
    add_window_portals()
    realestate_camera("CAM_P1", fstop=8.0)
    render_preset("final")      # "preview" | "final"

Headless: blender -b project.blend -P photoreal_setup.py -- --lat 48.85 --lon 2.35 \
          --when 2026-06-21T13:00 --north 0 --camera CAM_P1 --preset preview --render out.png

Conventions follow build_shell.py: plan +Y is "up" on the sheet, `north_deg` is the clockwise angle
from plan-up to true north (0 when the north arrow points straight up).
"""

import math
import os
import sys
from datetime import datetime, timezone

import bpy
from mathutils import Euler, Vector


# ---------------------------------------------------------------- sun position

def solar_position(lat, lon, when_utc):
    """Solar azimuth (deg, clockwise from true north) and elevation (deg) — NOAA approximation,
    accurate to well under a degree, which is plenty for placing shadows."""
    if isinstance(when_utc, str):
        when_utc = datetime.fromisoformat(when_utc)
    if when_utc.tzinfo is None:
        when_utc = when_utc.replace(tzinfo=timezone.utc)
    t = when_utc.astimezone(timezone.utc)
    doy = t.timetuple().tm_yday
    hour = t.hour + t.minute / 60.0 + t.second / 3600.0
    g = 2.0 * math.pi / 365.0 * (doy - 1 + (hour - 12.0) / 24.0)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    tst = hour * 60.0 + eqtime + 4.0 * lon          # true solar time, minutes
    ha = math.radians(tst / 4.0 - 180.0)            # hour angle
    la = math.radians(lat)
    cos_zen = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    zen = math.acos(max(-1.0, min(1.0, cos_zen)))
    az = math.degrees(math.atan2(math.sin(ha),
                                 math.cos(ha) * math.sin(la) - math.tan(decl) * math.cos(la))) + 180.0
    return az % 360.0, 90.0 - math.degrees(zen)


def _sun_direction_plan(azimuth_deg, elevation_deg, north_deg):
    """Unit vector pointing FROM the scene TOWARDS the sun, in plan coordinates."""
    plan_az = math.radians(azimuth_deg + north_deg)   # clockwise from plan +Y
    el = math.radians(elevation_deg)
    return Vector((math.sin(plan_az) * math.cos(el), math.cos(plan_az) * math.cos(el), math.sin(el)))


# ---------------------------------------------------------------- daylight

def setup_daylight(lat, lon, when_utc, north_deg=0.0, hdri=None, hdri_strength=1.0,
                   hdri_sun_azimuth_deg=None, sun_strength=None, sun_angle_deg=0.53):
    """Sun lamp at the real solar position + sky (Nishita) or an HDRI world.

    With an HDRI, pass `hdri_sun_azimuth_deg` = the azimuth of the sun in the HDRI's equirect
    (Poly Haven previews show it; 0 = image centre). The world is rotated so the HDRI sun lines up
    with the computed sun, keeping sky light and sun shadows consistent.
    """
    scene = bpy.context.scene
    az, el = solar_position(lat, lon, when_utc)
    to_sun = _sun_direction_plan(az, el, north_deg)

    col = bpy.data.collections.get("COL_Lighting") or bpy.data.collections.new("COL_Lighting")
    if col.name not in scene.collection.children:
        scene.collection.children.link(col)
    sun = bpy.data.objects.get("LGT_Sun")
    if sun is None:
        sun = bpy.data.objects.new("LGT_Sun", bpy.data.lights.new("LGT_Sun", "SUN"))
        col.objects.link(sun)
    sun.rotation_euler = (-to_sun).to_track_quat("-Z", "Y").to_euler()
    sun.data.angle = math.radians(sun_angle_deg)
    # Clear-sky sun ~ 1000 W/m² → Blender strength ≈ 3–5 with AgX; weaker when low
    sun.data.energy = sun_strength if sun_strength is not None else max(0.0, 4.0 * math.sin(math.radians(max(el, 0))) ** 0.6)
    sun.hide_render = el <= 0

    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_WORLD":
            nt.nodes.remove(n)
    out = next(n for n in nt.nodes if n.type == "OUTPUT_WORLD")
    bg = nt.nodes.new("ShaderNodeBackground")
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    if hdri:
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(hdri, check_existing=True)
        mapping = nt.nodes.new("ShaderNodeMapping")
        coord = nt.nodes.new("ShaderNodeTexCoord")
        nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
        if hdri_sun_azimuth_deg is not None:
            # equirect azimuth runs counter-clockwise seen from above; plan azimuth clockwise
            target = math.degrees(math.atan2(to_sun.y, to_sun.x))
            mapping.inputs["Rotation"].default_value[2] = math.radians(target - hdri_sun_azimuth_deg)
        bg.inputs["Strength"].default_value = hdri_strength
    else:
        sky = nt.nodes.new("ShaderNodeTexSky")
        for attr, val in (("sky_type", "NISHITA"), ("sky_type", "MULTIPLE_SCATTERING")):
            try:
                setattr(sky, attr, val)
                break
            except TypeError:
                continue
        if hasattr(sky, "sun_disc"):
            sky.sun_disc = False               # the sun lamp provides the direct light
        if hasattr(sky, "sun_elevation"):
            sky.sun_elevation = math.radians(max(el, 0.0))
            sky.sun_rotation = math.atan2(to_sun.x, to_sun.y)
        nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 0.3 * hdri_strength
    print(f"light:sun azimuth={az:.1f} elevation={el:.1f} (plan north {north_deg})")
    return az, el


def fix_window_glass():
    """Let direct sun and sky through window panes.

    With refractive caustics off (the sane default), Cycles blocks direct light behind a
    transmissive pane: no sun patches on the floor, a dark, blue room. Panes stay visible to the
    camera and in reflections but stop casting shadows."""
    panes = [o for o in bpy.data.objects if o.name.startswith("GEO_Glass_")]
    for o in panes:
        o.visible_shadow = False
    return [o.name for o in panes]


def add_window_portals(padding=0.02):
    """Cycles light portals in every window opening so sky light enters without noise.
    Also applies fix_window_glass()."""
    fix_window_glass()
    made = []
    for glass in [o for o in bpy.data.objects if o.name.startswith("GEO_Glass_")]:
        name = glass.name.replace("GEO_Glass_", "LGT_Portal_")
        if bpy.data.objects.get(name):
            continue
        w, _, h = glass.dimensions
        ld = bpy.data.lights.new(name, "AREA")
        ld.shape = "RECTANGLE"
        ld.size, ld.size_y = w + padding, h + padding
        if hasattr(ld, "cycles"):
            ld.cycles.is_portal = True
        obj = bpy.data.objects.new(name, ld)
        bpy.data.collections["COL_Lighting"].objects.link(obj)
        # area lights emit along -Z; the portal must face INTO the room (glass local +Y or -Y).
        obj.matrix_world = glass.matrix_world @ Euler((math.radians(90), 0, 0)).to_matrix().to_4x4()
        obj.scale = (1, 1, 1)
        made.append(obj.name)
    print(f"light:portals {made}")
    return made


def orient_portals_inward(room_point=None):
    """Flip any portal whose emission (-Z) points away from the room it lights.

    Without `room_point`, each portal aims at the centre of the nearest GEO_Floor_* room."""
    bpy.context.view_layer.update()
    floors = []
    for f in [o for o in bpy.data.objects if o.name.startswith("GEO_Floor_")]:
        pts = [f.matrix_world @ v.co for v in f.data.vertices]
        floors.append(sum(pts, Vector()) / len(pts) + Vector((0, 0, 1.2)))
    for o in [o for o in bpy.data.objects if o.name.startswith("LGT_Portal_")]:
        pos = o.matrix_world.translation
        target = Vector(room_point) if room_point else min(floors, key=lambda c: (c - pos).length)
        emit = o.matrix_world.to_3x3() @ Vector((0, 0, -1))
        if emit.dot(target - pos) < 0:
            o.rotation_euler.rotate_axis("X", math.pi)


def add_practical(name, location, watts=40.0, kelvin=2700, radius=0.05):
    """A real lamp: point light with blackbody colour. Put it inside the modelled shade."""
    ld = bpy.data.lights.new(name, "POINT")
    ld.energy = watts
    ld.shadow_soft_size = radius
    if hasattr(ld, "use_temperature"):
        ld.use_temperature = True
        ld.temperature = kelvin
    else:
        ld.color = _kelvin_rgb(kelvin)
    obj = bpy.data.objects.new(name, ld)
    bpy.data.collections["COL_Lighting"].objects.link(obj)
    obj.location = location
    return obj


def _kelvin_rgb(k):
    t = k / 100.0
    r = 1.0 if t <= 66 else min(1.0, 1.292936 * (t - 60) ** -0.1332047)
    g = (0.3900816 * math.log(t) - 0.6318414) if t <= 66 else 1.1298909 * (t - 60) ** -0.0755148
    b = 1.0 if t >= 66 else (0.0 if t <= 19 else 0.5432068 * math.log(t - 10) - 1.1962541)
    return tuple(max(0.0, min(1.0, c)) for c in (r, g, b))


# ---------------------------------------------------------------- camera and render

def realestate_camera(name, focal_mm=None, height=None, fstop=8.0, focus_distance=None, level=True):
    """Real-estate photography conventions: level camera (verticals stay vertical), pitch moved
    into lens shift, moderate DOF. Keeps the matched focal length unless one is given."""
    cam = bpy.data.objects[name]
    data = cam.data
    if focal_mm:
        data.lens = focal_mm
    if height is not None:
        cam.location.z = height
    if level:
        # work from the actual view direction: Euler angles can decompose with flipped axes
        fwd = cam.rotation_euler.to_matrix() @ Vector((0, 0, -1))
        pitch = math.asin(max(-1.0, min(1.0, fwd.z)))     # + looking up
        yaw = math.atan2(-fwd.x, fwd.y)
        cam.rotation_euler = (math.radians(90), 0.0, yaw)
        # vertical shift that keeps roughly the same framing: tan(pitch) * focal / sensor
        sensor = data.sensor_height if data.sensor_fit == "VERTICAL" else data.sensor_width
        data.shift_y = max(-0.3, min(0.3, math.tan(pitch) * data.lens / sensor))
    data.dof.use_dof = True
    data.dof.aperture_fstop = fstop
    data.dof.focus_distance = focus_distance or 3.0
    bpy.context.scene.camera = cam
    return cam


def render_preset(kind="final", width=3000, aspect=1.5, exposure=0.0, white_balance_k=None):
    """Cycles settings.

    `exposure` is in stops: match it to the real photos (interiors usually +0.5..+1.5).
    `white_balance_k` does what the photographer's camera did: a room lit mostly by skylight
    renders blue at a neutral 6500 K; ~7000-7500 K neutralises it (Blender 4.3+ only)."""
    s = bpy.context.scene
    s.view_settings.exposure = exposure
    if white_balance_k and hasattr(s.view_settings, "use_white_balance"):
        s.view_settings.use_white_balance = True
        s.view_settings.white_balance_temperature = white_balance_k
    s.render.engine = "CYCLES"
    c = s.cycles
    if kind == "preview":
        c.samples, c.adaptive_threshold, width = 128, 0.05, min(width, 1200)
    else:
        c.samples, c.adaptive_threshold = 1024, 0.01
    c.use_adaptive_sampling = True
    c.use_denoising = True
    c.max_bounces, c.diffuse_bounces, c.glossy_bounces = 12, 6, 6
    c.transmission_bounces, c.transparent_max_bounces = 12, 16
    c.caustics_reflective = c.caustics_refractive = False
    c.blur_glossy = 0.5
    s.view_settings.view_transform = "AgX"
    try:  # look names differ between Blender versions
        s.view_settings.look = "AgX - Base Contrast" if kind == "final" else "None"
    except TypeError:
        s.view_settings.look = "None"
    s.render.resolution_x = width
    s.render.resolution_y = int(round(width / aspect))
    s.render.film_transparent = False
    vl = s.view_layers[0]
    vl.use_pass_z = vl.use_pass_normal = vl.use_pass_mist = True
    vl.use_pass_diffuse_color = vl.use_pass_glossy_direct = True
    vl.use_pass_cryptomatte_object = vl.use_pass_cryptomatte_material = True
    print(f"render:{kind} {s.render.resolution_x}x{s.render.resolution_y} samples={c.samples}")


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opt = {argv[i][2:]: argv[i + 1] for i in range(0, len(argv) - 1, 2) if argv[i].startswith("--")}
    setup_daylight(float(opt.get("lat", 48.85)), float(opt.get("lon", 2.35)),
                   opt.get("when", "2026-06-21T12:00"), float(opt.get("north", 0)), hdri=opt.get("hdri"))
    add_window_portals()
    orient_portals_inward()
    if "camera" in opt:
        realestate_camera(opt["camera"])
    render_preset(opt.get("preset", "preview"))
    if "render" in opt:
        bpy.context.scene.render.filepath = os.path.abspath(opt["render"])
        bpy.ops.render.render(write_still=True)
