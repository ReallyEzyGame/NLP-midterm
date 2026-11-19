"""Kiểm thử Dataset 2 (Hán–Phiên âm–Dịch nghĩa) — dữ liệu tự tạo."""
from src.step4_trans_align import build_dataset_dich as D
from src.step4_trans_align.tu_dien_han_viet import am_key


def test_tach_cau_va_am_tiet_mask():
    assert D.split_units(["gỗ lim tu sửa chùa. Kính nghĩ:"]) == ["gỗ lim tu sửa chùa.", "Kính nghĩ:"]
    assert D.syllables("Nguyễn Hữu Tiến MASK thượng (?) hạ") == ["nguyễn", "hữu", "tiến", "？", "thượng", "？", "hạ"]
    assert D.han_chars("阮有進MASK上下") == "阮有進？上下"


def test_han_pa_va_bad_run():
    lex = {"天": {am_key("thiên")}, "地": {am_key("địa")}, "人": {am_key("nhân")}}   # giá trị = khoá âm (am_key)
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


def test_am_key_va_ban_do_chu_am():
    assert am_key("Hoà") == am_key("hòa") and am_key("kì") == am_key("kỳ")
    lex = {"天": {am_key("thiên")}, "地": {am_key("địa")}}
    D.align_han_pa("天X地", ["Thiên địa"], lex)
    assert D.align_han_pa.h2s == [0, None, 1]                   # chữ thừa X không có âm
    assert D.syllables("Hậu Phật (?)", lower=False) == ["Hậu", "Phật", "？"]


def test_ap_quyet_dinh_ra_soat_tay():
    d = {"id": "x", "han": "甲乙丙丁", "pa": ["Giáp ất.", "Bính đinh."], "dn": ["Một hai.", "Ba bốn."]}
    rec = lambda k, h, p, n: {"pair_id": k, "han": h, "phien_am": p, "dich_nghia": n, "status": "needs_review"}
    recs = [rec(1, "甲", "Giáp ất.", "Một"), rec(2, "乙", "Bính đinh.", "hai. Ba bốn.")]
    whys = ["a", "b"]
    rows = [{"pa_dau": "Giáp", "quyet_dinh": "SUA", "han": "甲乙戊", "phien_am": "", "dich_nghia": "Một hai.",
             "ghi_chu": "", "nguoi_sua": "T"},
            {"pa_dau": "Bính", "quyet_dinh": "LOAI", "han": "", "phien_am": "", "dich_nghia": "", "ghi_chu": "",
             "nguoi_sua": "T"},
            {"pa_dau": "Không có", "quyet_dinh": "OK", "han": "", "phien_am": "", "dich_nghia": "", "ghi_chu": "",
             "nguoi_sua": "T"}]
    log, warn = D.apply_review(d, recs, whys, rows)
    assert [r["han"] for r in recs] == ["甲乙戊"] and recs[0]["status"] == "ok" and recs[0]["dich_nghia"] == "Một hai."
    assert whys == ["a"] and len(log) == 2 and "戊" in log[0][5]       # chữ ngoài sách được ghi lại
    assert len(warn) == 1 and "khớp 0" in warn[0]
