# Báo cáo nhóm <<XX>>

## 1. Số liệu luyện tập
- F1 theo seed (rule / cross_check / overall): <<seed: ... / ... / ...>>
- Số ứng viên trên lô sạch (`--no-faults`): <<...>>; hàng đợi trên seed luyện tập: <<... ảnh>>
- Ngưỡng đã chọn và cách chọn (không dùng `_private`): <<...>>

## 2. Vì sao báo hết ứng viên làm F1 giảm?
<<Trả lời bằng số của nhóm.>>

## 3. Quyết định và lineage
<<QC v1 a/b, kết luận, vì sao R-021 phải xem lại hoặc train lại.>>

## 4. Hash chứng minh gì, không chứng minh gì?
<<>>

## 5. Truy vết
Làm bằng `tools/trace_query.py` (đọc `incoming/ticket.md`, `guideline/changelog.md`, `jobs.csv`, `metadata.json`, `labels/`).

- **Lớp bị đổi quy tắc:** `cup` (changelog v1.3: cup bị che > 50% hoặc cắt mép **vẫn phải gán box**; v1.2 cho bỏ qua). Ticket team AI nêu scene_469 và scene_529.
- **Job guideline cũ:** job có `guideline` trong `jobs.csv` khác phiên bản mới nhất (v1.3) → J01, J02, J03 (v1.2).
- **"Có lớp cup":** ảnh có ít nhất một box detection class_id 41 (`cup`) trong `labels/` của lô.
- **tier_a** = job cũ + có cup + thuộc scene team AI nêu → 4 ảnh: `000000002592`, `000000002685`, `000000003845`, `000000003934`.
- **tier_b** = job cũ + có cup + scene khác, chưa ai báo → 3 ảnh: `000000002157`, `000000002431`, `000000003661`.
- **notify:** cả 7 ảnh đều thuộc J02 → báo người gán **A01** và người kiểm **Q02**. Không báo người của J01/J03 vì các job đó không có ảnh nào có `cup` (báo hết người của mọi job cũ là báo thừa).
- Tự đo bằng `score_findings.py`: truy vết F1 ≈ 1.0 (tier_a / tier_b / notify) trên seed 43007, 101 và 202.

**Vì sao lấy guideline theo job, không theo ảnh:** quy tắc mới áp dụng cho *job tạo sau khi v1.3 ban hành*, nên phiên bản thật sự người gán dùng là phiên bản ghi ở job. Trường `guideline_version` ở từng ảnh trong `metadata.json` có thể bị sai, đó chính là lỗi `guideline_mismatch` (lô 43007 có 1 ảnh như vậy). Lọc theo ảnh sẽ kéo nhầm một ảnh của job v1.3 vào (hoặc bỏ sót một ảnh của job v1.2).

**Tầng a khác tầng b:** tầng a là chỗ team AI đã thấy tận mắt (xác nhận được ngay); tầng b là cùng nguyên nhân gốc (job v1.2 + có cup) nhưng chưa ai báo. Đây là phạm vi ảnh hưởng thật, cần mở lại cùng đợt để không phải chờ ticket tiếp theo.

## 6. Bug hoặc điểm chưa rõ trong lab (nếu có)
<<>>
