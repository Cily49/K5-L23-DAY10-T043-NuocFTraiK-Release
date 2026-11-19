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
import math
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
MIN_SEGMENT_PIXELS = 1024
MIN_SEGMENT_COVERAGE = 0.15
MIN_BOX_COVERAGE = 0.10
MISMATCH_SEGMENT_COVERAGE = 0.55
MISMATCH_BOX_COVERAGE = 0.25
MERGE_SEGMENT_COVERAGE = 0.30
MERGE_BOX_COVERAGE = 0.25
DRIFT_MAX_SEGMENT_COVERAGE = 0.75
DRIFT_CENTER_OFFSET = 0.15
DRIFT_SIZE_DELTA = 0.20


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


def class_names(path: Path) -> dict[int, str]:
    names = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            names[int(parts[0])] = parts[1].strip()
    return names


def box_bounds(box: tuple[int, float, float, float, float], width: int, height: int) -> tuple[int, int, int, int]:
    _, xc, yc, bw, bh = box
    return (
        max(0, math.floor((xc - bw / 2) * width)),
        max(0, math.floor((yc - bh / 2) * height)),
        min(width, math.ceil((xc + bw / 2) * width)),
        min(height, math.ceil((yc + bh / 2) * height)),
    )


def box_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    intersection = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection
    return intersection / union if union else 0.0


def box_mask_geometry_diff(box: tuple[int, int, int, int], segment: dict) -> bool:
    x1, y1, x2, y2 = box
    sx, sy, sw, sh = segment.get("bbox", (0, 0, 0, 0))
    bw, bh = x2 - x1, y2 - y1
    if min(bw, bh, sw, sh) <= 0:
        return False
    box_cx, box_cy = (x1 + x2) / 2, (y1 + y2) / 2
    seg_cx, seg_cy = sx + sw / 2, sy + sh / 2
    center_shift = (
        abs(box_cx - seg_cx) / bw >= DRIFT_CENTER_OFFSET
        or abs(box_cy - seg_cy) / bh >= DRIFT_CENTER_OFFSET
    )
    size_change = (
        abs(bw - sw) / sw >= DRIFT_SIZE_DELTA
        or abs(bh - sh) / sh >= DRIFT_SIZE_DELTA
    )
    return center_shift or size_change


def mask_counts_in_box(pixels: bytearray, width: int, bounds: tuple[int, int, int, int]) -> Counter:
    x1, y1, x2, y2 = bounds
    counts = Counter()
    for y in range(y1, y2):
        start = (y * width + x1) * 3
        end = (y * width + x2) * 3
        row = pixels[start:end]
        counts.update(zip(row[0::3], row[1::3], row[2::3]))
    return counts


