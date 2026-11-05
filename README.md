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
│       │   └── <Tên bia>/
│       │       ├── images/         # cạnh lớn nhất ≤ 1024, .001.jpg
│       │       ├── patches/        # xoay 90°, cao ≤ 96, .001.001.jpg
│       │       ├── det_gt.txt
│       │       ├── rec_gt.txt
│       │       └── results.xlsx
│       └── dataset_dich/<bia>.jsonl   # han / phien_am / dich_nghia
├── reports/                        # số box, số cặp câu
├── src/
│   ├── step1_book_mining/          # vision_ocr, regex_filter, split_by_bia
│   ├── step2_stele_ocr/            # download_bia, paddle_detect, filter_boxes, sort_bbox
│   ├── step3_ocr_align/            # text_aligner (Levenshtein/DP), crop_patches, export_ocr_dataset
│   ├── step4_trans_align/          # sentence_align (BertAlign), export_dich_dataset
│   └── utils/                      # file_io, image_processing (scale box khi resize), stats
├── .gitignore
├── requirements.txt
└── README.md
```

