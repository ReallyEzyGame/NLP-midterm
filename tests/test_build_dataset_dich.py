"""Kiểm thử Dataset 2 (Hán–Phiên âm–Dịch nghĩa) — dữ liệu tự tạo."""
from src.step4_trans_align import build_dataset_dich as D


def test_tach_cau_va_am_tiet_mask():
    assert D.split_units(["gỗ lim tu sửa chùa. Kính nghĩ:"]) == ["gỗ lim tu sửa chùa.", "Kính nghĩ:"]
    assert D.syllables("Nguyễn Hữu Tiến MASK thượng (?) hạ") == ["nguyễn", "hữu", "tiến", "？", "thượng", "？", "hạ"]
    assert D.han_chars("阮有進MASK上下") == "阮有進？上下"


def test_han_pa_va_bad_run():
    lex = {"天": {"thiên"}, "地": {"địa"}, "人": {"nhân"}}
    seg, hit = D.align_han_pa("天地人", ["Thiên địa", "nhân."], lex)
    assert seg == ["天地", "人"] and hit == 1.0 and max(D.align_han_pa.bad_run) == 0


def test_ibm1_hoc_tu_dien_dich():
    pairs = [(["quyến", "duy", "a"], ["kính", "nghĩ", "a"]), (["quyến", "duy", "b"], ["kính", "nghĩ", "b"]),
             (["x", "a"], ["x", "a"])]
    td = D.trans_dict(D.train_ibm1(pairs))
    assert {y for y, _ in td["duy"]} & {"kính", "nghĩ"}


def test_ve_dan_chuyen_sang_cau_sau():
    pa = ["Tu sửa chùa chiền đình miếu.", "Quyến duy ông Nguyễn tướng công."]
    dn = ["Tu sửa chùa chiền đình miếu.", "Kính nghĩ:", "ông Nguyễn tướng công."]
    td = {"quyến": [("kính", 0.5)], "duy": [("kính", 0.5), ("nghĩ", 0.5)]}   # như từ điển IBM1 học được
    out = D.align_pa_dn(pa, dn, idf={}, ratio=1.0, tdict=td)
    assert [o[1] for o in out if o[0]] == [[0], [1, 2]]                   # "Kính nghĩ:" về với "Quyến duy…"
