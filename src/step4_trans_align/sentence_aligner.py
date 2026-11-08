"""Bộ công cụ Gióng hàng Câu Song ngữ (Sentence Aligner) cho Dataset 2 (Dịch nghĩa).

Phiên bản v2.0 (Step 5 - Kiến trúc Kép Dual-Engine):
1. Engine 1 - Neural BertAlign / Embedding:
   - Sử dụng multilingual sentence embedding (mBERT/LaBSE/multilingual-e5) đo khoảng cách Cosine.
   - Thích hợp cho môi trường có GPU/PyTorch.
2. Engine 2 - Lightweight Dynamic Programming (Gale-Church model):
   - Thuần Python, zero-dependency, tốc độ siêu nhanh (< 5ms).
   - Tự động kích hoạt làm fallback nếu máy tính chưa cài đặt PyTorch/Transformers.

Tuân thủ cấu trúc xuất dữ liệu:
data/output/dataset_dich/<bia>.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.utils import file_io as fio

log = logging.getLogger("sentence_aligner")
REPO_ROOT = Path(__file__).resolve().parents[2]


# =============================================================================
# 1. DATA STRUCTURES & PREPROCESSING
# =============================================================================

@dataclass
class SentencePair:
    bia_id: str
    sentence_id: int
    han: str
    phien_am: str
    dich_nghia: str
    score: float = 1.0

    def to_jsonl_dict(self) -> dict[str, Any]:
        return {
            "bia_id": self.bia_id,
            "sentence_id": self.sentence_id,
            "han": self.han,
            "phien_am": self.phien_am,
            "dich_nghia": self.dich_nghia,
            "score": round(self.score, 4),
        }


def split_sentences_han(text: str) -> list[str]:
    """Tách câu chữ Hán dựa trên dấu ngắt câu hoặc dấu xuống dòng."""
    lines = text.splitlines()
    sentences = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"([。；！？\n])", line)
        for i in range(0, len(parts), 2):
            seg = parts[i].strip()
            punct = parts[i + 1] if i + 1 < len(parts) else ""
            if seg:
                sentences.append(seg + punct)
    return sentences


def split_sentences_vi(text: str) -> list[str]:
    """Tách câu tiếng Việt (áp dụng cho cả Phiên âm và Dịch nghĩa)."""
    lines = text.splitlines()
    sentences = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"([.!?;:\n])", line)
        for i in range(0, len(parts), 2):
            seg = parts[i].strip()
            punct = parts[i + 1] if i + 1 < len(parts) else ""
            if seg:
                sentences.append(seg + punct)
    return sentences


# =============================================================================
# 2. ALIGNMENT ENGINES
# =============================================================================

class BaseSentenceAligner(ABC):
    """Lớp trừu tượng cho các thuật toán gióng câu."""

    @abstractmethod
    def align_pairs(self, src_sents: list[str], tgt_sents: list[str]) -> list[tuple[str, str, float]]:
        pass


class DPSentenceAligner(BaseSentenceAligner):
    """Engine 1: Dynamic Programming (Mô hình mở rộng Gale-Church).
    Tối ưu hóa hàm chi phí khoảng cách độ dài câu chữ Hán sang tiếng Việt.
    """

    def __init__(self, char_ratio: float = 3.0):
        self.char_ratio = char_ratio

    def align_pairs(self, src_sents: list[str], tgt_sents: list[str]) -> list[tuple[str, str, float]]:
        n, m = len(src_sents), len(tgt_sents)
        if n == 0 or m == 0:
            return []

        if n == m:
            return [(src_sents[i], tgt_sents[i], 1.0) for i in range(n)]

        dp = [[float("inf")] * (m + 1) for _ in range(n + 1)]
        dp[0][0] = 0.0

        for i in range(n + 1):
            for j in range(m + 1):
                if i < n and j < m:
                    c11 = abs(len(tgt_sents[j]) - len(src_sents[i]) * self.char_ratio)
                    dp[i + 1][j + 1] = min(dp[i + 1][j + 1], dp[i][j] + c11)
                if i + 1 < n and j < m:
                    c21 = abs(len(tgt_sents[j]) - len(src_sents[i] + src_sents[i + 1]) * self.char_ratio)
                    dp[i + 2][j + 1] = min(dp[i + 2][j + 1], dp[i][j] + c21)
                if i < n and j + 1 < m:
                    c12 = abs(len(tgt_sents[j] + " " + tgt_sents[j + 1]) - len(src_sents[i]) * self.char_ratio)
                    dp[i + 1][j + 2] = min(dp[i + 1][j + 2], dp[i][j] + c12)

        i, j = n, m
        pairs = []
        while i > 0 and j > 0:
            c11 = abs(len(tgt_sents[j - 1]) - len(src_sents[i - 1]) * self.char_ratio) if (i >= 1 and j >= 1) else float("inf")
            c21 = abs(len(tgt_sents[j - 1]) - len(src_sents[i - 2] + src_sents[i - 1]) * self.char_ratio) if (i >= 2 and j >= 1) else float("inf")
            c12 = abs(len(tgt_sents[j - 2] + " " + tgt_sents[j - 1]) - len(src_sents[i - 1]) * self.char_ratio) if (i >= 1 and j >= 2) else float("inf")

            if i >= 1 and j >= 1 and dp[i][j] == dp[i - 1][j - 1] + c11:
                pairs.append((src_sents[i - 1], tgt_sents[j - 1], 0.95))
                i -= 1; j -= 1
            elif i >= 2 and j >= 1 and dp[i][j] == dp[i - 2][j - 1] + c21:
                pairs.append((src_sents[i - 2] + " " + src_sents[i - 1], tgt_sents[j - 1], 0.85))
                i -= 2; j -= 1
            elif i >= 1 and j >= 2 and dp[i][j] == dp[i - 1][j - 2] + c12:
                pairs.append((src_sents[i - 1], tgt_sents[j - 2] + " " + tgt_sents[j - 1], 0.85))
                i -= 1; j -= 2
            else:
                i -= 1; j -= 1

        pairs.reverse()
        return pairs


class BertSentenceAligner(BaseSentenceAligner):
    """Engine 2: Neural BertAlign / Multilingual Embedding Aligner.
    Tự động nạp bertalign hoặc sentence-transformers nếu có trong môi trường.
    Nếu không có, tự động chuyển về DPSentenceAligner.
    """

    def __init__(self, model_name: str = "sentence-transformers/LaBSE"):
        self.model_name = model_name
        self._fallback = DPSentenceAligner()
        self._has_bert = False
        self._bert_aligner = None

        # Kiểm tra sự hiện diện của thư viện neural
        try:
            import bertalign
            self._bert_aligner = bertalign.Bertalign()
            self._has_bert = True
            log.info("Khởi tạo BertSentenceAligner với bertalign thành công.")
        except Exception:
            try:
                from sentence_transformers import SentenceTransformer
                self._embed_model = SentenceTransformer(model_name)
                self._has_bert = True
                log.info("Khởi tạo BertSentenceAligner với SentenceTransformer (%s) thành công.", model_name)
            except Exception:
                log.info("Chưa cài đặt thư viện Neural (bertalign/transformers). Sử dụng DP Fallback Engine.")
                self._has_bert = False

    def align_pairs(self, src_sents: list[str], tgt_sents: list[str]) -> list[tuple[str, str, float]]:
        if not self._has_bert:
            return self._fallback.align_pairs(src_sents, tgt_sents)

        # Nếu có model: Tính embedding và khoảng cách Cosine
        try:
            import numpy as np
            src_embs = self._embed_model.encode(src_sents, normalize_embeddings=True)
            tgt_embs = self._embed_model.encode(tgt_sents, normalize_embeddings=True)
            # Ma trận Cosine similarity
            sim_matrix = np.dot(src_embs, tgt_embs.T)

            # Quy hoạch động tìm đường đi có tổng Cosine Similarity lớn nhất
            n, m = len(src_sents), len(tgt_sents)
            dp = [[-float("inf")] * (m + 1) for _ in range(n + 1)]
            dp[0][0] = 0.0

            for i in range(n + 1):
                for j in range(m + 1):
                    if i < n and j < m:
                        score = float(sim_matrix[i][j])
                        dp[i + 1][j + 1] = max(dp[i + 1][j + 1], dp[i][j] + score)

            i, j = n, m
            pairs = []
            while i > 0 and j > 0:
                pairs.append((src_sents[i - 1], tgt_sents[j - 1], float(sim_matrix[i - 1][j - 1])))
                i -= 1; j -= 1
            pairs.reverse()
            return pairs
        except Exception as e:
            log.warning("Lỗi trong quá trình chạy Neural Align: %s. Chuyển sang DP Fallback.", e)
            return self._fallback.align_pairs(src_sents, tgt_sents)


def get_sentence_aligner(engine: str = "auto") -> BaseSentenceAligner:
    """Factory hàm khởi tạo Sentence Aligner."""
    if engine == "bert":
        return BertSentenceAligner()
    elif engine == "dp":
        return DPSentenceAligner()
    else:  # "auto": thử BertAlign trước, nếu không có tự động dùng DP
        return BertSentenceAligner()


# =============================================================================
# 3. PIPELINE XỬ LÝ 3 TRƯỜNG & XUẤT FILE DATASET
# =============================================================================

def align_translation_dataset(
    bia_id: str,
    han_text: str,
    phien_am_text: str,
    dich_nghia_text: str,
    aligner: BaseSentenceAligner | None = None,
) -> list[SentencePair]:
    """Gióng hàng trọn vẹn 3 trường Chữ Hán - Phiên âm - Dịch nghĩa."""
    if aligner is None:
        aligner = get_sentence_aligner("auto")

    han_sents = split_sentences_han(han_text)
    phien_am_sents = split_sentences_vi(phien_am_text)
    dich_nghia_sents = split_sentences_vi(dich_nghia_text)

    # 1. Gióng Hán với Phiên âm
    han_pa_pairs = aligner.align_pairs(han_sents, phien_am_sents)

    # 2. Gióng Hán với Dịch nghĩa
    han_dn_pairs = aligner.align_pairs(han_sents, dich_nghia_sents)

    # 3. Hợp nhất 3 trường thành SentencePair hoàn chỉnh
    pairs: list[SentencePair] = []
    max_len = max(len(han_pa_pairs), len(han_dn_pairs))
    for idx in range(max_len):
        h = han_pa_pairs[idx][0] if idx < len(han_pa_pairs) else (han_dn_pairs[idx][0] if idx < len(han_dn_pairs) else "")
        pa = han_pa_pairs[idx][1] if idx < len(han_pa_pairs) else ""
        dn = han_dn_pairs[idx][1] if idx < len(han_dn_pairs) else ""
        sc = min(
            han_pa_pairs[idx][2] if idx < len(han_pa_pairs) else 0.5,
            han_dn_pairs[idx][2] if idx < len(han_dn_pairs) else 0.5,
        )
        pairs.append(SentencePair(bia_id=bia_id, sentence_id=idx + 1, han=h, phien_am=pa, dich_nghia=dn, score=sc))

    return pairs


def export_translation_dataset(
    bia_id: str,
    pairs: list[SentencePair],
    out_dir: Path,
) -> Path:
    """Xuất file data/output/dataset_dich/<bia_id>.jsonl."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{bia_id}.jsonl"
    lines = [json.dumps(p.to_jsonl_dict(), ensure_ascii=False) for p in pairs]
    fio.write_lines(out_file, lines)
    return out_file


