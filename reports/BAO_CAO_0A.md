# Báo cáo bước 0.A — Nhận tài liệu, phân loại định dạng, chọn công cụ OCR sách

Người thực hiện: Tuấn (A) · Cập nhật: 08/11/2026 · Hạn 0.A: T2 09/11/2026

> Báo cáo này **không chứa nội dung sách hay tên văn bia** của tài liệu lab; chỉ có số liệu, STT và số trang.
> Bảng chi tiết từng bia nằm trong `data/interim/text_tho/muc_luc_sach.csv` (không commit).
> Số liệu do script sinh ra từ dữ liệu thật, trừ mục ghi rõ "đọc bằng mắt" hoặc "chờ duyệt".

## 1. Kết luận nhanh

| # | Điều kiện đóng 0.A | Trạng thái | Bằng chứng / còn thiếu |
|---|---|---|---|
| 1 | Dữ liệu gốc + hash | ✅ | 251 ảnh + `DanhSach.xlsx`; `SHA256SUMS.txt` 252 dòng, **0 sai lệch**; thư mục gốc chỉ-đọc |
| 2 | `inventory.csv` | ✅ | 36 dòng, 5 cột đúng Data Contract §5.1, UTF-8 không BOM, LF, NFC; `file_nguon` có thật; khớp xlsx (35 bia, 69 mặt) |
| 3 | Phân loại định dạng | ✅ | toàn bộ `anh` (JPG 300 dpi, 248 ảnh trang đôi 1698×1200), không có lớp chữ ⇒ **OCR bắt buộc** |
| 4 | Mục lục sách → trang | ✅ | 66/66 bia định vị (tr. 39→460, tăng dần); tên khớp xlsx 66/66; 35 bia có ảnh đã kiểm bằng mắt, 0 sai lệch tại 6 điểm biên/bia |
| 5 | Chốt 3 bia thử | ⚠️ | đề xuất STT 25, 27, 22 (13 trang); **chờ Nhật xác nhận ảnh thác bản** |
| 6 | Chốt công cụ OCR sách | ✅ | **Gemini `gemini-3.5-flash-lite`** (Tuấn, 07/11); số đo ở mục 3. Còn: Tuấn duyệt bản chép chuẩn, kiểm tra hạn mức `flash-lite` |
| 7 | Quy ước Q1–Q13 | ⚠️ | đề xuất ở mục 4, **chờ Phong/nhóm** |
| 8 | Bàn giao + báo nhóm | ❌ | gói zip đã tạo, **chưa gửi**; chưa đăng báo cáo, chưa cập nhật kế hoạch |

0.A **chưa đóng hoàn toàn**: các mục 5, 7, 8 cần người khác hoặc cần Tuấn thực hiện (mục 5).

## 2. Dữ liệu và phát hiện về sách

- **Sách:** 498 trang in, 251 file ảnh (1 bìa, 1 trang đơn, 248 ảnh trang đôi, 1 trang cuối). OCR cục bộ 498/498 trang, độ tin cậy TB 0,932.
- **Danh mục:** 66 bia; **35 bia có ảnh thác bản**, tổng **69 mặt**; 31 bia không có ảnh ⇒ bỏ qua (theo giảng viên).
- **Cấu trúc mỗi bia:** chữ Hán → tiêu đề Việt → Phiên âm → Dịch nghĩa. Hán của bia N đứng **trước** tiêu đề Việt N. Nội dung bia: tr. 37–463; phụ lục từ tr. 464; giữa các bia có đoạn giới thiệu di tích cần loại.
- **Ngoại lệ:**
  - Không có chữ Hán trong sách: STT 29, 30, 32, 34, 39, 40, 42, 52–55 (chỉ STT 52 có ảnh ⇒ không gióng OCR được).
  - STT 13 có ảnh nhưng không có mục Phiên âm.
  - Số mặt sách ≠ số ảnh: STT 7, 28, 56, 64 (sách 2, ảnh 1); STT 62 (sách 4, ảnh 1); STT 65 (sách 4, ảnh 2).
- **Nhiễu cần lọc ở 1.A:** chữ in xuyên mặt sau, chú thích, số trang, tên tác giả, ký tự lạc.
- 5/248 ảnh có gáy lệch > 40 px so với giữa ảnh ⇒ cắt trang tại `w//2` có thể mất vài ký tự mép.

## 3. Chọn công cụ OCR sách

**Quyết định (Tuấn, 07/11/2026): Google AI Studio `gemini-3.5-flash-lite`**, `temperature=0`, prompt "chép nguyên văn, không sửa/dịch".
Dự phòng: RapidOCR cục bộ. Giảng viên đã cho phép AI Studio (tên người cấp phép/ngày: cần ghi vào checklist).
Đã loại: Google Vision (không bật được billing, API trả 403 `BILLING_DISABLED`), Tesseract, VietOCR, PaddleOCR gốc (không cần).

### Số đo CER của `gemini-3.5-flash-lite` — 4 trang mẫu (chạy bằng `ocr_gemini.py` + `eval_cer.py`, 08/11/2026)

