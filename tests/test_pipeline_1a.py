"""Kiểm thử các sửa đổi 1–7 của pipeline 1.A — dữ liệu tự tạo (không dùng nội dung sách, không gọi API)."""
import tempfile
from pathlib import Path
from types import SimpleNamespace

from src.step1_book_mining import clean_book_text as cb
from src.step1_book_mining import ocr_gemini as og
from src.step1_book_mining import pipeline_1a as pl
from src.step1_book_mining import regex_filter as rf

MODEL = "m"


def _setup(pages: dict[int, str]) -> Path:
    tmp = Path(tempfile.mkdtemp())
    cb.OCR_ROOT, cb.TEXT_THO, cb.NHAP = tmp / "ocr", tmp / "tho", tmp / "nhap"
    (tmp / "ocr" / MODEL).mkdir(parents=True)
    for p, t in pages.items():
        (tmp / "ocr" / MODEL / f"p{p:03d}.txt").write_text(t, encoding="utf-8")
    return tmp


ROW = {"tr_han_bat_dau": "10", "tr_tieu_de_viet": "10", "tr_ket_thuc": "10"}
P10 = "5.天地人\n日月星辰\n5. BIA THỬ NGHIỆM\nBia chùa X, số kí hiệu: 1.\nPhiên âm: Bia thử\nThiên địa nhân.\nDịch nghĩa: Bia thử\nTrời đất và người cùng\n"
P11 = "chung sống yên vui.\n\nĐÌNH LÀNG MẪU\nĐình làng Mẫu nằm ở xóm 1.\n6.山水\n"


def _read(tmp, kind):
    return (tmp / "nhap" / kind / "VBLN-005.txt").read_text(encoding="utf-8").split("\n")[:-1]


# ---- sửa 1 + 3 + 7: dừng ở tiêu đề di tích, nối câu qua trang, kiểm tra số tiêu đề
def test_tach_dung_o_tieu_de_di_tich_va_noi_cau():
    tmp = _setup({10: P10, 11: P11})
    st = cb.process(5, ROW, MODEL, (11, True))
    dich = _read(tmp, "Dich_nghia")
    assert dich == ["Bia thử", "Trời đất và người cùng chung sống yên vui."]      # không dính "Đình làng Mẫu…"
    assert st["loi"] == "" and st["canh_bao"] == []


def test_sai_so_tieu_de_han_la_loi():
    _setup({10: P10.replace("5.天地人", "4.天地人"), 11: P11})
    st = cb.process(5, ROW, MODEL, (11, True))
    assert "≠ STT 5" in st["loi"]


def test_canh_bao_khi_chua_gap_diem_ket_thuc():
    _setup({10: P10})                                      # thiếu trang 11 nhưng mục lục bảo hết ở 10
    st = cb.process(5, ROW, MODEL, (10, True))
    assert any("thiếu đoạn cuối" in c for c in st["canh_bao"])


def test_dung_o_tieu_de_viet_bia_ke_khong_co_han():
    tmp = _setup({10: P10, 11: "chung sống.\n6. BIA KẾ TIẾP\nBia chùa Y.\n"})
    st = cb.process(5, ROW, MODEL, (11, True))
    assert _read(tmp, "Dich_nghia")[-1] == "Trời đất và người cùng chung sống." and st["canh_bao"] == []


def test_page_end_mo_rong_toi_dau_bia_ke():
    rows = {5: {"tr_ket_thuc": "10"}, 6: {"tr_han_bat_dau": "11", "tr_tieu_de_viet": "12", "tr_ket_thuc": "14"}}
    assert cb.page_end(5, rows) == (11, True)
    rows[6]["tr_han_bat_dau"] = "30"                       # mục lục lệch xa ⇒ chỉ mở rộng tối đa MAX_THEM trang
    assert cb.page_end(5, rows) == (10 + cb.MAX_THEM, True)
    assert cb.page_end(6, rows)[1] is False                # bia cuối: không kỳ vọng điểm kết thúc


