"""Kiểm thử gióng hàng câu song ngữ trên văn bản thật Bia 1 (Pháp Vân tự bi).

Kiểm tra:
1. Gióng câu 3 trường: Chữ Hán, Phiên âm, Dịch nghĩa.
2. Xuất ra file .jsonl chuẩn định dạng Data Contract.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from src.step4_trans_align.sentence_aligner import (
    align_translation_dataset,
    export_translation_dataset,
)

TESTBED_DIR = Path(__file__).resolve().parent / "testbed"


def test_real_bia01_translation_alignment():
    han_text = (TESTBED_DIR / "gt_han" / "BIA01_Phap_Van_tu_bi.txt").read_text(encoding="utf-8")
    pa_text = (TESTBED_DIR / "gt_phien_am" / "BIA01_Phap_Van_tu_bi.txt").read_text(encoding="utf-8")
    dn_text = (TESTBED_DIR / "gt_dich_nghia" / "BIA01_Phap_Van_tu_bi.txt").read_text(encoding="utf-8")

    pairs = align_translation_dataset("BIA01", han_text, pa_text, dn_text)
    assert len(pairs) >= 10
    print(f"Bia 1 gióng được {len(pairs)} cặp câu song ngữ Hán - Việt:")
    for p in pairs[:5]:
        print(f"  [{p.sentence_id}] HÁN: {p.han} | DỊCH: {p.dich_nghia}")

    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = export_translation_dataset("BIA01", pairs, Path(tmpdir))
        assert out_file.exists()
        lines = out_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == len(pairs)
        row = json.loads(lines[0])
        assert row["bia_id"] == "BIA01"
        assert row["han"]
        assert row["phien_am"]
        assert row["dich_nghia"]


if __name__ == "__main__":
    test_real_bia01_translation_alignment()
    print("TEST REAL BIA01 TRANSLATION ALIGNMENT PASSED!")
