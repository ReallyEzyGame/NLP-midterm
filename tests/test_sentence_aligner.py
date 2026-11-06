"""Kiểm thử bộ gióng câu song ngữ sentence_aligner (Dataset 2).

Kiểm tra:
1. Tách câu chữ Hán và tiếng Việt.
2. Gióng câu bằng DP (Gale-Church model).
3. Xuất file .jsonl đúng định dạng.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from src.step4_trans_align.sentence_aligner import (
    align_translation_dataset,
    export_translation_dataset,
    split_sentences_han,
    split_sentences_vi,
)


def test_split_sentences():
    han = "重修法雲寺碑銘。銘曰：扶寧勝地，寺創法雲；幾代陳修樓殿。"
    vi = "Bài minh về việc trùng tu chùa Pháp Vân. Lời minh rằng: Đất Phù Ninh tươi đẹp, tạo dựng chùa Pháp Vân; Mấy đời nhà Trần sửa sang lầu điện."

    h_sents = split_sentences_han(han)
    v_sents = split_sentences_vi(vi)

    assert len(h_sents) >= 2
    assert len(v_sents) >= 2


def test_align_translation_and_export():
    han_text = """重修法雲寺碑銘
扶寧勝地，寺創法雲。
幾代陳修樓殿。"""

    pa_text = """Trùng tu Pháp Vân tự bi minh.
Phù Ninh thắng địa, Tự sáng Pháp Vân.
Kỉ đại Trần tu lâu điện."""

    dn_text = """Bài minh về việc trùng tu chùa Pháp Vân.
Đất Phù Ninh tươi đẹp, Tạo chùa Pháp Vân.
Bấy triều từng trải, Tu sửa lầu điện."""

    pairs = align_translation_dataset("BIA01", han_text, pa_text, dn_text)
    assert len(pairs) >= 2
    assert pairs[0].han == "重修法雲寺碑銘"
    assert "Trùng tu" in pairs[0].phien_am
    assert "chùa Pháp Vân" in pairs[0].dich_nghia

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        out_file = export_translation_dataset("BIA01", pairs, out_dir)
        assert out_file.exists()

        lines = out_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == len(pairs)
        first_row = json.loads(lines[0])
        assert first_row["bia_id"] == "BIA01"
        assert first_row["sentence_id"] == 1
        assert "han" in first_row
        assert "phien_am" in first_row
        assert "dich_nghia" in first_row


if __name__ == "__main__":
    test_split_sentences()
    test_align_translation_and_export()
    print("ALL SENTENCE ALIGNER TESTS PASSED!")
