"""Đo CER của kết quả OCR so với bản chép chuẩn (ground truth) — bước 0.A.6 của T.

Bản chép chuẩn: data/interim/ocr_thu/gt/p<trang>_<han|viet>.txt  (do Claude đọc từ ảnh, CHỜ Tuấn duyệt)
Kết quả OCR  : data/interim/sach_ocr/gemini/<model>/p<trang>.txt   (do ocr_gemini.py sinh ra)

Chuẩn hoá trước khi chấm:
  * NFC cả hai phía;
  * Hán: bỏ khoảng trắng, chữ số, dấu câu ``.。○，、:：``;
  * Việt: gộp khoảng trắng, bỏ số trang cuối trang;
  * ``--ignore`` bỏ những ký tự còn nghi ngờ ở bản chép chuẩn khỏi cả hai phía (vd ``--ignore 鐋鐺``).
CER = khoảng cách Levenshtein / số ký tự chuẩn.  "CER bỏ dấu" chỉ cho tiếng Việt.

Chạy:
    python -m src.step1_book_mining.eval_cer --models gemini-3.5-flash-lite --csv reports/ocr_benchmark.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path

from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).resolve().parents[2]
GT_DIR = ROOT / "data/interim/ocr_thu/gt"
OUT_ROOT = ROOT / "data/interim/sach_ocr/gemini"


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def strip_dia(s: str) -> str:
    s = unicodedata.normalize("NFD", s.replace("Đ", "D").replace("đ", "d"))
    return nfc("".join(c for c in s if unicodedata.category(c) != "Mn"))


def norm_han(s: str, ignore: str) -> str:
    s = re.sub(r"[\s0-9.。○，、:：]", "", nfc(s))
    return "".join(c for c in s if c not in ignore)


def norm_viet(s: str, page: int, ignore: str) -> str:
    s = " ".join(nfc(s).split())
    s = re.sub(rf"\s*\b{page}\b\s*$", "", s)
    return "".join(c for c in s if c not in ignore)


def score(gt: str, out: str) -> tuple[float, int]:
    ops = [o for o in Levenshtein.opcodes(gt, out) if o.tag != "equal"]
    return Levenshtein.distance(gt, out) / max(1, len(gt)), len(ops)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--ignore", default="", help="ký tự bỏ khỏi cả hai phía (GT còn nghi ngờ)")
    ap.add_argument("--csv", help="ghi kết quả ra CSV (UTF-8, LF)")
    a = ap.parse_args()

    rows = []
    for gtf in sorted(GT_DIR.glob("p*_*.txt")):
        m = re.fullmatch(r"p(\d+)_(han|viet)", gtf.stem)
        if not m:
            continue
        page, kind = int(m[1]), m[2]
        gt_raw = gtf.read_text(encoding="utf-8")
        for model in a.models:
            of = OUT_ROOT / model / f"p{page:03d}.txt"
            if not of.exists():
                continue
            out_raw = of.read_text(encoding="utf-8")
            if kind == "han":
                g, o = norm_han(gt_raw, a.ignore), norm_han(out_raw, a.ignore)
                cer, n = score(g, o)
                rows.append([page, kind, model, f"{cer:.4f}", "", n, len(g)])
            else:
                g, o = norm_viet(gt_raw, page, a.ignore), norm_viet(out_raw, page, a.ignore)
                cer, n = score(g, o)
                cer_nd, _ = score(strip_dia(g), strip_dia(o))
                rows.append([page, kind, model, f"{cer:.4f}", f"{cer_nd:.4f}", n, len(g)])

    head = ["trang", "loai", "cong_cu", "cer_co_dau", "cer_bo_dau", "so_cho_sai", "ky_tu_chuan"]
    print("\t".join(head))
    for r in rows:
        print("\t".join(map(str, r)))
    if a.csv:
        p = Path(a.csv)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(head)
            w.writerows(rows)
        print(f"-> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