| Trang | Loại | CER `flash-lite` | Số chỗ sai / ký tự chuẩn | RapidOCR tốt nhất (đo trước đó) |
|---|---|---|---|---|
| 100 | Hán | 4,35% | 12 / 276 | ≈ 9,1% (`chinese_cht` v3) |
| 217 | Hán | 2,62% | 5 / 191 | chưa đo |
| 218 | Phiên âm | **0,00%** | 0 / 890 | chưa đo |
| 219 | Dịch nghĩa | **0,00%** | 0 / 1083 | 10,6% (`ch` PP-OCRv6 small) |

Bảng đầy đủ (kể cả CER bỏ dấu): `reports/ocr_benchmark.csv`.

**Cách đọc kết quả**
- `flash-lite` tốt hơn RapidOCR rất nhiều: tiếng Việt ≈ 0,0% so với 10,6%; chữ Hán ≈ 2,6–4,4% so với ≈ 9%.
- **Không tất định:** ở `temperature=0` kết quả vẫn dao động giữa các lần chạy (tr. 218: 0,11% ngày 07/11, 0,00% ngày 08/11). Mỗi loại chỉ 4 trang nên chưa kết luận được độ chính xác thật; coi CER ≈ 0% của tiếng Việt là "tốt trên mẫu", không phải bảo đảm.
- **Chữ Hán sai nhiều hơn tiếng Việt** (2–4%): lỗi gồm đổi dị thể sang chữ chuẩn và nhầm chữ gần giống. Chữ Hán **luôn rà soát 100% với ảnh**.
- **Lỗi nguy hiểm nhất là "tự sửa" hợp ngữ cảnh** (đổi từ Hán-Việt, dị thể → chữ chuẩn, chữ hiếm → chữ phổ biến). Đọc xuôi không thấy, nên với tiếng Việt cũng phải đối chiếu với ảnh.

**Hạn chế của phép đo**
- Bản chép chuẩn (`data/interim/ocr_thu/gt/`) do **Claude đọc từ ảnh, Tuấn chưa duyệt**. Trong lúc đo đã phát hiện và sửa 2 lỗi của bản chép chuẩn; ký tự 鐋/鐺 vẫn chưa rõ.
- Chưa đo prompt `mixed` (trang có cả Hán và Việt). Hạn mức `flash-lite` chưa kiểm tra (chưa biết số yêu cầu/ngày và RPM).
- Dữ liệu trang đã được gửi tới Google AI Studio chỉ gồm **4 trang mẫu (100, 217, 218, 219)** cho mục đích đo; chưa gửi trang nào khác.

## 4. Đề xuất 3 bia thử và quy ước (chờ nhóm)

**3 bia thử** (số mặt sách = số ảnh, đủ ba khối văn bản, Hán ngắn để rà 100%):

| STT | Số mặt (ảnh) | Trang sách | Số trang |
|---|---|---|---|
| 25 | 1 | 217–219 | 3 |
| 27 | 1 | 234–238 | 5 |
| 22 | 2 | 203–207 | 5 |

Dự phòng: STT 24, 21, 23. Tránh: 13 (thiếu Phiên âm), 52 (thiếu Hán), 7/28/56/62/64/65 (lệch số mặt). Cần Nhật xác nhận ảnh có trên Vietnamica và cho **tên file thật** để chốt `bia_id`.

**Quy ước đề xuất (chưa chốt):** dòng tiêu đề Hán giữ ở dòng 1 của `Chu_Han`, bỏ tiền tố `N.`; giữ tiêu đề Việt, bỏ nhãn "Phiên âm:"/"Dịch nghĩa:"; bỏ `○`; giữ dị thể và chính tả "kí" như sách; loại chú thích, số trang, đoạn giới thiệu di tích; bia nhiều mặt chưa có quy ước (3 bia thử chọn để tránh); bia thiếu Hán/Phiên âm (52, 13) loại khỏi dataset và ghi lý do; thư mục trùng tên thì thêm STT/ký hiệu.

## 5. Việc còn lại

| Việc | Ai | Ghi chú |
|---|---|---|
| Duyệt 4 bản chép chuẩn, nhất là 鐋/鐺 | Tuấn | quyết định độ tin của CER |
| Ghi tên người cấp phép AI Studio + ngày | Tuấn | điều kiện tuân thủ |
| Kiểm tra hạn mức `flash-lite` | Tuấn | trong AI Studio |
| Xác nhận ảnh 3 bia thử + tên file thật; tìm ảnh còn thiếu của STT 62 | Nhật | |
| Chốt `doc_id`, Q3, Q10–Q13; merge nhánh `mock/frame-script` | Phong | `main` mới có 1 commit |
| Gửi gói zip `T-ALL_metadata_20261106.zip`, đăng báo cáo, cập nhật kế hoạch | Tuấn | kênh lab cho phép |

## 6. Tái lập

Xem `src/step1_book_mining/README.md` (lệnh chạy, cấu hình Gemini, giới hạn). Môi trường: `requirements.txt`, Python 3.12, `.venv`.
Key Gemini lưu **ngoài repo**; biến `GEMINI_API_KEY_FILE` chỉ chứa đường dẫn.
