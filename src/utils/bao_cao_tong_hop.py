"""Báo cáo tổng hợp số liệu bàn giao (sản phẩm 5 của docx: số bounding box, số cặp câu đã gióng + độ khớp OCR↔sách,
kết quả dóng hàng dịch âm). Mọi số đếm tính lại TỪ DỮ LIỆU, không ghi tay.

    python -m src.utils.bao_cao_tong_hop          → reports/BAO_CAO_TONG_HOP_<yyyymmdd>.md (KHÔNG chứa nội dung sách)
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

from openpyxl import load_workbook
from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).resolve().parents[2]
HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003134F]")


def van_ban_sach(proc: Path) -> list[list]:
    rows = []
    for kind in ("Chu_Han", "Phien_am", "Dich_nghia"):
        fs = sorted((proc / kind).glob("*.txt"))
        lines = [ln for f in fs for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        txt = "\n".join(lines)
        rows.append([kind, len(fs), len(lines), len(HAN.findall(txt)) if kind == "Chu_Han" else len(txt.split()),
                     txt.count("MASK")])
    return rows


def dataset_ocr(out: Path, proc: Path) -> tuple[dict, list[list]]:
    st = {"van_ban": 0, "anh": 0, "box": 0, "box_co_nhan": 0, "nhan_MASK": 0, "chu_co_nhan": 0}
    pairs, per_doc = [], []
    for d in sorted(p for p in out.iterdir() if p.is_dir()):
        st["van_ban"] += 1
        st["anh"] += len(list((d / "images").glob("*.jpg")))
        st["box"] += sum(len(json.loads(ln.split("\t", 1)[1])) for ln in
                         (d / "det_gt.txt").read_text(encoding="utf-8").splitlines() if "\t" in ln)
        wb = load_workbook(d / "results.xlsx", read_only=True)
        rows = [r for r in wb["results"].iter_rows(min_row=2, values_only=True)]
        wb.close()
        st["box_co_nhan"] += len(rows)
        st["nhan_MASK"] += sum(r[4] == "MASK" for r in rows)
        st["chu_co_nhan"] += sum(len(HAN.findall(r[4])) for r in rows)
        dp = [("".join(HAN.findall(r[3] or "")), "".join(HAN.findall((r[4] or "").replace("MASK", ""))))
              for r in rows if r[5] is not None]
        pairs += dp
        per_doc.append([d.name, len(rows), len(dp), char_sim(dp)])
    st["needs_review"] = max(0, sum(1 for _ in open(proc / "needs_review.csv", encoding="utf-8")) - 1)
    st["do_khop_theo_chu"] = char_sim(pairs)
    st["box_co_chu_sach"] = len(pairs)
    st["box_khop_100"] = sum(o == g for o, g in pairs)
    return st, per_doc


def char_sim(pairs: list[tuple[str, str]]) -> float | None:
    tot = sum(max(len(o), len(g)) for o, g in pairs)
    return round(100 * (1 - sum(Levenshtein.distance(o, g) for o, g in pairs) / tot), 2) if tot else None


def dataset_dich(out: Path) -> dict:
    recs = [json.loads(ln) for f in out.glob("*.jsonl") for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return {"van_ban": len(list(out.glob("*.jsonl"))), "cap": len(recs), "ok": sum(r["status"] == "ok" for r in recs),
            "needs_review": sum(r["status"] != "ok" for r in recs)}


def dong_hang(out: Path) -> dict:
    res = {}
    for name in ("bia", "sach"):
        f = out / name / "statistic.json"
        if f.exists():
            res[name] = json.loads(f.read_text(encoding="utf-8"))["summary"]
    nf = out / "notes.xlsx"
    if nf.exists():
        wb = load_workbook(nf, read_only=True)
        res["notes"] = sum(1 for _ in wb.active.iter_rows(min_row=2))
        wb.close()
    return res


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    proc, out = ROOT / "data" / "processed", ROOT / "data" / "output"
    vb = van_ban_sach(proc)
    d1, d1_doc = dataset_ocr(out / "dataset_ocr", proc)
    d2 = dataset_dich(out / "dataset_dich")
    dh = dong_hang(out / "dong_hang")
    L = [f"# Báo cáo tổng hợp số liệu — {date.today():%d/%m/%Y}", "",
         "Sinh tự động bởi `python -m src.utils.bao_cao_tong_hop` (đếm lại từ `data/`). Không chứa nội dung sách.", "",
         "## 1. Văn bản sạch (data/processed)", "", "| loại | số file | số dòng | chữ Hán / từ | token MASK |",
         "|---|---|---|---|---|"]
    L += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |" for r in vb]
    L += ["", "## 2. Dataset 1 — OCR văn bia (data/output/dataset_ocr)", "",
          f"- Thư mục (mỗi thư mục 1 mặt bia): **{d1["van_ban"]}**; ảnh mặt bia: **{d1['anh']}**",
          f"- Bounding box (det_gt): **{d1['box']}**; box có nhãn = patch (rec_gt): **{d1['box_co_nhan']}** "
          f"(trong đó nhãn `MASK`: {d1['nhan_MASK']}); chữ Hán có nhãn: **{d1['chu_co_nhan']}**",
          f"- Box còn `needs_review` (data/processed/needs_review.csv): {d1['needs_review']}",
          f"- **Độ khớp OCR văn bia ↔ chữ sách** (coi sách là đúng, so nguyên dạng): theo chữ **{d1['do_khop_theo_chu']}%** "
          f"trên {d1['box_co_chu_sach']} box có chữ sách; box khớp 100%: {d1['box_khop_100']}",
          "", "| thư mục (mặt bia) | patch | patch có chữ sách | độ khớp theo chữ (%) |", "|---|---|---|---|"]
    L += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |" for r in d1_doc]
    L += ["", "## 3. Dataset 2 — cặp câu Hán–Phiên âm–Dịch nghĩa (data/output/dataset_dich)", "",
          f"- Văn bản: **{d2['van_ban']}**; cặp câu: **{d2['cap']}** (ok {d2['ok']}, needs_review {d2['needs_review']})", "",
          "## 4. Dóng hàng Hán Nôm ↔ dịch âm (tool SinoNom-alignment của giảng viên, data/output/dong_hang)", "",
          "| bộ | dòng | vị trí căn chỉnh | khớp chữ chính | sửa nhờ Fallback | sửa nhờ chữ giống hình | còn lỗi | match_rate |",
          "|---|---|---|---|---|---|---|---|"]
    for name, sm in ((k, v) for k, v in dh.items() if k != "notes"):
        L.append(f"| {name} | {sm.get('processed_rows')} | {sm.get('alignment_positions')} | {sm.get('primary_match_count')} | "
                 f"{sm.get('fallback_count')} | {sm.get('similarity_count')} | {sm.get('hannom_error_count')} | "
                 f"{100 * sm.get('match_rate', 0):.2f}% |")
    L += ["", f"- notes.xlsx: {dh.get('notes', 0)} câu có sai khác chữ Hán ↔ phiên âm (ghi chú, không sửa bản dịch)", ""]
    f = ROOT / "reports" / f"BAO_CAO_TONG_HOP_{date.today():%Y%m%d}.md"
    f.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(L[:40]))
    print(f"→ {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
