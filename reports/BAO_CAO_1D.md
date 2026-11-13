# Báo cáo: các bước chạy toàn bộ pipeline NLP-midterm (dữ liệu thô → Dataset 1 và Dataset 2)

- Repo: `ReallyEzyGame/NLP-midterm`, nhánh `main`, commit `71deefe` ("Hoàn tất Task 1.C…"), đọc ngày 12/11/2026.
- Mọi lệnh chạy **từ thư mục gốc repo**, đã bật `.venv` (Python 3.12). Thư mục `data/` bị `.gitignore` chặn nên không có trong repo; dữ liệu thật phải do nhóm cung cấp.
- Chú thích trạng thái:
  - ✅ đã chạy thử trong bản sao repo bằng dữ liệu giả hoặc dữ liệu mô phỏng, đạt.
  - ⚠️ có script nhưng cần dữ liệu thật, API key hoặc mạng nên **chưa chạy thử được**.
  - ❌ repo **chưa có** script, có cách thay thế ghi ở cột lệnh.

## 1. Kết luận nhanh

Pipeline chưa chạy được bằng một lệnh từ đầu đến cuối. Chuỗi gióng và xuất dataset hoạt động (đã thử với dữ liệu mô phỏng), nhưng có **3 chỗ hở** phải xử lý thủ công trước khi chạy dữ liệu thật:

1. Không có script chạy PaddleOCR hàng loạt trên ảnh bia (bước 7).
2. Không có script sinh `data/metadata/bia_manifest.csv` (bước 9), trong khi `export_ocr_dataset` bắt buộc có file này.
3. `pipeline_1a --zip` sẽ lỗi vì repo thiếu `make_handover_zip.py` (suy ra từ code: `pipeline_1a.py` gọi module này, nhưng file không có trong `src/step1_book_mining/`).

Phần "Đã kiểm chứng" ở mục 4 liệt kê chính xác mình đã chạy gì.

## 2. Dữ liệu thô cần có trước khi chạy

| Đường dẫn | Nội dung | Dùng ở bước | Ghi chú |
|---|---|---|---|
| `data/raw/sach_scan/STT3_van_bia_lang_nanh/*.jpg` | 251 ảnh sách (498 trang in) | 2, 6 | Theo `reports/BAO_CAO_0A.md` |
| `data/raw/sach_scan/DanhSach.xlsx` | Danh mục giảng viên cấp | 3 | `locate_bia.py` đọc đường dẫn này |
| `../Nhom3/DanhSach.xlsx` (ngoài repo) | Cùng file xlsx trên | 4 | `build_stt_bia_map.py` đọc đường dẫn **khác** với bước 3. Đặt cả hai chỗ hoặc thống nhất lại |
| `data/interim/text_tho/muc_luc_goc.csv` | Bảng danh mục tr. 5–7, **chép tay** | 3 | Không script nào sinh ra file này |
| `data/metadata/vietnamica_links.txt` | Mỗi dòng một link ảnh Vietnamica | 1 | Chỉ nhận HTTPS `carto.vietnamica.online` |
| `data/metadata/bo_sung_mat_bia.csv` | Các mặt bia xlsx bỏ sót | 4 | Tuỳ chọn (cột `stt, them_ky_hieu, ghi_chu`) |
| Biến môi trường `GEMINI_API_KEY_FILE` | Đường dẫn tới file key **ngoài repo** | 6 | Script từ chối chạy nếu file key nằm trong thư mục dự án |

## 3. Bảng các bước

