"""OCR thô toàn bộ sách scan, cục bộ (RapidOCR/onnxruntime) — không gửi ảnh ra ngoài.

Mỗi ảnh trang đôi được cắt đôi tại giữa gáy; kết quả mỗi trang in lưu ở
data/interim/sach_ocr/scan_all/p<trang 3 số>.json (có thể chạy lại, bỏ qua trang đã xong).
Model nhận dạng 'ch' của PP-OCRv4 mất dấu tiếng Việt: chỉ dùng để ĐỊNH VỊ (tiêu đề, nhãn, khối Hán),
không dùng làm văn bản cuối cùng.

Lưu ý: tải model lần đầu phải chạy một tiến trình trước (tránh nhiều tiến trình cùng tải làm hỏng file model).
Chạy: python -m src.step1_book_mining.ocr_scan_all [--workers 4]
"""
from __future__ import annotations

import argparse
import json
import re
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data/raw/sach_scan/STT3_van_bia_lang_nanh"
OUT = ROOT / "data/interim/sach_ocr/scan_all"

_engine = None


def list_pages() -> list[tuple[Path, int, str]]:
    res = []
    for f in sorted(SRC.glob("*.jpg")):
        m = re.fullmatch(r"(\d{3})-(\d{3})", f.stem)
        if m:
            res += [(f, int(m[1]), "L"), (f, int(m[2]), "R")]
        elif f.stem in ("001", "498"):
            res.append((f, int(f.stem), "S"))
    return res


def make_engine():
    from rapidocr import LangDet, LangRec, ModelType, OCRVersion, RapidOCR
    return RapidOCR(params={
        "Rec.lang_type": LangRec.CH, "Rec.ocr_version": OCRVersion.PPOCRV4, "Rec.model_type": ModelType.MOBILE,
        "Det.lang_type": LangDet.CH, "Det.ocr_version": OCRVersion.PPOCRV4, "Det.model_type": ModelType.MOBILE,
        "EngineConfig.onnxruntime.intra_op_num_threads": 1,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
    })


def work(item) -> int:
    global _engine
    f, p, side = item
    out = OUT / f"p{p:03d}.json"
    if out.exists():
        return p
    if _engine is None:
        _engine = make_engine()
    im = Image.open(f).convert("RGB")
    w, h = im.size
    if side == "L":
        im = im.crop((0, 0, w // 2, h))
    elif side == "R":
        im = im.crop((w // 2, 0, w, h))
    r = _engine(np.array(im))
    lines = []
    if r.boxes is not None:
        for b, t, s in zip(r.boxes, r.txts, r.scores):
            lines.append({"y": int(min(pt[1] for pt in b)), "x": int(min(pt[0] for pt in b)),
                          "text": t, "score": round(float(s), 3)})
    lines.sort(key=lambda d: (d["y"], d["x"]))
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps({"page": p, "file": f.name, "side": side, "lines": lines}, ensure_ascii=False),
                   encoding="utf-8", newline="\n")
    tmp.replace(out)
    return p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    items = sorted(list_pages(), key=lambda t: (0 if 37 <= t[1] <= 470 else 1, t[1]))
    print(len(items), "trang", flush=True)
    t0 = time.time()
    with Pool(args.workers) as pool:
        for i, _ in enumerate(pool.imap_unordered(work, items)):
            if i % 20 == 0:
                print(i, round(time.time() - t0), "s", flush=True)
    print("done", round(time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