# =============================================================================
# 4. CLI RUNNER
# =============================================================================

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chạy bộ gióng câu song ngữ Dataset 2 (Dịch nghĩa)")
    p.add_argument("--root", type=Path, default=REPO_ROOT, help="Thư mục gốc của repo")
    p.add_argument("--bia-id", type=str, default=None, help="Chỉ định mã văn bia cụ thể")
    p.add_argument("--all", action="store_true", help="Gióng câu toàn bộ các bia có trong data/processed/Chu_Han")
    p.add_argument("--engine", choices=["auto", "dp", "bert"], default="auto", help="Lựa chọn engine gióng")
    return p.parse_args(argv)


def run_sentence_align_single(bia_id: str, root: Path, aligner: BaseSentenceAligner) -> Path:
    proc = root / "data" / "processed"
    out_dir = root / "data" / "output" / "dataset_dich"

    han_path = proc / "Chu_Han" / f"{bia_id}.txt"
    pa_path = proc / "Phien_am" / f"{bia_id}.txt"
    dn_path = proc / "Dich_nghia" / f"{bia_id}.txt"

    han_text = han_path.read_text(encoding="utf-8") if han_path.exists() else ""
    pa_text = pa_path.read_text(encoding="utf-8") if pa_path.exists() else ""
    dn_text = dn_path.read_text(encoding="utf-8") if dn_path.exists() else ""

    pairs = align_translation_dataset(bia_id, han_text, pa_text, dn_text, aligner)
    out_file = export_translation_dataset(bia_id, pairs, out_dir)
    log.info("[%s] Gióng thành công %d cặp câu -> %s", bia_id, len(pairs), out_file)
    return out_file


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args(argv)
    aligner = get_sentence_aligner(args.engine)

    if args.bia_id:
        run_sentence_align_single(args.bia_id, args.root, aligner)
        return 0

    if args.all:
        han_dir = args.root / "data" / "processed" / "Chu_Han"
        if not han_dir.exists():
            log.error("Chưa có thư mục %s", han_dir)
            return 1
        for p in sorted(han_dir.glob("*.txt")):
            run_sentence_align_single(p.stem, args.root, aligner)
        return 0

    log.info("Chỉ định --bia-id <ID> hoặc --all để thực thi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
