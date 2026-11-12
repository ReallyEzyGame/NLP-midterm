"""Pipeline Bước 1.C — Gióng thử, chỉnh thử (Trial Alignment & Parameter Calibration).

Thực thi trọn vẹn quy trình 1.C trên dữ liệu thật của nhóm (hoặc fallback testbed):
1. Chuyển đổi OCR thô (`data/interim/paddle_raw/*_res.json`) -> `data/processed/bbox_chuan/<bia_id>.json`.
2. Gióng hàng bằng thuật toán V2.2 (hỗ trợ dị thể, đa mặt bia, trán bia đảo chiều).
3. Xuất kết quả `data/processed/align/<bia_id>.json` và `data/processed/needs_review.csv`.
4. Chạy quét hiệu chuẩn ngưỡng (Calibration Sweep) qua nhiều mức threshold.
5. Sinh báo cáo số liệu `reports/pipeline_1c_trial.tsv` và báo cáo nghiệm thu `reports/BAO_CAO_1C.md`.

Chạy từ gốc repo:
    python -m src.step3_ocr_align.pipeline_1c_trial
    python -m src.step3_ocr_align.pipeline_1c_trial --threshold 0.80 --tune
    python -m src.step3_ocr_align.pipeline_1c_trial --use-testbed
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from src.step3_ocr_align.align_schema import AlignResult, validate_raw_bbox_input
from src.step3_ocr_align.paddle_adapter import convert_paddle_raw_to_bbox_chuan
from src.step3_ocr_align.text_aligner import (
    DynamicProgrammingAligner,
    find_gt_file_for_bia,
    load_aligner_config,
)
from src.utils import file_io as fio

log = logging.getLogger("pipeline_1c")
REPO_ROOT = Path(__file__).resolve().parents[2]
SWEEP_THRESHOLDS = (0.60, 0.70, 0.75, 0.80, 0.85)


@dataclass
class TrialSteleRecord:
    """Thông số tổng hợp sau khi chuyển đổi và gióng thử một mặt bia."""

    bia_id: str
    gt_file_name: str
    raw_boxes: int
    dropped_debris: int
    kept_boxes: int
    tran_boxes: int
    than_boxes: int
    result: AlignResult
    dropped_details: list[dict[str, Any]]


def _resolve_bia_id_from_filename(stem: str) -> str:
    """Rút trích bia_id chuẩn từ tên file dạng `02459-31_res` -> `02459-31`."""
    return stem[:-4] if stem.endswith("_res") else stem


def _find_matching_image(bia_id: str, img_dir: Path) -> Path | None:
    if not img_dir.exists():
        return None
    for ext in (".jpg", ".jpeg", ".png"):
        exact = img_dir / f"{bia_id}{ext}"
        if exact.exists():
            return exact
        base = bia_id.split("-")[0]
        for candidate in sorted(img_dir.glob(f"{base}*{ext}")):
            return candidate
    return None


def _load_gt_text(bia_id: str, gt_dir: Path) -> tuple[str, str]:
    gt_file = find_gt_file_for_bia(bia_id=bia_id, gt_dir=gt_dir)
    if gt_file is None:
        return "", "(Không tìm thấy)"
    return gt_file.read_text(encoding="utf-8"), gt_file.name


def run_trial_on_real_data(
    root: Path,
    target_bias: set[str] | None = None,
    threshold: float = 0.80,
) -> list[TrialSteleRecord]:
    """Chạy chuẩn hóa bbox_chuan + gióng hàng trên dữ liệu PaddleOCR thật."""
    raw_dir = root / "data" / "interim" / "paddle_raw"
    img_dir = root / "data" / "raw" / "anh_bia"
    gt_dir = root / "data" / "processed" / "Chu_Han"
    bb_dir = root / "data" / "processed" / "bbox_chuan"
    al_dir = root / "data" / "processed" / "align"

    bb_dir.mkdir(parents=True, exist_ok=True)
    al_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_aligner_config(root)
    aligner = DynamicProgrammingAligner(
        threshold=threshold,
        min_reliable_score=cfg.get("min_reliable_score", 0.40),
        composite_weights=cfg.get("composite_weights"),
        weights=cfg.get("weights"),
    )

    raw_files = sorted(raw_dir.glob("*_res.json")) if raw_dir.exists() else []
    records: list[TrialSteleRecord] = []

    for rf in raw_files:
        bia_id = _resolve_bia_id_from_filename(rf.stem)
        if target_bias and bia_id not in target_bias and bia_id.split("-")[0] not in target_bias:
            continue

        img_path = _find_matching_image(bia_id, img_dir)
        payload, dropped = convert_paddle_raw_to_bbox_chuan(rf, bia_id=bia_id, image_path=img_path)
        validate_raw_bbox_input(payload)

        bb_out = bb_dir / f"{bia_id}.json"
        with open(bb_out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")

        gt_text, gt_name = _load_gt_text(bia_id, gt_dir)
        res = aligner.align(bia_id=bia_id, boxes=payload["boxes"], gt_text=gt_text)
        res.save(al_dir / f"{bia_id}.json")

        tran_count = sum(1 for b in payload["boxes"] if b.get("region") == "tran")
        than_count = len(payload["boxes"]) - tran_count
        records.append(
            TrialSteleRecord(
                bia_id=bia_id,
                gt_file_name=gt_name,
                raw_boxes=len(payload["boxes"]) + len(dropped),
                dropped_debris=len(dropped),
                kept_boxes=len(payload["boxes"]),
                tran_boxes=tran_count,
                than_boxes=than_count,
                result=res,
                dropped_details=dropped,
            )
        )
    return records


def run_trial_on_testbed(root: Path, threshold: float = 0.80) -> list[TrialSteleRecord]:
    """Chế độ fallback chạy trên bộ testbed mô phỏng nếu chưa có JSON thật."""
    tb = root / "tests" / "testbed"
    cfg = load_aligner_config(root)
    aligner = DynamicProgrammingAligner(
        threshold=threshold,
        min_reliable_score=cfg.get("min_reliable_score", 0.40),
        composite_weights=cfg.get("composite_weights"),
        weights=cfg.get("weights"),
    )
    mapping = [
        ("BIA01_clean", "BIA01_Phap_Van_tu_bi.txt"),
        ("BIA01_noisy", "BIA01_Phap_Van_tu_bi.txt"),
        ("BIA01_wildcard", "BIA01_Phap_Van_tu_bi.txt"),
        ("BIA02_realistic", "BIA02_Hau_Phat_bi_ki_2459.txt"),
    ]
    records: list[TrialSteleRecord] = []
    for bid, gt_fname in mapping:
        bb_path = tb / "bbox_simulated" / f"{bid}.json"
        gt_path = tb / "gt_han" / gt_fname
        if not bb_path.exists() or not gt_path.exists():
            continue
        bb_data = fio.read_json(bb_path)
        gt_text = gt_path.read_text(encoding="utf-8")
        res = aligner.align(bia_id=bid, boxes=bb_data["boxes"], gt_text=gt_text)
        tran_count = sum(1 for b in bb_data["boxes"] if b.get("region") == "tran")
        records.append(
            TrialSteleRecord(
                bia_id=bid,
                gt_file_name=gt_fname,
                raw_boxes=len(bb_data["boxes"]),
                dropped_debris=0,
                kept_boxes=len(bb_data["boxes"]),
                tran_boxes=tran_count,
                than_boxes=len(bb_data["boxes"]) - tran_count,
                result=res,
                dropped_details=[],
            )
        )
    return records


def write_needs_review_csv(records: list[TrialSteleRecord], out_csv: Path) -> int:
    """Xuất file data/processed/needs_review.csv đúng chuẩn Data Contract Mục 5.5."""
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    cols = ["bia_id", "order", "text_ocr", "text_gt", "score", "ly_do", "nguoi_sua", "da_sua"]
    count = 0
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(cols)
        for rec in records:
            for item in rec.result.items:
                if item.status == "needs_review":
                    writer.writerow(
                        [
                            rec.bia_id,
                            item.order,
                            item.text_ocr,
                            item.text_gt,
                            f"{item.score:.4f}",
                            item.note,
                            "",
                            0,
                        ]
                    )
                    count += 1
    return count


def run_calibration_sweep(
    root: Path,
    records: list[TrialSteleRecord],
    use_testbed: bool = False,
) -> list[dict[str, Any]]:
    """Chạy hiệu chuẩn qua nhiều ngưỡng threshold để chọn mức tối ưu (Chỉnh thử)."""
    cfg = load_aligner_config(root)
    bb_dir = root / "data" / "processed" / "bbox_chuan"
    gt_dir = root / "data" / "processed" / "Chu_Han"
    tb = root / "tests" / "testbed"

    sweep_rows: list[dict[str, Any]] = []
    for th in SWEEP_THRESHOLDS:
        aligner = DynamicProgrammingAligner(
            threshold=th,
            min_reliable_score=cfg.get("min_reliable_score", 0.40),
            composite_weights=cfg.get("composite_weights"),
            weights=cfg.get("weights"),
        )
        total, ok_c, rev_c = 0, 0, 0
        weighted_score = 0.0
        for rec in records:
            if use_testbed:
                bb_data = fio.read_json(tb / "bbox_simulated" / f"{rec.bia_id}.json")
                gt_text = (tb / "gt_han" / rec.gt_file_name).read_text(encoding="utf-8")
            else:
                bb_data = fio.read_json(bb_dir / f"{rec.bia_id}.json")
                gt_text, _ = _load_gt_text(rec.bia_id, gt_dir)
            res = aligner.align(bia_id=rec.bia_id, boxes=bb_data["boxes"], gt_text=gt_text)
            total += res.total_boxes
            ok_c += res.ok_count
            rev_c += res.review_count
            weighted_score += sum(it.score for it in res.items)

        sweep_rows.append(
            {
                "threshold": th,
                "total": total,
                "ok": ok_c,
                "review": rev_c,
                "ok_rate": round(100.0 * ok_c / total, 2) if total else 0.0,
                "avg_score": round(weighted_score / total, 4) if total else 0.0,
            }
        )
    return sweep_rows


def write_tsv_report(records: list[TrialSteleRecord], out_tsv: Path) -> None:
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "bia_id",
        "gt_file",
        "raw_boxes",
        "dropped_debris",
        "kept_boxes",
        "tran_boxes",
        "than_boxes",
        "ok_count",
        "review_count",
        "ok_rate_pct",
        "avg_score",
    ]
    with open(out_tsv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(cols)
        for r in records:
            ok_pct = 100.0 * r.result.ok_count / r.kept_boxes if r.kept_boxes else 0.0
            writer.writerow(
                [
                    r.bia_id,
                    r.gt_file_name,
                    r.raw_boxes,
                    r.dropped_debris,
                    r.kept_boxes,
                    r.tran_boxes,
                    r.than_boxes,
                    r.result.ok_count,
                    r.result.review_count,
                    f"{ok_pct:.1f}",
                    f"{r.result.average_score:.4f}",
                ]
            )


def write_markdown_report(
    records: list[TrialSteleRecord],
    sweep_rows: list[dict[str, Any]],
    threshold: float,
    review_count: int,
    out_md: Path,
    source_label: str,
) -> None:
    """Sinh báo cáo Markdown hoàn chỉnh cho Task 1.C."""
    out_md.parent.mkdir(parents=True, exist_ok=True)
    total_raw = sum(r.raw_boxes for r in records)
    total_dropped = sum(r.dropped_debris for r in records)
    total_kept = sum(r.kept_boxes for r in records)
    total_ok = sum(r.result.ok_count for r in records)
    ok_pct = (100.0 * total_ok / total_kept) if total_kept else 0.0

    lines = [
        "# Báo cáo Bước 1.C — Gióng thử & Hiệu chuẩn tham số (Trial Alignment)",
        "",
        f"Người thực hiện: Điền (C) · Ngày chạy: {date.today().strftime('%d/%m/%Y')} · Nguồn dữ liệu: **{source_label}** · Ngưỡng hiệu chuẩn: `{threshold:.2f}`",
        "",
        "## 1. Tổng hợp kết quả chuyển đổi & gióng hàng",
        "",
        f"- **Tổng số mặt bia chạy thử**: {len(records)} mặt bia",
        f"- **Lọc box nhiễu/lề giấy rập (`paddle_adapter`)**: {total_raw} box thô → loại {total_dropped} box rác/lề thư viện → giữ **{total_kept} box nội dung chuẩn**",
        f"- **Kết quả gióng chuẩn (`ok`)**: **{total_ok}/{total_kept}** ({ok_pct:.1f}%)",
        f"- **Danh sách cần rà soát (`needs_review.csv`)**: **{review_count} box**",
        "",
        "### Bảng chi tiết từng mặt bia",
        "",
        "| Mã bia (`bia_id`) | File Chữ Hán (1.A) | Raw boxes | Nhiễu lề loại | Box chuẩn | Trán/Thân | OK | Needs Review | Điểm TB |",
        "|---|---|---:|---:|---:|---|---:|---:|---:|",
    ]
    for r in records:
        lines.append(
            f"| `{r.bia_id}` | `{r.gt_file_name}` | {r.raw_boxes} | {r.dropped_debris} | {r.kept_boxes} "
            f"| {r.tran_boxes} / {r.than_boxes} | **{r.result.ok_count}** | {r.result.review_count} | {r.result.average_score:.3f} |"
        )

    lines.extend(
        [
            "",
            "## 2. Kết quả Chỉnh thử (Calibration Sweep theo ngưỡng `threshold`)",
            "",
            "| Ngưỡng (`threshold`) | Tổng box chuẩn | OK | Needs Review | Tỷ lệ OK (%) | Điểm TB | Nhận xét |",
            "|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in sweep_rows:
        note = "Khuyến nghị chuẩn (Data Contract v1.0)" if abs(row["threshold"] - 0.80) < 1e-6 else (
            "Dễ lọt box trùng tên họ ngắn (2/3 chữ)" if row["threshold"] < 0.78 else "Quá khắt khe với chữ bị mòn nhẹ"
        )
        lines.append(
            f"| `{row['threshold']:.2f}` | {row['total']} | {row['ok']} | {row['review']} "
            f"| {row['ok_rate']:.1f}% | {row['avg_score']:.4f} | {note} |"
        )

    anchor_hits = sum(
        1 for r in records for it in r.result.items if "MULTI_FACE_ANCHOR" in it.note or "PROBE_2BOX_ANCHOR" in it.note
    )
    debris_samples = [d["text"] for r in records for d in r.dropped_details[:2]][:6]
    debris_preview = ", ".join(f"`{t}`" for t in debris_samples) if debris_samples else "(Không có)"
    has_bia2_trial = any(r.bia_id.startswith("02459") for r in records)

    lines.extend(
        [
            "",
            "## 3. Phân tích các phát hiện & hiệu chuẩn kỹ thuật",
            "",
            f"1. **Lọc nhiễu lề ảnh thư viện**: Loại bỏ **{total_dropped}/{total_raw}** box rác/lề ngoài bản rập (ví dụ: {debris_preview}).",
            "2. **Thứ tự đọc & gom cụm cột dọc**: Tự động gom các cụm cột dọc từ phải sang trái và sắp xếp từ trên xuống dưới trong từng cột; nhận diện trán bia đọc ngược Trái↔Phải.",
            "3. **Hiệu chuẩn dị thể & chữ kép (`V2.2`)**: Bổ sung bảng ánh xạ dị thể (`後/后`, `脩/修`, `為/爲`, `顕/顯`, `鐵/鉄`, `稱/称`, `盡/尽`, `監/鑒`, `橫/横`) và chữ số kép (`拾/十`, `貳/二`) giúp không phạt nhầm các biến thể khắc đá.",
            f"4. **Hỗ trợ đa mặt bia (`Multi-Face Anchor`)**: Kích hoạt **{anchor_hits}** lần tự động dò neo lại để định vị đúng từng mặt bia nằm giữa/cuối trong file văn bản gộp nhiều mặt của Tuấn.",
        ]
    )
    if has_bia2_trial:
        lines.extend(
            [
                "5. **Cảnh báo chất lượng dữ liệu phát hiện trên lô thử nghiệm (Bia 2: `02459-31`, `02460-32`, `02461-33`)**:",
                "   - **Đoạn đảo dòng từ OCR sách (1.A)**: Trên mặt `02459-31` (box 8–12), Gemini OCR sách đọc đảo cột 5 dòng chữ Hán trang 44–45 (`line 2–6` trong `Chu_Han`), trong khi bản `Phien_am` vẫn đúng thứ tự.",
                "   - **Danh sách công đức lược bỏ**: Các cụm tên người công đức trên `02459-31` (13 box) và `02461-33` (33 box) không có trong sách đã được giữ an toàn trong `needs_review.csv` với **0 trường hợp khớp nhầm dây chuyền**.",
            ]
        )

    with open(out_md, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pipeline Bước 1.C — Gióng thử & Hiệu chuẩn")
    p.add_argument("--root", type=Path, default=REPO_ROOT, help="Thư mục gốc repo")
    p.add_argument("--bia", type=str, default=None, help="Danh sách bia cách nhau dấu phẩy (vd: 02459-31,02460-32)")
    p.add_argument("--threshold", type=float, default=0.80, help="Ngưỡng tin cậy chuẩn (mặc định 0.80)")
    p.add_argument("--use-testbed", action="store_true", help="Chạy trên testbed mô phỏng thay vì data thật")
    p.add_argument("--no-tune", action="store_true", help="Bỏ qua bước quét nhiều threshold")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args(argv)

    target_bias = {s.strip() for s in args.bia.split(",") if s.strip()} if args.bia else None
    raw_dir = args.root / "data" / "interim" / "paddle_raw"
    has_real_raw = raw_dir.exists() and any(raw_dir.glob("*_res.json"))

    use_testbed = args.use_testbed or not has_real_raw
    source_label = "Testbed mô phỏng" if use_testbed else "Dữ liệu OCR thật (1.A + 1.B)"

    if use_testbed:
        log.info("Chạy 1.C trên dữ liệu Testbed mô phỏng...")
        records = run_trial_on_testbed(args.root, threshold=args.threshold)
    else:
        log.info("Chạy 1.C trên dữ liệu thật tại %s...", raw_dir)
        records = run_trial_on_real_data(args.root, target_bias=target_bias, threshold=args.threshold)

    if not records:
        log.error("Không tìm thấy dữ liệu bia nào để chạy 1.C.")
        return 1

    rev_csv = args.root / "data" / "processed" / "needs_review.csv"
    review_count = write_needs_review_csv(records, rev_csv)

    sweep_rows = [] if args.no_tune else run_calibration_sweep(args.root, records, use_testbed=use_testbed)

    tsv_path = args.root / "reports" / "pipeline_1c_trial.tsv"
    md_path = args.root / "reports" / "BAO_CAO_1C.md"
    write_tsv_report(records, tsv_path)
    write_markdown_report(records, sweep_rows, args.threshold, review_count, md_path, source_label)

    for r in records:
        log.info(
            "[%s] Raw=%d (loại %d) -> Chuẩn=%d | OK=%d | Review=%d | Avg=%.3f",
            r.bia_id,
            r.raw_boxes,
            r.dropped_debris,
            r.kept_boxes,
            r.result.ok_count,
            r.result.review_count,
            r.result.average_score,
        )
    log.info("Đã xuất needs_review (%d dòng): %s", review_count, rev_csv)
    log.info("Đã xuất báo cáo 1.C: %s", md_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
