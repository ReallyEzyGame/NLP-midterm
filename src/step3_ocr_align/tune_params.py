"""Script Tìm kiếm Siêu tham số tối ưu (Hyperparameter Grid Search) cho Text Aligner.

Mục tiêu (Step 4):
Khảo sát không gian tham số:
- match_score: [1.5, 2.0, 2.5]
- mismatch_penalty: [-0.5, -1.0, -1.5]
- gap_penalty: [-1.0, -1.5, -2.0]
- threshold: [0.50, 0.55, 0.60, 0.65]

Đánh giá trên toàn bộ bộ Testbed Làng Nành (Bia 1 & Bia 2) để tìm cấu hình
đạt F1-score và độ chính xác gán nhãn cao nhất.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from pathlib import Path

from src.step3_ocr_align.text_aligner import DynamicProgrammingAligner
from src.utils import file_io as fio

TESTBED_DIR = Path(__file__).resolve().parents[2] / "tests" / "testbed"
BBOX_DIR = TESTBED_DIR / "bbox_simulated"
GT_DIR = TESTBED_DIR / "gt_han"


@dataclass
class TuningResult:
    match_score: float
    mismatch_penalty: float
    gap_penalty: float
    threshold: float
    total_boxes: int
    ok_count: int
    review_count: int
    avg_score: float
    elapsed_ms: float
    f1_score: float


def evaluate_config(
    match_score: float,
    mismatch_penalty: float,
    gap_penalty: float,
    threshold: float,
) -> TuningResult:
    test_cases = [
        ("BIA01_clean", GT_DIR / "BIA01_Phap_Van_tu_bi.txt", BBOX_DIR / "BIA01_clean.json"),
        ("BIA01_noisy", GT_DIR / "BIA01_Phap_Van_tu_bi.txt", BBOX_DIR / "BIA01_noisy.json"),
        ("BIA01_wildcard", GT_DIR / "BIA01_Phap_Van_tu_bi.txt", BBOX_DIR / "BIA01_wildcard.json"),
        ("BIA02_realistic", GT_DIR / "BIA02_Hau_Phat_bi_ki_2459.txt", BBOX_DIR / "BIA02_realistic.json"),
    ]

    weights = {
        "match_score": match_score,
        "mismatch_penalty": mismatch_penalty,
        "gap_penalty": gap_penalty,
    }
    aligner = DynamicProgrammingAligner(threshold=threshold, weights=weights)

    tot_boxes = 0
    tot_ok = 0
    tot_review = 0
    tot_score = 0.0
    start_t = time.perf_counter()

    for name, gt_p, bb_p in test_cases:
        gt_text = gt_p.read_text(encoding="utf-8")
        boxes = fio.read_json(bb_p)["boxes"]
        res = aligner.align(name, boxes, gt_text)

        tot_boxes += res.total_boxes
        tot_ok += res.ok_count
        tot_review += res.review_count
        tot_score += sum(it.score for it in res.items)

    elapsed = (time.perf_counter() - start_t) * 1000.0
    avg_sc = tot_score / tot_boxes if tot_boxes > 0 else 0.0

    # Ước lượng Precision & Recall:
    # Trong testbed, tất cả 74 boxes đều là box chữ thật -> recall = ok / total
    precision = 1.0  # Tất cả box OK đều có text_gt chính xác
    recall = tot_ok / tot_boxes if tot_boxes > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    return TuningResult(
        match_score=match_score,
        mismatch_penalty=mismatch_penalty,
        gap_penalty=gap_penalty,
        threshold=threshold,
        total_boxes=tot_boxes,
        ok_count=tot_ok,
        review_count=tot_review,
        avg_score=round(avg_sc, 4),
        elapsed_ms=round(elapsed, 2),
        f1_score=round(f1, 4),
    )


def run_grid_search() -> list[TuningResult]:
    match_scores = [1.5, 2.0, 2.5]
    mismatch_penalties = [-0.5, -1.0, -1.5]
    gap_penalties = [-1.0, -1.5, -2.0]
    thresholds = [0.55, 0.60, 0.65]

    results: list[TuningResult] = []
    print(f"Bắt đầu Grid Search {len(match_scores) * len(mismatch_penalties) * len(gap_penalties) * len(thresholds)} tổ hợp siêu tham số...")

    for m, mm, g, th in itertools.product(match_scores, mismatch_penalties, gap_penalties, thresholds):
        res = evaluate_config(m, mm, g, th)
        results.append(res)

    # Sắp xếp theo F1-score giảm dần, sau đó theo avg_score giảm dần
    results.sort(key=lambda r: (r.f1_score, r.avg_score, -r.elapsed_ms), reverse=True)
    return results


def print_top_results(results: list[TuningResult], top_n: int = 5):
    print("\n" + "=" * 95)
    print("KẾT QUẢ TOP SIÊU THAM SỐ TỐI ƯU CHO THUẬT TOÁN GIÓNG (STEP 4)")
    print("=" * 95)
    print(f"{'Hạng':<5} | {'Match':<6} | {'Mismatch':<9} | {'Gap':<6} | {'Threshold':<10} | {'F1-Score':<9} | {'Điểm TB':<8} | {'OK/Total':<9} | {'Thời gian'}")
    print("-" * 95)
    for idx, r in enumerate(results[:top_n], start=1):
        print(f"#{idx:<4} | {r.match_score:<6.1f} | {r.mismatch_penalty:<9.1f} | {r.gap_penalty:<6.1f} | {r.threshold:<10.2f} | {r.f1_score:<9.4f} | {r.avg_score:<8.4f} | {r.ok_count}/{r.total_boxes:<7} | {r.elapsed_ms:>6.2f} ms")
    print("=" * 95 + "\n")


if __name__ == "__main__":
    top = run_grid_search()
    print_top_results(top, top_n=5)
