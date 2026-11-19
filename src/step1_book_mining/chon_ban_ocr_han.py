"""Chọn bản OCR tốt hơn cho từng trang có chữ Hán: Gemini thường (``<model>/``) hay Gemini giãn dòng (``<model>-gian-dong/``).

Vì sao: Gemini đọc nhầm nhiều trang Hán theo CỘT DỌC (chữ in thành lưới đều) mà vẫn trả STOP — vd tr.150, 312, 115 —
làm Chu_Han sai cả đoạn (18/11/2026: 33% chữ sách không box văn bia nào khớp). Không có bản đúng để so, nên dùng hai
"trọng tài" độc lập với chữ Hán của Gemini:
  1. khop_am — tỉ lệ chữ Hán của trang khớp âm với Phiên âm của chính văn bia đó (gióng semi-global, từ điển giảng viên
     QuocNgu_SinoNom). Phiên âm do Gemini đọc tiếng Việt (CER ≈ 0%) nên đáng tin; đọc dọc → khớp âm sụp (0,1–0,4).
  2. rapid — khoảng cách Levenshtein tới OCR cục bộ RapidOCR (``sach_ocr/scan_all``) — dùng khi văn bia không có
     Phiên âm (bia 13).
Luật (một chiều, bảo thủ): dùng bản giãn dòng khi khop_am ≥ 0,5 VÀ hơn bản thường > 0,02; văn bia không có Phiên âm thì
khi rapid giảm > 0,05; bản thường lệch hẳn RapidOCR (≥ 0,5) mà bản giãn dòng gần (≤ 0,3) → dùng (tr.302); và luôn đòi số chữ Hán ≥ 90% số chữ RapidOCR (mất dòng làm khop_am TĂNG giả vì dòng tên người
ít khớp âm bị bỏ — đã gặp ở tr.213). Đo trên 2 trang có bản chép tay (tr.100, 217): trang vốn tốt thì bản giãn dòng
không hơn (CER 3,3→4,4% / 3,7→3,7%) → không thay trang tốt. Trang ảnh chụp bia (tr.199: Gemini "đọc" chữ trên ảnh bia) không qua được ngưỡng 0,5 → giữ bản thường.

    python -m src.step1_book_mining.chon_ban_ocr_han          → data/interim/sach_ocr/gemini/chon_ban.csv (clean_book_text đọc)
"""
from __future__ import annotations

import ast
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from rapidfuzz.distance import Levenshtein

from src.step3_ocr_align.text_aligner import normalize_han_str
from src.step4_trans_align.build_dataset_dich import syllables
from src.step4_trans_align.tu_dien_han_viet import am_key, load_readings

ROOT = Path(__file__).resolve().parents[2]
GEM = ROOT / "data/interim/sach_ocr/gemini"
SCAN = ROOT / "data/interim/sach_ocr/scan_all"
CHON = GEM / "chon_ban.csv"
MODEL = "gemini-3.5-flash-lite"
FALLBACK = "gemini-3.5-flash"
HAN = re.compile(r"[㐀-鿿\U00020000-\U0003134F]")
KHOP_MIN, KHOP_HON, RAPID_HON = 0.5, 0.02, 0.05
DU_CHU = 0.9      # bản giãn dòng phải có ≥ 90% số chữ Hán RapidOCR đọc được (chặn bản bị mất dòng — tr.213 bản đầu)


def han(t: str) -> str:
    return normalize_han_str("".join(HAN.findall(t)))


def khop_am(h: str, sy: list[str], lex: dict[str, set[str]]) -> float:
    """Semi-global: chuỗi Hán `h` khớp trọn, dãy âm `sy` tự do hai đầu; trả số cặp chữ↔âm khớp từ điển / len(h)."""
    if not h or not sy:
        return 0.0
    m = len(sy)
    M, X, G = 1.0, -0.3, -0.6
    prev, cprev = np.zeros(m + 1), np.zeros(m + 1)
    for ch in h:
        ks = lex.get(ch, ())
        eq = np.fromiter((s in ks for s in sy), dtype=float, count=m)
        diag = prev[:-1] + np.where(eq > 0, M, X)
        up = prev[1:] + G
        take = diag >= up
        cur, cnt = np.empty(m + 1), np.empty(m + 1)
        cur[0], cnt[0] = prev[0] + G, cprev[0]
        cur[1:] = np.where(take, diag, up)
        cnt[1:] = np.where(take, cprev[:-1] + eq, cprev[1:])
        for j in range(1, m + 1):                     # đi ngang = âm tiết thừa
            if cur[j - 1] + G > cur[j]:
                cur[j], cnt[j] = cur[j - 1] + G, cnt[j - 1]
        prev, cprev = cur, cnt
    return float(cprev[int(np.argmax(prev))]) / len(h)


