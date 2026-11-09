"""Lập bảng ánh xạ STT (sách) -> bia_id (ảnh thác bản) — bước 1.A, mục "khớp ảnh".

Nguồn  : Nhom3/DanhSach.xlsx (CHỈ ĐỌC, không sửa) + data/metadata/bo_sung_mat_bia.csv (các mặt xlsx bỏ sót, đối chiếu
         Vietnamica: cột them_ky_hieu nối "|"; dòng không có ký hiệu = chỉ ghi chú xác nhận) + tên file thật trong data/raw/anh_bia/.
Đầu ra : data/metadata/stt_bia_map.csv  và  reports/stt_bia_map_canh_bao.txt (không chứa nội dung sách).

Quy ước tên ảnh: [số thư viện 5 chữ số]-[TF][idx]  (TF = tổng số mặt, idx = thứ tự mặt); bia 1 mặt có thể không hậu tố.
bia_id = tên file bỏ đuôi.

Chạy (từ NLP-midterm):  python -m src.step1_book_mining.build_stt_bia_map
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[2]
XLSX = ROOT.parent / "Nhom3" / "DanhSach.xlsx"
IMG = ROOT / "data/raw/anh_bia"
OUT = ROOT / "data/metadata/stt_bia_map.csv"
WARN = ROOT / "reports/stt_bia_map_canh_bao.txt"
BO_SUNG = ROOT / "data/metadata/bo_sung_mat_bia.csv"
NAME_RE = re.compile(r"^(\d{5})(?:-(\d)(\d))?$")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    files: dict[int, str] = {}
    for p in sorted(IMG.glob("*.jpg")):
        m = NAME_RE.match(p.stem)
        if not m:
            print("tên file lạ:", p.name)
            continue
        files[int(m.group(1))] = p.stem

    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    rows = []
    for r in wb.active.iter_rows(min_row=1, values_only=True):
        if isinstance(r[0], (int, float)) and isinstance(r[1], str):
            rows.append(r)
    extra: dict[int, list[int]] = {}
    if BO_SUNG.exists():
        for r in csv.DictReader(open(BO_SUNG, encoding="utf-8", newline="")):
            extra[int(r["stt"])] = [int(x) for x in re.findall(r"\d+", r.get("them_ky_hieu") or "")]
    warn: list[str] = []
    out: list[dict] = []
    claimed: set[int] = set()
    for stt, ten, ky, so_mat, *_ in rows:
        stt = int(stt)
        ids = [int(x) for x in re.findall(r"\d+", str(ky))] if str(ky).strip() not in ("0", "", "None") else []
        from_xlsx = set(ids)
        ids += [i for i in extra.get(stt, []) if i not in from_xlsx]          # mặt bổ sung (không sửa xlsx)
        if not ids:
            continue
        # thứ tự mặt = idx trong tên file (…-TF<idx>) nếu có, không thì theo thứ tự ghi
        def idx_of(i: int) -> int:
            m = NAME_RE.match(files.get(i, ""))
            return int(m.group(3)) if m and m.group(3) else 99
        ids = sorted(ids, key=lambda i: (idx_of(i), ids.index(i)))
        found = [i for i in ids if i in files]
        for i in ids:
            if i not in files:
                warn.append(f"STT {stt}: ký hiệu {i:05d} KHÔNG có ảnh trong anh_bia")
        for mat, i in enumerate(ids, 1):
            claimed.add(i)
            stem = files.get(i, "")
            m = NAME_RE.match(stem) if stem else None
            tf = int(m.group(2)) if m and m.group(2) else ""
            idx = int(m.group(3)) if m and m.group(3) else ""
            out.append({"stt": stt, "bia_id": stem, "library_id": f"{i:05d}", "mat_trong_xlsx": mat,
                        "so_mat_xlsx": so_mat, "TF_ten_file": tf, "idx_ten_file": idx,
                        "file_anh": f"data/raw/anh_bia/{stem}.jpg" if stem else "", "doc_id": f"VBLN-{stt:03d}",
                        "nguon": "xlsx" if i in from_xlsx else "bo_sung"})
        tfs = {files[i].split("-")[1][0] for i in found if "-" in files[i]}
        if found and tfs and tfs != {str(len(ids))}:
            warn.append(f"STT {stt}: xlsx + bổ sung có {len(ids)} ký hiệu nhưng TF trong tên file = {sorted(tfs)}")
        if len(found) < len(ids) and found:
            warn.append(f"STT {stt}: chỉ có {len(found)}/{len(ids)} mặt có ảnh")
        if any("-" not in files[i] for i in found) and len(ids) > 1:
            warn.append(f"STT {stt}: có file không hậu tố nhưng bia nhiều mặt")
    for i in sorted(set(files) - claimed):
        warn.append(f"ảnh {files[i]}.jpg không thuộc ký hiệu nào trong xlsx / bo_sung_mat_bia.csv")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    WARN.write_text("\n".join(warn) + "\n", encoding="utf-8", newline="\n")
    print(f"{len({o['stt'] for o in out})} STT, {len(out)} mặt, {len(files)} ảnh; {len(warn)} cảnh báo")
    print("\n".join(warn))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