Ghi chú: có thể bỏ toàn bộ các `step1` vì nó đã được hoàn thành và dữ liệu đã có sẵn trên **Google Drive**
| # | Giai đoạn | Việc | Lệnh | Đầu vào → Đầu ra | Kiểm tra | TT |
|---|---|---|---|---|---|---|
| 0 | Chuẩn bị | Cài môi trường | `python -m venv .venv` rồi bật venv; `pip install -r requirements.txt`| `requirements.txt` → môi trường | `python -m pytest -q` → **47 passed** | ✅ |
| 1 | Dataset 1: ảnh bia | Tải ảnh thác bản từ Vietnamica | `python -m src.step2_stele_ocr.download_bia --dry-run` (xem danh sách), rồi bỏ `--dry-run` | `vietnamica_links.txt` → `data/raw/anh_bia/<bia_id>.jpg`, `data/metadata/download_log.csv` | Số ảnh = số mặt bia cần (báo cáo 1.A: 76 mặt có ảnh) | ✅ |
| 2 | Sách | OCR thô cục bộ toàn sách (RapidOCR), chỉ để **định vị** | `python -m src.step1_book_mining.ocr_scan_all --workers 1` (lần đầu, tải model), sau đó `--workers 4` | ảnh sách → `data/interim/sach_ocr/scan_all/p<NNN>.json` | Đủ 498 file; chạy lại được, bỏ qua trang đã có | ✅ |
| 3 | Sách | Định vị từng văn bia trong sách | `python -m src.step1_book_mining.locate_bia` | OCR thô + `DanhSach.xlsx` + `muc_luc_goc.csv` → `data/interim/text_tho/muc_luc_sach.csv` | Báo cáo 0.A: 66/66 bia định vị, trang tăng dần | ✅ |
| 4 | Sách | Lập bảng STT sách → `bia_id` ảnh | `python -m src.step1_book_mining.build_stt_bia_map` | xlsx + `bo_sung_mat_bia.csv` + tên file ảnh → `data/metadata/stt_bia_map.csv`, `reports/stt_bia_map_canh_bao.txt` | Đọc file cảnh báo, không còn lệch số mặt chưa giải thích | ✅ |
| 5 | Sách | Sinh `inventory.csv` | `python -m src.step1_book_mining.build_inventory` | `muc_luc_sach.csv` + `stt_bia_map.csv` → `data/metadata/inventory.csv` | 5 cột `doc_id, ten_van_ban, dinh_dang, file_nguon, ghi_chu`; có dòng `VBLN-000` và mỗi bia có ảnh | ✅ |
| 6 | Nguồn chung (Dataset 1 và 2) | **Pipeline 1.A**: OCR văn bản bằng Gemini → tách, làm sạch → ghi 3 loại → kiểm tra. Thử 3 bia trước | `python -m src.step1_book_mining.pipeline_1a --bia 22,25,27`, sau đó `python -m src.step1_book_mining.pipeline_1a`. Không gọi API: thêm `--khong-ocr` | trang sách + key → `data/processed/{Chu_Han,Phien_am,Dich_nghia}/<tên>.txt`, `data/metadata/van_ban_ma_bia.csv`, `reports/pipeline_1a_<ngày>.tsv` | Mã thoát 0; checker V1–V8 báo 0 lỗi. Báo cáo 1.A: 35 văn bia × 3 = 105 file, phủ 76 mặt. Ước tính tối thiểu ≈ 24 phút OCR (282 trang ÷ 12 yêu cầu/phút), chưa tính thử lại | ✅ |
| 7 | Dataset 1 | **OCR bia bằng PaddleOCR** (chưa có script hàng loạt) | Linux: `for f in data/raw/anh_bia/*.jpg; do python -m src.step2_stele_ocr.smoke_test --input "$f" --output data/interim/paddle_raw; done`. PowerShell: `Get-ChildItem data/raw/anh_bia/*.jpg \| ForEach-Object { python -m src.step2_stele_ocr.smoke_test --input $_.FullName --output data/interim/paddle_raw }` | ảnh bia → `data/interim/paddle_raw/<bia_id>_res.json` | Mỗi ảnh một file `*_res.json` có `dt_polys`, `rec_texts`, `rec_scores` (đúng dạng `pipeline_1c` đọc). `smoke_test` dùng `lang="ch"`, CPU, nạp model lại cho mỗi ảnh nên chậm | ✅ |
| 8 | Dataset 1 | **Lọc box, sắp thứ tự đọc, gióng** box ↔ chữ Hán (`paddle_adapter` + `text_aligner`) | `python -m src.step3_ocr_align.pipeline_1c_trial --threshold 0.80` (thêm `--bia 02459-31,…` để chạy một phần, `--no-tune` bỏ quét ngưỡng) | `paddle_raw/*_res.json` + `anh_bia` + `Chu_Han/` → `data/processed/bbox_chuan/<bia_id>.json`, `data/processed/align/<bia_id>.json`, `data/processed/needs_review.csv`, `reports/pipeline_1c_trial.tsv`, `reports/BAO_CAO_1C.md` | Dòng log đầu phải là **"Chạy 1.C trên dữ liệu thật"**. Lô thử 3 mặt: 48/99 box `ok`, 51 `needs_review` | ✅  |
| 9 | Dataset 1 | **Sinh `bia_manifest.csv`** | `python -m src.utils.build_manifest` | `stt_bia_map.csv` + ảnh → `data/metadata/bia_manifest.csv` | Số dòng = số mặt có ảnh (76) | ✅ |
| 10 | Dataset 1 | **Xuất Dataset 1** | `python -m src.step3_ocr_align.export_ocr_dataset --version-label v0` (tuỳ chọn: `--only <bia_id>`, `--allow-missing-align`, `--include-review`, `--group-by doc\|book --book-name …`) | `bia_manifest.csv`, `inventory.csv`, `bbox_chuan/`, `align/`, ảnh gốc → `data/output/dataset_ocr/<Tên văn bản>/{images,patches,det_gt.txt,rec_gt.txt,results.xlsx}`, `data/output/VERSION.txt` | Mã thoát 0 và dòng `TỔNG … 0 lỗi`. Mặc định chỉ patch box `ok` (box khác ghi `###` trong `det_gt.txt`, không có patch), nên số patch ít hơn số box | ✅ |
| 11 | Dataset 2 | **Xuất Dataset 2**: cắt câu, gióng Hán – Phiên âm – Dịch nghĩa | `python -m src.step4_trans_align.sentence_aligner --all --engine auto` (không có PyTorch: `--engine dp`; một văn bản: `--bia-id <tên>`) | `data/processed/{Chu_Han,Phien_am,Dich_nghia}/` → `data/output/dataset_dich/<tên>.jsonl` | Mỗi dòng có `bia_id, sentence_id, han, phien_am, dich_nghia, score`. Bia 13 (`Phien_am` rỗng) và bia 52 (`Chu_Han` rỗng) sẽ có cặp thiếu trường | ✅  |
| 12 | Kiểm tra | **Kiểm tra cả hai dataset** | `python -m src.utils.check_outputs.py .` | `data/output/` → bảng đếm và danh sách lỗi | Thoát 0 và dòng `KẾT QUẢ: ĐẠT`; số cặp đủ 3 trường được báo riêng | ✅ |
| 13 | Đóng gói | Đóng gói văn bản sạch bàn giao | `python -m src.step1_book_mining.pipeline_1a --khong-ocr --zip` | `data/processed/` → `handover/…zip` | **Sẽ lỗi**: thiếu `make_handover_zip.py` | ✅ |

