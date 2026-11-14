"""Kiểm thử aligner v3 (neo toàn cục + chain DP + trán theo vị trí + MASK) — dữ liệu tự tạo."""
from src.step3_ocr_align import aligner_v3 as v3
from src.step3_ocr_align.text_aligner import get_aligner, normalize_han_str


def test_selftest_aligner_v3():
    v3._selftest()                       # trán theo vị trí, box ngoài sách, đoạn sách lược, MASK, ends_anchored, est_chars


def test_factory_mac_dinh_la_v3():
    assert type(get_aligner()).__name__ == "AlignerV3"


def test_di_the_bo_sung():
    assert normalize_han_str("鄕黨") == normalize_han_str("鄉党")   # nhóm dị thể bổ sung 15/11/2026
