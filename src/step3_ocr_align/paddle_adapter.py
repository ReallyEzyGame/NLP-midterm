"""Chuyển đổi kết quả PaddleOCR thô (*_res.json) sang chuẩn bbox_chuan (<bia_id>.json).

Tuân thủ Data Contract v1.0 (Mục 5.4 & Mục 10.2):
- Lọc bỏ box nhiễu / ký hiệu thư viện dán bên lề giấy rập (x ngoài rìa, số trang, kích thước...).
- Phân vùng Trán bia ('tran') vs Thân bia ('than').
- Sắp xếp đúng thứ tự đọc truyền thống của văn bia Hán Nôm:
  1. Trán bia trước, Thân bia sau.
  2. Trán bia: từ Phải sang Trái.
  3. Thân bia: gom cụm theo từng cột dọc từ Phải sang Trái, bên trong mỗi cột đọc từ Trên xuống Dưới.
"""
from __future__ import annotations

import logging
import re
import statistics
from pathlib import Path
from typing import Any

from PIL import Image

from src.utils import file_io as fio

log = logging.getLogger("paddle_adapter")

# CJK / Hán Nôm character matcher
_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ffff]")
# Provenance / rubbing caption typically printed along the paper margin of stele rubbings
_PROVENANCE_RE = re.compile(r"一碑.*面之|省.*府.*(縣|州).*社.*(寺|亭|碑)")
# Library dimension strings like "0,75×0,30", "0,86×0,6", "075×0.3", "(Scar", "2459", "1261."
_DIMENSION_OR_ID_RE = re.compile(r"^[\d\s,.\-×xX*()A-Za-z]+$")


def _box_metrics(poly: list[list[float]]) -> dict[str, float]:
    xs = [float(p[0]) for p in poly]
    ys = [float(p[1]) for p in poly]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    return {
        "xmin": xmin,
        "xmax": xmax,
        "ymin": ymin,
        "ymax": ymax,
        "cx": (xmin + xmax) / 2.0,
        "cy": (ymin + ymax) / 2.0,
        "w": xmax - xmin,
        "h": ymax - ymin,
    }


def _to_4pts(poly: list[list[float]]) -> list[list[int]]:
    """Chuẩn hóa polygon về đúng 4 đỉnh [TL, TR, BR, BL] dạng số nguyên."""
    pts = [[int(round(p[0])), int(round(p[1]))] for p in poly]
    if len(pts) != 4:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        return [[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax]]
    # Đảm bảo thứ tự chuẩn: trên-trái (TL), trên-phải (TR), dưới-phải (BR), dưới-trái (BL)
    by_sum = sorted(pts, key=lambda p: p[0] + p[1])
    tl, br = by_sum[0], by_sum[3]
    rem = sorted([by_sum[1], by_sum[2]], key=lambda p: p[0] - p[1], reverse=True)
    tr, bl = rem[0], rem[1]
    return [tl, tr, br, bl]


def is_debris_box(
    text: str,
    metrics: dict[str, float],
    img_width: int,
    img_height: int,
    min_conf: float = 0.20,
    score: float = 1.0,
) -> tuple[bool, str]:
    """Nhận diện box nhiễu/lề thư viện không thuộc nội dung văn bia."""
    clean = text.strip()
    if not clean:
        return True, "EMPTY_TEXT"
    if score < min_conf:
        return True, f"LOW_OCR_CONF({score:.2f})"

    # Box toàn số / chữ Latin / kích thước đo lường (vd: '2459', '0,86×0,6', '(Scar', 'A.', '36')
    han_chars = _HAN_RE.findall(clean)
    if not han_chars:
        return True, f"NON_HAN({clean!r})"

    if _DIMENSION_OR_ID_RE.match(clean):
        return True, f"ASCII_OR_NUMERIC({clean!r})"

    # Lề giấy rập bên phải (thường chiếm ~10-12% mép phải ảnh nơi Viện Hán Nôm dán nhãn + ghi xuất xứ)
    if img_width > 0:
        if metrics["xmin"] > img_width * 0.87:
            return True, f"RIGHT_PAPER_MARGIN(xmin={metrics['xmin']:.0f})"
        if _PROVENANCE_RE.search(clean) and (metrics["xmin"] > img_width * 0.80 or metrics["xmax"] < img_width * 0.15):
            return True, f"PROVENANCE_MARGIN({clean[:12]})"

    # Box quá nhỏ ở rìa góc ảnh
    if img_width > 0 and img_height > 0:
        if metrics["w"] < img_width * 0.015 and metrics["h"] < img_height * 0.015:
            return True, "TINY_ARTIFACT"

    return False, ""


def _vertical_overlap_ratio(a: dict[str, float], b: dict[str, float]) -> float:
    inter = max(0.0, min(a["ymax"], b["ymax"]) - max(a["ymin"], b["ymin"]))
    min_h = max(1.0, min(a["h"], b["h"]))
    return inter / min_h


