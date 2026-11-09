# Báo cáo bước 1.A — Văn bản sạch (Hán / Phiên âm / Dịch nghĩa) của 35 văn bia có ảnh

Người thực hiện: Tuấn (A) · 09/11/2026 · Hạn 1.A: T4 11/11/2026

> Báo cáo không trích câu của sách; chỉ có số liệu, STT, số trang và mô tả loại sai lệch.
> **Quy ước (giảng viên phản hồi 09/11/2026):** không tách theo mặt bia. Mỗi văn bia giữ nguyên bài, một bộ 3 file; tên file = các mã mặt bia có ảnh nối bằng `_`
> (vd `02440-21_02441-22`; bia 1 mặt: `02439`). Định dạng nối `_` là giả định, chờ Phong/giảng viên xác nhận. Ánh xạ: `data/metadata/stt_bia_map.csv`, `data/metadata/van_ban_ma_bia.csv`.

## 1. Kết quả

- **35/35 văn bia đều ghi đủ bộ 3 file** ở `data/processed/{Chu_Han,Phien_am,Dich_nghia}/<tên>.txt` (105 file); checker `check_van_ban_sach` (V1–V8) → **0 lỗi** (`reports/check_van_ban_*.txt`).
- Phủ **76/76 mặt bia có ảnh**.
- Tổng: 16.840 chữ Hán (319 dòng), 16.171 âm tiết Phiên âm (1024 dòng), 1782 dòng Dịch nghĩa.
- **2 bia thiếu một loại văn bản trong sách** (theo quyết định của Tuấn 09/11: vẫn đưa vào, loại không có để **file rỗng 0 byte**):
  - STT 13 (`02462`): `Phien_am` rỗng — sách không có mục Phiên âm (chỉ có Hán và Dịch nghĩa) ⇒ không có cặp Hán–Phiên âm–Dịch nghĩa ở bước 4.
  - STT 52 (`02497-21_02498-22`): `Chu_Han` rỗng — sách không có chữ Hán ⇒ không gióng được với box OCR ở bước 3.

### Số liệu từng văn bia

