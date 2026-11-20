"""Đóng gói sản phẩm nộp (5 mục của docx + phần dóng hàng dịch âm) vào một thư mục NGOÀI repo (dữ liệu không commit).

    python -m src.utils.dong_goi_nop                      → ../Ket_Qua_Nop/output/
    python -m src.utils.dong_goi_nop --dich ../Ket_Qua_Nop

output/
  van_ban_sach/{Chu_Han,Phien_am,Dich_nghia}/<tên>.txt     1. văn bản sạch (token MASK = chữ mất/sách lược)
  dataset_ocr/<tên>/{images,patches,det_gt.txt,rec_gt.txt,results.xlsx}   2+4. Dataset 1 (+ ảnh crop từng văn bản)
  dataset_dich/<tên>.jsonl                                  3. Dataset 2 (Hán – Phiên âm – Dịch nghĩa)
  dong_hang_dich_am/{bia,sach}/VBLN_*_parallel.{tsv,xlsx}, *_color.xlsx, statistic.json, input.csv, config.yaml; notes.xlsx
  ocr_van_bia/<bia_id>_res.json (+ _ocr_res_img.jpg, _ocr_labeled.jpg)   OCR văn bia (API lab CLC, nhóm sửa tay)
  bao_cao/                                                  5. báo cáo số liệu + danh sách cần rà soát
  VERSION.txt, README.md
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dich", type=Path, default=ROOT.parent / "Ket_Qua_Nop")
    ap.add_argument("--khong-anh-ocr", action="store_true", help="bỏ ảnh minh hoạ OCR văn bia (~300 MB)")
    ap.add_argument("--ten", default="output", help="tên thư mục bản nộp trong --dich (vd output_20112026)")
    a = ap.parse_args(argv)
    out = a.dich.resolve() / a.ten
    assert ROOT not in out.parents, "thư mục đích phải nằm ngoài repo (dữ liệu không commit)"
    for k in ("van_ban_sach", "dataset_ocr", "dataset_dich", "dong_hang_dich_am", "ocr_van_bia", "bao_cao",
              "VERSION.txt", "README.md"):     # chỉ xoá phần script tạo — giữ file khác người dùng để trong thư mục
        q = out / k
        if q.is_dir():
            shutil.rmtree(q)
        elif q.exists():
            q.unlink()
    out.mkdir(parents=True, exist_ok=True)
    d, p, r = ROOT / "data" / "output", ROOT / "data" / "processed", ROOT / "reports"
    for k in ("Chu_Han", "Phien_am", "Dich_nghia"):
        shutil.copytree(p / k, out / "van_ban_sach" / k)
    shutil.copytree(d / "dataset_ocr", out / "dataset_ocr")
    shutil.copytree(d / "dataset_dich", out / "dataset_dich")
    shutil.copytree(d / "dong_hang", out / "dong_hang_dich_am")
    ocr = out / "ocr_van_bia"
    ocr.mkdir()
    for f in sorted((ROOT / "data" / "interim" / "paddle_raw" / "nom_epitaph").iterdir()):
        if f.name.endswith(("_res.json", ".txt")) or (f.name.endswith(".jpg") and not a.khong_anh_ocr):
            shutil.copy(f, ocr / f.name)
    bc = out / "bao_cao"
    bc.mkdir()
    ngay = f"{date.today():%Y%m%d}"
    for src, name in [(r / f"BAO_CAO_TONG_HOP_{ngay}.md", "BAO_CAO_TONG_HOP.md"),
                      (r / f"dataset_ocr_{ngay}" / "do_khop_ocr_sach.csv", "dataset_ocr_do_khop_ocr_sach.csv"),
                      (r / f"dataset_ocr_{ngay}" / "metrics.csv", "dataset_ocr_metrics.csv"),
                      (r / f"dataset_ocr_{ngay}" / "xu_ly_needs_review.csv", "dataset_ocr_xu_ly_needs_review.csv"),
                      (p / "needs_review.csv", "dataset_ocr_needs_review.csv"),
                      (r / f"dataset_ocr_{ngay}" / "ra_soat_tay.csv", "dataset_ocr_ra_soat_tay.csv"),
                      (r / f"dataset_dich_{ngay}" / "ra_soat_tay.csv", "dataset_dich_ra_soat_tay.csv"),
                      (p / "sua_chu_han.csv", "sua_chu_han.csv"),
                      (r / f"dataset_dich_{ngay}" / "report.csv", "dataset_dich_report.csv"),
                      (r / f"dataset_dich_{ngay}" / "needs_review.csv", "dataset_dich_needs_review.csv"),
                      (r / f"dong_hang_{ngay}" / "bao_cao.csv", "dong_hang_bao_cao.csv"),
                      (ROOT / "data" / "interim" / "sach_ocr" / "gemini" / "chon_ban.csv", "ocr_sach_chon_ban_trang.csv")]:
        if src.exists():
            shutil.copy(src, bc / name)
        else:
            print(f"  thiếu {src} — chạy bước tương ứng trước")
    shutil.copy(d / "VERSION.txt", out / "VERSION.txt")
    cay = "output/" + __doc__.split("\noutput/", 1)[1]
    (out / "README.md").write_text(f"# Bản nộp — nhóm 3 (Văn bia làng Nành)\n\n```\n{cay}```\n", encoding="utf-8", newline="\n")
    for cfg in (out / "dong_hang_dich_am").glob("*/config.yaml"):    # không để đường dẫn tuyệt đối máy cá nhân
        t = cfg.read_text(encoding="utf-8").replace(ROOT.parent.as_posix() + "/", "../")
        cfg.write_text(t, encoding="utf-8", newline="\n")
    n = sum(1 for _ in out.rglob("*") if _.is_file())
    mb = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 2**20
    print(f"{n} file, {mb:.0f} MB → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
