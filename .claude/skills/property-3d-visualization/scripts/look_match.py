"""Measure how a render's exposure and colour differ from the real photo, on surfaces that are kept.

    python look_match.py --photo 00_input/photos/living_01.jpg --render 04_renders/P1_v3.png \
        --region 0.05,0.10,0.30,0.45 --region 0.60,0.02,0.95,0.15 [--preview qa/P1_look.png]

Both images must come from the same matched camera (after the photo-match gate). Each --region is
x0,y0,x1,y1 in 0-1 image coordinates (origin top-left) covering a surface that exists unchanged in
both images: a painted wall, the ceiling, a kept floor. Never measure furniture or windows.

Output (JSON): the exposure correction in stops and per-channel gains, measured in linear light,
plus plain-language advice for Blender:
  * exposure_stops  -> add to scene.view_settings.exposure
  * white balance   -> render warmer than photo: LOWER white_balance_temperature; cooler: RAISE it.
Re-render and re-measure until the verdict is "match" (|stops| <= 0.15, channel gains within 3 %).
--preview writes the render corrected by the measured gains: a quick look, not a deliverable;
the fix belongs in the Blender scene so light and materials stay physically consistent.
"""

import argparse
import json
import math
import sys

import numpy as np
from PIL import Image, ImageOps

REC709 = np.array([0.2126, 0.7152, 0.0722])


def to_linear(a):
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def to_srgb(a):
    a = np.clip(a, 0, 1)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * a ** (1 / 2.4) - 0.055)


def load(path, size=None):
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if size:
        img = img.resize(size, Image.LANCZOS)
    return to_linear(np.asarray(img, dtype=np.float64) / 255.0)


def region_pixels(a, box):
    h, w, _ = a.shape
    x0, y0, x1, y1 = box
    px = a[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)].reshape(-1, 3)
    lum = px @ REC709
    keep = (lum > 0.005) & (px.max(axis=1) < 0.98)          # ignore clipped and near-black pixels
    return px[keep]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photo", required=True)
    ap.add_argument("--render", required=True)
    ap.add_argument("--region", action="append", required=True, help="x0,y0,x1,y1 in 0-1, repeatable")
    ap.add_argument("--preview")
    args = ap.parse_args(argv)

    render_img = Image.open(args.render)
    photo = load(args.photo, render_img.size)
    render = load(args.render)
    boxes = [tuple(float(v) for v in r.split(",")) for r in args.region]
    p = np.concatenate([region_pixels(photo, b) for b in boxes])
    r = np.concatenate([region_pixels(render, b) for b in boxes])
    if len(p) < 500 or len(r) < 500:
        print(json.dumps({"error": "regions too small or clipped; choose larger unclipped kept surfaces"}))
        return 2

    # medians are robust to small differences in what the regions contain
    pm, rm = np.median(p, axis=0), np.median(r, axis=0)
    py, ry = float(pm @ REC709), float(rm @ REC709)
    stops = math.log2(py / ry)
    chroma_gain = (pm / py) / (rm / ry)                        # colour shift independent of exposure
    warmth = float(chroma_gain[2] / chroma_gain[0])             # >1: photo bluer than render -> render too warm
    if abs(warmth - 1) <= 0.03:
        wb = "white balance matches"
    elif warmth > 1:
        wb = f"render is warmer than the photo by ~{(warmth - 1) * 100:.0f} %: LOWER white_balance_temperature"
    else:
        wb = f"render is cooler than the photo by ~{(1 / warmth - 1) * 100:.0f} %: RAISE white_balance_temperature"
    match = abs(stops) <= 0.15 and np.all(np.abs(chroma_gain - 1) <= 0.03)
    out = {
        "exposure_stops": round(stops, 2),
        "exposure_advice": "exposure matches" if abs(stops) <= 0.15 else
        f"add {stops:+.2f} to scene.view_settings.exposure",
        "channel_gains_rgb": [round(float(g), 3) for g in chroma_gain],
        "white_balance_advice": wb,
        "photo_linear_rgb": [round(float(v), 4) for v in pm],
        "render_linear_rgb": [round(float(v), 4) for v in rm],
        "pixels": {"photo": int(len(p)), "render": int(len(r))},
        "verdict": "match" if match else "adjust",
    }
    if args.preview:
        gains = (2 ** stops) * chroma_gain
        Image.fromarray((to_srgb(render * gains) * 255 + 0.5).astype(np.uint8)).save(args.preview)
        out["preview"] = args.preview
    print(json.dumps(out, indent=2))
    return 0 if match else 2


if __name__ == "__main__":
    sys.exit(main())
