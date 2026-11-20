#!/usr/bin/env python3
"""Chia hàng đợi ứng viên cho các thành viên xem ảnh, rồi gộp kết quả lại.

Chia (gom theo ảnh: mọi giả thuyết của một ảnh về cùng một người):
  python tools/split_review.py split runs/r43007/candidates.json --out runs/r43007/review \
      --people Binh Huyen Nam HoangAnh Ngoc

  -> runs/r43007/review/<người>/candidates.json   (đưa vào tools/review_viewer.py)
  -> runs/r43007/review/<người>/review.csv        (người đó điền verdict + note)

Gộp (sau khi mọi người điền xong):
  python tools/split_review.py merge runs/r43007/review --out runs/r43007/review_log.csv

review.csv có cột image,type,verdict,note,nguoi_xem. Mỗi ảnh mang nhiều nhất một lỗi:
nếu một ảnh có nhiều giả thuyết, chỉ `confirmed` một dòng, các dòng còn lại `rejected`.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

FIELDS = ["image", "type", "verdict", "note", "nguoi_xem"]


def split(args: argparse.Namespace) -> int:
    cands = json.loads(Path(args.candidates).read_text(encoding="utf-8"))["candidates"]
    by_image: dict[str, list[dict]] = defaultdict(list)
    for c in cands:
        by_image[c["target"]].append(c)

    # Chia tham lam: ảnh nhiều giả thuyết trước, giao cho người đang ít việc nhất.
    load = {p: 0 for p in args.people}
    assigned: dict[str, list[str]] = {p: [] for p in args.people}
    for image in sorted(by_image, key=lambda im: (-len(by_image[im]), im)):
        person = min(args.people, key=lambda p: (load[p], args.people.index(p)))
        assigned[person].append(image)
        load[person] += len(by_image[image])

    out = Path(args.out)
    for person, images in assigned.items():
        folder = out / person
        folder.mkdir(parents=True, exist_ok=True)
        # review_viewer.py đọc khoá "image"; validator ghi "target" -> thêm cả hai.
        mine = [{**c, "image": c["target"]} for im in sorted(images) for c in by_image[im]]
        (folder / "candidates.json").write_text(
            json.dumps({"candidates": mine}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        review = folder / "review.csv"
        if review.exists() and not args.force:
            print(f"bỏ qua {review} (đã có; dùng --force để ghi đè)")
        else:
            with review.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                w.writeheader()
                for c in mine:
                    w.writerow({"image": c["target"], "type": c["type"], "verdict": "", "note": "", "nguoi_xem": person})
        print(f"{person}: {len(images)} ảnh, {len(mine)} ứng viên -> {folder}")
    return 0


def merge(args: argparse.Namespace) -> int:
    rows, problems = [], []
    for review in sorted(Path(args.folder).glob("*/review.csv")):
        with review.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                verdict = (row.get("verdict") or "").strip()
                note = (row.get("note") or "").strip()
                if verdict not in ("confirmed", "rejected"):
                    problems.append(f"{review.parent.name}: {row['image']} {row['type']} chưa có verdict")
                elif len(note) < 20:
                    problems.append(f"{review.parent.name}: {row['image']} {row['type']} ghi chú < 20 ký tự")
                rows.append({k: (row.get(k) or "").strip() for k in FIELDS})

    confirmed: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if r["verdict"] == "confirmed":
            confirmed[r["image"]].append(r["type"])
    for image, types in confirmed.items():
        if len(types) > 1:
            problems.append(f"{image}: confirmed {len(types)} loại {types}, mỗi ảnh chỉ một lỗi")

    if problems:
        print("Chưa gộp được:")
        for p in problems:
            print("  -", p)
        return 1
    with Path(args.out).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    n_conf = sum(r["verdict"] == "confirmed" for r in rows)
    print(f"{len(rows)} dòng ({n_conf} confirmed, {len(rows) - n_conf} rejected) -> {args.out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Chia / gộp hàng đợi review ảnh")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("split")
    s.add_argument("candidates")
    s.add_argument("--out", required=True)
    s.add_argument("--people", nargs="+", required=True)
    s.add_argument("--force", action="store_true", help="ghi đè review.csv đã có")
    m = sub.add_parser("merge")
    m.add_argument("folder")
    m.add_argument("--out", required=True)
    args = ap.parse_args()
    return split(args) if args.cmd == "split" else merge(args)


if __name__ == "__main__":
    raise SystemExit(main())
