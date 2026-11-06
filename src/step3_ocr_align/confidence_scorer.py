"""Hệ thống Hiệu chuẩn Điểm tin cậy (Confidence Scorer) & Chẩn đoán Trạng thái (Diagnostics).

Mục tiêu (Step 4):
1. Tính điểm tin cậy tổng hợp (Composite Confidence Score):
   Kết hợp giữa:
   - Character Edit Similarity (Độ khớp ký tự có tính Wildcard)
   - Length Consistency Ratio (Tỷ lệ tương thích độ dài giữa OCR và GT)
   - Detector Confidence (Độ tin cậy của PaddleOCR detection/recognition)
2. Hệ thống cờ chẩn đoán chi tiết (Diagnostic Flags):
   Cung cấp lý do giải thích cho trường 'note', hỗ trợ đắc lực cho Task 3.C (Sửa nhãn tay).
"""
from __future__ import annotations

from typing import Any

# Các cờ chẩn đoán (Diagnostic Flags)
FLAG_EXACT_MATCH = "EXACT_MATCH"              # Khớp chính xác 100%
FLAG_HIGH_CONFIDENCE = "HIGH_CONFIDENCE"      # Khớp rất tốt (> 0.80)
FLAG_ACCEPTABLE = "ACCEPTABLE"                # Đạt ngưỡng chuẩn (0.60 - 0.80)
FLAG_LOW_SIMILARITY = "LOW_SIMILARITY"        # Ký tự sai nhiều (mòn đá hoặc OCR lỗi)
FLAG_LENGTH_MISMATCH = "LENGTH_MISMATCH"      # Chênh lệch độ dài bất thường (> 35%)
FLAG_DEBRIS_SUSPECTED = "DEBRIS_SUSPECTED"    # Nghi ngờ box rác/hoa văn viền
FLAG_WILDCARD_MATCH = "WILDCARD_MATCH"        # Khớp nhờ ký tự khuyết tự ○, □
FLAG_EMPTY_OCR = "EMPTY_OCR"                  # Box rỗng / OCR không đọc được chữ


def compute_length_consistency(ocr_len: int, gt_len: int) -> float:
    """Đo độ tương thích về độ dài giữa chuỗi OCR và chuỗi GT.
    Nếu chênh lệch quá lớn (ví dụ: OCR 10 chữ nhưng GT 20 chữ), điểm phạt sẽ tăng.
    """
    if ocr_len == 0 and gt_len == 0:
        return 1.0
    if ocr_len == 0 or gt_len == 0:
        return 0.0
    ratio = min(ocr_len, gt_len) / max(ocr_len, gt_len)
    return round(ratio, 4)


def compute_composite_score(
    char_sim: float,
    ocr_len: int,
    gt_len: int,
    ocr_conf: float = 0.90,
    weights: dict[str, float] | None = None,
) -> float:
    """Tính điểm tin cậy tổng hợp đa tiêu chí:
    Confidence = w_char * char_sim + w_len * len_ratio + w_ocr * ocr_conf
    """
    if weights is None:
        weights = {"char_sim": 0.70, "len_ratio": 0.20, "ocr_conf": 0.10}

    w_char = weights.get("char_sim", 0.70)
    w_len = weights.get("len_ratio", 0.20)
    w_ocr = weights.get("ocr_conf", 0.10)

    len_ratio = compute_length_consistency(ocr_len, gt_len)
    # Kẹp ocr_conf trong khoảng [0.0, 1.0]
    safe_ocr_conf = min(1.0, max(0.0, ocr_conf))

    composite = (w_char * char_sim) + (w_len * len_ratio) + (w_ocr * safe_ocr_conf)
    return round(min(1.0, max(0.0, composite)), 4)


def diagnose_alignment(
    ocr_text: str,
    gt_text: str,
    char_sim: float,
    composite_score: float,
    threshold: float = 0.60,
    min_reliable_score: float = 0.40,
) -> tuple[str, str]:
    """Chẩn đoán trạng thái ('ok' vs 'needs_review') và sinh cờ giải thích lý do.
    Trả về (status, diagnostic_note).
    """
    if not ocr_text:
        return "needs_review", FLAG_EMPTY_OCR

    if not gt_text:
        return "needs_review", FLAG_DEBRIS_SUSPECTED

    # Khớp chính xác 100%
    if ocr_text == gt_text:
        return "ok", FLAG_EXACT_MATCH

    ocr_len = len(ocr_text)
    gt_len = len(gt_text)
    len_ratio = compute_length_consistency(ocr_len, gt_len)

    # Kiểm tra chênh lệch độ dài bất thường
    if len_ratio < 0.65:
        return "needs_review", f"{FLAG_LENGTH_MISMATCH} (OCR: {ocr_len} chữ vs GT: {gt_len} chữ)"

    # Có khuyết tự
    has_wildcard = any(c in gt_text for c in ("○", "□", "◇", "?"))

    # Đánh giá theo ngưỡng
    if composite_score >= 0.85:
        note = f"{FLAG_HIGH_CONFIDENCE} + {FLAG_WILDCARD_MATCH}" if has_wildcard else FLAG_HIGH_CONFIDENCE
        return "ok", note

    if composite_score >= threshold:
        note = f"{FLAG_ACCEPTABLE} + {FLAG_WILDCARD_MATCH}" if has_wildcard else FLAG_ACCEPTABLE
        return "ok", note

    # Trường hợp dưới ngưỡng
    if composite_score < min_reliable_score:
        return "needs_review", f"{FLAG_DEBRIS_SUSPECTED} (Score={composite_score:.2f})"

    return "needs_review", f"{FLAG_LOW_SIMILARITY} (Score={composite_score:.2f})"
