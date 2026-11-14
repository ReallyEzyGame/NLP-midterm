"""Kiểm thử quy tắc làm sạch chung (regex_filter) — dữ liệu tự tạo, không dùng nội dung sách."""
from src.step1_book_mining import regex_filter as rf


def test_viet_khoang_trang_va_dau_cau():
    assert rf.clean_viet("Ngày  lành ,tháng tốt .") == "Ngày lành, tháng tốt."
    assert rf.clean_viet("mỗi cỗ 10 đấu,,, chuối 2 quả") == "mỗi cỗ 10 đấu, chuối 2 quả"
    assert rf.clean_viet("( năm 1760 )") == "(năm 1760)"


def test_viet_ky_tu_rac_va_vo_hinh():
    assert rf.clean_viet("xứ​ Lỗi | một sào") == "xứ Lỗi một sào"
    assert rf.clean_viet("thượng hạ 上下 đẳng") == "thượng hạ đẳng"


def test_viet_giu_so_va_ba_cham():
    assert rf.clean_viet("khổ 0,85 x 0,65m") == "khổ 0,85 x 0,65m"          # không chèn khoảng trắng vào số
    assert rf.clean_viet("thập đấu…") == "thập đấu..."
    assert rf.clean_viet("thập đấu... Cảnh Hưng") == "thập đấu... Cảnh Hưng"
    assert rf.clean_viet("lập bia.Năm sau") == "lập bia. Năm sau"


def test_viet_log():
    log: list[str] = []
    rf.clean_viet("a ,b", log)
    assert "khoảng trắng trước dấu câu" in log


def test_han_dau_cau_va_khoang_trang():
    s, removed = rf.clean_han("天 地, 人.")
    assert s == "天地，人。"
    s, removed = rf.clean_han("天地○○○人12ab")
    assert s == "天地人" and "○○○" in removed


def test_han_chu_tuong_thich():
    s, _ = rf.clean_han("豈")                                      # 豈 dạng tương thích → U+8C48
    assert s == "豈"


def test_han_mask_chu_mat():
    # dấu lược của sách (giảng viên 14/11/2026: chữ mất → MASK); Gemini có khi ghi cách nhau bằng khoảng trắng
    assert rf.clean_han("阮 有 進 ． ． ． 上 下")[0] == "阮有進MASK上下"
    assert rf.clean_han("監生阮克宅。。。全村")[0] == "監生阮克宅MASK全村"
    assert rf.clean_han("盡 力 乎 。 。 。 封 恭")[0] == "盡力乎MASK封恭"           # trước đây ra 乎。。。 → dòng chỉ có 。
    assert rf.clean_han("一高三尺。 。。。")[0] == "一高三尺。MASK"                # hết câu + lược
    assert rf.clean_han("而推 ? 乎")[0] == "而推MASK乎"                            # `?` = 1 chữ không đọc được
    assert rf.split_han("盡力乎MASK封恭有餘而推MASK乎") == ["盡力乎MASK封恭有餘而推MASK乎"]


def test_viet_mask_chu_mat():
    assert rf.mask_viet("Nguyễn Đăng Quý... đồng xã") == "Nguyễn Đăng Quý MASK đồng xã"
    assert rf.mask_viet("vi oản điền....") == "vi oản điền MASK."
    assert rf.mask_viet("Hương lão Nguyễn Đình (?)... thượng hạ") == "Hương lão Nguyễn Đình MASK MASK thượng hạ"
    assert rf.viet_items(["Ruộng 1 sào ... xứ Đồng. Năm sau"]) == ["Ruộng 1 sào MASK xứ Đồng.", "Năm sau"]
