#!/usr/bin/env python3
"""Validator của nhóm: bắt lỗi luật trên một thư mục delivery.

    python validator/validate.py <delivery> --out errors.json [--candidates candidates.json]

Chỉ đọc thư mục delivery được truyền vào, chỉ dùng thư viện chuẩn (+ scripts/pngutil.py).
Mỗi ảnh mang nhiều nhất một lỗi, nên các luật chạy theo thứ tự ưu tiên và một ảnh
đã có lỗi thì không xét tiếp.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from pngutil import read_rgb  # noqa: E402

NUM_CLASSES = 80

# Ngưỡng duplicate_box: box lặp có cùng kích thước, tâm chỉ lệch 1-2 pixel.
# Cặp box tự nhiên của COCO chồng nhau (IoU tới ~0.66) thường khác kích thước rõ rệt.
DUP_SIZE_TOL_PX = 1.5
DUP_CENTER_TOL_PX = 3.0

# Sai số làm tròn khi đổi toạ độ YOLO (6 chữ số thập phân) về [0, 1].
OOB_EPS = 1e-4


# ---------------------------------------------------------------- tiện ích đọc file

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def jpeg_size(path: Path) -> tuple[int, int] | None:
    """Đọc (width, height) từ header JPEG (marker SOF), không cần Pillow."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            return width, height
        i += 2 + length
    return None


