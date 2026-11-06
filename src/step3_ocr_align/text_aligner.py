"""Bộ công cụ Gióng hàng Văn bia Hán Nôm - Phiên bản Tối ưu v2.1 (Step 4 Hiệu chuẩn).

Nâng cấp Step 4:
1. Tự động đọc cấu hình tham số từ configs/config.yml.
2. Tích hợp Confidence Scorer tính điểm tin cậy tổng hợp (Composite Score).
3. Hệ thống cờ chẩn đoán chi tiết (Diagnostic Flags) lưu vào trường 'note'.
4. Cơ chế chống trôi con trỏ (Anti-Drift) và Lookahead Anchor Recovery.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from abc import ABC, abstractmethod
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from src.step3_ocr_align.align_schema import (
    WILDCARD_CHARS,
    AlignItem,
    AlignResult,
    AlignStatus,
    sanitize_text,
    validate_raw_bbox_input,
)
from src.step3_ocr_align.confidence_scorer import (
    compute_composite_score,
    diagnose_alignment,
)
from src.utils import file_io as fio

log = logging.getLogger("text_aligner")
REPO_ROOT = Path(__file__).resolve().parents[2]


# =============================================================================
# 0. ĐỌC CẤU HÌNH (CONFIG LOADER)
# =============================================================================

def load_aligner_config(root: Path = REPO_ROOT) -> dict[str, Any]:
    """Đọc cấu hình từ configs/config.yml nếu có, hoặc trả về giá trị mặc định chuẩn."""
    cfg_path = root / "configs" / "config.yml"
    defaults = {
        "algo": "dp",
        "threshold": 0.60,
        "min_reliable_score": 0.40,
        "weights": {"match_score": 2.0, "mismatch_penalty": -1.0, "gap_penalty": -1.5},
        "composite_weights": {"char_sim": 0.70, "len_ratio": 0.20, "ocr_conf": 0.10},
    }
    if not cfg_path.exists():
        return defaults

    try:
        import yaml
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if data and "aligner" in data:
                al_cfg = data["aligner"]
                defaults.update({k: v for k, v in al_cfg.items() if v is not None})
    except Exception as e:
        log.warning("Không thể đọc %s: %s. Dùng cấu hình mặc định.", cfg_path, e)

    return defaults


# =============================================================================
# 1. TIỀN XỬ LÝ VĂN BẢN (TEXT NORMALIZATION)
# =============================================================================

def clean_gt_text(raw_text: str) -> str:
    """Làm sạch văn bản chữ Hán từ sách khảo cứu:
    - Chuẩn hóa Unicode NFC.
    - Chuẩn hóa các dạng dấu hỏi/ngoặc như (?) thành ký tự wildcard '○'.
    - Giữ lại chữ Hán (CJK Unified Ideographs, Hán Nôm mở rộng) và wildcard.
    """
    text = fio.nfc(raw_text)
    text = re.sub(r"\(\s*[\?？]\s*\)", "○", text)
    cleaned_chars = []
    for ch in text:
        if ch in WILDCARD_CHARS or "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf" or "\u20000" <= ch <= "\u2a6df":
            cleaned_chars.append(ch)
        elif ch.isalnum() and not ch.isascii():
            cleaned_chars.append(ch)
    return "".join(cleaned_chars)


def extract_title_and_body(gt_text: str) -> tuple[str, str]:
    """Tách phần tiêu đề (trán bia) và phần thân bia từ văn bản sách."""
    lines = [clean_gt_text(line) for line in gt_text.splitlines() if clean_gt_text(line)]
    if not lines:
        return "", ""
    if len(lines) == 1:
        return lines[0], lines[0]
    return lines[0], "".join(lines[1:])


# =============================================================================
# 2. THUẬT TOÁN SO KHỚP KÝ TỰ (CHARACTER-LEVEL ALIGNMENT)
# =============================================================================

def char_similarity(ocr_c: str, gt_c: str) -> float:
    """Đo độ tương đồng giữa 2 ký tự (có hỗ trợ wildcard)."""
    if ocr_c == gt_c:
        return 1.0
    if ocr_c in WILDCARD_CHARS or gt_c in WILDCARD_CHARS:
        return 1.0
    return 0.0


def semi_global_align(
    ocr_str: str,
    gt_str: str,
    match_score: float = 2.0,
    mismatch_penalty: float = -1.0,
    gap_penalty: float = -1.5,
) -> tuple[str, float, int, int]:
    """Thuật toán Semi-Global (Fitting Alignment) có hỗ trợ Wildcard:
    Tìm đoạn con tối ưu nhất trong gt_str khớp với ocr_str.
    Trả về (matched_gt, similarity_ratio, start_idx, end_idx).
    """
    n, m = len(ocr_str), len(gt_str)
    if n == 0 or m == 0:
        return "", 0.0, 0, 0

    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i * gap_penalty

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = match_score if char_similarity(ocr_str[i - 1], gt_str[j - 1]) > 0.0 else mismatch_penalty
            dp[i][j] = max(
                dp[i - 1][j - 1] + s,
                dp[i - 1][j] + gap_penalty,
                dp[i][j - 1] + gap_penalty,
            )

    best_j = max(range(m + 1), key=lambda j: dp[n][j])

    i, j = n, best_j
    al_gt = []
    matches = 0

    while i > 0 and j > 0:
        s = match_score if char_similarity(ocr_str[i - 1], gt_str[j - 1]) > 0.0 else mismatch_penalty
        if dp[i][j] == dp[i - 1][j - 1] + s:
            al_gt.append(gt_str[j - 1])
            if s == match_score:
                matches += 1
            i -= 1
            j -= 1
        elif dp[i][j] == dp[i - 1][j] + gap_penalty:
            al_gt.append("-")
            i -= 1
        else:
            al_gt.append(gt_str[j - 1])
            j -= 1

    al_gt.reverse()
    matched_gt = "".join(c for c in al_gt if c != "-")
    start_idx = j
    end_idx = best_j

    total_len = len(ocr_str) + len(matched_gt)
    sim = (2.0 * matches) / total_len if total_len > 0 else 0.0
    return matched_gt, round(min(1.0, max(0.0, sim)), 4), start_idx, end_idx


# =============================================================================
# 3. LỚP ALIGNER CƠ SỞ & NÂNG CẤP V2.1 (STEP 4)
# =============================================================================

class BaseAligner(ABC):
    """Lớp cơ sở trừu tượng cho mọi thuật toán gióng hàng."""

    def __init__(
        self,
        threshold: float = 0.60,
        min_reliable_score: float = 0.40,
        composite_weights: dict[str, float] | None = None,
        weights: dict[str, float] | None = None,
    ):
        self.threshold = threshold
        self.min_reliable_score = min_reliable_score
        self.composite_weights = composite_weights or {"char_sim": 0.70, "len_ratio": 0.20, "ocr_conf": 0.10}
        self.weights = weights or {"match_score": 2.0, "mismatch_penalty": -1.0, "gap_penalty": -1.5}

    @abstractmethod
    def align_sequence(self, ocr_text: str, gt_text: str) -> tuple[str, float, int, int]:
        pass

    def align(self, bia_id: str, boxes: list[dict], gt_text: str) -> AlignResult:
        """Thực hiện gióng hàng thông minh với cơ chế chống trôi con trỏ & Hiệu chuẩn điểm tin cậy."""
        sorted_boxes = sorted(boxes, key=lambda b: b.get("order", 0))
        tran_boxes = [b for b in sorted_boxes if b.get("region") == "tran"]
        than_boxes = [b for b in sorted_boxes if b.get("region") != "tran"]

        title_gt, body_gt = extract_title_and_body(gt_text)
        if not body_gt:
            body_gt = title_gt

        items: list[AlignItem] = []

        # 1. Gióng vùng Trán bia (nếu có)
        for b in tran_boxes:
            ocr = sanitize_text(b.get("text_ocr", ""))
            box_conf = float(b.get("score", 0.90))
            matched_gt, char_sim, _, _ = self.align_sequence(ocr, title_gt)

            comp_score = compute_composite_score(
                char_sim=char_sim,
                ocr_len=len(ocr),
                gt_len=len(matched_gt),
                ocr_conf=box_conf,
                weights=self.composite_weights,
            )
            status, note = diagnose_alignment(
                ocr_text=ocr,
                gt_text=matched_gt,
                char_sim=char_sim,
                composite_score=comp_score,
                threshold=self.threshold,
                min_reliable_score=self.min_reliable_score,
            )
            items.append(
                AlignItem(
                    order=b["order"],
                    text_ocr=ocr,
                    text_gt=matched_gt,
                    score=comp_score,
                    status=status,
                    region="tran",
                    note=f"Trán bia | {note}",
                )
            )

        # 2. Gióng vùng Thân bia với cơ chế Chống Trôi Con Trỏ & Lookahead
        body_clean = clean_gt_text(body_gt)
        curr_gt_idx = 0

        for idx, b in enumerate(than_boxes):
            ocr = sanitize_text(b.get("text_ocr", ""))
            box_conf = float(b.get("score", 0.90))

            if not ocr:
                items.append(
                    AlignItem(
                        order=b["order"],
                        text_ocr="",
                        text_gt="",
                        score=0.0,
                        status="needs_review",
                        region="than",
                        note="EMPTY_OCR (Box rỗng)",
                    )
                )
                continue

            # Cửa sổ tìm kiếm trượt
            window_size = max(len(ocr) + 12, int(len(ocr) * 2.5))
            candidate_gt = body_clean[curr_gt_idx : curr_gt_idx + window_size]

            matched_gt, char_sim, start_offset, end_offset = self.align_sequence(ocr, candidate_gt)

            # KIỂM TRA LOOKAHEAD: Nếu score quá thấp, kiểm tra xem box kế tiếp có match ngay tại curr_gt_idx không
            if char_sim < self.min_reliable_score and (idx + 1 < len(than_boxes)):
                next_ocr = sanitize_text(than_boxes[idx + 1].get("text_ocr", ""))
                if next_ocr:
                    next_cand = body_clean[curr_gt_idx : curr_gt_idx + max(len(next_ocr) + 12, int(len(next_ocr) * 2.5))]
                    _, next_sim, _, _ = self.align_sequence(next_ocr, next_cand)
                    if next_sim >= self.threshold:
                        # Box hiện tại là box rác chèn vào -> KHÔNG tăng con trỏ curr_gt_idx!
                        items.append(
                            AlignItem(
                                order=b["order"],
                                text_ocr=ocr,
                                text_gt="",
                                score=round(char_sim, 4),
                                status="needs_review",
                                region="than",
                                note="DEBRIS_SUSPECTED (Phát hiện Box rác/nhiễu viền, Anti-Drift kích hoạt)",
                            )
                        )
                        continue

            # Cập nhật con trỏ đọc trên chuỗi GT nếu điểm số đạt độ tin cậy
            if char_sim >= self.min_reliable_score:
                advance = end_offset if end_offset > 0 else max(1, len(matched_gt))
                curr_gt_idx += advance

            # Tính điểm tổng hợp và chẩn đoán
            final_gt = matched_gt if char_sim >= self.min_reliable_score else ""
            comp_score = compute_composite_score(
                char_sim=char_sim,
                ocr_len=len(ocr),
                gt_len=len(final_gt),
                ocr_conf=box_conf,
                weights=self.composite_weights,
            )
            status, note = diagnose_alignment(
                ocr_text=ocr,
                gt_text=final_gt,
                char_sim=char_sim,
                composite_score=comp_score,
                threshold=self.threshold,
                min_reliable_score=self.min_reliable_score,
            )

            items.append(
                AlignItem(
                    order=b["order"],
                    text_ocr=ocr,
                    text_gt=final_gt,
                    score=comp_score,
                    status=status,
                    region="than",
                    note=note,
                )
            )

        return AlignResult(bia_id=bia_id, items=items)


class DynamicProgrammingAligner(BaseAligner):
    """Thuật toán Semi-Global DP (Fitting Alignment) hỗ trợ Wildcard."""

    def align_sequence(self, ocr_text: str, gt_text: str) -> tuple[str, float, int, int]:
        ocr_clean = clean_gt_text(ocr_text)
        gt_clean = clean_gt_text(gt_text)

        if not ocr_clean or not gt_clean:
            return "", 0.0, 0, 0

        m_score = self.weights.get("match_score", 2.0)
        mm_penalty = self.weights.get("mismatch_penalty", -1.0)
        gap_penalty = self.weights.get("gap_penalty", -1.5)

        matched_gt, score, s_idx, e_idx = semi_global_align(
            ocr_clean, gt_clean, match_score=m_score, mismatch_penalty=mm_penalty, gap_penalty=gap_penalty
        )
        return matched_gt, score, s_idx, e_idx


class FastHeuristicAligner(BaseAligner):
    """Thuật toán Heuristic dùng SequenceMatcher (baseline nhanh)."""

    def align_sequence(self, ocr_text: str, gt_text: str) -> tuple[str, float, int, int]:
        ocr_clean = clean_gt_text(ocr_text)
        gt_clean = clean_gt_text(gt_text)
        if not ocr_clean or not gt_clean:
            return "", 0.0, 0, 0

        target_len = len(ocr_clean)
        cand = gt_clean[:target_len]
        sm = SequenceMatcher(None, ocr_clean, cand)
        score = sm.ratio()
        return cand, round(score, 4), 0, target_len


def get_aligner(
    algo: str | None = None,
    threshold: float | None = None,
    root: Path = REPO_ROOT,
) -> BaseAligner:
    """Factory hàm khởi tạo Aligner, tự động kết hợp CLI và file config.yml."""
    cfg = load_aligner_config(root)

    use_algo = algo or cfg.get("algo", "dp")
    use_threshold = threshold if threshold is not None else cfg.get("threshold", 0.60)
    min_rel = cfg.get("min_reliable_score", 0.40)
    weights = cfg.get("weights", {"match_score": 2.0, "mismatch_penalty": -1.0, "gap_penalty": -1.5})
    comp_weights = cfg.get("composite_weights", {"char_sim": 0.70, "len_ratio": 0.20, "ocr_conf": 0.10})

    if use_algo in ("dp", "needleman_wunsch", "semi_global"):
        return DynamicProgrammingAligner(
            threshold=use_threshold,
            min_reliable_score=min_rel,
            composite_weights=comp_weights,
            weights=weights,
        )
    elif use_algo in ("heuristic", "fast"):
        return FastHeuristicAligner(
            threshold=use_threshold,
            min_reliable_score=min_rel,
            composite_weights=comp_weights,
            weights=weights,
        )
    else:
        raise ValueError(f"Thuật toán không hỗ trợ: {use_algo!r}. Chọn 'dp' hoặc 'heuristic'.")


# =============================================================================
# 4. CLI RUNNER
# =============================================================================

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chạy bộ gióng hàng OCR - Chuẩn hóa Data Contract v1.0")
    p.add_argument("--root", type=Path, default=REPO_ROOT, help="Thư mục gốc của repo")
    p.add_argument("--bia-id", type=str, default=None, help="Chỉ định 1 bia cụ thể để gióng")
    p.add_argument("--all", action="store_true", help="Gióng toàn bộ các bia có trong data/processed/bbox_chuan")
    p.add_argument("--algo", choices=["dp", "heuristic"], default=None, help="Thuật toán gióng (mặc định theo config.yml)")
    p.add_argument("--threshold", type=float, default=None, help="Ngưỡng score phân loại ok/needs_review (mặc định theo config.yml)")
    return p.parse_args(argv)


def run_align_single(
    bia_id: str,
    root: Path,
    aligner: BaseAligner,
    doc_id: str | None = None,
) -> AlignResult:
    """Thực thi gióng hàng cho 1 mặt bia cụ thể."""
    proc = root / "data" / "processed"
    bb_path = proc / "bbox_chuan" / f"{bia_id}.json"
    if not bb_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file bbox_chuan: {bb_path}")

    bb_data = fio.read_json(bb_path)
    validate_raw_bbox_input(bb_data, bb_path)

    search_names = [bia_id]
    if doc_id:
        search_names.insert(0, doc_id)
    base_num = bia_id.split("-")[0]
    search_names.append(base_num)

    gt_file: Path | None = None
    for name in search_names:
        p = proc / "Chu_Han" / f"{name}.txt"
        if p.exists():
            gt_file = p
            break

    if gt_file is None:
        log.warning("Không tìm thấy file Chu_Han cho %s trong data/processed/Chu_Han/. Sử dụng chuỗi rỗng.", bia_id)
        gt_text = ""
    else:
        gt_text = fio.read_json(gt_file) if gt_file.suffix == ".json" else gt_file.read_text(encoding="utf-8")

    result = aligner.align(bia_id=bia_id, boxes=bb_data["boxes"], gt_text=gt_text)
    out_path = proc / "align" / f"{bia_id}.json"
    result.save(out_path)
    log.info(
        "[%s] Gióng xong %d boxes: %d OK, %d Needs Review (Điểm TB: %.2f) -> %s",
        bia_id,
        result.total_boxes,
        result.ok_count,
        result.review_count,
        result.average_score,
        out_path,
    )
    return result


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args(argv)
    aligner = get_aligner(algo=args.algo, threshold=args.threshold, root=args.root)

    proc = args.root / "data" / "processed"
    bb_dir = proc / "bbox_chuan"

    if args.bia_id:
        run_align_single(args.bia_id, args.root, aligner)
        return 0

    if args.all:
        if not bb_dir.exists():
            log.error("Thư mục %s chưa tồn tại.", bb_dir)
            return 1
        json_files = sorted(bb_dir.glob("*.json"))
        if not json_files:
            log.warning("Không có file nào trong %s", bb_dir)
            return 0
        for f in json_files:
            bia_id = f.stem
            try:
                run_align_single(bia_id, args.root, aligner)
            except Exception as e:
                log.error("Lỗi khi gióng bia %s: %s", bia_id, e)
        return 0

    log.info("Chỉ định --bia-id <ID> hoặc --all để chạy. Xem --help để biết thêm chi tiết.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