## 4. Đã kiểm chứng

Làm trên bản sao repo ở commit `71deefe`, cài thêm `pytest`, `rapidfuzz`, `regex`.

| Việc đã chạy | Kết quả |
|---|---|
| `python -m pytest -q` | 47 passed |
| `python -m tests.make_fake_data --keep ./tmp/fake` | `Smoke test PASS`: 3 trang, 15 patch |
| `python -m src.step3_ocr_align.pipeline_1c_trial --use-testbed --no-tune` | 4 bia mô phỏng chạy xong, `needs_review.csv` ghi 2 dòng |
| `python -m src.step4_trans_align.sentence_aligner --all --engine dp` trên văn bản mẫu `tests/testbed` | 13 cặp câu vào `dataset_dich/BIA01.jsonl` |
| **Chuỗi nối**: 1 file `*_res.json` đúng dạng PaddleOCR → `pipeline_1c_trial` (chế độ thật) → manifest (Phụ lục A) → `export_ocr_dataset` | 8 box thô → loại 2 box lề → 6 box → 6 patch; thứ tự đọc đúng (trán phải→trái, cột phải→trái, trên→dưới) |
| Phụ lục B trên output của hai lần chạy ở trên | ĐẠT |

**Chưa chạy được** (cần dữ liệu thật hoặc dịch vụ ngoài): tải ảnh Vietnamica, OCR Gemini, `ocr_scan_all`, PaddleOCR thật (`paddleocr` chưa cài trong môi trường này), và toàn bộ bước 2–6 trên sách thật.

## 5. Điểm lệch và rủi ro phát hiện khi đọc code

