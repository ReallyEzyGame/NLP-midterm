"""OCR ảnh thác bản cho bước 2 — PaddleOCR 3.x (GPU/CPU) hoặc RapidOCR (ONNX, CPU), có tiền xử lý dành cho thác bản.

Vì sao (đo trên 76 mặt, cùng aligner v3 — xem test_debug/result/result.md):
- Thác bản = chữ TRẮNG nền ĐEN; model PP-OCR học chữ tối nền sáng → ĐẢO MÀU + CLAHE.
- Ảnh rất dài (tới 8.322 px) bị thu về 2.560 px khi OCR nguyên tấm → chữ quá nhỏ, sót cột → CẮT TILE theo trục dài tại hàng
  ít mực nhất (không chém ngang chữ), tỉ lệ tile ≤ 1,6.
- Cấu hình `inv_clahe_tile` (PaddleOCR GPU): 805 box ok so với 700 của cấu hình gốc `raw_2560` (= smoke_test của nhóm).
Ảnh gốc KHÔNG bị sửa (xử lý trên bản sao trong bộ nhớ); toạ độ trả về trên ảnh gốc. Đầu ra đúng dạng `*_res.json` của PaddleOCR
(`dt_polys`, `rec_texts`, `rec_scores`) để `step3_ocr_align.paddle_adapter` đọc nguyên xi.

    python -m src.step2_stele_ocr.ocr_bia --engine paddle --variant inv_clahe_tile --device gpu
    python -m src.step2_stele_ocr.ocr_bia --engine rapid --variant inv_clahe_tile          # CPU, không cần paddle
    # Colab (ảnh tự tải từ Vietnamica + kiểm md5 bản nhóm): xem src/step2_stele_ocr/colab/README.md
Đầu ra: data/interim/paddle_raw/<engine>_<variant>/<bia_id>_res.json (+ <bia_id>_ocr_res_img.jpg với --ve-anh)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TILE_RATIO = 1.6
# tên → (tiền xử lý, cắt tile?, limit_side_len)
VARIANTS = {
    "raw_2560": ("raw", False, 2560),             # = cấu hình gốc của nhóm (smoke_test, lang="ch")
    "raw_tile": ("raw", True, 2560),
    "inv_clahe_tile": ("inv_clahe", True, 2560),  # tốt nhất khi đứng một mình
    "inv_clahe_tile_3200": ("inv_clahe", True, 3200),
    "raw_tile_3200": ("raw", True, 3200),
}
DEFAULT_SET = ["raw_2560", "inv_clahe_tile", "raw_tile", "inv_clahe_tile_3200", "raw_tile_3200"]


def preprocess(img: np.ndarray, mode: str) -> np.ndarray:
    if mode == "raw":
        return img
    g = 255 - cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16)).apply(g)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


def cut_points(gray: np.ndarray) -> list[int]:
    """Điểm cắt dọc theo trục dài, đặt ở hàng/cột ít mực nhất (khe giữa 2 hàng chữ).

    shortcut: box bị cắt ở biên tile thành 2 mảnh, không ghép lại — aligner v3 chịu được mảnh; ghép nếu cần box nguyên cột.
    """
    h, w = gray.shape
    axis_len, short = (h, w) if h >= w else (w, h)
    n = int(np.ceil(axis_len / (short * TILE_RATIO)))
    if n <= 1:
        return [0, axis_len]
    ink = np.abs(gray.astype(np.float32) - np.median(gray)).mean(axis=1 if h >= w else 0)  # đúng cả 2 chiều màu
    step, band = axis_len / n, int(axis_len / n * 0.08)
    cuts = [0]
    for k in range(1, n):
        c = int(k * step)
        cuts.append(c - band + int(np.argmin(ink[c - band : c + band])))
    return cuts + [axis_len]


def make_engine(engine: str, limit: int, device: str):
    """Trả hàm img(BGR) -> list[(poly, text, score)]."""
    if engine == "paddle":
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(lang="ch", device=device, use_doc_orientation_classify=False, use_doc_unwarping=False,
                        use_textline_orientation=False, text_det_limit_type="max", text_det_limit_side_len=limit,
                        text_rec_score_thresh=0.0)

        def run(img):
            out = []
            for r in ocr.predict(np.ascontiguousarray(img)):
                out += [(np.asarray(p).tolist(), t, float(s))
                        for p, t, s in zip(r["rec_polys"], r["rec_texts"], r["rec_scores"])]
            return out
        return run
    from rapidocr import RapidOCR
    eng = RapidOCR(params={"Global.max_side_len": 6000, "Global.text_score": 0.3, "Global.log_level": "error",
                           "Det.limit_type": "max", "Det.limit_side_len": limit})

    def run(img):
        r = eng(np.ascontiguousarray(img))
        if r.boxes is None:
            return []
        return [(np.asarray(b).tolist(), t, float(s)) for b, t, s in zip(r.boxes, r.txts, r.scores)]
    return run


def ocr_image(run, img: np.ndarray, tile: bool):
    """OCR (theo tile nếu cần); trả (polys trên toạ độ ảnh đầy đủ, texts, scores, số tile)."""
    cuts = cut_points(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)) if tile else [0, max(img.shape[:2])]
    vertical = img.shape[0] >= img.shape[1]
    polys, txts, scores = [], [], []
    for a, b in zip(cuts, cuts[1:]):
        part = (img[a:b] if vertical else img[:, a:b]) if tile else img
        for p, t, s in run(part):
            dx, dy = (0, a) if (tile and vertical) else ((a, 0) if tile else (0, 0))
            polys.append([[int(round(x + dx)), int(round(y + dy))] for x, y in p])
            txts.append(t)
            scores.append(s)
    return polys, txts, scores, len(cuts) - 1


FONTS = [Path.home() / ".paddlex" / "fonts" / "simfang.ttf", Path("C:/Windows/Fonts/simfang.ttf"),
         Path("C:/Windows/Fonts/simsun.ttc"), Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")]


def _font(size: int):
    from PIL import ImageFont
    for f in FONTS:
        if f.exists():
            return ImageFont.truetype(str(f), max(6, size))
    return ImageFont.load_default()


def _text_tile(w: int, h: int, txt: str):
    """Ảnh chữ kích thước w×h (như draw_box_txt_fine của PaddleX): box dọc (cao > 2·rộng) → chữ xếp dọc từng chữ;
    còn lại → 1 dòng ngang; cỡ chữ vừa khít box."""
    from PIL import Image, ImageDraw
    w, h = max(1, w), max(1, h)
    img = Image.new("RGB", (w, h), (255, 255, 255))
    if not txt:
        return img
    d = ImageDraw.Draw(img)
    if h > 2 * w and h > 30:
        size = int(min(w * 0.99, h / max(1, len(txt)) * 0.99))
        font, y = _font(size), 0
        for ch in txt:
            x0, y0, x1, y1 = d.textbbox((0, 0), ch, font=font)
            d.text(((w - (x1 - x0)) / 2 - x0, y - y0), ch, fill=(0, 0, 0), font=font)
            y += size + 2
    else:
        size = int(h * 0.99)
        font = _font(size)
        while size > 6 and d.textlength(txt, font=font) > w:
            size = int(size * w / max(1.0, d.textlength(txt, font=font)) * 0.98) or size - 1
            font = _font(size)
        d.text((0, 0), txt, fill=(0, 0, 0), font=font)
    return img


def draw_ocr_result(img_rgb, polys: list, texts: list):
    """Ảnh minh hoạ giống `save_to_img` của PaddleOCR (<bia_id>_ocr_res_img.jpg): nửa trái = ảnh gốc phủ màu bán trong
    suốt từng box; nửa phải = nền trắng, viền box cùng màu + chữ OCR vẽ vào box. Màu ngẫu nhiên seed 0 như PaddleX."""
    import random
    from PIL import Image, ImageDraw
    w, h = img_rgb.size
    left = img_rgb.copy()
    dl = ImageDraw.Draw(left)
    right = np.full((h, w, 3), 255, np.uint8)
    random.seed(0)
    for poly, txt in zip(polys, texts):
        color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        pts = np.asarray(poly, dtype=np.float32).reshape(-1, 2)
        dl.polygon([tuple(p) for p in pts.tolist()], fill=color)
        if len(pts) == 4:
            bw = int(np.hypot(*(pts[0] - pts[1])))
            bh = int(np.hypot(*(pts[0] - pts[3])))
            tile = np.asarray(_text_tile(bw, bh, txt))
            m = cv2.getPerspectiveTransform(np.float32([[0, 0], [bw, 0], [bw, bh], [0, bh]]), pts)
            warped = cv2.warpPerspective(tile, m, (w, h), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT,
                                         borderValue=(255, 255, 255))
            right = cv2.bitwise_and(right, warped)
        cv2.polylines(right, [pts.astype(np.int32).reshape(-1, 1, 2)], True, color, 1)
    out = Image.new("RGB", (w * 2, h), (255, 255, 255))
    out.paste(Image.blend(img_rgb, left, 0.5), (0, 0))
    out.paste(Image.fromarray(right), (w, 0))
    return out


def save_ocr_image(res_json: Path, img_path: Path, out_jpg: Path) -> None:
    from PIL import Image
    r = json.load(open(res_json, encoding="utf-8"))
    with Image.open(img_path) as im:
        draw_ocr_result(im.convert("RGB"), r.get("rec_polys") or r.get("dt_polys") or [], r.get("rec_texts") or []).save(
            out_jpg, quality=75)


def fetch_images(list_csv: Path, img_dir: Path) -> list[str]:
    """(Colab) tải ảnh gốc từ Vietnamica theo danh sách bia_id,url,md5; bỏ ảnh lệch md5 so với bản nhóm."""
    img_dir.mkdir(parents=True, exist_ok=True)
    ok, bad = [], []
    for r in csv.DictReader(open(list_csv, encoding="utf-8")):
        f = img_dir / f"{r['bia_id']}.jpg"
        if not f.exists():
            req = urllib.request.Request(r["url"], headers={"User-Agent": "VanBia-course-downloader/1.0"})
            f.write_bytes(urllib.request.urlopen(req, timeout=120).read())
        (ok if hashlib.md5(f.read_bytes()).hexdigest() == r["md5"] else bad).append(r["bia_id"])
    print(f"ảnh: {len(ok) + len(bad)} | lệch md5 so với bản nhóm: {bad or 'không'}", flush=True)
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["paddle", "rapid"], default="paddle")
    ap.add_argument("--variant", nargs="*", choices=list(VARIANTS), default=None, help=f"mặc định: {DEFAULT_SET}")
    ap.add_argument("--device", default="gpu", help="paddle: gpu | cpu")
    ap.add_argument("--img-dir", type=Path, default=ROOT / "data" / "raw" / "anh_bia")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "interim" / "paddle_raw")
    ap.add_argument("--only", nargs="*", help="chỉ các bia_id này")
    ap.add_argument("--tai-anh", type=Path, help="(Colab) CSV bia_id,url,md5 — tải ảnh vào --img-dir trước khi OCR")
    ap.add_argument("--force", action="store_true", help="OCR lại cả mặt đã có kết quả")
    ap.add_argument("--ve-anh", action="store_true",
                    help="vẽ thêm <bia_id>_ocr_res_img.jpg như save_to_img của PaddleOCR (mặt đã có JSON: chỉ vẽ)")
    a = ap.parse_args(argv)
    ids = fetch_images(a.tai_anh, a.img_dir) if a.tai_anh else sorted(p.stem for p in a.img_dir.glob("*.jpg"))
    ids = [i for i in ids if not a.only or i in a.only]
    for v in a.variant or (DEFAULT_SET if a.engine == "paddle" else ["inv_clahe_tile"]):
        mode, tile, lim = VARIANTS[v]
        out = a.out / f"{a.engine}_{v}"
        out.mkdir(parents=True, exist_ok=True)
        run = None                               # nạp model khi thật sự cần OCR (chỉ vẽ ảnh thì không cần paddle)
        t0 = time.time()
        for bid in ids:
            f = out / f"{bid}_res.json"
            if not f.exists() or a.force:
                run = run or make_engine(a.engine, lim, a.device)
                img = cv2.imdecode(np.fromfile(str(a.img_dir / f"{bid}.jpg"), np.uint8), cv2.IMREAD_COLOR)  # đường dẫn Unicode
                polys, txts, scores, n = ocr_image(run, preprocess(img, mode), tile)
                with open(f, "w", encoding="utf-8", newline="\n") as fh:
                    json.dump({"input_path": f"data/raw/anh_bia/{bid}.jpg", "engine": a.engine, "variant": v,
                               "tiles": n, "dt_polys": polys, "rec_texts": txts, "rec_scores": scores}, fh,
                              ensure_ascii=False)
            vis = out / f"{bid}_ocr_res_img.jpg"
            if a.ve_anh and (not vis.exists() or a.force):
                save_ocr_image(f, a.img_dir / f"{bid}.jpg", vis)
        print(f"{a.engine}_{v}: {len(ids)} mặt, {time.time() - t0:.0f}s -> {out}", flush=True)
    return 0


def _selftest() -> None:
    g = np.full((900, 200), 255, np.uint8)
    for a_, b_ in ((50, 285), (315, 585), (615, 880)):                                # 3 khối chữ, khe ~30 px
        g[a_:b_, 50:150] = 0
    cuts = cut_points(g)
    assert cuts[0] == 0 and cuts[-1] == 900 and len(cuts) == 4
    assert 285 <= cuts[1] < 315 and 585 <= cuts[2] < 615, cuts                        # cắt đúng khe, không chém chữ
    img = np.zeros((10, 10, 3), np.uint8)
    assert preprocess(img, "inv_clahe").mean() > 200                                  # nền đen → nền sáng
    print("ocr_bia selftest: ĐẠT")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
        sys.exit(0)
    sys.exit(main())
