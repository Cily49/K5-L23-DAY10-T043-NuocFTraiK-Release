# Bảo mật khi làm việc

> Gắn với lô `lab250_5cb4e05ec4f4` (seed 43007, 250 ảnh, 10 job J01–J10) nhóm vừa bàn giao.

## 1. Ca USB: hết giờ, muốn chép lô về nhà làm tiếp
Không chép. Lô `lab250_5cb4e05ec4f4` có ảnh người thật nhìn rõ mặt (ví dụ `000000001296`, `000000016598`), lại kèm `jobs.csv` ghi mã người gán/người kiểm và `manifest.json` của bản v1 đang HOLD. USB rời khỏi máy công ty là dữ liệu đã ra ngoài vùng kiểm soát: mất USB là lộ cả lô, và không còn biết ai đã giữ bản nào (lineage chỉ ghi được những gì xảy ra trong hệ thống). Gửi về email cá nhân hay nhờ người khác làm hộ cũng sai theo cùng một lý do: dữ liệu ra khỏi hệ thống được cấp quyền, và người kia không có quyền với job. Cách đúng: dừng ở job đang làm, lưu tiến độ trên CVAT/máy công ty, báo trưởng nhóm nếu trễ hạn để xin gia hạn hoặc chia lại job; nếu thật sự cần làm từ xa thì dùng VPN/máy ảo công ty đã được cấp phép.

## 2. Năm việc: được hay không
- **Mở job được giao trên máy công ty: ĐƯỢC.** Đúng người, đúng job, đúng thiết bị; ví dụ A01 mở J02 trên máy công ty để sửa box `cup` theo ticket.
- **Chụp màn hình gửi người quen: KHÔNG.** Ảnh chụp màn hình là bản sao dữ liệu nằm ngoài hệ thống, không xoá được, không truy vết được; trong lô có ảnh mặt người rõ.
- **Chép lô ra USB: KHÔNG.** Như mục 1: mất kiểm soát bản sao, phá lineage (v1 HOLD có thể bị dùng nhầm để train).
- **Dán nhãn thật lên chatbot: KHÔNG.** Dữ liệu dự án thật gửi lên dịch vụ bên ngoài có thể bị lưu hoặc dùng để train. Lab này chỉ được dán vì COCO là dữ liệu công khai, và nhóm đã ghi lại trong `prompts.md`.
- **Đưa tài khoản CVAT cho đồng nghiệp: KHÔNG.** Mọi thao tác sẽ ghi dưới tên mình, nên `rework_queue.csv` và `truyvet.csv` (giao lỗi theo annotator/reviewer) sẽ chỉ sai người. Đồng nghiệp cần quyền thì xin quản lý cấp tài khoản và job riêng.

## 3. Ca khuôn mặt: thấy mặt người rõ trong lô, guideline yêu cầu làm mờ
Trong lô có nhiều ảnh mặt người nhìn rõ, chưa làm mờ, ví dụ `000000001296` (cô gái cầm điện thoại, đám đông phía sau; scene_490, split val, job J01) và `000000016598` (người tóc xanh chụp ảnh qua gương; scene_102, split train, job J07). Kết luận: **Hold** lô, không Release và không đưa vào train cho đến khi xử lý xong. Báo ngay **người phụ trách dữ liệu / trưởng dự án** (và DPO nếu có), kèm danh sách tên ảnh, scene, job, để họ quyết định làm mờ theo quy trình chuẩn hoặc loại ảnh. Người gán **không tự làm mờ hay xoá ảnh**: tự sửa ảnh làm sai hash so với manifest, phá lineage (không ai biết bản nào đã sửa, sửa thế nào), có thể làm mờ sót hoặc làm hỏng nhãn, và quyết định xử lý dữ liệu cá nhân không thuộc quyền của người gán. Việc sửa phải tạo bản mới (v3) có lô cha, ghi lại trong lineage như cách nhóm đã làm với v2.