| STT | Tên file | Mặt có ảnh / sách ghi | Trang sách | Dòng Hán | Chữ Hán | Dòng PA | Âm tiết PA | Dòng DN | PA/Hán | Ghi chú |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | `02459-31_02460-32_02461-33` | 3 / 3 | 44-52 | 8 | 516 | 20 | 508 | 39 | 0.98 |  |
| 4 | `02335-21_02336-22` | 2 / 2 | 61-70 | 15 | 634 | 34 | 565 | 42 | 0.89 | tỉ lệ lệch |
| 5 | `02343-21_02344-22` | 2 / 2 | 70-80 | 25 | 558 | 37 | 560 | 65 | 1.00 |  |
| 6 | `02464-21_02465-22` | 2 / 2 | 80-89 | 9 | 511 | 36 | 525 | 106 | 1.03 |  |
| 7 | `02467-21_02468-22` | 2 / 2 | 89-98 | 6 | 556 | 38 | 558 | 89 | 1.00 |  |
| 8 | `02340-31_02341-32_02342-33` | 3 / ? | 98-109 | 9 | 704 | 63 | 1036 | 64 | 1.47 | tỉ lệ lệch |
| 9 | `02333-21_02334-22` | 2 / 2 | 109-114 | 4 | 418 | 22 | 408 | 29 | 0.98 |  |
| 10 | `02337-31_02338-32_02339-33` | 3 / 3 | 114-121 | 7 | 618 | 30 | 390 | 41 | 0.63 | tỉ lệ lệch |
| 11 | `02331-21_02332-22` | 2 / 2 | 121-128 | 21 | 554 | 28 | 398 | 59 | 0.72 | tỉ lệ lệch |
| 13 | `02462` | 1 / 1 | 137-143 | 7 | 194 | 0 | 0 | 62 | — | Phien_am rỗng |
| 15 | `02329-21_02330-22` | 2 / 2 | 149-154 | 4 | 451 | 26 | 384 | 46 | 0.85 | tỉ lệ lệch |
| 16 | `02437-21_02438-22` | 2 / 2 | 155-158 | 8 | 209 | 18 | 234 | 34 | 1.12 |  |
| 20 | `02444-21_02479-22` | 2 / 2 | 193-198 | 2 | 522 | 32 | 445 | 37 | 0.85 | cảnh báo giả (xem §4); tỉ lệ lệch |
| 21 | `02442-21_02443-22` | 2 / 2 | 199-203 | 6 | 249 | 14 | 204 | 12 | 0.82 | tỉ lệ lệch |
| 22 | `02440-21_02441-22` | 2 / 2 | 203-207 | 4 | 277 | 17 | 335 | 35 | 1.21 | tỉ lệ lệch |
| 23 | `02477-21_02478-22` | 2 / 2 | 208-212 | 6 | 296 | 18 | 288 | 23 | 0.97 |  |
| 24 | `02480-21_02481-22` | 2 / 2 | 212-216 | 5 | 205 | 12 | 196 | 49 | 0.96 |  |
| 25 | `02439` | 1 / 1 | 217-219 | 5 | 191 | 15 | 192 | 13 | 1.01 |  |
| 27 | `02434-21_02435-22` | 2 / 1 | 234-238 | 4 | 297 | 16 | 297 | 17 | 1.00 | không đọc số tiêu đề Hán; sách chỉ chép 1 mặt; Vietnamica có 2 mặt, đã xác nhận (văn bản sách có thể chỉ ứng với một phần các mặt) |
| 28 | `02432-21_02433-22` | 2 / 2 | 238-244 | 12 | 334 | 24 | 342 | 25 | 1.02 |  |
| 43 | `02466-21_02469-22` | 2 / 2 | 275-288 | 8 | 943 | 55 | 953 | 52 | 1.01 |  |
| 44 | `02473-41_02474-42_02475-43_02476-44` | 4 / 4 | 289-299 | 20 | 677 | 40 | 669 | 59 | 0.99 | tr.290 từ gemini-3.5-flash |
| 45 | `02455-21_02456-22` | 2 / 2 | 300-311 | 17 | 936 | 39 | 656 | 68 | 0.70 | tỉ lệ lệch |
| 46 | `02471-21_02472-22` | 2 / 2 | 311-321 | 17 | 761 | 50 | 661 | 72 | 0.87 | tỉ lệ lệch |
| 47 | `02493-41_02494-42_02495-43_02496-44` | 4 / 4 | 322-335 | 18 | 984 | 46 | 793 | 77 | 0.81 | tỉ lệ lệch |
| 48 | `02453-21_02454-22` | 2 / 2 | 335-344 | 8 | 686 | 45 | 696 | 62 | 1.01 |  |
| 49 | `02487-21_02488-22` | 2 / 2 | 345-352 | 10 | 517 | 28 | 520 | 49 | 1.01 |  |
| 50 | `02457-21_02458-22` | 2 / 2 | 352-359 | 5 | 352 | 30 | 401 | 43 | 1.14 |  |
| 51 | `02482-21_02483-22` | 2 / 2 | 359-366 | 3 | 468 | 38 | 501 | 57 | 1.07 |  |
| 52 | `02497-21_02498-22` | 2 / 2 | 367-373 | 0 | 0 | 26 | 458 | 47 | — | Chu_Han rỗng |
| 56 | `02436` | 1 / 2 | 384-392 | 17 | 397 | 21 | 423 | 27 | 1.07 | sách ghi 2 mặt; Vietnamica chỉ có 1 mặt, đã xác nhận (lấy nguyên bài) |
| 60 | `02485-21_02486-22` | 2 / 2 | 411-419 | 5 | 445 | 26 | 369 | 103 | 0.83 | tỉ lệ lệch |
| 62 | `02489-41_02490-42_02491-43_02492-44` | 4 / 4 | 430-439 | 6 | 432 | 37 | 491 | 65 | 1.14 |  |
| 64 | `02470-21_02484-22` | 2 / 2 | 443-451 | 4 | 408 | 25 | 405 | 64 | 0.99 | không đọc số tiêu đề Hán |
| 65 | `02531-21_02532-22` | 2 / 4 | 451-458 | 14 | 540 | 18 | 310 | 50 | 0.57 | tỉ lệ lệch; sách ghi 4 mặt; Vietnamica chỉ có 2 mặt, đã xác nhận (lấy nguyên bài) |

## 2. Quy trình (một lệnh, chạy lại được, không sửa `data/raw`)

`python -m src.step1_book_mining.pipeline_1a [--bia …] [--khong-ocr] [--zip]`

