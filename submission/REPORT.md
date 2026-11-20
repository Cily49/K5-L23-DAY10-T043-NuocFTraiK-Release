# Báo cáo nhóm T043 — NuocFTraiK

## 1. Số liệu luyện tập
- **F1 theo seed** (lỗi luật / lỗi gán nhãn / tổng), đo bằng `score_findings.py` (chỉ in số làm tròn):

  | Seed | `errors.json` dùng để đo | Lỗi luật | Lỗi gán nhãn | Tổng |
  |---|---|---|---|---|
  | 43007 (luyện tập) | bản nộp cuối: 10 lỗi luật + 9 lỗi gán nhãn `confirmed` | ≈ 1.0 | ≈ 0.6 | ≈ 0.8 |
  | 43007 | chỉ lỗi luật của validator (10 mục) | ≈ 1.0 | — | ≈ 0.7 |
  | 11 | chỉ lỗi luật (13 mục) | ≈ 1.0 | — | ≈ 0.8 |
  | 101 | chỉ lỗi luật (14 mục) | ≈ 1.0 | — | ≈ 0.8 |
  | 2024 | chỉ lỗi luật (12 mục) | ≈ 1.0 | — | ≈ 0.8 |
  | 777 | chỉ lỗi luật (15 mục) | ≈ 1.0 | — | ≈ 0.8 |

  Nhóm chỉ xem ảnh trên seed 43007, nên các seed khác chỉ có lỗi luật ("—" là chưa nộp lỗi gán nhãn nào).
- **Số ứng viên:**
  - Lô sạch (`inject_release.py --seed 5 --no-faults`, 50 ảnh khác bộ luyện tập): **0 lỗi luật**, **13 ứng viên**. Lô này không có lỗi cài vào, nên cả 13 ứng viên là lệch tự nhiên của COCO.
  - Seed 43007: **51 ứng viên trên 29 ảnh** (hàng đợi xem ảnh). Các seed khác cũng tương tự: 51–52 ứng viên trên 30–32 ảnh.
- **Ngưỡng và cách chọn** (chỉ dùng `delivery/` và lô sạch, không đọc `_private/`):
  - *Lỗi luật:* `duplicate_box` chỉ báo khi hai box cùng lớp có kích thước lệch ≤ 1,5 px và tâm lệch ≤ 3 px. Không dùng IoU, vì theo GUIDE thì COCO có cặp box thật chồng nhau tới IoU ≈ 0,66. `bbox_out_of_bounds` cho sai số 1e-4 để bỏ qua lỗi làm tròn số thực. Với các ngưỡng này, lô sạch không có lỗi luật nào.
  - *Ứng viên (đối chiếu detection ↔ panoptic):* chỉ xét segment thing có ít nhất 1024 pixel. Box và segment được ghép theo tỉ lệ phủ pixel của mask trong box, không chỉ theo IoU bbox. Các ngưỡng chính:
    - đổi lớp khi segment phủ ≥ 55% và box phủ ≥ 25%;
    - gộp instance khi segment phủ ≥ 30% mỗi box;
    - box lệch khi tâm lệch ≥ 15% hoặc kích thước lệch ≥ 20%.
  - Cách chỉnh: chạy trên lô sạch để đếm ứng viên do lệch tự nhiên, rồi chạy trên seed 43007 để xem hàng đợi có vừa sức 5 người xem trong thời gian Pha 2 không. Kết quả là 13 ứng viên trên lô sạch và 29 ảnh trên lô luyện tập, mỗi người khoảng 6 ảnh. Nhóm không siết thêm vì ghép lỏng hơn thì hàng đợi to ra, còn siết chặt hơn thì dễ bỏ sót lỗi thật.

## 2. Vì sao báo hết ứng viên làm F1 giảm?
Nhóm thử đưa thẳng cả 51 ứng viên của seed 43007 vào `errors.json` mà không xem ảnh (cùng với 10 lỗi luật), rồi chấm lại:

| Cách nộp | Số mục | Lỗi gán nhãn F1 | Tổng F1 |
|---|---|---|---|
| Chỉ lỗi luật | 10 | — | ≈ 0.7 |
| Lỗi luật + **toàn bộ 51 ứng viên** | 61 | ≈ 0.1 | ≈ 0.4 |
| Lỗi luật + 9 ứng viên đã xem ảnh và `confirmed` (bản nộp) | 19 | ≈ 0.6 | ≈ 0.8 |

