"""Bộ công cụ Gióng hàng Văn bia Hán Nôm - Phiên bản Tối ưu v2.2 (Task 1.C Hiệu chuẩn thực tế).

Nâng cấp v2.2 từ dữ liệu thực tế (Task 1.C):
1. Chuẩn hóa Dị thể / Giản-Phồn thể / Chữ số kép trên đá (HAN_VARIANT_MAP).
2. Hỗ trợ Trán bia bị PaddleOCR đọc ngược chiều (Phải -> Trái vs Trái -> Phải).
3. Cơ chế Neo đa mặt bia & Tự đồng bộ lại (Multi-Face Global Anchor Recovery):
   - Tự định vị đúng mặt bia (vd 02459-31, 02460-32, 02461-33) trong file gộp của sách (Tuấn 1.A).
   - Bảo vệ box ngắn (tên công đức 2-4 chữ) khỏi khớp nhầm dây chuyền (Short-Box Guard).
   - Nhận diện và gióng chuẩn các đoạn bị OCR sách đảo dòng (Out-of-order Book OCR).
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
# 0. BẢNG TƯƠNG ĐƯƠNG DỊ THỂ / CHỮ KÉP HÁN NÔM & CẤU HÌNH
# =============================================================================

_VARIANT_GROUPS = (
    "後后",
    "修脩",
    "為爲",
    "顯顕",
    "鐵鉄",
    "稱称",
    "盡尽",
    "對対",
    "窮穷",
    "恆恒",
    "萬万",
    "參参",
    "監鑒",
    "橫横",
    "諡謚",
    "吳吴",
    "黃黄",
    "歸帰",
    "國国",
    "門门",
    "禮礼",
    "壽寿",
    "與与",
    "無无",
    "當当",
    "從从",
    "傳传",
    "廣广",
    "靈霊",
    "聖圣",
    "榮荣",
    "華华",
    "會会",
    "衆眾众",
    "祿禄",
    "宮宫",
    "寶宝",
    "處処",
    "實实",
    "歲歳",
    "應応",
    "樂楽",
    "曆歷历",
    "龜龟",
    "彌弥",
    "廟庙",
    "臺台",
    "餘余",
    "關关",
    "發发",
    "書书",
    "寫写",
    "畫画",
    "壇坛",
    "鐘鍾钟",
    "區区",
    "圖图",
    "團团",
    "壓压",
    "壞坏",
    "聲声",
    "學学",
    "體体",
    "點点",
    "齊齐",
    "齒齿",
    "龍龙",
    "總総总",
    "邊边",
    "戶戸",
    "鄉郷",
    "來来",
    "經经",
    "義义",
    "啟啓",
    "羣群",
    "眞真",
    "內内",
    "旣既",
    "卽即",
    "德徳",
    "供洪",
    # Chữ số kép trên văn bia cổ <-> chữ số thường trong sách (như Tuấn báo cáo ở BAO_CAO_1A)
    "一壹",
    "二貳",
    "三叄叁",
    "四肆",
    "五伍",
    "六陸",
    "七柒",
    "八捌",
    "九玖",
    "十拾",
    "百佰",
    "千仟",
)

HAN_VARIANT_MAP: dict[str, str] = {}
for _grp in _VARIANT_GROUPS:
    _canon = _grp[0]
    for _ch in _grp:
        HAN_VARIANT_MAP[_ch] = _canon

# Dị thể bổ sung gặp trên dữ liệu thật 76 mặt (debug 14/11/2026). Nhóm có chữ đã nằm trong bảng trên → NỐI vào nhóm đó
# (giữ dạng đại diện cũ), không tạo nhóm mới đè lên.
_EXTRA_VARIANT_GROUPS = ("黨党", "鄉鄕", "戶户戸", "鑒鉴", "敘叙", "並并", "茲兹", "穀糓", "牀床", "爾尒", "決决", "況况",
                         "淨净", "凉涼", "册冊", "徳德", "冲沖", "沒没", "惠恵", "藏蔵", "恭㳟", "顏顔", "姊姉", "曾曽")
for _grp in _EXTRA_VARIANT_GROUPS:
    _canon = next((HAN_VARIANT_MAP[c] for c in _grp if c in HAN_VARIANT_MAP), _grp[0])
    for _ch in _grp:
        HAN_VARIANT_MAP[_ch] = _canon


def normalize_han_char(ch: str) -> str:
    """Chuẩn hóa ký tự Hán Nôm về dạng đại diện khi so khớp dị thể/chữ kép."""
    return HAN_VARIANT_MAP.get(ch, ch)


def normalize_han_str(text: str) -> str:
    return "".join(normalize_han_char(c) for c in text)


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
    """Đo độ tương đồng giữa 2 ký tự (hỗ trợ wildcard và dị thể Hán Nôm)."""
    if ocr_c == gt_c:
        return 1.0
    if ocr_c in WILDCARD_CHARS or gt_c in WILDCARD_CHARS:
        return 1.0
    if normalize_han_char(ocr_c) == normalize_han_char(gt_c):
        return 1.0
    return 0.0


def semi_global_align(
    ocr_str: str,
    gt_str: str,
    match_score: float = 2.0,
    mismatch_penalty: float = -1.0,
    gap_penalty: float = -1.5,
) -> tuple[str, float, int, int]:
    """Thuật toán Semi-Global (Fitting Alignment) có hỗ trợ Wildcard & Dị thể:
    Tìm đoạn con tối ưu nhất trong gt_str khớp với ocr_str.
    Trả về (matched_gt, similarity_ratio, start_idx, end_idx).
    """
    n, m = len(ocr_str), len(gt_str)
    if n == 0 or m == 0:
        return "", 0.0, 0, 0

    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i * gap_penalty

    norm_ocr = [normalize_han_char(c) for c in ocr_str]
    norm_gt = [normalize_han_char(c) for c in gt_str]

    for i in range(1, n + 1):
        oc = ocr_str[i - 1]
        noc = norm_ocr[i - 1]
        oc_wild = oc in WILDCARD_CHARS
        dp_prev = dp[i - 1]
        dp_curr = dp[i]
        for j in range(1, m + 1):
            gc = gt_str[j - 1]
            is_match = oc_wild or noc == norm_gt[j - 1] or (gc in WILDCARD_CHARS)
            s = match_score if is_match else mismatch_penalty
            diag = dp_prev[j - 1] + s
            up = dp_prev[j] + gap_penalty
            left = dp_curr[j - 1] + gap_penalty
            dp_curr[j] = diag if (diag >= up and diag >= left) else (up if up >= left else left)

    best_j = max(range(m + 1), key=lambda j: dp[n][j])

    i, j = n, best_j
    al_gt = []
    matches = 0

    while i > 0 and j > 0:
        is_match = char_similarity(ocr_str[i - 1], gt_str[j - 1]) > 0.0
        s = match_score if is_match else mismatch_penalty
        if dp[i][j] == dp[i - 1][j - 1] + s:
            al_gt.append(gt_str[j - 1])
            if is_match:
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


def _has_bigram_hit(probe: str, target: str) -> bool:
    """Lọc nhanh trước khi quét toàn văn bản: ít nhất một cặp 2 chữ liên tiếp khớp (có chuẩn hóa dị thể)."""
    np_str = normalize_han_str(probe)
    nt_str = normalize_han_str(target)
    if len(np_str) < 2:
        return np_str in nt_str
    return any(np_str[k : k + 2] in nt_str for k in range(len(np_str) - 1))


# =============================================================================
# 3. LỚP ALIGNER CƠ SỞ & NÂNG CẤP V2.2 (TASK 1.C)
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

    def _build_item(
        self,
        order: int,
        ocr: str,
        gt_matched: str,
        char_sim: float,
        box_conf: float,
        region: str,
        extra_note: str = "",
    ) -> AlignItem:
        comp_score = compute_composite_score(
            char_sim=char_sim,
            ocr_len=len(ocr),
            gt_len=len(gt_matched),
            ocr_conf=box_conf,
            weights=self.composite_weights,
        )
        status, note = diagnose_alignment(
            ocr_text=ocr,
            gt_text=gt_matched,
            char_sim=char_sim,
            composite_score=comp_score,
            threshold=self.threshold,
            min_reliable_score=self.min_reliable_score,
        )
        full_note = f"{extra_note} | {note}" if extra_note else note
        return AlignItem(
            order=order,
            text_ocr=ocr,
            text_gt=gt_matched,
            score=comp_score,
            status=status,
            region=region,
            note=full_note,
        )

    def align(self, bia_id: str, boxes: list[dict], gt_text: str) -> AlignResult:
        """Thực hiện gióng hàng hỗ trợ đa mặt bia, chống trôi con trỏ & phục hồi neo."""
        sorted_boxes = sorted(boxes, key=lambda b: b.get("order", 0))
        tran_boxes = [b for b in sorted_boxes if b.get("region") == "tran"]
        than_boxes = [b for b in sorted_boxes if b.get("region") != "tran"]

        title_gt, body_gt = extract_title_and_body(gt_text)
        if not body_gt:
            body_gt = title_gt

        items: list[AlignItem] = []

        # 1. Gióng vùng Trán bia (hỗ trợ tiêu đề đọc ngược Trái<->Phải của PaddleOCR)
        for b in tran_boxes:
            ocr = sanitize_text(b.get("text_ocr", ""))
            box_conf = float(b.get("score", 0.90))
            matched_gt, char_sim, _, _ = self.align_sequence(ocr, title_gt)

            note_prefix = "Trán bia"
            if len(ocr) > 1:
                rev_gt, rev_sim, _, _ = self.align_sequence(ocr[::-1], title_gt)
                if rev_sim > char_sim:
                    matched_gt, char_sim = rev_gt, rev_sim
                    note_prefix = "Trán bia (Đảo chiều OCR)"

            items.append(
                self._build_item(
                    order=b["order"],
                    ocr=ocr,
                    gt_matched=matched_gt,
                    char_sim=char_sim,
                    box_conf=box_conf,
                    region="tran",
                    extra_note=note_prefix,
                )
            )

        # 2. Gióng vùng Thân bia với Multi-Face Re-Anchoring & Anti-Drift
        body_clean = clean_gt_text(body_gt)
        curr_gt_idx = 0
        has_anchored = False

        for idx, b in enumerate(than_boxes):
            ocr = sanitize_text(b.get("text_ocr", ""))
            ocr_clean = clean_gt_text(ocr)
            box_conf = float(b.get("score", 0.90))

            if not ocr or not ocr_clean:
                items.append(
                    AlignItem(
                        order=b["order"],
                        text_ocr=ocr,
                        text_gt="",
                        score=0.0,
                        status="needs_review",
                        region="than",
                        note="EMPTY_OCR (Box rỗng)",
                    )
                )
                continue

            # Bảo vệ box ngắn (tên công đức 2-4 chữ): yêu cầu độ khớp cao hơn tránh khớp bừa
            is_short = len(ocr_clean) <= 4
            local_min_sim = 0.70 if is_short else self.min_reliable_score

            window_size = max(len(ocr_clean) + 14, int(len(ocr_clean) * 2.5))
            candidate_gt = body_clean[curr_gt_idx : curr_gt_idx + window_size]

            matched_gt, char_sim, start_offset, end_offset = self.align_sequence(ocr_clean, candidate_gt)
            len_ok = len(matched_gt) >= max(1, int(len(ocr_clean) * 0.55))

            if char_sim >= local_min_sim and len_ok:
                advance = end_offset if end_offset > 0 else max(1, len(matched_gt))
                curr_gt_idx += advance
                has_anchored = True
                items.append(self._build_item(b["order"], ocr, matched_gt, char_sim, box_conf, "than"))
                continue

            # Thử Anti-Drift Lookahead: chỉ kích hoạt khi ĐÃ neo và box hiện tại nhỏ/nhiễu xen ngang
            if has_anchored and is_short and (idx + 1 < len(than_boxes)):
                next_ocr = clean_gt_text(sanitize_text(than_boxes[idx + 1].get("text_ocr", "")))
                if next_ocr:
                    n_win = max(len(next_ocr) + 14, int(len(next_ocr) * 2.5))
                    _, next_sim, _, _ = self.align_sequence(next_ocr, body_clean[curr_gt_idx : curr_gt_idx + n_win])
                    if next_sim >= max(0.70, self.threshold):
                        items.append(
                            AlignItem(
                                order=b["order"],
                                text_ocr=ocr,
                                text_gt="",
                                score=round(char_sim, 4),
                                status="needs_review",
                                region="than",
                                note="DEBRIS_SUSPECTED (Anti-Drift: Box nhiễu chèn giữa)",
                            )
                        )
                        continue

            # Phục hồi neo tiến tới (Forward Re-anchoring) cho văn bản nhiều mặt bia / sau đoạn bị lược bỏ
            reanchored = False
            forward_slice = body_clean[curr_gt_idx:]
            if len(ocr_clean) >= 6 and len(forward_slice) > window_size and _has_bigram_hit(ocr_clean, forward_slice):
                fw_gt, fw_sim, fw_s, fw_e = self.align_sequence(ocr_clean, forward_slice)
                if fw_sim >= 0.65 and len(fw_gt) >= int(len(ocr_clean) * 0.60):
                    curr_gt_idx += fw_e
                    has_anchored = True
                    reanchored = True
                    note_tag = "MULTI_FACE_ANCHOR" if fw_s > 0 else ""
                    items.append(self._build_item(b["order"], ocr, fw_gt, fw_sim, box_conf, "than", note_tag))

            if reanchored:
                continue

            # Thử Probe 2 box liên tiếp (hữu ích khi chuyển vào đoạn thơ/cột ngắn 4 chữ như '天開南越'+'地闢北京')
            if len(ocr_clean) >= 2 and (idx + 1 < len(than_boxes)):
                next_ocr = clean_gt_text(sanitize_text(than_boxes[idx + 1].get("text_ocr", "")))
                probe = ocr_clean + next_ocr
                if len(probe) >= 7 and len(forward_slice) > len(probe) and _has_bigram_hit(probe, forward_slice):
                    p_gt, p_sim, p_s, _ = self.align_sequence(probe, forward_slice)
                    if p_sim >= 0.78 and len(p_gt) >= int(len(probe) * 0.75):
                        anchor_slice = forward_slice[p_s : p_s + len(ocr_clean) + 6]
                        a_gt, a_sim, _, a_e = self.align_sequence(ocr_clean, anchor_slice)
                        if a_sim >= 0.70:
                            curr_gt_idx += p_s + a_e
                            has_anchored = True
                            items.append(
                                self._build_item(b["order"], ocr, a_gt, a_sim, box_conf, "than", "PROBE_2BOX_ANCHOR")
                            )
                            continue

            # Dự phòng văn bản sách bị OCR đảo thứ tự dòng (Out-of-order fallback trước curr_gt_idx)
            if curr_gt_idx > 0 and len(ocr_clean) >= 8:
                prefix_slice = body_clean[:curr_gt_idx]
                if _has_bigram_hit(ocr_clean, prefix_slice):
                    bw_gt, bw_sim, _, _ = self.align_sequence(ocr_clean, prefix_slice)
                    if bw_sim >= 0.72 and len(bw_gt) >= int(len(ocr_clean) * 0.70):
                        items.append(
                            self._build_item(
                                b["order"], ocr, bw_gt, bw_sim, box_conf, "than", "OUT_OF_ORDER_BOOK_SHUFFLE"
                            )
                        )
                        continue

            # Không khớp được: giữ nguyên con trỏ curr_gt_idx, đánh dấu needs_review
            items.append(
                self._build_item(
                    order=b["order"],
                    ocr=ocr,
                    gt_matched="",
                    char_sim=0.0,
                    box_conf=box_conf,
                    region="than",
                    extra_note="NOT_IN_BOOK_OR_LOW_MATCH",
                )
            )

        return AlignResult(bia_id=bia_id, items=items)


class DynamicProgrammingAligner(BaseAligner):
    """Thuật toán Semi-Global DP (Fitting Alignment) hỗ trợ Wildcard & Dị thể."""

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
        sm = SequenceMatcher(None, normalize_han_str(ocr_clean), normalize_han_str(cand))
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

    if use_algo == "v3":
        from src.step3_ocr_align.aligner_v3 import AlignerV3      # import trễ: aligner_v3 import module này

        return AlignerV3(
            threshold=use_threshold,
            min_reliable_score=min_rel,
            composite_weights=comp_weights,
            weights=weights,
        )
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


def find_gt_file_for_bia(bia_id: str, gt_dir: Path, doc_id: str | None = None) -> Path | None:
    """Tìm file Chu_Han khớp với bia_id (hỗ trợ cả file đơn lẻ và file ghép mã '_') của Tuấn."""
    if not gt_dir.exists():
        return None
    search_names = [bia_id]
    if doc_id:
        search_names.insert(0, doc_id)
    base_num = bia_id.split("-")[0]
    search_names.append(base_num)

    for name in search_names:
        p = gt_dir / f"{name}.txt"
        if p.exists():
            return p

    for f in sorted(gt_dir.glob("*.txt")):
        parts = f.stem.split("_")
        if bia_id in parts or base_num in [p.split("-")[0] for p in parts]:
            return f
    return None


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

    gt_dir = proc / "Chu_Han"
    gt_file = find_gt_file_for_bia(bia_id=bia_id, gt_dir=gt_dir, doc_id=doc_id)

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