1. **OCR** (`ocr_gemini.py`): Google AI Studio `gemini-3.5-flash-lite`, temperature 0, tối đa 8192 token ra, 12 yêu cầu/phút; chỉ trang chưa có. Tổng **282 trang** sách (gồm 1 trang bằng model dự phòng `gemini-3.5-flash`); chỉ gửi trang sách nhóm 3.
2. **Tách & làm sạch** (`clean_book_text.py` + `regex_filter.py`): máy trạng thái theo cấu trúc sách (Hán → tiêu đề Việt → thông tin → Phiên âm → Dịch nghĩa → dừng ở Hán/tiêu đề của bia kế); bỏ nhãn, thông tin hành chính, số trang, chú thích cuối trang, đoạn giới thiệu di tích, `○○○`, markdown/LaTeX; Hán chỉ giữ chữ Hán và dấu câu; Việt chuẩn hoá khoảng trắng/dấu câu, cắt mỗi câu một dòng.
3. **Ghi** nguyên bài theo mã bia + file kê mã `data/metadata/van_ban_ma_bia.csv`.
4. **Kiểm tra** checker V1–V8 + cờ tự động (tỉ lệ âm tiết Phiên âm / chữ Hán ngoài 0,9–1,15; chưa gặp điểm kết thúc; số tiêu đề Hán ≠ STT).
5. **Báo cáo máy** `reports/pipeline_1a_<ngày>.tsv` (không chứa nội dung sách); đóng gói `make_handover_zip.py`.

**Không có bước rà soát/sửa tay từng chữ** (quyết định: pipeline phải chạy hàng loạt, làm sạch chung bằng quy tắc). Kiểm thử quy tắc: `tests/test_regex_filter.py`, `tests/test_pipeline_1a.py` (23 test, dữ liệu tự tạo).

## 3. Chất lượng và giới hạn (cần biết khi dùng dữ liệu)

- **Chữ Hán là kết quả OCR, chưa đối chiếu ảnh.** Số đo ban đầu trên 4 trang mẫu (08/11): CER Hán 2,6–4,4%, Việt ≈ 0%. OCR không tất định ở temperature 0. Lỗi điển hình: dị thể bị đổi sang chữ chuẩn, nhầm chữ gần giống, thỉnh thoảng chép nhầm cả cụm. Các lỗi này **còn nằm trong dữ liệu**.
- **Sách khác bia thật:** Hán trong sách bị rút gọn (`○○○`, bỏ các danh sách ruộng đất…), dùng chữ số thường còn đá dùng số kép, có chỗ khác chữ. Hệ quả ở bước 3: nhiều box trên ảnh sẽ không có chữ đúng để gióng (⇒ `needs_review`); ở bước 4: Dịch nghĩa thường dài hơn Hán/Phiên âm nên nhiều dòng Dịch nghĩa không có cặp.
- **Tỉ lệ âm tiết Phiên âm / chữ Hán** (kỳ vọng ≈ 1): trung vị 0.99, nhỏ nhất 0.57, lớn nhất 1.47; 20/33 bia trong 0,9–1,15. Cờ `TI_LE_LECH` ở 13 bia (STT 4, 8, 10, 11, 15, 20, 21, 22, 45, 46, 47, 60, 65): chủ yếu do sách rút gọn Hán hoặc Phiên âm (đã xác nhận bằng ảnh ở bia 22: sách bỏ khoảng 13 dòng danh sách ruộng đất ở mặt sau). Chưa kiểm từng bia.
- **Hán trong sách không chia câu** (nhiều bia chỉ 1–5 dòng dài) trong khi Phiên âm chia 12–60 dòng ⇒ bước 4 phải tự chia Hán theo câu trước khi gióng.
- **Bia nhiều mặt:** lấy nguyên bài. Đã bổ sung 7 mặt `DanhSach.xlsx` bỏ sót (đối chiếu Vietnamica, Tuấn 09/11): STT 7 `02468-22`, 27 `02435-22`, 28 `02433-22`, 62 `02490-42`, `02491-43`, `02492-44`, 64 `02484-22` (tên gốc trên Vietnamica `02484&02470-22`) — ghi ở `data/metadata/bo_sung_mat_bia.csv`, không sửa xlsx. Còn lệch nhưng đã xác nhận: STT 56 (sách ghi 2 mặt, Vietnamica chỉ có 1) và 65 (sách 4 mặt, Vietnamica chỉ có 2) ⇒ văn bản chứa cả phần của mặt không có ảnh. STT 27: sách chỉ chép 1 mặt nhưng Vietnamica có 2 mặt — đã bổ sung `02435-22` (mặt sau; Tuấn 09/11) ⇒ văn bản sách có thể chỉ ứng với mặt trước `02434-21`.

## 4. Sự cố đã gặp và cách xử lý (đã sửa trong pipeline)

