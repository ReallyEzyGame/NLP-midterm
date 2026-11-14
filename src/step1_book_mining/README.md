# step1_book_mining — OCR sách & lập mục lục (người A / Tuấn)

Mọi lệnh chạy **từ thư mục `NLP-midterm`**, đã bật `.venv` (Python 3.12). Dữ liệu nằm trong `data/` (bị `.gitignore` chặn,
**không commit**). Cấu hình tái lập của bước 0.A.6 (chọn công cụ OCR sách) ở mục 3.

## 1. Các script (theo thứ tự chạy)

| Thứ tự | Script | Việc làm | Đầu ra |
|---|---|---|---|
| **0** | **`pipeline_1a.py`** | **Một lệnh cho cả bước 1.A**: OCR (gọi `ocr_gemini`, bỏ qua trang đã có) → tách & làm sạch (`clean_book_text`) → ghi nguyên bài theo mã bia (`stt_bia_map.csv`) → checker → báo cáo → `--zip`. Bia thiếu OCR/Hán/Phiên âm thì dừng riêng bia đó và ghi trạng thái. | `data/processed/`, `reports/pipeline_1a_<ngày>.tsv` |
| 1 | `ocr_scan_all.py` | OCR **cục bộ** (RapidOCR/onnxruntime) 498 trang: cắt ảnh trang đôi tại giữa gáy, lưu dòng chữ + tọa độ + độ tin cậy. Chạy lại được (bỏ qua trang đã có). Dùng để **định vị** (tiêu đề, nhãn, khối Hán), không dùng làm văn bản cuối. | `data/interim/sach_ocr/scan_all/p<NNN>.json` |
| 2 | `locate_bia.py` | Định vị 66 bia từ OCR thô + `DanhSach.xlsx` + `muc_luc_goc.csv` (bảng danh mục tr. 5–7, chép tay): trang Hán, tiêu đề Việt, Phiên âm, Dịch nghĩa, trang cuối; cờ cảnh báo. | `data/interim/text_tho/muc_luc_sach.csv` |
| 3 | `build_inventory.py` | Sinh `inventory.csv` theo Data Contract §5.1 (VBLN-000 + mỗi bia có ảnh). | `data/metadata/inventory.csv` |
| 4 | `ocr_gemini.py` | OCR **văn bản cuối** bằng Google AI Studio (Gemini). Chạy lại được, giới hạn tốc độ, lùi khi 429. | `data/interim/sach_ocr/gemini/<model>/p<NNN>.txt` + `.json` |
| 6 | `clean_book_text.py` + `regex_filter.py` | Gộp OCR thô → `text_tho/<bia_id>.txt`; tách Hán / Phiên âm / Dịch nghĩa, làm sạch, ghi **bản nháp** (chưa rà soát) + log. Không gọi API. | `data/interim/text_tho/`, `data/interim/van_ban_nhap/{Chu_Han,Phien_am,Dich_nghia,_log}/` |
| 7 | `check_van_ban_sach.py` | Checker V1–V8 cho 3 thư mục văn bản sạch (`--selftest` kiểm chính checker; `--log` ghi báo cáo không chứa nội dung sách). Chờ Phong gộp vào `validate.py`. | mã thoát 0/1, log tuỳ chọn |
| 5 | `eval_cer.py` | Đo CER so với bản chép chuẩn `data/interim/ocr_thu/gt/`. | `reports/ocr_benchmark.csv` |
| 8 | `build_stt_bia_map.py` | Lập bảng **STT (sách) → `bia_id` (tên file ảnh thác bản)**: đọc `Nhom3/DanhSach.xlsx` (CHỈ ĐỌC) + tên file thật trong `data/raw/anh_bia/`; ghi cảnh báo lệch số mặt. | `data/metadata/stt_bia_map.csv`, `reports/stt_bia_map_canh_bao.txt` |
| 9 | `make_handover_zip.py` | Đóng gói `data/processed/{Chu_Han,Phien_am,Dich_nghia}` + `MANIFEST.txt` (SHA-256) vào `handover/`; chạy checker trước, lỗi thì không đóng gói. | `handover/T-ALL_van_ban_sach_<yyyymmdd>.zip` |