def sort_stele_boxes(
    boxes: list[dict[str, Any]],
    img_width: int,
    img_height: int,
) -> list[dict[str, Any]]:
    """Phân vùng Trán/Thân và sắp xếp đúng thứ tự đọc:
    - Trán bia trước (Phải -> Trái)
    - Thân bia sau: gom cụm cột dọc (không chồng lấn y), xếp cột Phải -> Trái, trong cột Trên -> Dưới.
    """
    tran_boxes: list[dict[str, Any]] = []
    than_boxes: list[dict[str, Any]] = []

    for b in boxes:
        m = b["_m"]
        # Trán bia: nằm ở 28% phía trên ảnh và KHÔNG phải cột dọc cao hẹp
        is_top_band = img_height > 0 and m["ymax"] < img_height * 0.30
        aspect = m["w"] / max(1.0, m["h"])
        if is_top_band and aspect >= 0.72:
            b["region"] = "tran"
            tran_boxes.append(b)
        else:
            b["region"] = "than"
            than_boxes.append(b)

    # Sắp xếp Trán bia: Phải -> Trái (theo cx giảm dần)
    # Nếu có nhiều hàng trên trán bia, ưu tiên hàng trên trước khi cách biệt y lớn
    tran_boxes.sort(key=lambda b: (-b["_m"]["cx"]))

    # Gom cụm cột cho Thân bia
    ordered_than: list[dict[str, Any]] = []
    if than_boxes:
        widths = [b["_m"]["w"] for b in than_boxes]
        median_w = statistics.median(widths) if widths else 150.0
        col_tol = max(40.0, median_w * 0.65)

        # Duyệt các box theo thứ tự cx giảm dần (từ phải sang trái)
        remaining = sorted(than_boxes, key=lambda b: (-b["_m"]["cx"], b["_m"]["ymin"]))
        columns: list[dict[str, Any]] = []

        for b in remaining:
            m = b["_m"]
            best_col = None
            best_dist = float("inf")

            for col in columns:
                # Kiểm tra khoảng cách tâm X so với cột hiện tại
                dist = abs(m["cx"] - col["mean_cx"])
                if dist > col_tol:
                    continue
                # Bất biến hình học: 2 box nằm ngang hàng (chồng lấn y > 45%) KHÔNG thể chung 1 cột dọc
                has_y_conflict = any(_vertical_overlap_ratio(m, existing["_m"]) > 0.45 for existing in col["items"])
                if has_y_conflict:
                    continue
                if dist < best_dist:
                    best_dist = dist
                    best_col = col

            if best_col is not None:
                best_col["items"].append(b)
                best_col["mean_cx"] = sum(it["_m"]["cx"] for it in best_col["items"]) / len(best_col["items"])
            else:
                columns.append({"mean_cx": m["cx"], "items": [b]})

        # Xếp các cột từ Phải sang Trái (mean_cx giảm dần)
        columns.sort(key=lambda c: -c["mean_cx"])
        for col in columns:
            # Trong mỗi cột, xếp từ Trên xuống Dưới (ymin tăng dần)
            col["items"].sort(key=lambda it: (it["_m"]["ymin"], -it["_m"]["cx"]))
            ordered_than.extend(col["items"])

    combined = tran_boxes + ordered_than
    result: list[dict[str, Any]] = []
    for idx, b in enumerate(combined, start=1):
        result.append(
            {
                "order": idx,
                "region": b["region"],
                "points": b["points"],
                "text_ocr": fio.nfc(b["text_ocr"]),
                "score": round(float(b["score"]), 4),
                "source": "auto",
            }
        )
    return result


def convert_paddle_raw_to_bbox_chuan(
    raw_json_path: Path,
    bia_id: str,
    image_path: Path | None = None,
    min_conf: float = 0.20,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Đọc file *_res.json của PaddleOCR và trả về (payload_bbox_chuan, dropped_boxes)."""
    raw = fio.read_json(raw_json_path)

    img_w, img_h = 0, 0
    if image_path and image_path.exists():
        with Image.open(image_path) as im:
            img_w, img_h = im.size
    else:
        # Ước lượng kích thước từ tọa độ lớn nhất nếu không có file ảnh
        polys = raw.get("dt_polys") or raw.get("rec_polys") or []
        if polys:
            img_w = int(max(p[0] for poly in polys for p in poly))
            img_h = int(max(p[1] for poly in polys for p in poly))

    polys = raw.get("dt_polys") or raw.get("rec_polys") or []
    texts = raw.get("rec_texts") or []
    scores = raw.get("rec_scores") or [0.90] * len(texts)

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    for idx, (poly, txt, sc) in enumerate(zip(polys, texts, scores)):
        m = _box_metrics(poly)
        is_bad, reason = is_debris_box(txt, m, img_w, img_h, min_conf=min_conf, score=float(sc))
        if is_bad:
            dropped.append({"raw_index": idx, "text": txt, "score": round(float(sc), 4), "reason": reason})
            continue
        kept.append(
            {
                "points": _to_4pts(poly),
                "text_ocr": txt.strip(),
                "score": float(sc),
                "_m": m,
            }
        )

    sorted_boxes = sort_stele_boxes(kept, img_width=img_w, img_height=img_h)
    payload = {
        "schema_version": fio.SCHEMA_VERSION,
        "bia_id": bia_id,
        "boxes": sorted_boxes,
    }
    return payload, dropped
