#  Dự Án OCR trên Văn Bia Đá
## Tổ chức cây thư mục của dự án


```bash
vanbia-ocr-project/
├── configs/config.yaml             # đường dẫn, ngưỡng lọc box, max_side=1024, patch_h=96
├── data/                           # .gitignore toàn bộ
│   ├── raw/
│   │   ├── sach_scan/
│   │   └── anh_bia/                # ảnh gốc, không sửa tại chỗ
│   ├── metadata/bia_manifest.csv   # ID mặt bia ↔ văn bản trong sách
│   ├── interim/
│   │   ├── text_tho/
│   │   ├── paddle_raw/<bia>/       # box + text + score
│   │   └── bbox_sua_tay/
│   ├── processed/
│   │   ├── Chu_Han/<bia>.txt
│   │   ├── Phien_am/<bia>.txt
│   │   ├── Dich_nghia/<bia>.txt
│   │   └── bbox_chuan/<bia>.json   # đã lọc + đúng thứ tự đọc
│   └── output/
│       ├── dataset_ocr/
│       │   └── <bia>/
│       │       ├── images/         # cạnh lớn nhất ≤ 1024, .001.jpg
│       │       ├── patches/        # xoay 90°, cao ≤ 96, .001.001.jpg
│       │       ├── det_gt.txt
│       │       ├── rec_gt.txt
│       │       └── results.xlsx
│       └── dataset_dich/<bia>.jsonl   # han / phien_am / dich_nghia
├── reports/                        # số box, số cặp câu
├── src/
│   ├── step1_book_mining/          # vision_ocr, regex_filter, clean_book_text
│   ├── step2_stele_ocr/            # download_bia, paddle_detect, filter_boxes, sort_bbox
│   ├── step3_ocr_align/            # text_aligner (Levenshtein/DP), crop_patches, export_ocr_dataset
│   ├── step4_trans_align/          # sentence_align (BertAlign), export_dich_dataset
│   └── utils/                      # file_io, image_processing (scale box khi resize), stats
│   │__ tests/                      # generate test data
├── .gitignore
├── requirements.txt
└── README.md
```

## Hướng dẫn chạy

```bash
# Ở thư mục gốc của đồ án
# Tạo .venv
python -m venv .venv
# Chạy môi trường ảo
# Linux
source .venv/bin/activate
# Tải các gói cần trong dự án
pip install -r requirements.txt

# Chạy mock thử
python -m tests.make_fake_data --keep ./tmp/fake      # thử bằng dữ liệu giả
# Sau khi chạy, dời tmp/fake/data vào data của thư mục gốc để chạy thử tiếp ở dưới
python -m src.step3_ocr_align.export_ocr_dataset     # chạy thật
python -m src.step3_ocr_align.export_ocr_dataset --only 00270-TF1 --allow-missing-align   # chỉ xuất det_gt khi C chưa xong
``````

## Chạy toàn bộ pipeline trên dữ liệu thật (cập nhật 18/11/2026)

Mọi lệnh chạy từ `NLP-midterm/` với `.venv` đã bật. Dữ liệu (`data/`) không commit. Cần thêm ngoài repo (cùng cấp
`NLP-midterm/`): `dict/` (dict.zip của giảng viên) và `SinoNom-alignment/` (tool dóng hàng của giảng viên,
github.com/VongHaiYen11/SN-QN-alignment) — đường dẫn trong `configs/config.yml` mục `dong_hang`.

```bash
# Bước 1 — văn bản sạch; chữ mất/sách lược → token MASK (giảng viên 14/11/2026)
python -m src.step1_book_mining.ocr_gemini --pages 150:han --gian-dong   # OCR lại trang Hán Gemini đọc theo cột dọc
python -m src.step1_book_mining.chon_ban_ocr_han                          # chọn bản OCR từng trang (khớp âm với Phiên âm)
python -m src.step1_book_mining.pipeline_1a --khong-ocr
# Bước 2 — OCR văn bia bằng API lab CLC (đã chạy: data/interim/paddle_raw/nom_epitaph/)
python -m src.step2_stele_ocr.ocr_bia --input data/raw/anh_bia --ve-anh
# Bước 3 — Dataset 1: gióng v3 + MASK + xử lý needs_review → bbox_chuan/, align/, needs_review.csv; xuất dataset
python -m src.step3_ocr_align.pipeline_dataset_ocr                       # mặc định nguồn nom_epitaph (OCR lab CLC)
python -m src.step3_ocr_align.export_ocr_dataset --version-label v1
# Bước 4 — Dataset 2 (Hán – Phiên âm – Dịch nghĩa) và dóng hàng chữ Hán ↔ dịch âm (tool giảng viên)
python -m src.step4_trans_align.build_dataset_dich
python -m src.step4_trans_align.dong_hang_dich_am
# Kiểm tra, báo cáo, đóng gói nộp (../Ket_Qua_Nop/output, ngoài repo)
python -m src.utils.validate
python -m src.utils.bao_cao_tong_hop
python -m src.utils.dong_goi_nop
```

Định dạng Dataset 1 theo góp ý giảng viên 18/11/2026: thư mục/ID theo mã bia, không dấu cách, không tiếng Việt;
mỗi thư mục chứa đúng 1 MẶT bia (`02329-21/images/02329-21.001.jpg`,
`02329-21/patches/02329-21.001.005.jpg`; `--group-by doc` để gộp theo văn bản); `results.xlsx` = `Image ID | Patch ID | Bounding Box |
SinoNom OCR (OCR văn bia) | SinoNom Book (chữ sách đã gióng = nhãn rec_gt) | Similarity (%)` + sheet `summary`.
Box trán nằm ngang nhiều chữ: nhãn ghi theo thứ tự chữ trong ảnh patch (trái→phải).

Kết quả 18/11/2026 (76 mặt, 35 văn bia; số liệu đầy đủ: `reports/BAO_CAO_TONG_HOP_<ngày>.md`):
- Văn bản sạch: 24 trang Hán Gemini đọc dọc đã OCR lại (3.261/17.249 ký tự Hán thay đổi; Việt gần như không đổi).
- Dataset 1: 2.376 box, 2.369 patch có nhãn (946 nhãn chữ sách + 1.423 `MASK`), 16.089 chữ Hán có nhãn, phủ 96,3% văn
  bản sách; độ khớp OCR văn bia ↔ sách 81,3% (theo chữ). 375 box `needs_review` đã rà soát tay (ảnh + khe sách + Phiên âm,
  `data/processed/quyet_dinh_ra_soat.csv`, pipeline tự áp lại): còn 7 box không gán được (`da_sua=1`, có lý do).
- Dataset 2: 816 cặp, 740 ok.
- Dóng hàng dịch âm (tool giảng viên): bộ văn bia 826 box, khớp 88,2%; bộ sách 961 câu, khớp 88,3%; notes.xlsx 288 câu.