Lý do:
- **Ứng viên chỉ là giả thuyết.** Sau khi xem ảnh, nhóm chỉ `confirmed` 9/51 ứng viên. Nếu nộp hết thì có khoảng 42 mục báo sai (false positive), precision tụt mạnh nên F1 giảm, dù recall có thể tăng một chút.
- **Một ảnh có thể ra nhiều giả thuyết, nhưng mỗi ảnh mang nhiều nhất một lỗi.** 51 ứng viên chỉ nằm trên 29 ảnh, nên dù đoán may thì ít nhất 22 mục chắc chắn sai.
- **COCO tự nó đã lệch.** Lô sạch không có lỗi cài vào mà vẫn ra 13 ứng viên. Những lệch tự nhiên này sẽ thành báo sai nếu không có người xem ảnh để `rejected`.

Kết luận: cộng nhiều ứng viên vào `errors.json` không làm điểm tăng. Phải có bước người xem ảnh để lọc, và số 0.4 so với 0.8 trong bảng trên cho thấy bước này đáng công.

## 3. Quyết định và lineage
- **Tỉ lệ ảnh lỗi (QC v1):** lấy số ảnh lỗi trong `errors.json` chia cho 250 ảnh của lô `lab250_5cb4e05ec4f4`. Mỗi ảnh chỉ tính một lỗi. Lỗi `scene_leak` cũng tính là một ảnh.
  - Số cuối từ `errors.json` đã chốt: **18/250 = 7,2%**. File có 19 mục, gồm 10 lỗi luật và 9 lỗi gán nhãn đã được cả nhóm xem ảnh và xác nhận (`confirmed`). Vì ảnh `000000017182` có hai mục (`bbox_drift` và `missing_box`) nên 19 mục chỉ ứng với 18 ảnh/cảnh khác nhau.
- **Kết luận: HOLD (không phát hành lô v1).** Quy tắc của Day 7 là hơn 2% ảnh lỗi thì không được Release. Với 250 ảnh, mức 2% tương đương 5 ảnh, mà lô có 18 ảnh lỗi (7,2%), tức hơn gấp ba lần ngưỡng. Riêng 10 lỗi luật đã vượt ngưỡng từ trước khi xem ảnh.
- **Vì sao tính theo tỉ lệ chứ không theo số lỗi:** cùng là 10 lỗi nhưng trong lô 250 ảnh thì rất nặng, còn trong lô 100.000 ảnh thì gần như không đáng kể. Tỉ lệ cho biết cả lô hỏng nhiều hay ít, nên dùng nó để quyết định có đem lô đi huấn luyện hay không.
- **Lineage (nhật ký truy vết):** file `runs/lineage.jsonl` chỉ thêm dòng mới, không sửa được. Có các dòng: tạo lô (`inject`, seed 43007), lần huấn luyện `R-021` dùng lô này, quyết định `HOLD` cho v1, và sự kiện `release` cho v2 (`lab250_5cb4e05ec4f4_v2`, lô cha là `lab250_5cb4e05ec4f4`) được ghi sau khi lô v2 chốt.
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
- **`release_id` của lô v1 khác nhau giữa các máy dù cùng seed.**
  - Trên máy của Bình (macOS), `inject_release.py --seed 43007` ra `lab250_9ad14f1e765d`, chạy lại 2 lần vẫn ra đúng id này. Lô v2 trong `submission/` được dựng trên máy của thành viên khác, từ lô `lab250_5cb4e05ec4f4`.
  - So `manifest` của hai lô: 483 hash giống nhau, chỉ khác 1 mục. Ảnh và nhãn YOLO giống nhau.
  - Nhóm đoán nguyên nhân là file mask PNG được nén khác nhau tuỳ phiên bản Python/zlib, nên hash khác, kéo theo `release_id` khác. Điều này chưa được kiểm chứng.
  - Hệ quả: `check_handover.py` chạy trên máy khác với máy đã sinh lô sẽ không tìm thấy v1/v2 đúng tên, và mục H1 có thể FAIL dù nội dung lô không đổi. Nhóm đề nghị giảng viên chấm H1 theo nội dung ảnh/nhãn, hoặc tính `release_id` không phụ thuộc cách nén PNG.
- **Ảnh `000000017182` có hai mục trong `errors.json`** (`bbox_drift` và `missing_box`), trong khi GUIDE nói mỗi ảnh mang nhiều nhất một lỗi. Nhóm đã ghi rõ trường hợp này ở mục 3 nhưng chưa rõ sẽ được chấm thế nào.
