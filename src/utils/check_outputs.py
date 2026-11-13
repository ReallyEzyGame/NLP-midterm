import json, sys
from pathlib import Path
from openpyxl import load_workbook
from PIL import Image

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
errs, warns = [], []

# ---------- Dataset 1 ----------
d1 = root / "data/output/dataset_ocr"
print("== Dataset 1 (dataset_ocr) ==")
if not d1.exists():
    errs.append("thiếu data/output/dataset_ocr")
else:
    for d in sorted(p for p in d1.iterdir() if p.is_dir()):
        imgs = sorted((d / "images").glob("*.jpg")); pats = sorted((d / "patches").glob("*.jpg"))
        rec = (d / "rec_gt.txt").read_text(encoding="utf-8").splitlines()
        det = (d / "det_gt.txt").read_text(encoding="utf-8").splitlines()
        rows = list(load_workbook(d / "results.xlsx").active.iter_rows(min_row=2, values_only=True))
        n_box = sum(len(json.loads(l.split("\t")[1])) for l in det)
        n_ign = sum(a["transcription"] == "###" for l in det for a in json.loads(l.split("\t")[1]))
        if not (len(rec) == len(pats) == len(rows)):
            errs.append(f"{d.name}: rec_gt={len(rec)} patch={len(pats)} results.xlsx={len(rows)} không bằng nhau")
        if len(det) != len(imgs):
            errs.append(f"{d.name}: det_gt={len(det)} dòng ≠ {len(imgs)} ảnh")
        for p in imgs:
            with Image.open(p) as im:
                if max(im.size) > 1024: errs.append(f"{p.name}: cạnh dài {max(im.size)} > 1024")
        for p in pats:
            with Image.open(p) as im:
                if im.height > 96: errs.append(f"{p.name}: cao {im.height} > 96")
        for l in rec:
            if not (d.parent / l.split("\t")[0]).exists():
                errs.append(f"{d.name}: rec_gt trỏ tới file không tồn tại: {l.split(chr(9))[0]}")
        for l in det:
            path, js = l.split("\t")
            with Image.open(d.parent / path) as im:
                for a in json.loads(js):
                    if not all(0 <= x < im.width and 0 <= y < im.height for x, y in a["points"]):
                        errs.append(f"{path}: box ngoài ảnh")
        print(f"  {d.name}: {len(imgs)} ảnh | {n_box} box ({n_ign} chưa nhãn ###) | {len(pats)} patch")

# ---------- Dataset 2 ----------
d2 = root / "data/output/dataset_dich"
print("== Dataset 2 (dataset_dich) ==")
if not d2.exists():
    errs.append("thiếu data/output/dataset_dich")
else:
    tot = full = 0
    for f in sorted(d2.glob("*.jsonl")):
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        ok = sum(all(r.get(k) for k in ("han", "phien_am", "dich_nghia")) for r in rows)
        tot += len(rows); full += ok
        if not rows: errs.append(f"{f.name}: rỗng")
        elif ok < len(rows): warns.append(f"{f.name}: {len(rows) - ok}/{len(rows)} cặp thiếu ít nhất 1 trong 3 trường")
    print(f"  {len(list(d2.glob('*.jsonl')))} file | {tot} cặp | {full} cặp đủ 3 trường")

for w in warns: print("CẢNH BÁO:", w)
for e in errs: print("LỖI:", e)
print("KẾT QUẢ:", "ĐẠT" if not errs else f"{len(errs)} LỖI")
sys.exit(1 if errs else 0)
