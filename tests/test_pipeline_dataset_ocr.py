"""Kiểm thử các quy tắc của pipeline Dataset 1 (gộp nguồn, MASK sách không chép, xử lý needs_review)."""
from src.step3_ocr_align import pipeline_dataset_ocr as P

BOX = {"points": [[500, 0], [600, 0], [600, 900], [500, 900]], "region": "than"}
NR = {"status": "needs_review", "text_gt": "", "text_ocr": "阮文甲阮文乙"}


def test_candidate_loai_rac_va_mep():
    assert P.candidate(NR, BOX, 1000)
    assert not P.candidate({**NR, "text_ocr": "阮文"}, BOX, 1000)                     # mảnh 1–2 chữ
    assert not P.candidate({**NR, "text_ocr": "29OM阮"}, BOX, 1000)                   # số hiệu/Latin
    assert not P.candidate(NR, {**BOX, "points": [[5, 0], [30, 0], [30, 900], [5, 900]]}, 1000)   # sát mép
    assert not P.candidate(NR, {**BOX, "region": "tran"}, 1000)


def test_in_book():
    assert P.in_book("典天無", "卓爾豐碑與天無極民之思之")                                # OCR sai 1 chữ vẫn là chữ sách
    assert not P.in_book("阮文甲阮文乙", "卓爾豐碑與天無極民之思之")


def test_partition_gioi_cuc_bo():
    r = P.partition(["天開南越地闢北京", "阮文甲阮文乙", "縣名東崖社號扶寧"], "天開南越地闢北京縣名東岸社號扶寧")
    assert r[0][:2] == (0, 8) and r[1] is None and r[2][:2] == (8, 16), r
    assert P.partition(["生"], "阮生")[0] == (1, 2, 1.0)
    assert P.partition(["甲"], "阮生")[0] is None


def test_anchor_chi_nhan_dai_va_tim_tien():
    g = "生阮公天開南越地闢生阮公縣名東岸社號"
    pos = P.anchor_positions([(0, "生"), (1, "天開南越"), (2, "阮公"), (3, "縣名東岸")], g)
    assert set(pos) == {1, 3} and pos[1] == (3, 7) and pos[3] == (12, 16)


def test_chon_nguon_khong_dem_chu_MASK():
    assert P.labeled_chars([{"status": "ok", "text_gt": "MASK"}, {"status": "ok", "text_gt": "阮有進MASK"},
                            {"status": "needs_review", "text_gt": "天地"}]) == 3
