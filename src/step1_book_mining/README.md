# step1_book_mining — OCR sách & lập mục lục (người A / Tuấn)

Mọi lệnh chạy **từ thư mục `NLP-midterm`**, đã bật `.venv` (Python 3.12). Dữ liệu nằm trong `data/` (bị `.gitignore` chặn,
**không commit**). Cấu hình tái lập của bước 0.A.6 (chọn công cụ OCR sách) ở mục 3.

## 1. Các script (theo thứ tự chạy)

| Thứ tự | Script | Việc làm | Đầu ra |
|---|---|---|---|
| 1 | `ocr_scan_all.py` | OCR **cục bộ** (RapidOCR/onnxruntime) 498 trang: cắt ảnh trang đôi tại giữa gáy, lưu dòng chữ + tọa độ + độ tin cậy. Chạy lại được (bỏ qua trang đã có). Dùng để **định vị** (tiêu đề, nhãn, khối Hán), không dùng làm văn bản cuối. | `data/interim/sach_ocr/scan_all/p<NNN>.json` |
| 2 | `locate_bia.py` | Định vị 66 bia từ OCR thô + `DanhSach.xlsx` + `muc_luc_goc.csv` (bảng danh mục tr. 5–7, chép tay): trang Hán, tiêu đề Việt, Phiên âm, Dịch nghĩa, trang cuối; cờ cảnh báo. | `data/interim/text_tho/muc_luc_sach.csv` |
| 3 | `build_inventory.py` | Sinh `inventory.csv` theo Data Contract §5.1 (VBLN-000 + mỗi bia có ảnh). | `data/metadata/inventory.csv` |
| 4 | `ocr_gemini.py` | OCR **văn bản cuối** bằng Google AI Studio (Gemini). Chạy lại được, giới hạn tốc độ, lùi khi 429. | `data/interim/sach_ocr/gemini/<model>/p<NNN>.txt` + `.json` |
| 5 | `eval_cer.py` | Đo CER so với bản chép chuẩn `data/interim/ocr_thu/gt/`. | `reports/ocr_benchmark.csv` |

```powershell
.\.venv\Scripts\Activate.ps1
python -m src.step1_book_mining.ocr_scan_all --workers 4          # chạy 1 tiến trình trước để tải model, rồi mới --workers 4
python -m src.step1_book_mining.locate_bia
python -m src.step1_book_mining.build_inventory
python -m src.step1_book_mining.ocr_gemini --bia 25,27,22 --dry-run   # xem kế hoạch (không gọi API)
python -m src.step1_book_mining.ocr_gemini --bia 25,27,22             # OCR 13 trang của 3 bia thử
python -m src.step1_book_mining.eval_cer --models gemini-3.5-flash-lite --csv reports/ocr_benchmark.csv
```

## 2. Cấu trúc sách (đã kiểm chứng) — cơ sở của `locate_bia.py`
Mỗi bia N: **chữ Hán** (tiêu đề dạng `N.<tên Hán>`) → tiêu đề Việt `N. TÊN` → thông tin → `Phiên âm:` → `Dịch nghĩa:`.
Hán của bia N đứng **trước** tiêu đề Việt N. Nội dung bia là tr. 37–463; phụ lục từ tr. 464. Số trong tên file ảnh = số trang in.

## 3. Cấu hình tái lập: OCR sách bằng Gemini (0.A.6.6)

| Mục | Giá trị |
|---|---|
| Công cụ chốt (Tuấn, 07/11/2026) | Google AI Studio, model **`gemini-3.5-flash-lite`** (mặc định của script) |
| Dự phòng | RapidOCR cục bộ (`chinese_cht` v3 cho Hán, `ch` PP-OCRv6 small cho Việt). Đổi model Gemini bằng `--model` |
| Thư viện | `google-genai==3.0.0` (xem `requirements.txt`) |
| Tham số sinh | `temperature=0`; ảnh = 1 trang in (cắt từ ảnh trang đôi tại `w//2`), PNG |
| Prompt | `han` / `viet` / `mixed` trong `ocr_gemini.py` (băm SHA-256 ghi vào `.json` mỗi trang). **`mixed` chưa được đo CER** |
| Key | file **ngoài repo**; biến môi trường `GEMINI_API_KEY_FILE` chỉ chứa **đường dẫn**. Script từ chối chạy nếu file key nằm trong thư mục dự án. Không bao giờ in/ghi key |
| Hạn mức | `flash-lite`: **chưa kiểm tra** trong AI Studio. Mặc định `--rpm 12` (giữ dưới 15 RPM) |
| Phạm vi gửi | **chỉ trang sách nhóm 3**; không gửi tài liệu lab khác |
| Chuẩn hoá khi chấm | NFC; Hán bỏ khoảng trắng/chữ số/dấu câu; Việt gộp khoảng trắng và bỏ số trang |

### Số đo CER của `gemini-3.5-flash-lite` trên 4 trang mẫu (08/11/2026, `temperature=0`)
Bản chép chuẩn do Claude đọc từ ảnh, **chờ Tuấn duyệt**; ký tự 鐋/鐺 ở tr. 100 chưa rõ (xuất hiện 3 lần). Chi tiết: `reports/ocr_benchmark.csv`.

| Trang | Loại | CER |
|---|---|---|
| 100 | Hán | 4,35% |
| 217 | Hán | 2,62% |
| 218 | Phiên âm | 0,00% |
| 219 | Dịch nghĩa | 0,00% |

**Lưu ý khi dùng kết quả**
- **Không tất định:** hai lần chạy ở `temperature=0` cho số khác nhau (tr. 218: 0,11% rồi 0,00%). Mỗi loại chỉ 4 trang ⇒ chỉ là "tốt trên mẫu".
- **Lỗi "tự sửa" hợp ngữ cảnh** (đổi từ Hán-Việt, dị thể → chữ chuẩn, chữ hiếm → chữ phổ biến) khó thấy khi đọc xuôi: **luôn rà soát 100% với ảnh**, chữ Hán bắt buộc.
- RapidOCR tốt nhất đo trước đó (1 trang/loại): Hán ≈ 9,1%, Việt 10,6% — chỉ còn là dự phòng.

## 4. Giới hạn đã biết
- Ảnh trang đôi cắt tại giữa ảnh (`w//2`); 5/248 ảnh có gáy lệch > 40 px so với giữa ⇒ trang đó có thể mất vài ký tự ở mép, kiểm tra khi OCR trang đó.
- `locate_bia.py` phụ thuộc OCR cục bộ: trang `tr_*` là trang **bắt đầu** của mục (xấp xỉ), 1.A phải kiểm lại trên ảnh.
- Bia không có chữ Hán trong sách (STT 29, 30, 32, 34, 39, 40, 42, 52–55) và bia 13 không có Phiên âm: xem cột `ghi_chu` của `muc_luc_sach.csv`.
