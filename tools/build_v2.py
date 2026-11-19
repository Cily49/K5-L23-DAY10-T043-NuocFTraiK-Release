#!/usr/bin/env python3
"""Dựng lô bàn giao v2 từ lô v1 và errors.json (Pha 4). Chỉ dùng thư viện chuẩn.

  python tools/build_v2.py --run runs/r43007
  python tools/build_v2.py --run runs/r43007 --damaged 000000007511   # ảnh wrong_hash mà bạn mở ra thấy hỏng

Đọc : <run>/delivery/ (v1, KHÔNG sửa) và <run>/errors.json.
Ghi : <run>/handover/<release_id>_v2/ với images/, labels/, rework_queue.csv, manifest.csv,
      label_summary.csv, truyvet.csv, README.txt.

Quy tắc phân loại (xem GUIDE.md, Pha 4):
  - REWORK   : lỗi ở nhãn detection hoặc thiếu file -> ảnh rời khỏi v2, vào rework_queue.csv.
  - SỬA TRONG V2: wrong_hash (chỉ sai manifest, ảnh còn nguyên), guideline_mismatch, scene_leak.
  - PANOPTIC : lỗi chỉ ở panoptic -> nhãn detection vẫn đúng, ảnh Ở LẠI v2, ghi vào Ghi chú README.

Script không đọc _private/, không dùng mạng, không nhúng tên ảnh hay đáp án.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

# Lỗi ở nhãn detection hoặc thiếu file: ảnh phải gán lại, rời khỏi v2.
DET_REWORK = {"missing_image", "invalid_class", "bbox_out_of_bounds", "duplicate_box",
              "class_swap", "bbox_drift", "missing_box"}
# Lỗi chỉ ở panoptic: ảnh ở lại v2, báo team panoptic.
PANOPTIC = {"invalid_category_id", "thing_overlap", "category_swap", "instance_merge"}
THRESHOLD = 0.02  # Day 7: trên 2% ảnh lỗi thì không Release

ACTION = {
    "missing_image": "bổ sung lại ảnh (file thiếu trong lô v1)",
    "invalid_class": "gán lại nhãn: class_id nằm ngoài 0-79",
    "bbox_out_of_bounds": "gán lại box: box vượt ra ngoài ảnh",
    "duplicate_box": "gán lại nhãn: xoá box bị lặp",
    "class_swap": "gán lại lớp của box detection (xem ảnh để biết lớp đúng)",
    "bbox_drift": "gán lại box: box lệch khỏi vật",
    "missing_box": "gán lại nhãn: thiếu box cho vật đáng kể",
    "wrong_hash": "ảnh hỏng khi kiểm: xin lại ảnh gốc rồi gán lại",
}


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()  # đọc bytes, không đọc dạng text


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def looks_like_valid_jpeg(path: Path) -> bool:
    """Kiểm sơ bộ: JPEG hợp lệ bắt đầu bằng FFD8 và kết thúc bằng FFD9. Vẫn phải mở ảnh xem bằng mắt."""
    data = path.read_bytes().rstrip(b"\x00")
    return len(data) > 4 and data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"


def load_delivery(d: Path) -> dict:
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))["items"]
    meta = {m["image"]: m for m in json.loads((d / "metadata.json").read_text(encoding="utf-8"))["items"]}
    jobs = {row["job_id"]: row for row in read_csv(d / "jobs.csv")}
    release_id = json.loads((d / "release.json").read_text(encoding="utf-8"))["release_id"]
    names = {}
    for line in (d / "classes.txt").read_text(encoding="utf-8").splitlines():
        if line.strip():
            cid, name = line.split(" ", 1)
            names[int(cid)] = name.strip()
    return {"manifest": manifest, "meta": meta, "jobs": jobs, "release_id": release_id, "names": names}


def classify(errors: list[dict], manifest: dict, scenes: set[str]) -> dict:
    """Chia lỗi vào các nhóm. target của scene_leak là scene_id, các loại khác là tên ảnh."""
    by_type: dict[str, list[str]] = defaultdict(list)
    for e in errors:
        by_type[e["type"]].append(e["target"])
    unknown = [t for ts in by_type.values() for t in ts if t not in manifest and t not in scenes]
    return {"by_type": by_type, "unknown": unknown}


def pick_split_for_scene(images: list[str], meta: dict) -> str:
    """Cảnh bị rò train/val: chọn split chiếm đa số, hoà thì chọn train."""
    c = Counter(meta[i]["split"] for i in images)
    return "val" if c.get("val", 0) > c.get("train", 0) else "train"


def main() -> int:
    ap = argparse.ArgumentParser(description="Dựng lô bàn giao v2")
    ap.add_argument("--run", required=True, help="ví dụ runs/r43007")
    ap.add_argument("--damaged", nargs="*", default=[], help="ảnh wrong_hash mà bạn mở ra thấy bị hỏng (đưa vào rework)")
    args = ap.parse_args()

    run = Path(args.run)
    d = run / "delivery"
    data = load_delivery(d)
    manifest, meta, jobs, rid, names = data["manifest"], data["meta"], data["jobs"], data["release_id"], data["names"]
    errors = json.loads((run / "errors.json").read_text(encoding="utf-8"))["errors"]

    scene_images: dict[str, list[str]] = defaultdict(list)
    for img, m in meta.items():
        scene_images[m["scene_id"]].append(img)

    info = classify(errors, manifest, set(scene_images))
    by_type = info["by_type"]
    for t in info["unknown"]:
        print(f"CẢNH BÁO: target '{t}' không có trong manifest hay cảnh nào, bỏ qua")

    # ---- 1. Ảnh nào vào rework --------------------------------------------------------------
    rework: dict[str, str] = {}  # ảnh -> loại lỗi
    for t in DET_REWORK:
        for img in by_type.get(t, []):
            if img in manifest:
                rework[img] = t

    # wrong_hash: ảnh còn nguyên thì chỉ sai manifest (sửa hash trong v2); ảnh hỏng thì rework.
    hash_fixed, hash_suspect = [], []
    for img in by_type.get("wrong_hash", []):
        if img not in manifest:
            continue
        path = d / manifest[img]["image"]
        if img in args.damaged or not path.is_file() or not looks_like_valid_jpeg(path):
            rework[img] = "wrong_hash"
            hash_suspect.append(img)
        else:
            hash_fixed.append(img)

    # ---- 2. Dựng thư mục v2 -----------------------------------------------------------------
    v2 = run / "handover" / f"{rid}_v2"
    if v2.exists():
        shutil.rmtree(v2)  # chỉ xoá bản v2 do script này sinh ra
    (v2 / "images").mkdir(parents=True)
    (v2 / "labels").mkdir(parents=True)

    kept = [img for img in sorted(manifest) if img not in rework]
    for img in kept:
        shutil.copyfile(d / manifest[img]["image"], v2 / "images" / f"{img}.jpg")
        shutil.copyfile(d / manifest[img]["label"], v2 / "labels" / f"{img}.txt")  # nhãn giữ nguyên byte

    # ---- 3. rework_queue.csv ----------------------------------------------------------------
    rq_rows = []
    for img in sorted(rework):
        job = jobs[meta[img]["job_id"]]
        rq_rows.append({"image": img, "type": rework[img], "annotator": job["annotator"],
                        "reviewer": job["reviewer"], "action": ACTION.get(rework[img], "gán lại")})
    write_csv(v2 / "rework_queue.csv", ["image", "type", "annotator", "reviewer", "action"], rq_rows)

    # ---- 4. manifest.csv (sha256 tính trên file thật trong v2) -------------------------------
    man_rows = []
    for sub in ("images", "labels"):
        for p in sorted((v2 / sub).iterdir()):
            man_rows.append({"file": f"{sub}/{p.name}", "sha256": sha256_of(p)})
    write_csv(v2 / "manifest.csv", ["file", "sha256"], man_rows)

    # ---- 5. label_summary.csv ---------------------------------------------------------------
    counts: dict[str, int] = {}
    for p in sorted((v2 / "labels").glob("*.txt")):
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                c = int(float(ln.split()[0]))
                key = names.get(c, str(c))
                counts[key] = counts.get(key, 0) + 1
    rows = [{"class": k, "count": counts[k]} for k in sorted(counts)]
    rows.append({"class": "TOTAL", "count": sum(counts.values())})
    write_csv(v2 / "label_summary.csv", ["class", "count"], rows)

    # ---- 6. truyvet.csv: guideline theo JOB; mỗi cảnh một split -----------------------------
    leaked = sorted(set(by_type.get("scene_leak", [])))
    scene_split = {}
    for sc, imgs in scene_images.items():
        splits = {meta[i]["split"] for i in imgs}
        scene_split[sc] = pick_split_for_scene(imgs, meta) if len(splits) > 1 else next(iter(splits))
    tv_rows = []
    for img in kept:
        m = meta[img]
        job = jobs[m["job_id"]]
        tv_rows.append({"image": img, "scene_id": m["scene_id"], "split": scene_split[m["scene_id"]],
                        "job_id": m["job_id"], "annotator": job["annotator"], "reviewer": job["reviewer"],
                        "guideline": job["guideline"]})
    write_csv(v2 / "truyvet.csv", ["image", "scene_id", "split", "job_id", "annotator", "reviewer", "guideline"], tv_rows)
    guideline_fixed = sorted(img for img in by_type.get("guideline_mismatch", []) if img in kept)

    # ---- 7. README.txt ----------------------------------------------------------------------
    bad_targets = {e["target"] for e in errors}  # mỗi ảnh (hoặc cảnh) tính một lần
    n_bad, n_all = len(bad_targets), len(manifest)
    rate = n_bad / n_all
    v1_decision = "Hold" if rate > THRESHOLD else "Release"
    by_guideline = defaultdict(list)
    for jid, j in sorted(jobs.items()):
        by_guideline[j["guideline"]].append(jid)
    guideline_txt = ", ".join(f"{g} ({js[0]}-{js[-1]})" if len(js) > 1 else f"{g} ({js[0]})"
                              for g, js in sorted(by_guideline.items()))
    pano_imgs = sorted(img for t in PANOPTIC for img in by_type.get(t, []) if img in kept)
    owners = sorted({f"{r['annotator']}/{r['reviewer']}" for r in rq_rows})

    notes = []
    if hash_fixed:
        notes.append(f"- wrong_hash: ảnh qua kiểm sơ bộ (JPEG hợp lệ) nên chỉ ghi lại sha256 đúng trong manifest.csv; cần người mở ảnh xác nhận nội dung còn đúng ({', '.join(hash_fixed)})")
    if hash_suspect:
        notes.append(f"- wrong_hash nhưng ảnh hỏng: chuyển vào rework_queue: {', '.join(hash_suspect)}")
    if guideline_fixed:
        notes.append(f"- guideline_mismatch: truyvet.csv lấy guideline theo job trong jobs.csv: {', '.join(guideline_fixed)}")
    if leaked:
        for sc in leaked:
            notes.append(f"- scene_leak: cảnh {sc} đưa về một split ({scene_split[sc]}) trong truyvet.csv")
    if rq_rows:
        notes.append(f"- Rework: {len(rq_rows)} ảnh tách khỏi v2, giao lại cho người gán/kiểm (annotator/reviewer): {', '.join(owners)}")
    if pano_imgs:
        notes.append(f"- Lỗi chỉ ở panoptic, ảnh ở lại v2, báo team panoptic: {', '.join(pano_imgs)}")

    lines = [
        f"Release: {rid}_v2",
        f"Parent: {rid}",
        f"Số ảnh: {len(kept)}",
        f"Số nhãn: {sum(counts.values())}",
        f"Guideline: {guideline_txt}",
        f"QC v1: {n_bad}/{n_all} = {rate * 100:.1f}%".replace(".", ","),
        f"Kết luận v1: {v1_decision} — {n_bad}/{n_all} ảnh/cảnh lỗi ({rate * 100:.1f}%), "
        f"{'vượt' if rate > THRESHOLD else 'không vượt'} ngưỡng 2% của Day 7".replace(".", ",", 1),
        f"Kết luận v2: {'Rework' if rq_rows else 'Release'} — tách {len(rq_rows)} ảnh vào rework, "
        f"sửa hash/guideline/split trong v2, giữ {len(kept)} ảnh",
        "Ghi chú:",
        *notes,
    ]
    (v2 / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"v2: {v2}")
    print(f"  ảnh giữ lại {len(kept)} | rework {len(rq_rows)} | nhãn {sum(counts.values())} | QC v1 {n_bad}/{n_all}")
    if hash_fixed or hash_suspect:
        print("  wrong_hash cần MỞ ẢNH kiểm bằng mắt:", ", ".join(hash_fixed + hash_suspect))
        print("  nếu ảnh nào hỏng, chạy lại với --damaged <ảnh>")
    print("Tiếp theo:")
    print(f"  py scripts/pack_release.py {v2}")
    print(f"  py scripts/lineage.py record --event release --release-id {rid}_v2 --parent {rid}")
    print(f"  py scripts/check_handover.py --run {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
