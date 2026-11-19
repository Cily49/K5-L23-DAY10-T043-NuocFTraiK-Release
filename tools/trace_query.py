#!/usr/bin/env python3
"""Pha 5 — truy vết ticket của team AI.

  python tools/trace_query.py <delivery> --out <trace.json>

Đọc incoming/ticket.md (lớp bị báo + các scene team AI nêu) và guideline/changelog.md
(lớp bị đổi quy tắc ở phiên bản mới nhất). Tiêu chí:
  - "job guideline cũ": guideline ghi ở JOB trong jobs.csv khác phiên bản mới nhất trong changelog.
    KHÔNG dùng guideline_version ghi ở từng ảnh trong metadata.json vì đó có thể là lỗi guideline_mismatch.
  - "có lớp đó": ảnh có ít nhất một box detection lớp đó trong labels/ của lô (class_id hợp lệ 0–79).
  - tier_a: ảnh thoả hai điều kiện trên VÀ thuộc scene team AI đã nêu.
  - tier_b: ảnh thoả hai điều kiện trên nhưng ở scene khác (chưa ai báo).
  - notify: annotator + reviewer của các job chứa ảnh tier_a và tier_b.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Truy vết ticket -> trace.json")
    ap.add_argument("delivery")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    d = Path(args.delivery)

    ticket = (d / "incoming" / "ticket.md").read_text(encoding="utf-8")
    changelog = (d / "guideline" / "changelog.md").read_text(encoding="utf-8")

    # Phiên bản mới nhất = mục "## vX.Y" đầu tiên; lớp bị đổi quy tắc = lớp trong backtick của mục đó.
    sections = re.split(r"^##\s+", changelog, flags=re.M)[1:]
    latest = sections[0].split("\n", 1)[0].strip()
    rule_classes = set(re.findall(r"`([^`]+)`", sections[0]))
    ticket_classes = set(re.findall(r"`([^`]+)`", ticket))
    target = rule_classes & ticket_classes or rule_classes
    if len(target) != 1:
        raise SystemExit(f"không xác định được lớp bị đổi quy tắc: changelog={rule_classes} ticket={ticket_classes}")
    cls_name = target.pop()
    scenes = set(re.findall(r"scene_\w+", ticket))

    names = {}
    for line in (d / "classes.txt").read_text(encoding="utf-8").splitlines():
        if line.strip():
            i, n = line.split(" ", 1)
            names[n.strip()] = int(i)
    cls_id = names[cls_name]

    with (d / "jobs.csv").open(encoding="utf-8", newline="") as f:
        jobs = {r["job_id"]: r for r in csv.DictReader(f)}
    old_jobs = {j for j, r in jobs.items() if r["guideline"] != latest}
    meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))["items"]

    def has_class(name: str) -> bool:
        p = d / "labels" / f"{name}.txt"
        if not p.is_file():
            return False
        for ln in p.read_text(encoding="utf-8").splitlines():
            parts = ln.split()
            if parts and int(float(parts[0])) == cls_id:
                return True
        return False

    hit = [m for m in meta if m["job_id"] in old_jobs and has_class(m["image"])]
    tier_a = sorted(m["image"] for m in hit if m["scene_id"] in scenes)
    tier_b = sorted(m["image"] for m in hit if m["scene_id"] not in scenes)
    job_ids = sorted({m["job_id"] for m in hit})
    notify = sorted({jobs[j]["annotator"] for j in job_ids} | {jobs[j]["reviewer"] for j in job_ids})

    out = {"tier_a": tier_a, "tier_b": tier_b, "notify": notify}
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"lớp đổi quy tắc: {cls_name} (id {cls_id}); guideline mới nhất {latest}; job cũ: {sorted(old_jobs)}")
    print(f"scene team AI nêu: {sorted(scenes)}")
    print(f"tier_a {len(tier_a)} ảnh, tier_b {len(tier_b)} ảnh, job liên quan {job_ids}, notify {notify} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
