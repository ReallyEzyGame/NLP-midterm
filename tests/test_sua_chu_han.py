from src.step1_book_mining.sua_chu_han import apply_rule


def test_sua_chu_han_qua_dau_cau_va_xuong_dong():
    lines = ["甲乙。丙日", "丁戊MASK己"]
    assert apply_rule(lines, "丙日丁", "丙曰丁") == "ok" and lines == ["甲乙。丙曰丁", "戊MASK己"]   # chữ nằm 2 dòng
    assert apply_rule(lines, "丙日丁", "丙曰丁") == "da_sua"                                      # chạy lại an toàn
    assert apply_rule(lines, "庚辛", "壬") == "khong_thay"
    assert apply_rule(["甲乙", "甲乙"], "甲乙", "丙") == "nhieu_cho"
    l2 = ["甲日六", "二立丁"]
    assert apply_rule(l2, "日六二立", "旦立") == "ok" and l2 == ["甲旦立", "丁"]
