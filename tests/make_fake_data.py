"""Sinh dữ liệu giả + chạy thử export + kiểm tra nhanh kết quả.

    python -m tests.make_fake_data            # tạo ở thư mục tạm, chạy export, kiểm tra
    python -m tests.make_fake_data --keep DIR # giữ lại kết quả ở DIR để xem bằng mắt
"""
from __future__ import annotations

import argparse
import csv
import json
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from src.step3_ocr_align import export_ocr_dataset as ex
from src.utils import file_io as fio

W, H = 3300, 6000
DOCS = [("D1", "Văn bia thử A"), ("D2", "Văn bia thử B")]
BIA = [("00270-TF1", "D1"), ("00270-TF2", "D1"), ("00271-TF1", "D2")]


def fake_boxes():
    boxes = [{"order": 1, "region": "tran", "points": [[800, 300], [2500, 300], [2500, 600], [800, 600]],
              "text_ocr": "記碑神佛", "score": 0.91, "source": "auto"}]
    for i in range(5):                       # 5 cột thân, đọc phải -> trái
        x = 2900 - i * 450
        boxes.append({"order": 2 + i, "region": "than",
                      "points": [[x, 900], [x + 220, 900], [x + 220, 5400], [x, 5400]],
                      "text_ocr": "蓋聞古語", "score": 0.9, "source": "auto"})
    return boxes


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)


def build(root: Path) -> None:
    meta, raw, proc = root / "data/metadata", root / "data/raw/anh_bia", root / "data/processed"
    write_csv(meta / "inventory.csv", ["doc_id", "ten_van_ban", "dinh_dang", "file_nguon", "ghi_chu"],
              [[d, n, "pdf_text", "x.pdf", ""] for d, n in DOCS])
    write_csv(meta / "bia_manifest.csv",
              ["bia_id", "nguon_url", "file_anh", "rong_px", "cao_px", "doc_id", "is_trial", "ghi_chu"],
              [[b, "", f"{b}.jpg", W, H, d, 1, ""] for b, d in BIA])
    raw.mkdir(parents=True, exist_ok=True)
    for b, _ in BIA:
        img = Image.new("RGB", (W, H), (235, 230, 220))
        dr = ImageDraw.Draw(img)
        for box in fake_boxes():
            (x0, y0), (x2, y2) = box["points"][0], box["points"][2]
            dr.rectangle([x0, y0, x2, y2], fill=(30, 30, 30))
        img.save(raw / f"{b}.jpg", quality=90)

        boxes = fake_boxes()
        fio.write_json(proc / "bbox_chuan" / f"{b}.json", {"schema_version": 1, "bia_id": b, "boxes": boxes})
        items = [{"order": bx["order"], "text_ocr": bx["text_ocr"], "text_gt": "蓋聞古語", "score": 0.95, "status": "ok"}
                 for bx in boxes]
        items[-1].update(text_gt="", score=0.4, status="needs_review")     # 1 box cần rà soát
        fio.write_json(proc / "align" / f"{b}.json", {"schema_version": 1, "bia_id": b, "items": items})


def check(out_dir: Path) -> None:
    folders = sorted(p for p in out_dir.iterdir() if p.is_dir())
    assert len(folders) == len(DOCS), folders
    from openpyxl import load_workbook
    for d in folders:
        imgs, patches = sorted((d / "images").glob("*.jpg")), sorted((d / "patches").glob("*.jpg"))
        assert imgs and patches
        for p in imgs:
            with Image.open(p) as im: assert max(im.size) <= 1024, (p, im.size)
        for p in patches:
            with Image.open(p) as im: assert im.height <= 96, (p, im.size)
        rec = (d / "rec_gt.txt").read_text(encoding="utf-8").splitlines()
        det = (d / "det_gt.txt").read_text(encoding="utf-8").splitlines()
        rows = list(load_workbook(d / "results.xlsx").active.iter_rows(min_row=2, values_only=True))
        assert len(rec) == len(patches) == len(rows), (len(rec), len(patches), len(rows))
        assert len(det) == len(imgs)
        for line in rec:
            assert (out_dir / line.split("\t")[0]).exists(), line
        for line in det:
            path, js = line.split("\t")
            with Image.open(out_dir / path) as im:
                for a in json.loads(js):
                    assert all(0 <= x < im.width and 0 <= y < im.height for x, y in a["points"]), path
        print(f"OK  {d.name}: {len(imgs)} ảnh, {len(patches)} patch, {len(det)} dòng det_gt")


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--keep", type=Path); a = ap.parse_args()
    ctx = None if a.keep else tempfile.TemporaryDirectory()
    root = a.keep if a.keep else Path(ctx.name)
    root.mkdir(parents=True, exist_ok=True)
    build(root)
    code = ex.main(["--root", str(root), "--version-label", "v0"])
    assert code == 0, "export báo lỗi"
    check(root / "data/output/dataset_ocr")
    print("Smoke test PASS", root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
