#!/usr/bin/env python3
"""Draw detection + panoptic labels on images for visual review (viewer tool, Pillow allowed).

  python tools/overlay.py <delivery> <candidates.json> --out <dir>
  python tools/overlay.py <delivery> --images 000000006213 000000008277 --out <dir>

Output per image:
  <image>.png  top:    clean original image (to see the real objects)
               bottom: RED BOX = detection box (tag "D1 sink"),
                       COLORED AREA + outline = panoptic thing segment (tag "P1 sink"), one color per segment
  <image>.txt  lists detection boxes and panoptic segments (pixel x,y,w,h) + suspected error types
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pngutil  # noqa: E402

COLORS = [(0, 220, 0), (0, 160, 255), (255, 0, 255), (255, 200, 0), (0, 255, 255),
          (255, 120, 0), (150, 80, 255), (120, 255, 120), (255, 80, 160), (200, 200, 200)]


def seg_mask(px_img: Image.Image, seg_id: int) -> Image.Image:
    """Binary mask (mode L) of one segment: pixels whose R,G,B encode exactly this id."""
    rgb = pngutil.segment_rgb(seg_id)
    out = None
    for ch, v in zip(px_img.split(), rgb):
        m = ch.point(lambda p, v=v: 255 if p == v else 0)
        out = m if out is None else ImageChops.multiply(out, m)
    return out


def render(d: Path, stem: str, names: dict, cats: dict, ann: dict, suspects: list[str], out: Path) -> None:
    img = Image.open(d / "images" / f"{stem}.jpg").convert("RGB")
    W, H = img.size
    overlay = img.copy()
    lines = [f"Ảnh {stem}  {W}x{H}  nghi: {', '.join(suspects) or '-'}", "", "DETECTION (khung đỏ):"]

    # Panoptic: fill each thing segment.
    segs = [s for s in ann.get("segments_info", []) if cats.get(s["category_id"], {}).get("isthing")]
    mask_path = d / "masks" / f"{stem}.png"
    labels_p = []
    if mask_path.is_file() and segs:
        w, h, px = pngutil.read_rgb(mask_path)
        px_img = Image.frombytes("RGB", (w, h), bytes(px))
        if (w, h) != (W, H):
            px_img = px_img.resize((W, H), Image.NEAREST)
        for k, s in enumerate(segs):
            color = COLORS[k % len(COLORS)]
            m = seg_mask(px_img, s["id"])
            overlay.paste(Image.blend(overlay, Image.new("RGB", (W, H), color), 0.45), (0, 0), m)
            edge = ImageChops.subtract(m.filter(ImageFilter.MaxFilter(3)), m)
            overlay.paste(Image.new("RGB", (W, H), color), (0, 0), edge)
            name = cats[s["category_id"]]["name"]
            labels_p.append((f"P{k + 1} {name}" + (" (crowd)" if s.get("iscrowd") else ""), s["bbox"], color))

    draw = ImageDraw.Draw(overlay)
    label_file = d / "labels" / f"{stem}.txt"
    if label_file.is_file():
        for k, ln in enumerate(l for l in label_file.read_text(encoding="utf-8").splitlines() if l.strip()):
            c, x, y, bw, bh = (float(v) for v in ln.split()[:5])
            x1, y1, x2, y2 = (x - bw / 2) * W, (y - bh / 2) * H, (x + bw / 2) * W, (y + bh / 2) * H
            name = names.get(int(c), f"id{int(c)}")
            draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=2)
            tag = f"D{k + 1} {name}"
            draw.rectangle([x1, max(0, y1 - 11), x1 + 6 * len(tag) + 4, max(11, y1)], fill=(255, 0, 0))
            draw.text((x1 + 2, max(0, y1 - 11)), tag, fill=(255, 255, 255))
            lines.append(f"  {tag:<22} x={round(x1)} y={round(y1)} w={round(x2 - x1)} h={round(y2 - y1)}")

    lines += ["", "PANOPTIC (vùng màu):"]
    for tag, (bx, by, bw, bh), color in labels_p:
        # Tag sits just below the segment's bbox, clamped inside the image
        # (a segment touching the bottom edge would otherwise put its tag off-image).
        ty = min(by + bh, H - 12)
        tx = min(bx, max(0, W - 6 * len(tag) - 4))
        draw.rectangle([tx, ty, tx + 6 * len(tag) + 4, ty + 11], fill=color)
        draw.text((tx + 2, ty), tag, fill=(0, 0, 0))
        lines.append(f"  {tag:<22} x={bx} y={by} w={bw} h={bh}")

    canvas = Image.new("RGB", (W, 2 * H + 30), (25, 25, 25))
    canvas.paste(img, (0, 0))
    canvas.paste(overlay, (0, H + 30))
    # Pillow's default font has no Vietnamese diacritics -> keep on-image text ASCII.
    ImageDraw.Draw(canvas).text((6, H + 9), f"{stem}  nghi: {', '.join(suspects)}   "
                                "| RED box = detection, COLOR = panoptic", fill=(255, 255, 255))
    if max(W, H) < 500:  # small image: upscale so it is easier to see
        canvas = canvas.resize((canvas.width * 2, canvas.height * 2), Image.NEAREST)
    canvas.save(out / f"{stem}.png")
    (out / f"{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Draw detection + panoptic labels on candidate images")
    ap.add_argument("delivery", type=Path)
    ap.add_argument("candidates", nargs="?", type=Path)
    ap.add_argument("--images", nargs="*", default=[])
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    suspects: dict[str, list[str]] = defaultdict(list)
    if args.candidates:
        for c in json.loads(args.candidates.read_text(encoding="utf-8"))["candidates"]:
            suspects[c.get("target") or c["image"]].append(c["type"])
    for im in args.images:
        suspects.setdefault(im, [])

    d = args.delivery
    names = {int(l.split(" ", 1)[0]): l.split(" ", 1)[1].strip()
             for l in (d / "classes.txt").read_text(encoding="utf-8").splitlines() if l.strip()}
    pan = json.loads((d / "panoptic.json").read_text(encoding="utf-8"))
    cats = {c["id"]: c for c in pan["categories"]}
    anns = {Path(a["file_name"]).stem: a for a in pan["annotations"]}
    args.out.mkdir(parents=True, exist_ok=True)
    for stem in sorted(suspects):
        if not (d / "images" / f"{stem}.jpg").is_file():
            print(f"bỏ qua {stem}: thiếu ảnh")
            continue
        render(d, stem, names, cats, anns.get(stem, {}), sorted(set(suspects[stem])), args.out)
    print(f"{len(suspects)} ảnh -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
