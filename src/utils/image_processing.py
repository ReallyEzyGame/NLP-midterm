"""Xử lý ảnh cho bước xuất dataset — theo Data Contract v1.0 (mục 5.6).

- Tọa độ box luôn tính trên ẢNH GỐC; chỉ scale khi xuất `output/`.
- Patch cắt từ ảnh GỐC (không cắt từ ảnh đã resize) để giữ chất lượng.
- Thứ tự 4 điểm của box: trên-trái, trên-phải, dưới-phải, dưới-trái.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

Points = list[list[float]]   # 4 điểm [x, y]


def load_rgb(path: Path) -> Image.Image:
    img = Image.open(path)
    img.load()
    return img.convert("RGB")


def page_scale(width: int, height: int, max_side: int = 1024) -> float:
    """Hệ số thu nhỏ để cạnh dài ≤ max_side. Không bao giờ phóng to (≤ 1.0)."""
    return min(1.0, max_side / max(width, height))


def resize_page(img: Image.Image, ratio: float) -> Image.Image:
    if ratio >= 1.0:
        return img.copy()
    size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
    return img.resize(size, Image.LANCZOS)


def scale_points(points: Points, ratio: float, size: tuple[int, int]) -> list[list[int]]:
    """Scale tọa độ theo `ratio`, làm tròn số nguyên và kẹp vào trong ảnh (w, h)."""
    w, h = size
    out = []
    for x, y in points:
        sx = min(max(round(x * ratio), 0), w - 1)
        sy = min(max(round(y * ratio), 0), h - 1)
        out.append([sx, sy])
    return out


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def crop_quad(img: Image.Image, points: Points) -> Image.Image:
    """Cắt vùng tứ giác (TL, TR, BR, BL) và nắn thẳng thành hình chữ nhật."""
    tl, tr, br, bl = points
    w = max(1, round((_dist(tl, tr) + _dist(bl, br)) / 2))
    h = max(1, round((_dist(tl, bl) + _dist(tr, br)) / 2))
    # PIL QUAD nhận thứ tự: trên-trái, dưới-trái, dưới-phải, trên-phải
    quad = (*tl, *bl, *br, *tr)
    return img.transform((w, h), Image.QUAD, quad, Image.BICUBIC)


def make_patch(img: Image.Image, points: Points, max_height: int = 96) -> Image.Image:
    """Tạo patch cho nhận dạng: cột đứng xoay 90° NGƯỢC chiều kim đồng hồ,
    rồi thu nhỏ để chiều cao ≤ max_height (giữ tỉ lệ)."""
    patch = crop_quad(img, points)
    if patch.height > patch.width:                    # cột chữ đứng
        patch = patch.rotate(90, expand=True)         # PIL: góc dương = ngược chiều kim đồng hồ
    if patch.height > max_height:
        r = max_height / patch.height
        patch = patch.resize((max(1, round(patch.width * r)), max_height), Image.LANCZOS)
    return patch