def read_labels(path: Path) -> list[tuple[int, float, float, float, float]] | None:
    """Trả về list (class_id, xc, yc, w, h); None nếu file không đọc/parse được."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    boxes = []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 5:
            return None
        try:
            cls = int(float(parts[0]))
            xc, yc, w, h = (float(p) for p in parts[1:])
        except ValueError:
            return None
        boxes.append((cls, xc, yc, w, h))
    return boxes


# ---------------------------------------------------------------- từng luật

def check_missing_and_hash(delivery: Path, manifest: dict) -> dict[str, str]:
    """missing_image: manifest có ảnh mà thiếu file. wrong_hash: sha256 thật khác manifest."""
    found: dict[str, str] = {}
    for stem, item in manifest["items"].items():
        image_path = delivery / item["image"]
        if not image_path.is_file():
            found[stem] = "missing_image"
            continue
        for key in ("image", "label", "mask"):
            rel, expected = item.get(key), item.get(f"{key}_sha256")
            if not rel or not expected:
                continue
            path = delivery / rel
            if path.is_file() and sha256_file(path) != expected.lower():
                found[stem] = "wrong_hash"
                break
    return found


def check_detection(stem: str, boxes: list, size: tuple[int, int] | None) -> str | None:
    """invalid_class, bbox_out_of_bounds, duplicate_box trên nhãn YOLO của một ảnh."""
    for cls, *_ in boxes:
        if not 0 <= cls < NUM_CLASSES:
            return "invalid_class"
    for _, xc, yc, w, h in boxes:
        x1, x2, y1, y2 = xc - w / 2, xc + w / 2, yc - h / 2, yc + h / 2
        if min(x1, y1) < -OOB_EPS or max(x2, y2) > 1 + OOB_EPS or w <= 0 or h <= 0:
            return "bbox_out_of_bounds"
    if size is None:
        return None
    width, height = size
    px = [(c, xc * width, yc * height, w * width, h * height) for c, xc, yc, w, h in boxes]
    for i in range(len(px)):
        ci, xi, yi, wi, hi = px[i]
        for j in range(i + 1, len(px)):
            cj, xj, yj, wj, hj = px[j]
            if ci != cj:
                continue
            same_size = abs(wi - wj) <= DUP_SIZE_TOL_PX and abs(hi - hj) <= DUP_SIZE_TOL_PX
            near = abs(xi - xj) <= DUP_CENTER_TOL_PX and abs(yi - yj) <= DUP_CENTER_TOL_PX
            if same_size and near:
                return "duplicate_box"
    return None


def check_panoptic(ann: dict, valid_cats: set[int], mask_path: Path) -> str | None:
    """invalid_category_id; thing_overlap = area khai > số pixel thật của segment trong mask."""
    for seg in ann.get("segments_info", []):
        if seg.get("category_id") not in valid_cats:
            return "invalid_category_id"
    if not mask_path.is_file():
        return None
    try:
        _, _, pixels = read_rgb(mask_path)
    except Exception:
        return None
    # Đếm pixel theo id = R + G*256 + B*256^2 (zip 3 kênh chạy ở tầng C, nhanh hơn vòng lặp Python).
    counts = Counter(zip(pixels[0::3], pixels[1::3], pixels[2::3]))
    for seg in ann.get("segments_info", []):
        sid = seg["id"]
        real = counts.get((sid & 255, (sid >> 8) & 255, (sid >> 16) & 255), 0)
        if seg.get("area", 0) > real:
            return "thing_overlap"
    return None


def check_metadata(meta_items: list[dict], jobs: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """guideline_mismatch theo ảnh; scene_leak theo scene (target = scene_id)."""
    per_image: dict[str, str] = {}
    for m in meta_items:
        job_guideline = jobs.get(m.get("job_id"))
        if job_guideline is not None and m.get("guideline_version") != job_guideline:
            per_image[m["image"]] = "guideline_mismatch"
    splits: dict[str, set[str]] = defaultdict(set)
    for m in meta_items:
        splits[m["scene_id"]].add(m["split"])
    leaks = sorted(scene for scene, s in splits.items() if len(s) > 1)
    return per_image, leaks


# ---------------------------------------------------------------- main

def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(delivery: Path) -> list[dict]:
    manifest = load_json(delivery / "manifest.json")
    metadata = load_json(delivery / "metadata.json")
    panoptic = load_json(delivery / "panoptic.json")
    with (delivery / "jobs.csv").open(encoding="utf-8", newline="") as f:
        jobs = {row["job_id"]: row["guideline"] for row in csv.DictReader(f)}

    errors: dict[str, str] = {}  # stem -> type (mỗi ảnh nhiều nhất một lỗi)

    # 1. File: thiếu ảnh, sai hash.
    errors.update(check_missing_and_hash(delivery, manifest))

    # 2. Detection: lớp, box tràn, box lặp.
    sizes = {Path(im["file_name"]).stem: (im["width"], im["height"]) for im in panoptic.get("images", [])}
    for stem, item in manifest["items"].items():
        if stem in errors:
            continue
        boxes = read_labels(delivery / item["label"])
        if boxes is None:
            continue
        size = sizes.get(stem) or jpeg_size(delivery / item["image"])
        kind = check_detection(stem, boxes, size)
        if kind:
            errors[stem] = kind

    # 3. Panoptic: category_id lạ, area khai khống.
    valid_cats = {c["id"] for c in panoptic["categories"]}
    for ann in panoptic["annotations"]:
        stem = Path(ann["file_name"]).stem
        if stem in errors:
            continue
        item = manifest["items"].get(stem, {})
        mask_path = delivery / item.get("mask", f"masks/{ann['file_name']}")
        kind = check_panoptic(ann, valid_cats, mask_path)
        if kind:
            errors[stem] = kind

    # 4. Metadata: guideline theo job, scene bị chia hai split.
    guideline_errors, leaks = check_metadata(metadata["items"], jobs)
    for stem, kind in guideline_errors.items():
        errors.setdefault(stem, kind)

    out = [{"type": t, "target": s} for s, t in sorted(errors.items())]
    out += [{"type": "scene_leak", "target": scene} for scene in leaks]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Validator lỗi luật cho lô detection + panoptic")
    ap.add_argument("delivery", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--candidates", type=Path, help="ghi ứng viên lỗi gán nhãn (Pha 2)")
    args = ap.parse_args()

    errors = validate(args.delivery)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"errors": errors}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = Counter(e["type"] for e in errors)
    print(f"{len(errors)} lỗi luật -> {args.out}")
    for kind, n in sorted(counts.items()):
        print(f"  {kind}: {n}")

    if args.candidates:
        # TODO Pha 2: đối chiếu detection <-> panoptic để sinh ứng viên.
        args.candidates.parent.mkdir(parents=True, exist_ok=True)
        args.candidates.write_text(json.dumps({"candidates": []}, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
