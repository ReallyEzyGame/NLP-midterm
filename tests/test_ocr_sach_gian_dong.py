"""OCR trang Hán giãn dòng (ocr_gemini --gian-dong) + chọn bản theo độ khớp âm (chon_ban_ocr_han) — dữ liệu tự tạo."""
import numpy as np
from PIL import Image, ImageDraw

from src.step1_book_mining import ocr_gemini as og
from src.step1_book_mining.chon_ban_ocr_han import khop_am
from src.step4_trans_align.tu_dien_han_viet import am_key


def _trang(nhat_dong_dau: bool = True) -> Image.Image:
    im = Image.new("RGB", (600, 400), "white")
    d = ImageDraw.Draw(im)
    for k in range(5):                                   # 5 dòng chữ "đậm", dòng đầu in nhạt
        y = 40 + k * 60
        d.rectangle([60, y, 540, y + 30], fill=(150, 150, 150) if (k == 0 and nhat_dong_dau) else (0, 0, 0))
    return im


def test_gian_dong_khong_mat_dong_nhat():
    im = _trang()
    bands = og.text_bands(im)
    assert len(bands) == 4                               # dòng nhạt (xám 150) không dò được ...
    out, n = og.spaced_image(im)
    g = np.asarray(out.convert("L"))
    rows = (g < 200).sum(axis=1) > 100
    runs = sum(1 for y in range(1, len(rows)) if rows[y] and not rows[y - 1]) + int(rows[0])
    assert runs == 5                                     # ... nhưng vẫn có trong ảnh giãn dòng (không bỏ hàng ảnh nào)
    assert out.height > im.height


def test_khop_am_bat_doc_doc():
    lex = {"天": {am_key("thiên")}, "地": {am_key("địa")}, "人": {am_key("nhân")}, "和": {am_key("hòa")}}
    sy = [am_key(x) for x in "thiên địa nhân hoà".split()]
    assert khop_am("天地人和", sy, lex) == 1.0
    assert khop_am("天人地和"[::-1], sy, lex) < 0.6     # đọc sai thứ tự → khớp âm sụp
