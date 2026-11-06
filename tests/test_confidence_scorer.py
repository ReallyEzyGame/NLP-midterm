"""Unit test cho module confidence_scorer.py (Step 4).

Kiểm tra:
1. Tính điểm tin cậy tổng hợp (Composite Score).
2. Xử lý phạt độ dài khi OCR và GT chênh lệch lớn.
3. Sinh đúng các cờ chẩn đoán (Diagnostic Flags).
"""
from __future__ import annotations

from src.step3_ocr_align.confidence_scorer import (
    FLAG_DEBRIS_SUSPECTED,
    FLAG_EMPTY_OCR,
    FLAG_EXACT_MATCH,
    FLAG_HIGH_CONFIDENCE,
    FLAG_LENGTH_MISMATCH,
    compute_composite_score,
    compute_length_consistency,
    diagnose_alignment,
)


def test_length_consistency():
    # Độ dài bằng nhau -> 1.0
    assert compute_length_consistency(10, 10) == 1.0
    # Chênh lệch nhẹ -> > 0.8
    assert compute_length_consistency(8, 10) == 0.8
    # Chênh lệch quá lớn -> thấp
    assert compute_length_consistency(4, 20) == 0.2


def test_composite_score():
    score = compute_composite_score(
        char_sim=0.90,
        ocr_len=10,
        gt_len=10,
        ocr_conf=0.95,
        weights={"char_sim": 0.70, "len_ratio": 0.20, "ocr_conf": 0.10},
    )
    # 0.70 * 0.90 + 0.20 * 1.0 + 0.10 * 0.95 = 0.63 + 0.20 + 0.095 = 0.925
    assert 0.92 < score < 0.93


def test_diagnostics_flags():
    # 1. Exact match
    status, note = diagnose_alignment("法雲寺", "法雲寺", 1.0, 1.0)
    assert status == "ok"
    assert note == FLAG_EXACT_MATCH

    # 2. Empty OCR
    status, note = diagnose_alignment("", "法雲寺", 0.0, 0.0)
    assert status == "needs_review"
    assert note == FLAG_EMPTY_OCR

    # 3. Debris / Missing GT
    status, note = diagnose_alignment("花紋", "", 0.0, 0.0)
    assert status == "needs_review"
    assert note == FLAG_DEBRIS_SUSPECTED

    # 4. Length mismatch
    status, note = diagnose_alignment("寺", "重修法雲寺碑銘銘曰扶寧勝地", 1.0, 0.5)
    assert status == "needs_review"
    assert FLAG_LENGTH_MISMATCH in note


if __name__ == "__main__":
    test_length_consistency()
    test_composite_score()
    test_diagnostics_flags()
    print("ALL CONFIDENCE SCORER TESTS PASSED!")
