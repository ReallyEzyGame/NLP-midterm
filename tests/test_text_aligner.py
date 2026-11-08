"""Unit test toàn diện cho text_aligner.py và tích hợp luồng Step 1.

Kiểm tra:
1. Làm sạch văn bản và chuẩn hóa wildcard (?).
2. Thuật toán Needleman-Wunsch có wildcard cho điểm tối đa khi khớp với ký tự bất kỳ.
3. Tách trán bia và thân bia hoạt động chính xác.
4. Chạy mô phỏng end-to-end: bbox_chuan -> text_aligner -> export_ocr_dataset.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from src.step3_ocr_align import export_ocr_dataset as ex
from src.step3_ocr_align.text_aligner import (
    DynamicProgrammingAligner,
    clean_gt_text,
    extract_title_and_body,
    run_align_single,
    semi_global_align,
)
from src.utils import file_io as fio


def test_clean_gt_text_and_wildcards():
    raw = "重修法雲寺碑銘( ? )。 扶寧勝地，寺創法雲。"
    cleaned = clean_gt_text(raw)
    assert "○" in cleaned
    assert "，" not in cleaned
    assert "。" not in cleaned
    assert cleaned == "重修法雲寺碑銘○扶寧勝地寺創法雲"


def test_needleman_wunsch_wildcards():
    # Khi ký tự là wildcard '○', phải match hoàn hảo với bất kỳ ký tự nào
    ocr_str = "勝地"
    gt_str = "○地"
    matched_gt, score, s_idx, e_idx = semi_global_align(ocr_str, gt_str)
    assert score == 1.0
    assert matched_gt == "○地"

    # Test khi có nhiễu OCR (1 ký tự sai)
    ocr_str = "扶寧勝地寺削法雲"
    gt_str = "扶寧勝地寺創法雲"  # Chữ '創' bị OCR nhận sai thành '削'
    matched_gt, score, s_idx, e_idx = semi_global_align(ocr_str, gt_str)
    assert score > 0.85
    assert matched_gt == "扶寧勝地寺創法雲"


def test_extract_title_and_body():
    text = "重修法雲寺碑銘\n銘曰：扶寧勝地\n寺創法雲"
    title, body = extract_title_and_body(text)
    assert title == "重修法雲寺碑銘"
    assert "扶寧勝地" in body
    assert "寺創法雲" in body


def test_end_to_end_step1_pipeline():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        proc = root / "data" / "processed"
        bb_dir = proc / "bbox_chuan"
        gt_dir = proc / "Chu_Han"
        bb_dir.mkdir(parents=True)
        gt_dir.mkdir(parents=True)

        bia_id = "00270-TF1"

        # 1. Giả lập chữ Hán từ Tuấn (A)
        gt_content = "重修法雲寺碑銘\n扶寧勝地寺創法雲幾代陳修樓殿莫朝陳氏之女"
        fio.write_text(gt_dir / f"{bia_id}.txt", gt_content)

        # 2. Giả lập box từ Nhật (B) với chữ OCR có chút nhiễu
        bb_data = {
            "schema_version": 1,
            "bia_id": bia_id,
            "boxes": [
                {
                    "order": 1,
                    "region": "tran",
                    "points": [[100, 100], [500, 100], [500, 300], [100, 300]],
                    "text_ocr": "重修法雲寺碑銘",  # Trán bia
                    "score": 0.95,
                    "source": "auto",
                },
                {
                    "order": 2,
                    "region": "than",
                    "points": [[100, 400], [200, 400], [200, 1000], [100, 1000]],
                    "text_ocr": "扶寧勝地寺削法雲",  # Thân cột 1 (sai 1 chữ)
                    "score": 0.88,
                    "source": "auto",
                },
                {
                    "order": 3,
                    "region": "than",
                    "points": [[250, 400], [350, 400], [350, 1000], [250, 1000]],
                    "text_ocr": "幾代陳修樓殿",  # Thân cột 2
                    "score": 0.92,
                    "source": "auto",
                },
            ],
        }
        fio.write_json(bb_dir / f"{bia_id}.json", bb_data)

        # 3. Chạy text_aligner của Điền (C)
        aligner = DynamicProgrammingAligner(threshold=0.60)
        res = run_align_single(bia_id=bia_id, root=root, aligner=aligner)

        assert res.total_boxes == 3
        assert res.ok_count == 3
        assert res.review_count == 0
        assert res.items[0].text_gt == "重修法雲寺碑銘"
        assert res.items[0].region == "tran"

        # 4. Kiểm tra Phong (D) dùng load_boxes đọc trực tiếp kết quả
        cfg = ex.ExportConfig(root=root)
        loaded_boxes = ex.load_boxes(bia_id, cfg)
        assert len(loaded_boxes) == 3
        assert all(b.status == "ok" for b in loaded_boxes)
        assert loaded_boxes[0].text_gt == "重修法雲寺碑銘"


if __name__ == "__main__":
    test_clean_gt_text_and_wildcards()
    test_needleman_wunsch_wildcards()
    test_extract_title_and_body()
    test_end_to_end_step1_pipeline()
    print("ALL END-TO-END STEP 1 TESTS PASSED SUCCESSFULLY!")
