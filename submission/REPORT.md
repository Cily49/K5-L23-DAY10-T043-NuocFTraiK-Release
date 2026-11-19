# Báo cáo nhóm <<XX>>

## 1. Số liệu luyện tập
- F1 theo seed (rule / cross_check / overall): <<seed: ... / ... / ...>>
- Số ứng viên trên lô sạch (`--no-faults`): <<...>>; hàng đợi trên seed luyện tập: <<... ảnh>>
- Ngưỡng đã chọn và cách chọn (không dùng `_private`): <<...>>

## 2. Vì sao báo hết ứng viên làm F1 giảm?
<<Trả lời bằng số của nhóm.>>

## 3. Quyết định và lineage
- **Tỉ lệ ảnh lỗi (QC v1):** lấy số ảnh lỗi trong `errors.json` chia cho 250 ảnh của lô `lab250_5cb4e05ec4f4`. Mỗi ảnh chỉ tính một lỗi. Lỗi `scene_leak` cũng tính là một ảnh.
  - Số cuối từ `errors.json` đã chốt: **18/250 = 7,2%**. File có 19 mục, gồm 10 lỗi luật và 9 lỗi gán nhãn đã được cả nhóm xem ảnh và xác nhận (`confirmed`). Vì ảnh `000000017182` có hai mục (`bbox_drift` và `missing_box`) nên 19 mục chỉ ứng với 18 ảnh/cảnh khác nhau.
- **Kết luận: HOLD (không phát hành lô v1).** Quy tắc của Day 7 là hơn 2% ảnh lỗi thì không được Release. Với 250 ảnh, mức 2% tương đương 5 ảnh, mà lô có 18 ảnh lỗi (7,2%), tức hơn gấp ba lần ngưỡng. Riêng 10 lỗi luật đã vượt ngưỡng từ trước khi xem ảnh.
- **Vì sao tính theo tỉ lệ chứ không theo số lỗi:** cùng là 10 lỗi nhưng trong lô 250 ảnh thì rất nặng, còn trong lô 100.000 ảnh thì gần như không đáng kể. Tỉ lệ cho biết cả lô hỏng nhiều hay ít, nên dùng nó để quyết định có đem lô đi huấn luyện hay không.
- **Lineage (nhật ký truy vết):** file `runs/lineage.jsonl` chỉ thêm dòng mới, không sửa được. Hiện có các dòng: tạo lô (`inject`, seed 43007), lần huấn luyện `R-021` dùng lô này, và quyết định `HOLD` cho v1. Dòng `release` cho v2 (`lab250_5cb4e05ec4f4_v2`, lô cha là `lab250_5cb4e05ec4f4`) sẽ ghi sau khi chốt lô v2. [Cập nhật sau khi ghi.]
- **Vì sao `R-021` phải xem lại hoặc train lại:** khi chạy `lineage.py impact --release-id lab250_5cb4e05ec4f4` ta được `R-021: affected=True action=review_or_retrain`. `R-021` đã học từ lô v1 khi lô này còn lỗi. Sau đó dù sửa dataset thì model vẫn giữ những gì đã học, nó không tự được sửa theo. Vì vậy phải xem lại kết quả của `R-021` xem lỗi của lô có ảnh hưởng đến nó không, hoặc train lại trên lô v2.

## 4. Hash chứng minh gì, không chứng minh gì?
**Hash (sha256) giúp biết một điều:** file có bị thay đổi hay không. Nếu hash của file khớp với hash đã ghi thì file vẫn y nguyên như lúc ghi. Ở v2, `manifest.csv` ghi hash của mọi ảnh và nhãn, còn file `.sha256` giúp kiểm tra lại gói zip trên bất kỳ máy nào.

**Hash không cho biết những điều sau:**
- **Nhãn có đúng không.** Một nhãn gán sai vẫn có hash hợp lệ. Các lỗi như `class_swap` hay `bbox_drift` hash không phát hiện được.
- **Ảnh có đúng nội dung không.** Hash khớp chỉ có nghĩa là file chưa bị đổi, không có nghĩa ảnh không hỏng từ đầu.
- **Hash ghi trong manifest có đúng không.** Ví dụ ảnh `000000007511` bị `wrong_hash`. Tôi mở ảnh ra xem thì thấy ảnh bình thường (một người thả diều trên bãi biển), tức là chỉ manifest ghi sai hash. Vì vậy trong v2 vẫn giữ ảnh này và ghi lại hash đúng. Nếu ảnh bị hỏng thì phải đưa vào danh sách gán lại. Hash lệch chỉ báo "có chỗ không khớp", còn bên nào sai thì phải mở ảnh mới biết.
- Ngoài ra, `check_handover.py` báo PASS chỉ có nghĩa lô v2 đúng định dạng và số liệu khớp nhau, không có nghĩa nhãn đúng.

**Vì sao không ghi đè lên v1:** v1 là bản đã giao, và lần huấn luyện `R-021` đã dùng nó. Mã `release_id` được tính từ hash của `manifest.json` và `metadata.json`, nên nếu sửa v1 thì mã đổi, lineage và hash không còn khớp với những gì `R-021` đã học. Vì vậy bản sửa được làm riêng thành v2 và ghi rõ lô cha (`Parent: lab250_5cb4e05ec4f4`). Nhờ đó vẫn biết v1 gốc trông thế nào và run nào đã học từ bản nào. Việc kiểm tra v1 vẫn nguyên được làm bởi mã H1 của `check_handover.py`.

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