def test_heading_va_header_bia_ke():
    assert rf.is_section_heading("TỪ ĐƯỜNG HỌ NGUYỄN")
    assert not rf.is_section_heading("Từ đường họ Nguyễn")
    assert not rf.is_section_heading("KÊ:")                 # 1 từ
    assert not rf.is_section_heading("22. HẬU PHẬT BI KÍ")  # có số
    assert rf.is_later_viet_header("6. BIA KẾ TIẾP", 5)
    assert not rf.is_later_viet_header("5. BIA NÀY", 5)
    assert not rf.is_later_viet_header("6. năm sau dân làng", 5)


def test_noi_cau_chi_khi_can():
    assert rf.viet_items(["Câu một chưa hết", "", "phần còn lại."]) == ["Câu một chưa hết phần còn lại."]
    assert rf.viet_items(["Câu một.", "", "câu hai."]) == ["Câu một.", "câu hai."]
    assert rf.viet_items(["Mục một", "", "Mục hai."]) == ["Mục một", "Mục hai."]


# ---- sửa 2: phản hồi Gemini rỗng / bị chặn / bị cắt
def test_finish_reason():
    ok = SimpleNamespace(candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))])
    cut = SimpleNamespace(candidates=[SimpleNamespace(finish_reason="FinishReason.MAX_TOKENS")])
    assert og.finish_reason(ok) == "STOP"
    assert og.finish_reason(cut) == "MAX_TOKENS"
    assert og.finish_reason(SimpleNamespace(candidates=[])) == "NONE"
    assert og.finish_reason(SimpleNamespace()) == "NONE"


# ---- sửa 4: file cũ / thừa
def test_xoa_file_cu_va_don_file_thua():
    out = Path(tempfile.mkdtemp())
    for k in pl.KINDS:
        (out / k).mkdir()
        for n in ("00001-21", "00001-21_00002-22", "00009", "00003-11"):
            (out / k / f"{n}.txt").write_text("x\n", encoding="utf-8")
    gone = pl.xoa_file_cu(out, ["00001-21", "00002-22"])
    assert len(gone) == 2 * len(pl.KINDS)
    assert sorted(f.stem for f in (out / "Chu_Han").glob("*.txt")) == ["00003-11", "00009"]
    pl.don_file_thua(out, {"00009"})
    assert [f.stem for f in (out / "Chu_Han").glob("*.txt")] == ["00009"]


# ---- chú thích cuối trang
def test_nhan_dien_dong_chu_thich():
    for s in ("¹ Tức Nguyễn Mậu Thịnh, người xã X.", "1 Chính giác:", "3 Phạm Kính Trai tức Phạm Khiêm Ích",
              "1 Trần Xuân Yến (xem thêm chú thích bia số 5).", "(Xem chú thích 1 bia 18)", "* ghi chú"):
        assert rf.is_footnote(s), s
    for s in ("1 sào ở xứ Thạch Sàng.", "10 thước ruộng mạ ở xứ Lỗi.", "2 mảnh 1 sào rưỡi", "Ngày 2 tháng 3 năm 1760."):
        assert not rf.is_footnote(s), s


def test_chu_thich_cuoi_trang_bi_bo_ca_phan_con_lai():
    p10 = ("5.天地人\n5. BIA THỬ\nBia chùa X.\nPhiên âm: A\nThiên địa.\nDịch nghĩa: A\n"
           "Trời đất. Những\n1 Tinh xá:\nchú giải tiếp theo của chú thích\n")
    p11 = "ngày này, được tổ chức.\n6.山水\n"
    tmp = _setup({10: p10, 11: p11})
    st = cb.process(5, ROW, MODEL, (11, True))
    assert _read(tmp, "Dich_nghia") == ["A", "Trời đất.", "Những ngày này, được tổ chức."]
    assert st["loi"] == ""


def test_bo_chi_so_tren_trong_dong():
    assert rf.clean_viet("người ấy¹ và vợ²") == "người ấy và vợ"


# ---- chuỗi lặp của Gemini, markdown/LaTeX, đường kẻ chú thích
def test_degenerate():
    assert og.degenerate("嘉男" * 50)
    assert og.degenerate("a b c " + "xin chào " * 10)
    assert not og.degenerate("__________________")          # đường kẻ hợp lệ
    assert not og.degenerate("一所田一所田")                  # lặp 2 lần: nội dung thật
    assert not og.degenerate("Nguyễn Văn A, Nguyễn Văn B, Nguyễn Văn C.")


