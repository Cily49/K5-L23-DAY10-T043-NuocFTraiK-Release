"""Human image-review helper for the Day 10 COCO lab.

Usage from the repository root:
    py tools/review_images.py --delivery runs/r43007/delivery \
        --out runs/r43007/review_log.csv

This viewer is separate from the validator and reads only the supplied
delivery directory. It does not inspect _private or decide whether a case is
a real error; a reviewer supplies the verdict and visual evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError as exc:  # pragma: no cover - depends on local desktop setup
    raise SystemExit(
        "Pillow is required for this review viewer. Install it for the review "
        "tool, or use another image viewer."
    ) from exc


LOG_FIELDS = ["image", "type", "verdict", "note"]
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def load_classes(path: Path) -> dict[int, str]:
    classes: dict[int, str] = {}
    if not path.is_file():
        return classes
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2:
            try:
                classes[int(parts[0])] = parts[1]
            except ValueError:
                continue
    return classes


def segment_metadata(path: Path, image_id: str) -> tuple[dict[int, str], dict[int, tuple[int, int, int]]]:
    if not path.is_file():
        return {}, {}
    data = json.loads(path.read_text(encoding="utf-8"))
    category_names = {int(row["id"]): row["name"] for row in data.get("categories", [])}
    annotation = next(
        (row for row in data.get("annotations", []) if str(row.get("image_id")) == image_id),
        None,
    )
    if annotation is None:
        return {}, {}
    names: dict[int, str] = {}
    colors: dict[int, tuple[int, int, int]] = {}
    for index, segment in enumerate(annotation.get("segments_info", [])):
        segment_id = int(segment["id"])
        names[segment_id] = category_names.get(int(segment["category_id"]), "unknown")
        colors[segment_id] = (
            (67 + index * 97) % 220 + 30,
            (149 + index * 67) % 220 + 30,
            (211 + index * 43) % 220 + 30,
        )
    return names, colors


def add_panoptic_edges(image: Image.Image, mask_path: Path) -> Image.Image:
    """Overlay colored mask boundaries; labels are listed in the side panel."""
    if not mask_path.is_file():
        return image
    mask = Image.open(mask_path).convert("RGB")
    if mask.size != image.size:
        mask = mask.resize(image.size, Image.Resampling.NEAREST)
    mask_pixels = mask.load()
    width, height = mask.size
    overlay = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(height):
        for x in range(width):
            current = mask_pixels[x, y]
            segment_id = current[0] + current[1] * 256 + current[2] * 65536
            if segment_id == 0:
                continue
            is_edge = (
                (x > 0 and mask_pixels[x - 1, y] != current)
                or (x + 1 < width and mask_pixels[x + 1, y] != current)
                or (y > 0 and mask_pixels[x, y - 1] != current)
                or (y + 1 < height and mask_pixels[x, y + 1] != current)
            )
            if is_edge:
                color = ((segment_id * 71) % 200 + 55, (segment_id * 37) % 200 + 55, (segment_id * 19) % 200 + 55)
                draw.point((x, y), fill=(*color, 230))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def build_preview(delivery: Path, image_path: Path, classes: dict[int, str]) -> tuple[Image.Image, str]:
    image_id = image_path.stem
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    details = [f"Image: {image_path.name}"]
    label_path = delivery / "labels" / f"{image_id}.txt"
    if label_path.is_file():
        for row_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), 1):
            fields = line.split()
            if len(fields) != 5:
                details.append(f"Invalid YOLO row {row_number}: {line}")
                continue
            try:
                class_id = int(fields[0])
                cx, cy, box_w, box_h = map(float, fields[1:])
            except ValueError:
                details.append(f"Invalid YOLO row {row_number}: {line}")
                continue
            x1, y1 = (cx - box_w / 2) * width, (cy - box_h / 2) * height
            x2, y2 = (cx + box_w / 2) * width, (cy + box_h / 2) * height
            class_name = classes.get(class_id, f"class_{class_id}")
            draw.rectangle((x1, y1, x2, y2), outline=(40, 255, 80), width=max(2, width // 240))
            draw.text((x1 + 2, max(0, y1 - 14)), f"det: {class_name}", fill=(40, 255, 80), stroke_width=1, stroke_fill=(0, 0, 0))
            details.append(f"Detection: {class_name}")
    else:
        details.append("Detection label file is missing.")

    mask_path = delivery / "masks" / f"{image_id}.png"
    segment_names, _ = segment_metadata(delivery / "panoptic.json", image_id)
    image = add_panoptic_edges(image, mask_path)
    details.extend(f"Panoptic segment: {name}" for name in segment_names.values())
    if not mask_path.is_file():
        details.append("Panoptic mask is missing.")
    return image, "\n".join(details)


class ReviewViewer:
    def __init__(self, delivery: Path, output: Path, selected_image: str | None = None):
        self.delivery = delivery
        self.output = output
        self.classes = load_classes(delivery / "classes.txt")
        self.images = sorted(
            path for path in (delivery / "images").iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        )
        if selected_image:
            wanted = Path(selected_image).stem
            self.images = [path for path in self.images if path.stem == wanted]
            if not self.images:
                raise SystemExit(f"Image not found in delivery/images: {selected_image}")
        if not self.images:
            raise SystemExit(f"No images found in {delivery / 'images'}")
        self.index = 0
        self.photo = None

        self.root = tk.Tk()
        self.root.title("Day 10 Lab — Image Review")
        self.root.geometry("1120x820")
        self.root.minsize(760, 560)
        self.canvas = tk.Canvas(self.root, background="#202124", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        panel = ttk.Frame(self.root, padding=10, width=320)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)

        self.heading = ttk.Label(panel, text="", wraplength=290)
        self.heading.pack(anchor="w", pady=(0, 8))
        self.info = tk.Text(panel, height=18, width=36, wrap="word", state="disabled")
        self.info.pack(fill="x", pady=(0, 10))
        ttk.Label(panel, text="Loại ứng viên (nhập theo danh sách nhóm)").pack(anchor="w")
        self.kind = ttk.Entry(panel)
        self.kind.pack(fill="x", pady=(2, 10))
        ttk.Label(panel, text="Người review").pack(anchor="w")
        self.reviewer = ttk.Entry(panel)
        self.reviewer.pack(fill="x", pady=(2, 10))
        ttk.Label(panel, text="Ghi chú: mô tả điều nhìn thấy trong ảnh").pack(anchor="w")
        self.note = tk.Text(panel, height=5, width=36, wrap="word")
        self.note.pack(fill="x", pady=(2, 10))

        verdicts = ttk.Frame(panel)
        verdicts.pack(fill="x", pady=(0, 10))
        ttk.Button(verdicts, text="Confirmed", command=lambda: self.save("confirmed")).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(verdicts, text="Rejected", command=lambda: self.save("rejected")).pack(side="left", expand=True, fill="x", padx=(4, 0))
        navigation = ttk.Frame(panel)
        navigation.pack(fill="x")
        ttk.Button(navigation, text="← Trước", command=lambda: self.move(-1)).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(navigation, text="Tiếp →", command=lambda: self.move(1)).pack(side="left", expand=True, fill="x", padx=(4, 0))
        ttk.Label(panel, text=f"CSV sẽ ghi vào:\n{output}", wraplength=290).pack(anchor="w", pady=(12, 0))
        self.root.bind("<Left>", lambda _event: self.move(-1))
        self.root.bind("<Right>", lambda _event: self.move(1))
        self.root.bind("<Configure>", self.on_resize)
        self.render()

    def render(self) -> None:
        path = self.images[self.index]
        preview, details = build_preview(self.delivery, path, self.classes)
        self.heading.configure(text=f"{self.index + 1}/{len(self.images)} — {path.name}")
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", details)
        self.info.configure(state="disabled")
        self.preview = preview
        self.show_preview()

    def show_preview(self) -> None:
        if not hasattr(self, "preview"):
            return
        self.root.update_idletasks()
        max_width = max(200, self.canvas.winfo_width() - 12)
        max_height = max(200, self.canvas.winfo_height() - 12)
        resized = self.preview.copy()
        resized.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(resized)
        self.canvas.delete("all")
        self.canvas.create_image(max_width // 2, max_height // 2, image=self.photo, anchor="center")

    def on_resize(self, event: tk.Event) -> None:
        if event.widget is self.root:
            self.show_preview()

    def move(self, offset: int) -> None:
        self.index = (self.index + offset) % len(self.images)
        self.render()

    def save(self, verdict: str) -> None:
        image_id = self.images[self.index].stem
        kind = self.kind.get().strip()
        note = self.note.get("1.0", "end").strip()
        reviewer = self.reviewer.get().strip()
        if not kind:
            messagebox.showwarning("Thiếu loại lỗi", "Nhập type ứng viên, ví dụ class_swap hoặc bbox_drift.")
            return
        if len(note) < 20:
            messagebox.showwarning("Ghi chú quá ngắn", "Hãy mô tả điều nhìn thấy trong ảnh (ít nhất 20 ký tự).")
            return
        if reviewer:
            note = f"{note} [reviewer: {reviewer}]"
        self.output.parent.mkdir(parents=True, exist_ok=True)
        needs_header = not self.output.exists() or self.output.stat().st_size == 0
        with self.output.open("a", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
            if needs_header:
                writer.writeheader()
            writer.writerow({"image": image_id, "type": kind, "verdict": verdict, "note": note})
        messagebox.showinfo("Đã ghi review", f"Đã thêm {image_id}, {kind}, {verdict} vào review log.")

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Xem ảnh và ghi verdict review do người đưa ra.")
    parser.add_argument("--delivery", type=Path, default=Path("runs/r43007/delivery"), help="Thư mục delivery cần xem")
    parser.add_argument("--out", type=Path, default=Path("runs/r43007/review_log.csv"), help="CSV review log; bản ghi được thêm vào cuối file")
    parser.add_argument("--image", help="Chỉ mở một ảnh theo tên hoặc image id, ví dụ 000000000139")
    args = parser.parse_args()
    delivery = args.delivery.resolve()
    if not delivery.is_dir():
        parser.error(f"delivery directory does not exist: {delivery}")
    ReviewViewer(delivery, args.out, args.image).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
