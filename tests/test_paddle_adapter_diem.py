"""Thứ tự 4 điểm box (TL, TR, BR, BL thuận chiều kim đồng hồ) — kể cả box xoay ~45° (lỗi D5 ở 02496-44)."""
from src.step3_ocr_align.paddle_adapter import _to_4pts


def _cw(p):   # diện tích có dấu > 0 trong toạ độ ảnh (y xuống) = thuận chiều kim đồng hồ
    return sum(p[i][0] * p[(i + 1) % 4][1] - p[(i + 1) % 4][0] * p[i][1] for i in range(4)) > 0


def test_box_thoi_va_box_thuong():
    thoi = _to_4pts([[1722, 6127], [1772, 6078], [1772, 6176], [1821, 6127]])
    assert _cw(thoi) and thoi[0] == [1722, 6127]
    for pts in ([[10, 10], [100, 12], [98, 300], [8, 298]], [[98, 300], [8, 298], [10, 10], [100, 12]]):
        assert _to_4pts(pts) == [[10, 10], [100, 12], [98, 300], [8, 298]]
