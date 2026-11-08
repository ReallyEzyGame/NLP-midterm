"""Kiểm thử tính tương thích của align_schema với Data Contract v1.0.

Đảm bảo:
1. align_schema serialize/deserialize chính xác 100%.
2. load_boxes trong export_ocr_dataset.py đọc được file xuất ra từ align_schema mà không có bất kỳ lỗi nào.
3. Các trường hợp chuỗi chứa ký tự tab, xuống dòng, ký tự đặc biệt được làm sạch triệt để.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from src.step3_ocr_align import export_ocr_dataset as ex
from src.step3_ocr_align.align_schema import (
    AlignItem,
    AlignResult,
    sanitize_text,
    validate_raw_bbox_input,
)
from src.utils import file_io as fio


def test_sanitize_text():
    raw = "   \t蓋聞\n仁義之舉\r\n\t  "
    clean = sanitize_text(raw)
    assert "\t" not in clean
    assert "\n" not in clean
    assert "\r" not in clean
    assert clean == "蓋聞 仁義之舉"


def test_align_schema_validation_and_stats():
    items = [
        AlignItem(order=1, text_ocr="碑銘", text_gt="重修法雲寺碑銘", score=0.95, status="ok", region="tran"),
        AlignItem(order=2, text_ocr="蓋聞", text_gt="蓋聞古語", score=0.88, status="ok", region="than"),
        AlignItem(order=3, text_ocr="???", text_gt="", score=0.20, status="needs_review", region="than"),
    ]
    res = AlignResult(bia_id="test-bia-01", items=items)

    assert res.total_boxes == 3
    assert res.ok_count == 2
    assert res.review_count == 1
    assert res.unmatched_count == 0
    assert 0.65 < res.average_score < 0.70

    # Test JSON serialization & loading
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "test-bia-01.json"
        res.save(p)
        assert p.exists()

        loaded = AlignResult.load(p)
        assert loaded.bia_id == res.bia_id
        assert len(loaded.items) == len(res.items)
        assert loaded.items[0].text_gt == "重修法雲寺碑銘"
        assert loaded.items[0].region == "tran"
        assert loaded.items[2].status == "needs_review"


def test_compatibility_with_export_ocr_dataset():
    """Kiểm tra load_boxes trong export_ocr_dataset.py đọc ngon lành file align được tạo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        proc = root / "data" / "processed"
        bb_dir = proc / "bbox_chuan"
        al_dir = proc / "align"
        bb_dir.mkdir(parents=True)
        al_dir.mkdir(parents=True)

        bia_id = "00270-TF1"

        # 1. Tạo bbox_chuan giả lập
        bb_data = {
            "schema_version": 1,
            "bia_id": bia_id,
            "boxes": [
                {
                    "order": 1,
                    "region": "tran",
                    "points": [[100, 100], [500, 100], [500, 300], [100, 300]],
                    "text_ocr": "記碑神佛",
                    "score": 0.9,
                    "source": "auto",
                },
                {
                    "order": 2,
                    "region": "than",
                    "points": [[100, 400], [200, 400], [200, 1000], [100, 1000]],
                    "text_ocr": "蓋聞古語",
                    "score": 0.85,
                    "source": "auto",
                },
            ],
        }
        fio.write_json(bb_dir / f"{bia_id}.json", bb_data)
        validate_raw_bbox_input(bb_data)

        # 2. Tạo AlignResult
        items = [
            AlignItem(order=1, text_ocr="記碑神佛", text_gt="重修法雲寺碑銘", score=0.92, status="ok", region="tran"),
            AlignItem(order=2, text_ocr="蓋聞古語", text_gt="蓋聞仁義之舉", score=0.88, status="ok", region="than"),
        ]
        align_res = AlignResult(bia_id=bia_id, items=items)
        align_res.save(al_dir / f"{bia_id}.json")

        # 3. Test hàm load_boxes của Phong
        cfg = ex.ExportConfig(root=root)
        boxes = ex.load_boxes(bia_id, cfg)

        assert len(boxes) == 2
        assert boxes[0].order == 1
        assert boxes[0].text_gt == "重修法雲寺碑銘"
        assert boxes[0].status == "ok"
        assert boxes[1].order == 2
        assert boxes[1].text_gt == "蓋聞仁義之舉"
        assert boxes[1].status == "ok"


if __name__ == "__main__":
    test_sanitize_text()
    test_align_schema_validation_and_stats()
    test_compatibility_with_export_ocr_dataset()
    print("ALL TESTS PASSED: align_schema is 100% compatible with Data Contract v1.0!")