def test_markdown_va_latex():
    assert rf.clean_viet("**Lưu truyền muôn thủa**") == "Lưu truyền muôn thủa"
    assert rf.clean_viet("năm thứ 7 Hoàng Thượng$^1$.") == "năm thứ 7 Hoàng Thượng."
    assert rf.clean_viet("tên _in nghiêng_ ở đây") == "tên in nghiêng ở đây"
    assert rf.clean_viet("xứ Ao_Lư") == "xứ Ao_Lư"           # gạch dưới giữa từ giữ nguyên


def test_duong_ke_ngan_chu_thich():
    assert rf.is_footnote("__________________")
    assert rf.is_footnote("-----")
    assert not rf.is_footnote("Ngày 2 tháng 3 - năm 1760")


# ---- trang lấy từ model dự phòng
def test_trang_thieu_lay_tu_model_du_phong():
    tmp = _setup({10: P10})                                   # model chính thiếu tr.11
    (tmp / "ocr" / "gemini-3.5-flash").mkdir()
    (tmp / "ocr" / "gemini-3.5-flash" / "p011.txt").write_text(P11, encoding="utf-8")
    st = cb.process(5, ROW, MODEL, (11, True))
    assert any("tr.11 lấy từ gemini-3.5-flash" in c for c in st["canh_bao"])
    assert _read(tmp, "Dich_nghia")[-1] == "Trời đất và người cùng chung sống yên vui."


def test_thieu_ca_hai_model_van_la_loi():
    _setup({10: P10})
    try:
        cb.process(5, ROW, MODEL, (11, True))
    except SystemExit as e:
        assert "Thiếu OCR trang 11" in str(e)
    else:
        raise AssertionError("phải dừng khi thiếu trang ở mọi model")


# ---- bia thiếu một loại văn bản ⇒ file rỗng (0 byte), vẫn hợp lệ
def test_bia_khong_co_han_van_tach_duoc():
    page = "52. BIA KHÔNG CÓ HÁN\nBia chùa X, số kí hiệu: 1.\nPhiên âm: A\nThiên địa nhân.\nDịch nghĩa: A\nTrời đất và người.\n"
    tmp = _setup({10: page})
    st = cb.process(52, {"tr_han_bat_dau": "", "tr_tieu_de_viet": "10", "tr_ket_thuc": "10"}, MODEL, (10, False))
    assert st["loi"] == ""
    assert (tmp / "nhap" / "Chu_Han" / "VBLN-052.txt").read_bytes() == b""              # rỗng hoàn toàn
    assert (tmp / "nhap" / "Phien_am" / "VBLN-052.txt").read_text(encoding="utf-8") == "A\nThiên địa nhân.\n"


def test_bia_thieu_phien_am():
    page = "13.天地人\n13. BIA THIẾU PHIÊN ÂM\nBia chùa X.\nDịch nghĩa: A\nTrời đất và người.\n"
    tmp = _setup({10: page})
    cb.process(13, {"tr_han_bat_dau": "10", "tr_tieu_de_viet": "10", "tr_ket_thuc": "10"}, MODEL, (10, False))
    assert (tmp / "nhap" / "Phien_am" / "VBLN-013.txt").read_bytes() == b""
    assert (tmp / "nhap" / "Dich_nghia" / "VBLN-013.txt").read_text(encoding="utf-8") == "A\nTrời đất và người.\n"


def test_checker_chap_nhan_file_0_byte_nhung_bat_dong_trong():
    from src.step1_book_mining import check_van_ban_sach as chk
    d = Path(tempfile.mkdtemp())
    for k in chk.KINDS:
        (d / k).mkdir()
    (d / "Chu_Han" / "X.txt").write_bytes(b"")
    (d / "Phien_am" / "X.txt").write_text("A.\n", encoding="utf-8", newline="\n")
    (d / "Dich_nghia" / "X.txt").write_text("B.\n", encoding="utf-8", newline="\n")
    rep, n = chk.check_dir(d)
    assert n == 0 and "1 file rỗng có chủ ý" in rep[0]
    (d / "Chu_Han" / "X.txt").write_bytes(b"\n")
    assert chk.check_dir(d)[1] == 1
    (d / "Chu_Han" / "X.txt").unlink()
    assert chk.check_dir(d)[1] == 1                         # thiếu hẳn file vẫn là V6
