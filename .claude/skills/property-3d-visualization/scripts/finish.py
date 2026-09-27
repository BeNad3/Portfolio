"""Photographic finishing for a rendered still: the small optical traits of a real camera.

    python finish.py --src 04_renders/P1_final.png --out 05_final/P1.jpg [--strength 1.0]

Applies, in this order and all subtle by default: gentle S-curve, lateral chromatic aberration
toward the edges, lens vignetting, luminance grain. `--strength` scales every effect (0 = off,
1 = default "good camera", 2 = visibly stylised; stay at or below 1 for real-estate).

These are the traits whose absence makes CGI read as CGI. They are presentation only: they never
change geometry, colours of finishes or light direction. Version-independent (Pillow + numpy),
so the same finish applies to Blender, ComfyUI or upscaled outputs.
"""

import argparse
import sys

import numpy as np
from PIL import Image


def s_curve(a, amount):
    # smoothstep blend around mid-grey: lifts contrast without crushing blacks or clipping whites
    s = a * a * (3 - 2 * a)
    return a + (s - a) * amount


def chromatic_aberration(a, px):
    """Scale R out and B in radially by up to `px` pixels at the corners."""
    if px <= 0:
        return a
    h, w, _ = a.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    r_max = np.hypot(cx, cy)
    out = a.copy()
    for ch, sign in ((0, 1.0), (2, -1.0)):
        k = 1 + sign * px / r_max
        sx = np.clip(cx + (xx - cx) / k, 0, w - 1).astype(np.int32)
        sy = np.clip(cy + (yy - cy) / k, 0, h - 1).astype(np.int32)
        out[..., ch] = a[sy, sx, ch]
    return out


def vignette(a, amount):
    h, w, _ = a.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2)) / np.sqrt(2)
    falloff = 1 - amount * np.clip(r, 0, 1) ** 2.2        # cos^4-like natural falloff
    return a * falloff[..., None]


def grain(a, sigma, seed=0):
    rng = np.random.default_rng(seed)
    h, w, _ = a.shape
    n = rng.normal(0, sigma, (h, w)).astype(np.float32)
    lum = a.mean(axis=2, keepdims=True)
    weight = 4 * lum * (1 - lum)                           # grain strongest in mid-tones, like film/sensor noise
    return a + n[..., None] * weight


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--contrast", type=float, default=0.12)
    ap.add_argument("--ca-px", type=float, default=None, help="corner chromatic aberration in px (default: 0.9 px per 1000 px width)")
    ap.add_argument("--vignette", type=float, default=0.10)
    ap.add_argument("--grain", type=float, default=0.012)
    ap.add_argument("--quality", type=int, default=94)
    args = ap.parse_args(argv)

    img = Image.open(args.src).convert("RGB")
    a = np.asarray(img, dtype=np.float32) / 255.0
    k = args.strength
    ca = args.ca_px if args.ca_px is not None else 0.9 * img.width / 1000
    a = s_curve(a, args.contrast * k)
    a = chromatic_aberration(a, ca * k)
    a = vignette(a, args.vignette * k)
    a = grain(a, args.grain * k)
    out = Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8))
    save = {"quality": args.quality, "subsampling": 0} if args.out.lower().endswith((".jpg", ".jpeg")) else {}
    out.save(args.out, **save)
    print(f"finish:{args.out} strength={k} ca_px={ca * k:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
