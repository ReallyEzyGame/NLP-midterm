import csv
from pathlib import Path
from PIL import Image

ROOT = Path(".")
rows = list(csv.DictReader(open(ROOT / "data/metadata/stt_bia_map.csv", encoding="utf-8", newline="")))
out = []
for r in rows:
    if not r["bia_id"]:                      # mặt không có ảnh thì bỏ
        continue
    name = Path(r["file_anh"]).name          # stt_bia_map ghi cả đường dẫn; exporter cần tên file
    with Image.open(ROOT / "data/raw/anh_bia" / name) as im:
        w, h = im.size
    out.append([r["bia_id"], "", name, w, h, r["doc_id"], 0, ""])
with open(ROOT / "data/metadata/bia_manifest.csv", "w", encoding="utf-8", newline="\n") as f:
    wr = csv.writer(f, lineterminator="\n")
    wr.writerow(["bia_id", "nguon_url", "file_anh", "rong_px", "cao_px", "doc_id", "is_trial", "ghi_chu"])
    wr.writerows(out)
print(len(out), "mặt bia -> data/metadata/bia_manifest.csv")