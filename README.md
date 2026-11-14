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

## Chạy toàn bộ pipeline trên dữ liệu thật (cập nhật 15/11/2026)

Mọi lệnh chạy từ `NLP-midterm/` với `.venv` đã bật. Dữ liệu (`data/`) không commit.

```bash
# Bước 1 — văn bản sạch (không gọi API khi đã có OCR sách); chữ mất/sách lược → token MASK (giảng viên 14/11/2026)
python -m src.step1_book_mining.pipeline_1a --khong-ocr
# Bước 2 — OCR ảnh bia: mỗi nguồn một thư mục data/interim/paddle_raw/<engine>_<variant>/
python -m src.step2_stele_ocr.ocr_bia --engine paddle --device gpu   # GPU; Colab: src/step2_stele_ocr/colab/README.md
python -m src.step2_stele_ocr.ocr_bia --engine paddle --ve-anh       # vẽ <bia_id>_ocr_res_img.jpg (JSON đã có thì chỉ vẽ)
python -m src.step2_stele_ocr.ocr_bia --engine rapid                 # RapidOCR CPU (tuỳ chọn, thêm 1 nguồn)
# Bước 3 — Dataset 1: gióng v3, gộp nguồn theo mặt, MASK, xử lý needs_review → bbox_chuan/, align/, needs_review.csv
python src/utils/build_manifest.py                                    # data/metadata/bia_manifest.csv (nếu chưa có)
python -m src.step3_ocr_align.pipeline_dataset_ocr
python -m src.step3_ocr_align.export_ocr_dataset
# Bước 4 — Dataset 2: bộ ba Hán – Phiên âm – Dịch nghĩa
python -m src.step4_trans_align.build_dataset_dich
# Kiểm tra
python -m src.utils.validate
```

Kết quả (76 mặt, 35 văn bia): Dataset 1 — 1.905/2.292 box có nhãn (774 nhãn chữ Hán + 1.131 `MASK`), 11.877 chữ Hán có
nhãn; Dataset 2 — 813 cặp (580 ok). Box/cặp còn cần người xem có `ly_do` trong `data/processed/needs_review.csv` và
`reports/dataset_dich_<ngày>/needs_review.csv`. Chi tiết thay đổi và số đo: `test_debug/result/result.md` (ngoài repo).