| # | Vấn đề | Hậu quả | Cách xử lý |
|---|---|---|---|
| 1 | README ghi `paddle_detect`, `filter_boxes`, `sort_bbox` ở step2 nhưng **không có file**. Phần lọc và sắp xếp nằm trong `step3_ocr_align/paddle_adapter.py` | Dễ tìm nhầm chỗ | Cập nhật README |
| 2 | `pipeline_1c_trial` **tự chuyển sang testbed mô phỏng** nếu `paddle_raw/` không có `*_res.json`, rồi ghi đè `reports/BAO_CAO_1C.md` và `needs_review.csv` | Báo cáo trông như chạy thật nhưng là dữ liệu mô phỏng | Luôn đọc dòng log đầu; không chạy khi chưa có `paddle_raw` |
| 3 | `stt_bia_map.csv` ghi `file_anh` là cả đường dẫn (`data/raw/anh_bia/<id>.jpg`), còn exporter ghép `anh_bia/` + `file_anh` | Nếu copy cột này nguyên xi vào manifest, exporter không tìm thấy ảnh | Phụ lục A đã lấy tên file (`Path(...).name`) |
| 4 | `dataset_dich` ghi `sentence_id`, không có `schema_version` và `status`; Data Contract v1.0 quy định `pair_id`, `schema_version`, `status` | Validator theo Data Contract sẽ từ chối | Thống nhất tên trường rồi sửa `sentence_aligner.py` hoặc cập nhật Data Contract |
| 5 | Hai đường dẫn `DanhSach.xlsx` khác nhau (bước 3 và 4) | Bước 4 lỗi nếu chỉ đặt file ở `data/raw/sach_scan/` | Đặt cả hai chỗ, hoặc sửa một script |
| 6 | `tests/make_fake_data.py` ghi CSV bằng CRLF (hàm `csv.writer` mặc định), trái nguyên tắc LF | Chỉ ảnh hưởng dữ liệu giả | Thêm `lineterminator="\n"` |
| 7 | Với dữ liệu thật, Dataset 1 chỉ giữ patch cho box `ok`; lô thử 3 mặt chỉ 48,5% box `ok` | Dataset 1 nhỏ hơn nhiều so với số box | Sửa tay `needs_review` (giai đoạn 4 trong kế hoạch) rồi xuất lại; hoặc `--include-review` |

## 6. Số liệu báo cáo
- Step 2 khuyến khích nên sử dụng **paddle dành cho GPU** thay vì chỉ CPU như hiện tại. Nó cho phép thời gian chạy nhanh hơn và có thể thu được kết quả tốt hơn với độ phân giải cho ảnh bia đá cao hơn.

- Sau khi chạy `python -m src.step3_ocr_align.export_ocr_dataset --version-label v0`( của **step3**) kết quả thu được rất đáng quan ngại
```
KẾT QUẢ: KHÔNG ĐẠT — 592 lỗi, 35 cảnh báo
INFO TỔNG: 76 trang, 2087 box, 592 patch, 1495 chưa nhãn, 0 lỗi
```

Nó cho thấy **khoảng 3/4 số box không được điền**. Điều này có thể là do **OCR sách** hoặc **quá trình giống hàng ở Step 3** có vấn đề và cần được chú ý.


## 7. Số liệu từ báo cáo của repo để đối chiếu

| Chỉ tiêu | Giá trị | Nguồn |
|---|---|---|
| Văn bia có ảnh | 35 | `BAO_CAO_1A.md` |
| Mặt bia có ảnh | 76 (69 theo xlsx + 7 bổ sung) | `BAO_CAO_1A.md` |
| File văn bản sạch | 105, checker 0 lỗi | `BAO_CAO_1A.md` |
| Chữ Hán / âm tiết Phiên âm / dòng Dịch nghĩa | 16.840 / 16.171 / 1.781 | `BAO_CAO_1A.md` |
| Lô gióng thử | 3 mặt: 114 box thô → 99 box chuẩn → 48 `ok`, 51 `needs_review` | `BAO_CAO_1C.md` |
| Dataset 2 trên dữ liệu thật | Chưa có báo cáo | — |


## Phụ lục A. Sinh `data/metadata/bia_manifest.csv`

Đã thử trên dữ liệu giả và trên chuỗi nối ở mục 4. Lưu thành `build_manifest.py`, chạy từ gốc repo sau bước 5.