```powershell
.\.venv\Scripts\Activate.ps1
python -m src.step1_book_mining.ocr_scan_all --workers 4          # chạy 1 tiến trình trước để tải model, rồi mới --workers 4
python -m src.step1_book_mining.locate_bia
python -m src.step1_book_mining.build_inventory
python -m src.step1_book_mining.ocr_gemini --bia 25,27,22 --dry-run   # xem kế hoạch (không gọi API)
python -m src.step1_book_mining.ocr_gemini --bia 25,27,22             # OCR 13 trang của 3 bia thử
python -m src.step1_book_mining.clean_book_text --bia 25,27,22          # tách + làm sạch (không gọi API)
python -m src.step1_book_mining.eval_cer --models gemini-3.5-flash-lite --csv reports/ocr_benchmark.csv
```

## 1b. Tên file văn bản sạch (giảng viên chốt 09/11/2026: không tách theo mặt)
- `doc_id` = `VBLN-<STT>` = **một văn bản trong sách** (khoá của `inventory.csv`; dùng cho `text_tho/` và bản nháp `van_ban_nhap/`).
- `bia_id` = tên file ảnh thác bản bỏ đuôi (`<số thư viện 5 số>-<TF><idx>`, vd `02440-21`) = **một mặt bia**.
- **Mỗi văn bia giữ nguyên bài**, một bộ 3 file trong `data/processed/*/`, tên = các `bia_id` có ảnh của văn bia nối bằng `_`
  (vd STT 22 → `02440-21_02441-22.txt`; 1 mặt → `02439.txt`). Định dạng nối `_` là giả định, chờ xác nhận. Ánh xạ ở `stt_bia_map.csv`.
- TF trong tên file ảnh = số mặt thật trên Vietnamica; `DanhSach.xlsx` có thể chỉ lấy một số mặt (vd STT 27 chỉ `02434` ⇒ `02434-21`).
  Mặt không có ảnh thì không có trong tên file; văn bản vẫn lấy nguyên bài.

## 1c. Chạy bước 1.A bằng pipeline
```powershell
python -m src.step1_book_mining.pipeline_1a --bia 22,25,27          # OCR (nếu thiếu) + làm sạch + kiểm tra 3 bia thử
python -m src.step1_book_mining.pipeline_1a                         # mọi văn bia có ảnh (đọc stt_bia_map.csv)
python -m src.step1_book_mining.pipeline_1a --khong-ocr --zip       # không gọi API; đóng gói bàn giao
```
**Chữ mất / sách lược → `MASK`** (giảng viên 14/11/2026): Hán `。。。` / `．．．` (dấu lược giữa câu, kể cả khi OCR ghi cách nhau `。 。 。`) và `？` (1 chữ không đọc được); Phiên âm/Dịch nghĩa `...` / `…` / `(?)`. Trước đây `。。。` bị xoá như hoa văn (và bản có khoảng trắng sinh ra các dòng chỉ có `。`).

**Làm sạch chung** (`regex_filter.py`, áp cho mọi bia, không đối chiếu từng chữ): bỏ nhãn/khối thông tin/số trang/chú thích/`○○○`;
Hán: chỉ giữ chữ Hán + dấu câu sách, dấu nửa khổ → toàn khổ, chữ tương thích → chuẩn (NFC), bỏ khoảng trắng;
Việt: NFC, bỏ ký tự vô hình/rác và chữ Hán lọt (in xuyên trang), sửa khoảng trắng quanh dấu câu, gộp dấu lặp, `…`→`...`,
cắt câu ở `. ; : ? !`. Dị thể (仝/全, 内/內…) KHÔNG sửa tự động (không có quy tắc máy móc). Kiểm thử: `tests/test_regex_filter.py`.