def rapid(p: int) -> str:
    f = SCAN / f"p{p:03d}.json"
    if not f.exists():
        return ""
    d = json.loads(f.read_text(encoding="utf-8"))
    ls = d["lines"] if isinstance(d["lines"], list) else ast.literal_eval(d["lines"])
    return han("".join(x["text"] for x in ls))


def pages_and_docs() -> dict[int, list[str]]:
    """trang Hán → tên văn bản (file Phien_am) theo inventory (tr_han) + van_ban_ma_bia."""
    ten = {r["doc_id"]: r["ten_file"] for r in csv.DictReader(open(ROOT / "data/metadata/van_ban_ma_bia.csv", encoding="utf-8"))}
    out: dict[int, list[str]] = {}
    for r in csv.DictReader(open(ROOT / "data/metadata/inventory.csv", encoding="utf-8")):
        m = re.search(r"tr_han=(\d+)-?(\d+)?", r["ghi_chu"])
        if m and r["doc_id"] in ten:
            for p in range(int(m[1]), int(m[2] or m[1]) + 1):
                out.setdefault(p, []).append(ten[r["doc_id"]])
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    lex: dict[str, set[str]] = defaultdict(set)
    for ch, ks in load_readings().items():
        lex[normalize_han_str(ch)] |= ks
    rows = []
    for p, stems in sorted(pages_and_docs().items()):
        fb = next((f for f in (GEM / MODEL / f"p{p:03d}.txt", GEM / FALLBACK / f"p{p:03d}.txt") if f.exists()), None)
        fg = GEM / f"{MODEL}-gian-dong" / f"p{p:03d}.txt"
        if not fg.exists():
            continue
        hb, hg = han(fb.read_text(encoding="utf-8")) if fb else "", han(fg.read_text(encoding="utf-8"))
        sy = []
        for st in stems:
            pf = ROOT / "data/processed/Phien_am" / f"{st}.txt"
            if pf.exists():
                sy += [am_key(x) for line in pf.read_text(encoding="utf-8").splitlines() for x in syllables(line) if x != "？"]
        R = rapid(p)
        kb, kg = round(khop_am(hb, sy, lex), 3), round(khop_am(hg, sy, lex), 3)
        rb = round(Levenshtein.normalized_distance(hb, R), 3) if R else None
        rg = round(Levenshtein.normalized_distance(hg, R), 3) if R else None
        du = not R or len(R) < 30 or len(hg) >= DU_CHU * len(R)
        if not du:
            use, why = False, f"thiếu chữ so với RapidOCR ({len(hg)}/{len(R)})"
        elif rb is not None and rb >= 0.5 and rg <= 0.3:
            use, why = True, f"bản thường lệch hẳn RapidOCR ({rb}), bản giãn dòng khớp ({rg}); khop_am {kb}→{kg}"
        elif sy:
            use = kg >= KHOP_MIN and kg > kb + KHOP_HON
            why = f"khop_am {kb}→{kg}"
        else:
            use = rb is not None and rg < rb - RAPID_HON and rg < 0.5
            why = f"không có Phiên âm; rapid {rb}→{rg}"
        nguon = fg.parent.name if use else (fb.parent.name if fb else "")
        rows.append([p, nguon, kb, kg, rb, rg, len(hb), len(hg), ("DÙNG GIÃN DÒNG: " if use else "giữ bản thường: ") + why])
    with open(CHON, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["trang", "nguon", "khop_am_thuong", "khop_am_gian_dong", "rapid_thuong", "rapid_gian_dong",
                    "chu_han_thuong", "chu_han_gian_dong", "ly_do"])
        w.writerows(rows)
    used = [r for r in rows if r[1].endswith("gian-dong")]
    print(f"{len(rows)} trang có bản giãn dòng; dùng bản giãn dòng {len(used)} trang: {[r[0] for r in used]} → {CHON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