def generate_candidates(delivery: Path, rule_errors: list[dict]) -> list[dict]:
    manifest = load_json(delivery / "manifest.json")
    panoptic = load_json(delivery / "panoptic.json")
    names = class_names(delivery / "classes.txt")
    categories = {c["id"]: c for c in panoptic["categories"]}
    image_sizes = {
        Path(image["file_name"]).stem: (image["width"], image["height"])
        for image in panoptic.get("images", [])
    }
    annotations = {
        Path(annotation["file_name"]).stem: annotation
        for annotation in panoptic.get("annotations", [])
    }
    excluded = {e["target"] for e in rule_errors if e["target"] in manifest["items"]}
    found = set()

    for stem, item in manifest["items"].items():
        if stem in excluded:
            continue
        label_path = delivery / item["label"]
        mask_path = delivery / item["mask"]
        boxes = read_labels(label_path)
        annotation = annotations.get(stem)
        size = image_sizes.get(stem)
        if boxes is None or annotation is None or size is None or not mask_path.is_file():
            continue

        width, height = size
        mask_width, mask_height, pixels = read_rgb(mask_path)
        if (mask_width, mask_height) != size:
            continue

        segment_info = {
            segment["id"]: segment
            for segment in annotation.get("segments_info", [])
            if categories.get(segment.get("category_id"), {}).get("isthing")
            and not segment.get("iscrowd")
        }
        if not segment_info:
            continue

        total_pixels = Counter(zip(pixels[0::3], pixels[1::3], pixels[2::3]))
        segment_areas = {
            sid: total_pixels.get((sid & 255, (sid >> 8) & 255, (sid >> 16) & 255), 0)
            for sid in segment_info
        }
        box_names = [names.get(box[0]) for box in boxes]
        box_bounds_list = [box_bounds(box, width, height) for box in boxes]
        box_areas = [
            max(0, x2 - x1) * max(0, y2 - y1)
            for x1, y1, x2, y2 in box_bounds_list
        ]
        overlaps = [
            mask_counts_in_box(pixels, width, bounds)
            for bounds in box_bounds_list
        ]
        matches_by_segment: dict[int, list[tuple[int, float, float]]] = defaultdict(list)
        same_class_overlap: set[int] = set()
        mismatch_by_box: set[int] = set()
        strong_same_class_by_box: set[int] = set()
        best_same_class_by_box: dict[int, tuple[float, float, dict]] = {}

        for box_index, box in enumerate(boxes):
            box_name = box_names[box_index]
            box_area = box_areas[box_index]
            if box_name is None or box_area == 0:
                continue
            for sid, segment in segment_info.items():
                area = segment_areas[sid]
                overlap = overlaps[box_index].get(
                    (sid & 255, (sid >> 8) & 255, (sid >> 16) & 255), 0
                )
                if area == 0 or overlap == 0:
                    continue
                segment_coverage = overlap / area
                box_coverage = overlap / box_area
                category_name = categories[segment["category_id"]]["name"]

                if box_name != category_name:
                    if segment_coverage >= MISMATCH_SEGMENT_COVERAGE and box_coverage >= MISMATCH_BOX_COVERAGE:
                        mismatch_by_box.add(box_index)
                    continue

                same_class_overlap.add(sid)
                if segment_coverage >= MIN_SEGMENT_COVERAGE and box_coverage >= MIN_BOX_COVERAGE:
                    matches_by_segment[sid].append((box_index, segment_coverage, box_coverage))
                    iou = overlap / (area + box_area - overlap)
                    best = best_same_class_by_box.get(box_index)
                    if best is None or iou > best[0]:
                        best_same_class_by_box[box_index] = (iou, segment_coverage, segment)
                if segment_coverage >= MISMATCH_SEGMENT_COVERAGE and box_coverage >= MISMATCH_BOX_COVERAGE:
                    strong_same_class_by_box.add(box_index)

        if mismatch_by_box - strong_same_class_by_box:
            found.add(("class_swap", stem))
            found.add(("category_swap", stem))

        for box_index, (_, coverage, segment) in best_same_class_by_box.items():
            if (
                coverage < DRIFT_MAX_SEGMENT_COVERAGE
                and box_mask_geometry_diff(box_bounds_list[box_index], segment)
            ):
                found.add(("bbox_drift", stem))

        for sid, segment in segment_info.items():
            area = segment_areas[sid]
            if area < MIN_SEGMENT_PIXELS:
                continue
            matches = matches_by_segment.get(sid, [])
            merge_matches = [
                match for match in matches
                if match[1] >= MERGE_SEGMENT_COVERAGE and match[2] >= MERGE_BOX_COVERAGE
            ]
            separate_boxes = any(
                box_iou(box_bounds_list[a[0]], box_bounds_list[b[0]]) < 0.35
                for index, a in enumerate(merge_matches)
                for b in merge_matches[index + 1:]
            )
            if len(merge_matches) >= 2 and separate_boxes:
                found.add(("instance_merge", stem))
            elif sid not in same_class_overlap:
                sid_rgb = (sid & 255, (sid >> 8) & 255, (sid >> 16) & 255)
                overlaps_other_class = any(
                    box_names[index] is not None
                    and box_names[index] != categories[segment["category_id"]]["name"]
                    and overlaps[index].get(sid_rgb, 0) / area >= MIN_SEGMENT_COVERAGE
                    for index in range(len(boxes))
                )
                if not overlaps_other_class:
                    found.add(("missing_box", stem))

    return [{"type": kind, "target": target} for kind, target in sorted(found)]


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
        args.candidates.parent.mkdir(parents=True, exist_ok=True)
        candidates = generate_candidates(args.delivery, errors)
        args.candidates.write_text(
            json.dumps({"candidates": candidates}, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"{len(candidates)} ứng viên -> {args.candidates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
