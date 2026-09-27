"""Photo-match gate: compare a clay render from a matched camera against the real photo.

    python photo_match_overlay.py --photo living_01.jpg --render clay_CAM_P1.png --out qa/P1_match.png

Writes a 3-panel sheet (photo | render | render edges in red over the photo) and prints a JSON
score. `edge_match` is the share of the render's structural edges (wall corners, openings,
ceiling line) that land within `--tolerance` pixels of an edge in the photo. It is a guide, not
proof: furniture and clutter add photo edges, so read the sheet as well as the number.

Requires Pillow only.
"""

import argparse
import json
import sys

from PIL import Image, ImageChops, ImageFilter, ImageOps

Image.MAX_IMAGE_PIXELS = None


def edge_mask(img, threshold):
    grey = ImageOps.autocontrast(img.convert("L").filter(ImageFilter.GaussianBlur(1.2)))
    edges = grey.filter(ImageFilter.FIND_EDGES)
    mask = edges.point(lambda v: 255 if v >= threshold else 0)
    # FIND_EDGES fires on the image border; blank a thin frame so it never counts as structure
    inner = Image.new("L", mask.size, 0)
    b = 4
    inner.paste(mask.crop((b, b, mask.width - b, mask.height - b)), (b, b))
    return inner


def count_on(mask):
    return mask.histogram()[255]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photo", required=True)
    ap.add_argument("--render", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1600, help="working width in px")
    ap.add_argument("--tolerance", type=int, default=6, help="edge distance tolerance in px at working width")
    ap.add_argument("--photo-threshold", type=int, default=20,
                    help="keep <= render threshold; raise it for noisy or heavily textured photos")
    ap.add_argument("--render-threshold", type=int, default=25)
    args = ap.parse_args(argv)

    photo = ImageOps.exif_transpose(Image.open(args.photo)).convert("RGB")
    render = Image.open(args.render).convert("RGB")

    pa, ra = photo.width / photo.height, render.width / render.height
    aspect_error = abs(pa - ra) / pa
    w = args.width
    h = int(round(w / pa))
    photo = photo.resize((w, h), Image.LANCZOS)
    render = render.resize((w, h), Image.LANCZOS)

    p_edges = edge_mask(photo, args.photo_threshold)
    r_edges = edge_mask(render, args.render_threshold)
    k = 2 * args.tolerance + 1
    p_near = p_edges.filter(ImageFilter.MaxFilter(k))
    hits = count_on(ImageChops.multiply(r_edges, p_near))
    total = max(count_on(r_edges), 1)

    overlay = photo.copy()
    red = Image.new("RGB", (w, h), (255, 40, 40))
    overlay.paste(red, (0, 0), r_edges.filter(ImageFilter.MaxFilter(3)))

    sheet = Image.new("RGB", (w * 3, h), (255, 255, 255))
    for i, panel in enumerate((photo, render, overlay)):
        sheet.paste(panel, (i * w, 0))
    sheet.save(args.out)

    score = {
        "photo": args.photo,
        "render": args.render,
        "sheet": args.out,
        "aspect_error": round(aspect_error, 4),
        "edge_match": round(hits / total, 3),
        "tolerance_px": args.tolerance,
        "verdict": "check" if aspect_error > 0.01 else ("pass" if hits / total >= 0.75 else "fail"),
    }
    print(json.dumps(score, indent=2))
    return 0 if score["verdict"] == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())
