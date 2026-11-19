"""Dóng hàng chữ Hán Nôm ↔ dịch âm Quốc ngữ theo ``Hướng dẫn dóng hàng - dịch âm.docx`` (giảng viên, 18/11/2026).

Công cụ dóng hàng ký tự là của giảng viên: ``SinoNom-alignment/align_texts.py`` (github.com/VongHaiYen11/SN-QN-alignment,
M.E.D Levenshtein + từ điển QuocNgu_SinoNom + SinoNom_Similar). Script này chỉ làm phần docx giao cho người dùng:
"sắp xếp bbox, tách câu, ghép tương ứng câu/box" → CSV đầu vào → gọi tool → gom kết quả bàn giao.

Hai bộ dữ liệu (mỗi bộ một lần chạy tool):
  bia  — mỗi box văn bia (status ok, nhãn có chữ Hán) một dòng:
           ID       = <bia_id>_<order 3 số>
           HanNom   = chữ OCR văn bia (OCR lab CLC, đã sắp thứ tự đọc; bỏ dấu câu/ký tự không phải Hán)
           DichAm   = các âm Phiên âm ứng với đoạn sách của box (gióng chữ Hán sách ↔ âm tiết bằng NW + từ điển
                      giảng viên ∪ từ điển tự học — build_dataset_dich.align_han_pa)
           Fallback = chữ sách của box (= nhãn Dataset 1; MASK → [MASK])  — docx §2.2: "nguyên văn Hán Nôm trong sách
                      có thể xem là một nguồn Fallback"
           Bbox     = 4 điểm của box trên ảnh gốc (giữ hệ toạ độ ảnh nguồn)
  sach — mỗi câu Phiên âm của sách một dòng: HanNom = đoạn Hán sách tương ứng, DichAm = câu Phiên âm (bỏ dấu câu).
Đầu ra (data/output/dong_hang/<bộ>/): input.csv, config.yaml, VBLN_<bộ>_parallel.{tsv,xlsx}, VBLN_<bộ>_parallel_color.xlsx,
statistic.json; data/output/dong_hang/notes.xlsx — chỗ chữ Hán sách và phiên âm sách không khớp từ điển (docx: ghi chú,
KHÔNG sửa bản dịch); reports/dong_hang_<ngày>/bao_cao.csv.

    python -m src.step4_trans_align.dong_hang_dich_am
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from src.step3_ocr_align.text_aligner import normalize_han_str
from src.step4_trans_align import build_dataset_dich as d2
from src.step4_trans_align.tu_dien_han_viet import am_key, dict_dir, load_readings, load_similar

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "data" / "output" / "dong_hang"
REP = ROOT / "reports" / f"dong_hang_{date.today():%Y%m%d}"
MA_TAC_PHAM = "VBLN"                    # Văn bia làng Nành
HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003134F]")
MASK_TOOL = "[MASK]"                    # docx: ký hiệu chữ hư/không đoán định được, khai báo damaged_tokens


def tool_dir() -> Path:
    import yaml
    cfg = yaml.safe_load((ROOT / "configs" / "config.yml").read_text(encoding="utf-8")) or {}
    p = Path((cfg.get("dong_hang") or {}).get("tool_dir") or "../SinoNom-alignment")
    return p if p.is_absolute() else (ROOT / p).resolve()


def han_tool(s: str) -> str:
    """Chuỗi Hán đã bỏ dấu câu cho tool; MASK/？ (chữ mất) → [MASK] (docx: không xoá [MASK])."""
    s = s.replace("MASK", "？")
    return "".join(c if c != "？" else MASK_TOOL for c in s if c == "？" or HAN.match(c))


def am_tool(tokens: list[str]) -> str:
    return " ".join(MASK_TOOL if t == "？" else t for t in tokens)


def box_span(label: str, g: str, start: int) -> tuple[int, int] | None:
    """Vị trí nhãn (chữ sách của box) trong chuỗi Hán sách `g` (MASK = '？'). Nhãn = lát cắt của sách nhưng aligner có
    thể bỏ các '？' mà bia không thiếu chữ → cho phép '？' xen giữa. Tìm tiến từ `start`, không thấy thì tìm từ đầu."""
    lab = "".join(c for c in label.replace("MASK", "？") if c == "？" or HAN.match(c))
    if not lab.replace("？", ""):
        return None
    pat = re.compile("？*".join(map(re.escape, lab)))
    m = pat.search(g, start) or pat.search(g)
    return (m.start(), m.end()) if m else None


def rows_for_doc(doc: dict, lex: dict) -> tuple[list[list], list[list], dict]:
    """Sinh dòng CSV của bộ `bia` và `sach` cho một văn bản."""
    stem, g = doc["id"], doc["han"]
    st = {"van_ban": stem, "box_ok_co_chu": 0, "dong_bia": 0, "box_khong_co_am": 0, "dong_sach": 0}
    if not g or not doc["pa"]:
        return [], [], st
    han_seg, _ = d2.align_han_pa(g, doc["pa"], lex)
    h2s = d2.align_han_pa.h2s
    toks = [t for line in doc["pa"] for t in d2.syllables(line, lower=False)]
    # --- bộ sach: mỗi câu PA một dòng
    sach = []
    for k, (line, seg) in enumerate(zip(doc["pa"], han_seg), 1):
        hn, am = han_tool(seg), am_tool(d2.syllables(line, lower=False))
        if hn and am:
            sach.append([f"{stem}_{k:03d}", hn, am])
    # --- bộ bia: mỗi box ok có chữ sách một dòng, theo thứ tự đọc (mặt theo thứ tự trong tên văn bản)
    bia, pos = [], 0
    for bid in stem.split("_"):
        af, bf = PROC / "align" / f"{bid}.json", PROC / "bbox_chuan" / f"{bid}.json"
        if not af.exists() or not bf.exists():
            continue
        pts = {b["order"]: b["points"] for b in json.loads(bf.read_text(encoding="utf-8"))["boxes"]}
        for it in sorted(json.loads(af.read_text(encoding="utf-8"))["items"], key=lambda x: x["order"]):
            if it["status"] != "ok" or not HAN.search(it["text_gt"] or ""):
                continue
            st["box_ok_co_chu"] += 1
            sp = box_span(it["text_gt"], g, pos)
            js = sorted({h2s[i] for i in range(*sp) if h2s[i] is not None}) if sp else []
            if not js:
                st["box_khong_co_am"] += 1          # sách không phiên âm đoạn này (vd chỉ chép Hán) / không định vị được
                continue
            pos = sp[1]
            hn = han_tool(it["text_ocr"])
            if not hn:
                st["box_khong_co_am"] += 1
                continue
            bia.append([f"{bid}_{it['order']:03d}", hn, am_tool(toks[js[0]: js[-1] + 1]), han_tool(it["text_gt"]),
                        json.dumps(pts[it["order"]])])
    st["dong_bia"], st["dong_sach"] = len(bia), len(sach)
    return bia, sach, st


def run_tool(name: str, header: list[str], rows: list[list]) -> dict:
    """Ghi input.csv + config.yaml cho tool của giảng viên, chạy align_texts.py, trả `summary` của statistic.json."""
    import yaml
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "input.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    cfg = {
        "dataset": {"name": f"{MA_TAC_PHAM}_{name}", "input_file": (out / "input.csv").as_posix(),
                    "columns": {"encoding": "utf-8-sig", "sinonom_column": "HanNom", "quocngu_column": "DichAm",
                                "fallback_column": "Fallback" if "Fallback" in header else None,
                                "id_column": "ID"}},
        "dictionary": {"translation_dict": (dict_dir() / "QuocNgu_SinoNom_TongHop3.csv").as_posix(),
                       "similarity_dict": (dict_dir() / "SinoNom_Similar_Dic_v2.csv").as_posix(), "encoding": "utf-8-sig"},
        "alignment": {"damaged_tokens": [MASK_TOOL], "costs": {"match": 0, "mismatch": 1, "insertion": 1, "deletion": 1}},
        "output": {"directory": out.as_posix(), "filename": f"{MA_TAC_PHAM}_{name}_parallel.tsv",
                   "statistics_filename": "statistic.json",
                   "color_mapping": {"match": {"hex": "000000"}, "mismatch": {"hex": "FF0000"},
                                     "ocr_fallback": {"hex": "008000"}, "similarity": {"hex": "0000FF"}}},
        "processing": {"verbose": False, "show_progress": False},
        "quick_test": False, "test_limit": 10,
    }
    (out / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
    tool = tool_dir() / "align_texts.py"
    if not tool.exists():
        sys.exit(f"Không thấy tool của giảng viên: {tool} (clone github.com/VongHaiYen11/SN-QN-alignment, xem config dong_hang.tool_dir)")
    r = subprocess.run([sys.executable, str(tool), str(out / "config.yaml")], cwd=tool.parent,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        sys.exit(f"Tool lỗi ({name}):\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return json.loads((out / "statistic.json").read_text(encoding="utf-8"))["summary"]


def notes(docs: list[dict], lex: dict) -> list[list]:
    """docx §2.1: sai khác giữa bản Hán và bản phiên âm → notes.xlsx (tên tác phẩm, câu Hán, câu Việt, lỗi, chỉnh sửa).
    Chỉ ghi cặp chữ↔âm đã gióng (bước chéo NW) mà chữ KHÔNG đọc được âm đó theo từ điển giảng viên, chữ CÓ trong từ điển
    (chữ ngoài từ điển là thiếu từ điển, không phải sai khác). Phân loại:
      - chữ giống hình (SinoNom_Similar) đọc được âm → nghi OCR sách đọc nhầm chữ (đề xuất chữ đó);
      - còn lại → phiên âm/chữ Hán sách khác nhau (ghi lại, không sửa)."""
    rd, sim = load_readings(), load_similar()
    out = []
    for doc in docs:
        if not doc["han"] or not doc["pa"]:
            continue
        han_seg, _ = d2.align_han_pa(doc["han"], doc["pa"], lex)
        h2s = d2.align_han_pa.h2s
        toks = [t for line in doc["pa"] for t in d2.syllables(line, lower=False)]
        owner = [li for li, line in enumerate(doc["pa"]) for _ in d2.syllables(line)]
        bad: dict[int, list[str]] = defaultdict(list)
        for i, j in enumerate(h2s):
            ch = doc["han"][i]
            if j is None or ch in "？○" or toks[j] == "？" or ch not in rd:
                continue
            k = am_key(toks[j])
            if k in rd[ch] or k in lex.get(normalize_han_str(ch), ()):
                continue
            cand = [c for c in sim.get(ch, ()) if k in rd.get(c, ())]
            bad[owner[j]].append(f"{ch}↔{toks[j]}" + (f" (chữ giống hình đọc được: {cand[0]})" if cand else ""))
        for li, errs in bad.items():
            sug = [e for e in errs if "giống hình" in e]
            out.append([doc["id"], han_seg[li].replace("？", "MASK"), doc["pa"][li],
                        "; ".join(errs),
                        ("Nghi OCR sách đọc nhầm chữ Hán — đối chiếu ảnh trang sách: " + "; ".join(sug)) if sug else
                        "Ghi nhận sai khác chữ Hán ↔ phiên âm; không sửa bản dịch (docx §2.1)"])
    return out


def write_notes(rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "notes"
    ws.append(["tên tác phẩm", "câu Hán", "câu Việt", "lỗi", "chỉnh sửa"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    for col, w in zip("ABCDE", (28, 50, 60, 50, 60)):
        ws.column_dimensions[col].width = w
    OUT.mkdir(parents=True, exist_ok=True)
    wb.save(OUT / "notes.xlsx")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    docs = d2.load_docs()
    lex = d2.build_lexicon(docs)
    bia, sach, stats = [], [], []
    for doc in docs:
        b, s, st = rows_for_doc(doc, lex)
        bia += b
        sach += s
        stats.append(st)
    sb = run_tool("bia", ["ID", "HanNom", "DichAm", "Fallback", "Bbox"], bia)
    ss = run_tool("sach", ["ID", "HanNom", "DichAm"], sach)
    nt = notes(docs, lex)
    write_notes(nt)
    REP.mkdir(parents=True, exist_ok=True)
    with open(REP / "bao_cao.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(stats[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(stats)
    keys = ("total_rows_input", "processed_rows", "alignment_positions", "primary_match_count", "fallback_count",
            "similarity_count", "hannom_error_count", "match_rate", "mismatch_rate")
    for name, sm in (("bia", sb), ("sach", ss)):
        print(f"[{name}] " + ", ".join(f"{k}={sm.get(k)}" for k in keys if k in sm))
    print(f"notes.xlsx: {len(nt)} câu có sai khác | {OUT} | {REP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