| Vấn đề | Cách xử lý |
|---|---|
| Chú thích cuối trang lọt vào Dịch nghĩa (khoảng 14 bia; kiểu `¹ …`, `1 Chính giác:`) | Gặp dòng chú thích hoặc đường kẻ ngăn thì bỏ phần còn lại của trang. Kiểm lại: 0 dòng rò |
| Markdown, LaTeX (`**…**`, `$^1$`), chỉ số trên trong phản hồi Gemini | Làm sạch bằng quy tắc chung; không còn ký tự lạ |
| Gemini **lặp** ở 7 trang (một cụm lặp, hoặc các dòng dài dần cùng đuôi); có trang làm 1 bia phình tới 4.900 chữ Hán | Phát hiện lặp (cụm lặp liên tiếp; đoạn 12 chữ Hán lặp ≥ 4 lần) → không lưu, thử lại temperature 0,3 → 0,7; trang lỗi cũ bị xoá để không dùng nhầm. 6/7 trang sửa được bằng flash-lite (tr.45, 115, 302, 412 sau khi OCR lại; tr.312, 360 bằng prompt `mixed`); trang còn lại xem dòng dưới |
| tr.290 (bia 44) bị chữ in xuyên trang nặng, flash-lite lặp hoặc ra chữ sai ở mọi cách thử (3 nhiệt độ, `mixed`, nhị phân hoá ảnh) | Dùng **`gemini-3.5-flash`** cho riêng trang này (Tuấn đồng ý 09/11); nội dung khớp ảnh; báo cáo ghi rõ. Một chữ nghi nhầm, giữ nguyên |
| Trang OCR bị dừng sớm (`MAX_TOKENS`), rỗng hoặc bị chặn | Không lưu; lần chạy sau tự thử lại; bia chứa trang đó báo `THIEU_OCR` thay vì ghi dữ liệu thiếu |
| Dịch nghĩa bị cụt / nhầm bia do số trang trong mục lục chỉ gần đúng | Đọc tới đầu bia kế (tối đa +2 trang); kiểm số ở tiêu đề Hán = STT; cảnh báo nếu chưa gặp điểm kết thúc |
| Câu bị ngắt ở cuối trang | Nối khi đoạn trước chưa hết câu và dòng sau viết thường |
| Bia không có chữ Hán (52) hoặc không có mục Phiên âm (13): máy trạng thái không vào được khối Hán / checker coi file rỗng là lỗi | Máy trạng thái nhận tiêu đề Việt làm điểm vào khi không có Hán; ghi file rỗng 0 byte cho loại thiếu; checker V1–V8 chấp nhận file 0 byte (file chỉ có dòng trống vẫn là lỗi V4) |
| File cũ còn sót khi chạy lại; một bia lỗi làm dừng cả lần chạy | Xoá file cũ trước khi ghi; lỗi được cô lập từng bia (`LOI_XU_LY`) |
| `DanhSach.xlsx` bỏ sót mặt bia (STT 7, 27, 28, 62, 64) | Tải bổ sung 7 ảnh; file bổ sung riêng; pipeline có bước **kiểm tra đồng bộ** processed ⇔ kê mã ⇔ `stt_bia_map` ⇔ ảnh ⇔ `inventory` (hiện: KHỚP) |

**Cảnh báo còn lại, đã kiểm và không ảnh hưởng dữ liệu:**
- Bia 20: "chưa gặp điểm kết thúc" là báo nhầm — tr.199 chỉ là chú thích ảnh, Hán của bia kế bắt đầu ở tr.200; văn bản bia 20 đầy đủ.
- Bia 27, 64: không đọc được số ở tiêu đề Hán (Gemini bỏ số đầu dòng) nên không đối chiếu được STT; không ảnh hưởng nội dung.

## 5. Còn lại

| Việc | Ai |
|---|---|
| Xác nhận định dạng tên file ghép mã (`02440-21_02441-22`) và ghi vào Data Contract (khoá `bia_id` hiện là một mặt; `validate.py`) | Phong / giảng viên |
| Xác nhận file rỗng (0 byte) cho loại văn bản sách không có (bia 13: `Phien_am`; bia 52: `Chu_Han`) được `validate.py` chấp nhận (Data Contract hiện yêu cầu 3 file không rỗng) | Phong |
| Ý nghĩa file ảnh không hậu tố (`02439`, `02436`, `02462`) và số mặt của bia 8 (sách không đọc được số mặt; hiện 3 ảnh) | Nhật / Phong |
| Báo Nhật: đã thêm 7 link vào `vietnamica_links.txt` và tải 7 ảnh vào `data/raw/anh_bia/` (bằng `download_bia.py`, có log) | Tuấn |
| Nếu cần chất lượng Hán cao hơn: OCR 2 lần rồi chỉ xem lại chỗ khác nhau, hoặc đối chiếu ảnh các bia ưu tiên | Tuấn / Điền |
| Gửi gói zip cho Điền/Phong qua kênh lab cho phép; cập nhật kế hoạch | Tuấn |

