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


def test_ap_quyet_dinh_ra_soat_tay(tmp_path):
    """GAN/MASK/KHONG_GAN/LOAI áp theo bia_id + text_ocr; LOAI xoá box và đánh lại order liên tục."""
    import csv
    from src.step3_ocr_align.pipeline_dataset_ocr import QD_COLS, apply_review
    boxes = [{"order": k, "region": "than", "points": [[0, 0], [1, 0], [1, 1], [0, 1]], "text_ocr": t, "score": 0.9,
              "source": "auto"} for k, t in enumerate(["甲乙", "02338", "丙丁", "戊己"], 1)]
    items = [{"order": b["order"], "text_ocr": b["text_ocr"], "text_gt": "", "score": 0.1, "status": "needs_review"}
             for b in boxes]
    data = {"B1": ({"schema_version": 1, "bia_id": "B1", "boxes": boxes}, items)}
    f = tmp_path / "qd.csv"
    with open(f, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(QD_COLS)
        w.writerows([["B1", 1, "甲乙", "GAN", "甲乙", "khe sách", "x"], ["B1", 2, "02338", "LOAI", "", "số hiệu", "x"],
                     ["B1", 3, "丙丁", "MASK", "", "sách không chép", "x"], ["B1", 4, "戊己", "KHONG_GAN", "", "khác sách", "x"]])
    log, warn, by_item = apply_review(data, f)
    assert not warn and len(log) == 4
    assert [b["order"] for b in data["B1"][0]["boxes"]] == [1, 2, 3] and [i["order"] for i in items] == [1, 2, 3]
    assert [(i["text_gt"], i["status"]) for i in items] == [("甲乙", "ok"), ("MASK", "ok"), ("", "needs_review")]
    assert by_item[id(items[2])][1] == 3                     # log ghi order SAU khi đánh lại
