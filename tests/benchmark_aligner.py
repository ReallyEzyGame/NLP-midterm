"""Benchmark so sánh hiệu năng và độ chính xác của các thuật toán gióng hàng.

Đánh giá 2 thuật toán:
1. DynamicProgrammingAligner (Semi-Global Fitting Alignment)
2. FastHeuristicAligner (SequenceMatcher Baseline)

Trên 4 kịch bản kiểm thử thực tế từ sách Văn bia làng Nành (Step 2 Testbed).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from src.step3_ocr_align.text_aligner import (
    DynamicProgrammingAligner,
    FastHeuristicAligner,
    clean_gt_text,
)
from src.utils import file_io as fio

TESTBED_DIR = Path(__file__).resolve().parent / "testbed"
BBOX_DIR = TESTBED_DIR / "bbox_simulated"
GT_DIR = TESTBED_DIR / "gt_han"


@dataclass
class BenchmarkMetric:
    testbed_name: str
    algo_name: str
    total_boxes: int
    ok_count: int
    review_count: int
    avg_score: float
    elapsed_ms: float
    gt_char_len: int
    matched_char_len: int


def run_single_benchmark(
    testbed_name: str,
    gt_file: Path,
    bbox_file: Path,
    algo_name: str,
    threshold: float = 0.60,
) -> BenchmarkMetric:
    gt_text = gt_file.read_text(encoding="utf-8")
    bb_data = fio.read_json(bbox_file)
    boxes = bb_data["boxes"]

    if algo_name == "dp":
        aligner = DynamicProgrammingAligner(threshold=threshold)
    else:
        aligner = FastHeuristicAligner(threshold=threshold)

    start_t = time.perf_counter()
    result = aligner.align(bia_id=testbed_name, boxes=boxes, gt_text=gt_text)
    elapsed = (time.perf_counter() - start_t) * 1000.0

    total_matched_chars = sum(len(it.text_gt) for it in result.items)
    clean_gt = clean_gt_text(gt_text)

    return BenchmarkMetric(
        testbed_name=testbed_name,
        algo_name=algo_name,
        total_boxes=result.total_boxes,
        ok_count=result.ok_count,
        review_count=result.review_count,
        avg_score=result.average_score,
        elapsed_ms=round(elapsed, 2),
        gt_char_len=len(clean_gt),
        matched_char_len=total_matched_chars,
    )


def run_all_benchmarks() -> list[BenchmarkMetric]:
    test_cases = [
        ("BIA01_clean", GT_DIR / "BIA01_Phap_Van_tu_bi.txt", BBOX_DIR / "BIA01_clean.json"),
        ("BIA01_noisy", GT_DIR / "BIA01_Phap_Van_tu_bi.txt", BBOX_DIR / "BIA01_noisy.json"),
        ("BIA01_wildcard", GT_DIR / "BIA01_Phap_Van_tu_bi.txt", BBOX_DIR / "BIA01_wildcard.json"),
        ("BIA02_realistic", GT_DIR / "BIA02_Hau_Phat_bi_ki_2459.txt", BBOX_DIR / "BIA02_realistic.json"),
    ]

    metrics: list[BenchmarkMetric] = []
    for name, gt_p, bb_p in test_cases:
        m_dp = run_single_benchmark(name, gt_p, bb_p, "dp")
        m_heu = run_single_benchmark(name, gt_p, bb_p, "heuristic")
        metrics.extend([m_dp, m_heu])

    return metrics


def print_report(metrics: list[BenchmarkMetric]):
    print("\n" + "=" * 90)
    print("BÁO CÁO BENCHMARK THUẬT TOÁN GIÓNG VĂN BIA HÁN NÔM (STEP 2 TESTBED)")
    print("=" * 90)
    print(f"{'Kịch bản':<18} | {'Thuật toán':<10} | {'Boxes':<5} | {'OK':<4} | {'Review':<6} | {'Điểm TB':<7} | {'Thời gian':<10} | {'Chữ khớp'}")
    print("-" * 90)
    for m in metrics:
        algo_display = "Semi-GL DP" if m.algo_name == "dp" else "Heuristic"
        print(f"{m.testbed_name:<18} | {algo_display:<10} | {m.total_boxes:<5} | {m.ok_count:<4} | {m.review_count:<6} | {m.avg_score:<7.4f} | {m.elapsed_ms:>6.2f} ms | {m.matched_char_len}/{m.gt_char_len}")
    print("=" * 90 + "\n")


if __name__ == "__main__":
    results = run_all_benchmarks()
    print_report(results)