**Mặt bia bổ sung** `data/metadata/bo_sung_mat_bia.csv` (`stt, them_ky_hieu, ghi_chu`; ký hiệu nối `|`): các mặt `DanhSach.xlsx` bỏ sót (đối chiếu Vietnamica) — `build_stt_bia_map.py` gộp với xlsx (không sửa xlsx), cột `nguon` = `xlsx`/`bo_sung`; dòng không có ký hiệu = ghi chú đã xác nhận số mặt (pipeline ghi "đã xác nhận" thay vì cảnh báo). Ảnh bổ sung tải bằng `src/step2_stele_ocr/download_bia.py` (link thêm vào `vietnamica_links.txt`). Chạy toàn bộ pipeline còn **kiểm tra đồng bộ** processed ⇔ kê mã ⇔ `stt_bia_map.csv` ⇔ ảnh `anh_bia` ⇔ `inventory.csv` (lệch ⇒ mã thoát 1, không đóng gói).

**File kê mã** `data/metadata/van_ban_ma_bia.csv` (pipeline tự sinh/cập nhật): `ten_file, doc_id, stt, danh_sach_bia_id` (nối `|`), `so_mat_co_anh`, `so_mat_theo_sach`, `trang_sach`, `ghi_chu` — cho biết mỗi file văn bản gồm những mã mặt bia nào. Chạy một phần (`--bia`) thì chỉ cập nhật các STT vừa chạy.

OCR (`ocr_gemini`): trang trả về rỗng hoặc bị dừng sớm (`finish_reason` ≠ STOP: bị chặn, hết token…) KHÔNG được lưu (ghi `p<trang>.loi.json`), lần chạy sau tự thử lại. Gemini còn có thể **lặp** (một cụm lặp liên tiếp, hoặc các dòng dài dần cùng một đuôi — bắt bằng `degenerate()`: đơn vị 1–8 ký tự lặp ≥ 8 lần, hoặc đoạn 12 chữ Hán xuất hiện ≥ 4 lần trên một trang) dù `finish_reason` là STOP: trang như vậy cũng không được lưu, bản đã lưu mà bị lặp bị OCR lại ở lần chạy sau. Thứ tự thử lại: temperature 0 → 0,3 → 0,7 (giới hạn 8192 token ra) → cắt đôi trang tại khe giữa hai dòng (`--khong-chia-doi` để tắt). Trang vẫn hỏng thì bia chứa nó báo `THIEU_OCR` (không ghi chữ Hán sai). Trang nhiễu xuyên trang nặng (vd tr.290) flash-lite không đọc nổi; prompt `mixed` đôi khi giúp (`ocr_gemini --pages 312:mixed --force`). Chạy lại pipeline: file cũ của văn bia được xoá trước khi ghi; chạy toàn bộ (không `--bia`) thì xoá cả file không thuộc lần chạy. Kiểm thử: `tests/test_pipeline_1a.py`.

Không có bước sửa tay hay đối chiếu ảnh: kết quả cuối là kết quả của OCR + quy tắc làm sạch chung.

Trạng thái trong báo cáo: `OK`, `THIEU_OCR` (có trang OCR hỏng/chưa có), `THIEU_MUC_LUC`, `LOI_TACH` (số tiêu đề Hán ≠ STT ⇒ lấy nhầm bia; hoặc không tách được loại nào), `LOI_XU_LY` (lỗi bất thường của riêng bia đó; các bia khác vẫn chạy), `KHONG_CO_ANH`. **Bia sách thiếu một loại văn bản** (STT 52 không có Hán, STT 13 không có Phiên âm) vẫn `OK`: loại thiếu ghi thành **file rỗng 0 byte** (`ghi_chu` = `RONG <loại> (…)`); checker chấp nhận file 0 byte nhưng vẫn bắt file chỉ có dòng trống. Cảnh báo "có thể thiếu đoạn cuối" khi đọc tới đầu bia kế (tối đa +2 trang so với mục lục) mà không gặp Hán/tiêu đề bia kế hay tiêu đề di tích; cờ `TI_LE_LECH` khi âm tiết Phiên âm / chữ Hán ngoài 0,9–1,15.

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
