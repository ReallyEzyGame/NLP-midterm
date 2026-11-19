"""Sửa chữ Hán Gemini đọc sai trong `data/processed/Chu_Han/` theo `data/processed/sua_chu_han.csv`.

Mỗi quy tắc: `doc` (tên file Chu_Han không đuôi), `old` → `new` — so trên chuỗi Hán đã làm sạch (bỏ dấu câu/xuống dòng,
như `build_dataset_dich.han_chars`), nên khớp được cả khi chữ nằm sát chỗ xuống dòng; `⏎` trong old/new = xuống dòng thô.
Nhãn = chữ IN trong sách (đã đối chiếu ảnh scan) — kể cả khi sách in khác bia/Phiên âm. Chạy lại an toàn (đã sửa thì bỏ qua).
Chạy SAU `clean_book_text` (file Chu_Han bị sinh lại thì phải chạy lại):

    python -m src.step1_book_mining.sua_chu_han
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from src.step3_ocr_align.text_aligner import clean_gt_text

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
TOKEN = re.compile(r"MASK|\(\s*[\?？]\s*\)|.", re.S)


def tokens(lines: list[str]) -> list[tuple[int, int, int, str]]:
    """(dòng, cột đầu, cột cuối, chữ đã làm sạch) cho từng chữ Hán/ký tự khuyết còn lại sau khi làm sạch."""
    out = []
    for li, line in enumerate(lines):
        for m in TOKEN.finditer(line):
            ch = "？" if m.group() == "MASK" else clean_gt_text(m.group())
            if ch:
                out.append((li, m.start(), m.end(), ch))
    return out


def apply_rule(lines: list[str], old: str, new: str) -> str:
    """Áp 1 quy tắc lên `lines` (sửa tại chỗ). Trả 'ok' | 'da_sua' | 'khong_thay' | 'nhieu_cho'."""
    tk = tokens(lines)
    g = "".join(t[3] for t in tk)
    o, n = old.replace("⏎", ""), new.replace("⏎", "")
    hits = [m.start() for m in re.finditer(re.escape(o), g)]
    if len(hits) > 1:
        return "nhieu_cho"
    if not hits:
        return "da_sua" if n in g else "khong_thay"
    a, b = hits[0], hits[0] + len(o) - 1
    (l1, c1, _, _), (l2, _, c2, _) = tk[a], tk[b]
    if l1 == l2:
        lines[l1] = lines[l1][:c1] + n + lines[l1][c2:]
    else:                                                  # chữ nằm ở 2 dòng liền: phần mới ghi ở dòng đầu, bỏ phần cũ ở dòng sau
        lines[l1] = lines[l1][:c1] + n
        lines[l2] = lines[l2][c2:]
        for k in range(l1 + 1, l2):
            lines[k] = ""
        lines[:] = [x for k, x in enumerate(lines) if x or not l1 < k <= l2]
    return "ok"


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    f = PROC / "sua_chu_han.csv"
    if not f.exists():
        print(f"không có {f}")
        return 0
    with open(f, encoding="utf-8", newline="") as fh:
        rules = list(csv.DictReader(fh))
    stat: dict[str, int] = {}
    by_doc: dict[str, list[dict]] = {}
    for r in rules:
        by_doc.setdefault(r["doc"], []).append(r)
    for doc, rs in by_doc.items():
        p = PROC / "Chu_Han" / f"{doc}.txt"
        lines = p.read_text(encoding="utf-8").splitlines()
        for r in rs:
            st = apply_rule(lines, r["old"], r["new"])
            stat[st] = stat.get(st, 0) + 1
            if st in ("khong_thay", "nhieu_cho"):
                print(f"  CẢNH BÁO {doc}: {st}: {r['old']!r}")
        p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("sửa Chu_Han:", stat)
    return 0


if __name__ == "__main__":
    sys.exit(main())
