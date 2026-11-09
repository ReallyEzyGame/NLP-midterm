"""Sinh data/metadata/inventory.csv (Data Contract 5.1) từ muc_luc_sach.csv — bước 0.A của T.

Cột: doc_id, ten_van_ban, dinh_dang, file_nguon, ghi_chu   (dinh_dang ∈ {pdf_text, pdf_scan, anh})
 - VBLN-000        : cả cuốn sách scan (ảnh JPG, không có text layer ⇒ OCR bắt buộc)
 - VBLN-<STT 3 số> : mỗi văn bia CÓ ẢNH thác bản (so_mat > 0); bia không có ảnh bị bỏ qua theo giảng viên

Chạy: python -m src.step1_book_mining.build_inventory
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MUC_LUC = ROOT / "data/interim/text_tho/muc_luc_sach.csv"
OUT = ROOT / "data/metadata/inventory.csv"
MAP = ROOT / "data/metadata/stt_bia_map.csv"
BOOK_DIR = "data/raw/sach_scan/STT3_van_bia_lang_nanh/"
HEADER = ["doc_id", "ten_van_ban", "dinh_dang", "file_nguon", "ghi_chu"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    rows_in = list(csv.DictReader(open(MUC_LUC, encoding="utf-8", newline="")))
    n_img = len(list((ROOT / BOOK_DIR).glob("*.jpg")))
    ids: dict[int, list[str]] = {}
    if MAP.exists():                                  # tên file ảnh thật (bia_id) của từng mặt — build_stt_bia_map.py
        for m in csv.DictReader(open(MAP, encoding="utf-8", newline="")):
            ids.setdefault(int(m["stt"]), []).append(m["bia_id"])
    out = [["VBLN-000",
            "Văn bia làng Nành (Đinh Khắc Thuân khảo cứu, NXB KHXH 2003) - sách scan nhóm 3",
            "anh", BOOK_DIR,
            f"{n_img} anh JPG 300dpi (bia.jpg; 001; 248 anh trang doi NNN-MMM; 498); khong co text layer nen OCR bat buoc; "
            "danh muc DanhSach.xlsx: 66 bia, 35 bia co anh, 69 mat; so trong ten file = so trang in"]]
    for r in rows_in:
        if r["co_anh"] != "1":
            continue
        stt = int(r["stt"])
        first = r["tr_han_bat_dau"] or r["tr_tieu_de_viet"]
        ky = " - ".join(x.split("-")[0].lstrip("0") for x in ids[stt]) if ids.get(stt) else r['ky_hieu_thu_vien']   # xlsx + bổ sung
        so_mat = len(ids[stt]) if ids.get(stt) else r['so_mat']
        note = (f"stt={stt}; ky_hieu={ky}; so_mat_co_anh={so_mat}; nien_dai={r['nien_dai']}; "
                f"tr_sach={first}-{r['tr_ket_thuc']}; tr_han={r['tr_han_bat_dau'] or '-'}-{r['tr_han_ket_thuc'] or '-'}; "
                f"tr_viet={r['tr_tieu_de_viet']}-{r['tr_ket_thuc']}")
        if ids.get(stt):
            note += "; bia_id=" + "|".join(ids[stt])
        if r["ghi_chu"]:
            note += f"; CANH_BAO={r['ghi_chu']}"
        out.append([f"VBLN-{stt:03d}", f"{r['ten_bia']} (STT {stt})", "anh", BOOK_DIR, note])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:      # không BOM, LF
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADER)
        w.writerows(out)
    print(f"Đã ghi {OUT.relative_to(ROOT).as_posix()} ({len(out)} dòng dữ liệu)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