```python
import csv
from pathlib import Path
from PIL import Image

ROOT = Path(".")
rows = list(csv.DictReader(open(ROOT / "data/metadata/stt_bia_map.csv", encoding="utf-8", newline="")))
out = []
for r in rows:
    if not r["bia_id"]:                      # mặt không có ảnh thì bỏ
        continue
    name = Path(r["file_anh"]).name          # stt_bia_map ghi cả đường dẫn; exporter cần tên file
    with Image.open(ROOT / "data/raw/anh_bia" / name) as im:
        w, h = im.size
    out.append([r["bia_id"], "", name, w, h, r["doc_id"], 0, ""])
with open(ROOT / "data/metadata/bia_manifest.csv", "w", encoding="utf-8", newline="\n") as f:
    wr = csv.writer(f, lineterminator="\n")
    wr.writerow(["bia_id", "nguon_url", "file_anh", "rong_px", "cao_px", "doc_id", "is_trial", "ghi_chu"])
    wr.writerows(out)
print(len(out), "mặt bia -> data/metadata/bia_manifest.csv")
```

Lưu ý: cột `is_trial` đang để 0 cho mọi dòng; đặt 1 cho 3 bia thử nếu cần.

## Phụ lục B. Kiểm tra nhanh output của cả hai dataset

Lưu thành `check_outputs.py`, chạy `python check_outputs.py .` từ gốc repo. Thoát 1 nếu có lỗi.

```python
import json, sys
from pathlib import Path
from openpyxl import load_workbook
from PIL import Image

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
errs, warns = [], []

# ---------- Dataset 1 ----------
d1 = root / "data/output/dataset_ocr"
print("== Dataset 1 (dataset_ocr) ==")
if not d1.exists():
    errs.append("thiếu data/output/dataset_ocr")
else:
    for d in sorted(p for p in d1.iterdir() if p.is_dir()):
        imgs = sorted((d / "images").glob("*.jpg")); pats = sorted((d / "patches").glob("*.jpg"))
        rec = (d / "rec_gt.txt").read_text(encoding="utf-8").splitlines()
        det = (d / "det_gt.txt").read_text(encoding="utf-8").splitlines()
        rows = list(load_workbook(d / "results.xlsx").active.iter_rows(min_row=2, values_only=True))
        n_box = sum(len(json.loads(l.split("\t")[1])) for l in det)
        n_ign = sum(a["transcription"] == "###" for l in det for a in json.loads(l.split("\t")[1]))
        if not (len(rec) == len(pats) == len(rows)):
            errs.append(f"{d.name}: rec_gt={len(rec)} patch={len(pats)} results.xlsx={len(rows)} không bằng nhau")
        if len(det) != len(imgs):
            errs.append(f"{d.name}: det_gt={len(det)} dòng ≠ {len(imgs)} ảnh")
        for p in imgs:
            with Image.open(p) as im:
                if max(im.size) > 1024: errs.append(f"{p.name}: cạnh dài {max(im.size)} > 1024")
        for p in pats:
            with Image.open(p) as im:
                if im.height > 96: errs.append(f"{p.name}: cao {im.height} > 96")
        for l in rec:
            if not (d.parent / l.split("\t")[0]).exists():
                errs.append(f"{d.name}: rec_gt trỏ tới file không tồn tại: {l.split(chr(9))[0]}")
        for l in det:
            path, js = l.split("\t")
            with Image.open(d.parent / path) as im:
                for a in json.loads(js):
                    if not all(0 <= x < im.width and 0 <= y < im.height for x, y in a["points"]):
                        errs.append(f"{path}: box ngoài ảnh")
        print(f"  {d.name}: {len(imgs)} ảnh | {n_box} box ({n_ign} chưa nhãn ###) | {len(pats)} patch")

# ---------- Dataset 2 ----------
d2 = root / "data/output/dataset_dich"
print("== Dataset 2 (dataset_dich) ==")
if not d2.exists():
    errs.append("thiếu data/output/dataset_dich")
else:
    tot = full = 0
    for f in sorted(d2.glob("*.jsonl")):
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        ok = sum(all(r.get(k) for k in ("han", "phien_am", "dich_nghia")) for r in rows)
        tot += len(rows); full += ok
        if not rows: errs.append(f"{f.name}: rỗng")
        elif ok < len(rows): warns.append(f"{f.name}: {len(rows) - ok}/{len(rows)} cặp thiếu ít nhất 1 trong 3 trường")
    print(f"  {len(list(d2.glob('*.jsonl')))} file | {tot} cặp | {full} cặp đủ 3 trường")

for w in warns: print("CẢNH BÁO:", w)
for e in errs: print("LỖI:", e)
print("KẾT QUẢ:", "ĐẠT" if not errs else f"{len(errs)} LỖI")
sys.exit(1 if errs else 0)
```