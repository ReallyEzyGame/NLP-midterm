"""Định vị từng văn bia trong sách scan dựa trên OCR thô theo trang (bước 0.A của T).

Đầu vào  : data/interim/sach_ocr/scan_all/p<trang>.json   (do ocr_scan_all.py sinh ra)
           data/raw/sach_scan/DanhSach.xlsx                (danh mục giảng viên cấp)
           data/interim/text_tho/muc_luc_goc.csv           (bảng "Danh mục văn bia" tr.5-7: stt, nien_dai, ky_hieu_sach)
Đầu ra   : data/interim/text_tho/muc_luc_sach.csv           (file nội bộ của T, không thuộc Data Contract)

Cấu trúc đã kiểm chứng trên sách "Văn bia làng Nành" (mỗi văn bia N):
    [chữ Hán, tiêu đề dạng "N.<tên Hán>"]  ->  "N. TÊN BIA" (Việt)  ->  thông tin  ->  "Phiên âm:"  ->  "Dịch nghĩa:"
Tức chữ Hán của bia N nằm TRƯỚC tiêu đề Việt của bia N (sau phần dịch nghĩa của bia N-1).

Chạy: python -m src.step1_book_mining.locate_bia
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

import openpyxl
import regex

ROOT = Path(__file__).resolve().parents[2]
OCR_DIR = ROOT / "data/interim/sach_ocr/scan_all"
XLSX = ROOT / "data/raw/sach_scan/DanhSach.xlsx"
GOC = ROOT / "data/interim/text_tho/muc_luc_goc.csv"
OUT = ROOT / "data/interim/text_tho/muc_luc_sach.csv"

FIRST_BODY_PAGE = 37     # mục lục sách: "Nội dung văn bia" bắt đầu tr.37
LAST_BODY_PAGE = 463     # phụ lục bắt đầu tr.464
HAN = regex.compile(r"\p{Han}")
HEADER = re.compile(r"^\s*(\d{1,2})\s*[.,]\s*([A-Z][A-Z \-']{3,}.*)$")
LBL_PA = re.compile(r"(?i)^\s*phi[eê]n\s*a[mâ]")
LBL_DN = re.compile(r"(?i)^\s*d[iị]ch\s*ngh[iĩ]a")


def load_pages() -> dict[int, dict]:
    pages = {}
    for f in OCR_DIR.glob("p*.json"):
        j = json.loads(f.read_text(encoding="utf-8"))
        pages[j["page"]] = j
    return pages


def is_han(text: str, score: float) -> bool:
    h = len(HAN.findall(text))
    return h >= 3 and h / len(text) >= 0.5 and score >= 0.7


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    pages = load_pages()
    missing = sorted(set(range(1, 499)) - set(pages))
    if missing:
        print("THIẾU OCR trang:", missing)
        return 1

    # 1) tiêu đề Việt "N. TÊN" -> (trang, y)
    hdr: dict[int, tuple[int, int]] = {}
    for p in range(FIRST_BODY_PAGE, LAST_BODY_PAGE + 1):
        for l in pages[p]["lines"]:
            m = HEADER.match(l["text"])
            if m and 1 <= int(m[1]) <= 66 and int(m[1]) not in hdr:
                hdr[int(m[1])] = (p, l["y"])
    lack = sorted(set(range(1, 67)) - set(hdr))
    if lack:
        print("KHÔNG tìm thấy tiêu đề Việt của STT:", lack)
        return 1
    order = [hdr[i][0] * 10000 + hdr[i][1] for i in range(1, 67)]
    if order != sorted(order):
        print("Thứ tự tiêu đề không tăng dần — kiểm tra thủ công")
        return 1
    pos = lambda p, y: p * 10000 + y
    end_pos = pos(LAST_BODY_PAGE + 1, 0)

    lines = [(p, l["y"], l["text"], l["score"])
             for p in range(FIRST_BODY_PAGE, LAST_BODY_PAGE + 1) for l in pages[p]["lines"]]

    ws = openpyxl.load_workbook(XLSX, data_only=True).active
    ds = {int(r[0]): (str(r[1]).strip(), str(r[2]).strip(), int(r[3]))
          for r in ws.iter_rows(min_row=4, values_only=True) if r[0] is not None}
    goc = {int(r["stt"]): r for r in csv.DictReader(open(GOC, encoding="utf-8", newline=""))}

    rows = []
    for i in range(1, 67):
        h_start = pos(FIRST_BODY_PAGE, 0) if i == 1 else pos(*hdr[i - 1])
        h_end = pos(*hdr[i])
        han_lines = [x for x in lines if h_start <= pos(x[0], x[1]) < h_end and is_han(x[2], x[3])]
        # phần Việt của bia i: từ tiêu đề i đến dòng Hán đầu tiên của bia i+1 (hoặc tiêu đề i+1)
        v_start = pos(*hdr[i])
        if i < 66:
            nxt_han = [x for x in lines if pos(*hdr[i]) <= pos(x[0], x[1]) < pos(*hdr[i + 1]) and is_han(x[2], x[3])]
            v_end = pos(nxt_han[0][0], nxt_han[0][1]) if nxt_han else pos(*hdr[i + 1])
        else:
            v_end = end_pos
        viet = [x for x in lines if v_start <= pos(x[0], x[1]) < v_end]
        pa = [x for x in viet if LBL_PA.match(x[2])]
        dn = [x for x in viet if LBL_DN.match(x[2])]
        ten, kh, mat = ds[i]
        g = goc[i]
        # số mặt bia theo mô tả của sách ("Bia 2 mặt, khổ ...") — OCR mất dấu nên khớp "mat"
        mo_ta = [x for x in viet if x[0] <= hdr[i][0] + 1][:12]
        mat_sach = ""
        for x in mo_ta:
            m2 = re.search(r"(?i)^\s*Bia\s*(?:tr[uụ]\s*)?(\d+)\s*m[aăặ]t", x[2])
            if m2:
                mat_sach = int(m2[1])
                break
        flags = []
        if not han_lines:
            flags.append("KHONG_CO_CHU_HAN_TRONG_SACH")
        if mat > 0 and not pa:
            flags.append("KHONG_THAY_NHAN_PHIEN_AM")
        if mat > 0 and not dn:
            flags.append("KHONG_THAY_NHAN_DICH_NGHIA")
        if mat > 0 and mat_sach != "" and mat_sach != mat:
            flags.append(f"LECH_SO_MAT(sach={mat_sach};anh={mat})")
        if mat > 0 and mat_sach == "":
            flags.append("KHONG_DOC_DUOC_SO_MAT_TRONG_SACH")
        title = ""
        if han_lines:
            # dòng tiêu đề Hán có tiền tố số "N." ngay trước/giữa các dòng Hán đầu tiên
            cand = [x for x in lines if h_start <= pos(x[0], x[1]) < h_end and regex.match(rf"^\s*{i}\s*[.:：]?\s*\p{{Han}}", x[2])]
            title = (cand[0][2] if cand else han_lines[0][2])
        rows.append({
            "stt": i, "ten_bia": ten, "ky_hieu_thu_vien": kh, "so_mat": mat, "nien_dai": g["nien_dai"],
            "co_anh": 1 if mat > 0 else 0,
            "mat_theo_sach_ocr": mat_sach,
            "tr_han_bat_dau": han_lines[0][0] if han_lines else "",
            "tr_han_ket_thuc": han_lines[-1][0] if han_lines else "",
            "tr_tieu_de_viet": hdr[i][0],
            "tr_phien_am": pa[0][0] if pa else "",
            "tr_dich_nghia": dn[0][0] if dn else "",
            "tr_ket_thuc": max(x[0] for x in viet) if viet else hdr[i][0],
            "han_dong_ocr": len(han_lines),
            "han_ky_tu_ocr": sum(len(HAN.findall(x[2])) for x in han_lines),
            "tieu_de_han_ocr": title,
            "ghi_chu": ";".join(flags),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Đã ghi {OUT.relative_to(ROOT).as_posix()} ({len(rows)} dòng)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
