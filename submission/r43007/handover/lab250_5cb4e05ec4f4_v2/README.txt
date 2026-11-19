Release: lab250_5cb4e05ec4f4_v2
Parent: lab250_5cb4e05ec4f4
Số ảnh: 242
Số nhãn: 1638
Guideline: v1.2 (J01-J03), v1.3 (J04-J10)
QC v1: 18/250 = 7,2%
Kết luận v1: Hold — 18/250 ảnh/cảnh lỗi (7,2%), vượt ngưỡng 2% của Day 7
Kết luận v2: Rework — tách 8 ảnh vào rework, sửa hash/guideline/split trong v2, giữ 242 ảnh
Ghi chú:
- wrong_hash: ảnh qua kiểm sơ bộ (JPEG hợp lệ) nên chỉ ghi lại sha256 đúng trong manifest.csv; cần người mở ảnh xác nhận nội dung còn đúng (000000007511)
- guideline_mismatch: truyvet.csv lấy guideline theo job trong jobs.csv: 000000016451
- scene_leak: cảnh scene_150 đưa về một split (train) trong truyvet.csv
- Rework: 8 ảnh tách khỏi v2, giao lại cho người gán/kiểm (annotator/reviewer): A01/Q01, A03/Q01, A03/Q02, A05/Q02
- Lỗi chỉ ở panoptic, ảnh ở lại v2, báo team panoptic: 000000002587, 000000006213, 000000006723, 000000006818, 000000008277, 000000018380, 000000022479
