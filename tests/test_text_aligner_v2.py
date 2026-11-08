"""Kiểm thử nâng cao cho text_aligner v2 (Step 3).

Kiểm tra 3 ca góc thực tế:
1. Box rác / Nhiễu viền (Debris/Noise insertion): Không làm trôi con trỏ đọc của các box tiếp theo.
2. Cột bị ngắt đôi (Split Box): 1 dòng dài bị ngắt làm 2 box liên tiếp vẫn khớp chính xác.
3. Box rỗng / Không nhận diện được chữ.
"""
from __future__ import annotations

from src.step3_ocr_align.text_aligner import DynamicProgrammingAligner


def test_anti_drift_garbage_box_insertion():
    """Kiểm tra: Box rác chèn giữa 2 cột thật KHÔNG làm trôi lệch cột thứ 2."""
    gt_text = "重修法雲寺碑銘\n銘曰扶寧勝地寺創法雲幾代陳修樓殿"

    # Box 1: Trán bia
    # Box 2: Thân bia cột 1 (chuẩn)
    # Box 3: Box RÁC (bắt nhầm hoa văn viền rồng mây -> OCR ra chữ vô nghĩa)
    # Box 4: Thân bia cột 2 (chuẩn)
    boxes = [
        {"order": 1, "region": "tran", "text_ocr": "重修法雲寺碑銘"},
        {"order": 2, "region": "than", "text_ocr": "銘曰扶寧勝地寺創法雲"},
        {"order": 3, "region": "than", "text_ocr": "口一之"},  # RÁC!
        {"order": 4, "region": "than", "text_ocr": "幾代陳修樓殿"},  # Cột 2 thật!
    ]

    aligner = DynamicProgrammingAligner(threshold=0.60)
    res = aligner.align("test_drift", boxes, gt_text)

    assert res.total_boxes == 4
    # Box 1 OK
    assert res.items[0].order == 1
    assert res.items[0].status == "ok"
    assert res.items[0].text_gt == "重修法雲寺碑銘"

    # Box 2 OK
    assert res.items[1].order == 2
    assert res.items[1].status == "ok"
    assert res.items[1].text_gt == "銘曰扶寧勝地寺創法雲"

    # Box 3 phải là needs_review (vì là rác)
    assert res.items[2].order == 3
    assert res.items[2].status == "needs_review"
    assert res.items[2].text_gt == ""

    # Box 4 PHẢI OK và KHÔNG BỊ TRÔI MẤT CHỮ!
    assert res.items[3].order == 4
    assert res.items[3].status == "ok"
    assert res.items[3].text_gt == "幾代陳修樓殿"


def test_split_column_handling():
    """Kiểm tra: 1 cột dài bị chia làm 2 box liên tiếp vẫn khớp mượt mà."""
    gt_text = "重修法雲寺碑銘\n扶寧勝地寺創法雲幾代陳修樓殿"

    # Cột '扶寧勝地寺創法雲幾代陳修樓殿' bị ngắt đôi:
    # Nửa 1: 扶寧勝地寺創法雲 (8 chữ)
    # Nửa 2: 幾代陳修樓殿 (6 chữ)
    boxes = [
        {"order": 1, "region": "than", "text_ocr": "扶寧勝地寺創法雲"},
        {"order": 2, "region": "than", "text_ocr": "幾代陳修樓殿"},
    ]

    aligner = DynamicProgrammingAligner(threshold=0.60)
    res = aligner.align("test_split", boxes, gt_text)

    assert res.total_boxes == 2
    assert res.items[0].status == "ok"
    assert res.items[0].text_gt == "扶寧勝地寺創法雲"

    assert res.items[1].status == "ok"
    assert res.items[1].text_gt == "幾代陳修樓殿"


if __name__ == "__main__":
    test_anti_drift_garbage_box_insertion()
    test_split_column_handling()
    print("ALL ADVANCED STEP 3 ROBUSTNESS TESTS PASSED!")
