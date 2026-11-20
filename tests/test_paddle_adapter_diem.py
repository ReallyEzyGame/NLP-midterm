"""Thứ tự 4 điểm box (TL, TR, BR, BL thuận chiều kim đồng hồ) — kể cả box xoay ~45° (lỗi D5 ở 02496-44)."""
from src.step3_ocr_align.paddle_adapter import _to_4pts


def _cw(p):   # diện tích có dấu > 0 trong toạ độ ảnh (y xuống) = thuận chiều kim đồng hồ
    return sum(p[i][0] * p[(i + 1) % 4][1] - p[(i + 1) % 4][0] * p[i][1] for i in range(4)) > 0


def test_box_thoi_va_box_thuong():
    thoi = _to_4pts([[1722, 6127], [1772, 6078], [1772, 6176], [1821, 6127]])
    assert _cw(thoi) and thoi[0] == [1722, 6127]
    for pts in ([[10, 10], [100, 12], [98, 300], [8, 298]], [[98, 300], [8, 298], [10, 10], [100, 12]]):
        assert _to_4pts(pts) == [[10, 10], [100, 12], [98, 300], [8, 298]]


def test_so_chu_lech_so_box_bao_loi_score_cu_bo_qua(tmp_path):
    import json
    from src.step3_ocr_align.paddle_adapter import convert_paddle_raw_to_bbox_chuan
    box = [[[100 + 200 * i, 100], [250 + 200 * i, 100], [250 + 200 * i, 2000], [100 + 200 * i, 2000]] for i in range(3)]
    f = tmp_path / "x_res.json"
    f.write_text(json.dumps({"dt_polys": box, "rec_texts": ["天地人和", "山水風月", "日月星辰"], "rec_scores": [0.9]}),
                 encoding="utf-8")
    payload, _ = convert_paddle_raw_to_bbox_chuan(f, "x")
    assert len(payload["boxes"]) == 3                  # score cũ thiếu → không mất box
    f.write_text(json.dumps({"dt_polys": box, "rec_texts": ["天地人和", "山水風月"]}), encoding="utf-8")
    try:
        convert_paddle_raw_to_bbox_chuan(f, "x")
        raise AssertionError("phải báo lỗi khi số chữ ≠ số box")
    except ValueError:
        pass
