"""Kiểm thử tiền xử lý OCR thác bản (cắt tile ở khe giữa hàng chữ, đảo màu)."""
from src.step2_stele_ocr import ocr_bia


def test_selftest_ocr_bia():
    ocr_bia._selftest()


def test_ve_anh_ket_qua_giong_paddleocr():
    from PIL import Image
    img = Image.new("RGB", (200, 400), (0, 0, 0))
    out = ocr_bia.draw_ocr_result(img, [[[50, 20], [90, 20], [90, 380], [50, 380]]], ["天地人和"])
    assert out.size == (400, 400)                                   # 2 nửa: ảnh có box | chữ OCR
    assert out.getpixel((300, 10)) == (255, 255, 255)               # nửa phải nền trắng
    assert out.getpixel((70, 200)) != (0, 0, 0)                     # box được tô màu bán trong suốt
