#!/usr/bin/env python3
"""Công cụ xem ảnh cho Pha 2 (được dùng Pillow; validator thì không).

  python tools/review_viewer.py <delivery> <candidates.json> --out <thư_mục_png>

Mỗi ứng viên ra một PNG: trái = ảnh gốc có vẽ box detection (đỏ = box nghi vấn, vàng = box khác)
và viền segment panoptic nghi vấn (xanh lá); phải = vùng cắt quanh vật, phóng to.
Nhãn chữ ghi lớp detection / lớp panoptic để người xem đối chiếu với vật thật trong ảnh.
  Công cụ tạo ảnh xem trước; người review tự ghi verdict vào review_log.csv
  (image,type,verdict,note), với note mô tả điều đã thấy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pngutil  # noqa: E402


def outline(img: Image.Image, mask: Path, seg_id: int, color=(0, 255, 0)) -> None:
    """Tô nhạt segment và vẽ viền của nó lên ảnh."""
    w, h, px = pngutil.read_rgb(mask)
    rgb = pngutil.segment_rgb(seg_id)
    chans = Image.frombytes("RGB", (w, h), bytes(px)).split()
    bin_ = None
    for ch, v in zip(chans, rgb):
        m = ch.point(lambda p, v=v: 255 if p == v else 0)
        bin_ = m if bin_ is None else ImageChops.multiply(bin_, m)
    edge = ImageChops.subtract(bin_.filter(ImageFilter.MaxFilter(5)), bin_.filter(ImageFilter.MinFilter(3)))
    img.paste(Image.blend(img, Image.new("RGB", (w, h), color), 0.3), (0, 0), bin_)
    img.paste(Image.new("RGB", (w, h), color), (0, 0), edge)


def yolo_boxes(label: Path, W: int, H: int, names: dict):
    out = []
    if label.is_file():
        for ln in label.read_text(encoding="utf-8").splitlines():
            p = ln.split()
            if len(p) >= 5:
                c, x, y, w, h = int(float(p[0])), *map(float, p[1:5])
                out.append((names.get(c, str(c)), [(x - w / 2) * W, (y - h / 2) * H, (x + w / 2) * W, (y + h / 2) * H]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("delivery")
    ap.add_argument("candidates")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    d, out = Path(args.delivery), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = {int(l.split(" ", 1)[0]): l.split(" ", 1)[1].strip()
             for l in (d / "classes.txt").read_text(encoding="utf-8").splitlines() if l.strip()}
    cands = json.loads(Path(args.candidates).read_text(encoding="utf-8"))["candidates"]
    panoptic = json.loads((d / "panoptic.json").read_text(encoding="utf-8"))
    categories = {cat["id"]: cat for cat in panoptic.get("categories", [])}
    annotations = {
        Path(ann["file_name"]).stem: ann
        for ann in panoptic.get("annotations", [])
    }
    for c in cands:
        # Current validator schema is {"type": ..., "target": image_stem}.
        # Accept the older/proposed "image" key too for compatibility.
        name = str(c.get("image", c.get("target", "")))
        if not name:
            print(f"skip candidate without image/target: {c}")
            continue
        image_path = d / "images" / f"{name}.jpg"
        if not image_path.is_file():
            print(f"skip {name}: image file is missing")
            continue
        img = Image.open(image_path).convert("RGB")
        W, H = img.size
        mask_path = d / "masks" / f"{name}.png"
        segment_ids = [c["segment_id"]] if c.get("segment_id") else []
        if not segment_ids:
            ann = annotations.get(name, {})
            segment_ids = [
                segment["id"] for segment in ann.get("segments_info", [])
                if categories.get(segment.get("category_id"), {}).get("isthing")
                and not segment.get("iscrowd")
            ]
        for segment_id in segment_ids:
            if mask_path.is_file():
                outline(img, mask_path, segment_id)
        draw = ImageDraw.Draw(img)
        focus = c.get("box_px") or c.get("segment_box_px") or (c.get("boxes_px") or [[0, 0, W, H]])[0]
        hot = [c.get("box_px")] + (c.get("boxes_px") or [])
        for cls, b in yolo_boxes(d / "labels" / f"{name}.txt", W, H, names):
            red = any(h and all(abs(a - b2) < 2 for a, b2 in zip(h, b)) for h in hot)
            draw.rectangle(b, outline=(255, 0, 0) if red else (255, 220, 0), width=3 if red else 1)
            if red:
                draw.text((b[0] + 3, b[1] + 3), f"det:{cls}", fill=(255, 0, 0))
        if c.get("segment_box_px"):
            sb = c["segment_box_px"]
            draw.rectangle(sb, outline=(0, 200, 255), width=2)
        xs = [focus[0], focus[2]] + ([c["segment_box_px"][0], c["segment_box_px"][2]] if c.get("segment_box_px") else [])
        ys = [focus[1], focus[3]] + ([c["segment_box_px"][1], c["segment_box_px"][3]] if c.get("segment_box_px") else [])
        for b in c.get("boxes_px") or []:
            xs += [b[0], b[2]]
            ys += [b[1], b[3]]
        pad = 30
        crop = img.crop((max(0, min(xs) - pad), max(0, min(ys) - pad), min(W, max(xs) + pad), min(H, max(ys) + pad)))
        scale = max(1.0, 400 / max(crop.size))
        crop = crop.resize((int(crop.width * scale), int(crop.height * scale)))
        canvas = Image.new("RGB", (W + crop.width + 10, max(H, crop.height) + 40), (30, 30, 30))
        canvas.paste(img, (0, 40))
        canvas.paste(crop, (W + 10, 40))
        title = f"{name}  {c['type']}  det={c.get('det_class', '-')}  pan={c.get('pan_class', '-')}  " \
                f"iou={c.get('iou', '-')}  out={c.get('seg_outside', '-')}"
        ImageDraw.Draw(canvas).text((5, 12), title, fill=(255, 255, 255))
        canvas.save(out / f"{name}_{c['type']}.png")
    print(f"{len(cands)} ảnh -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
