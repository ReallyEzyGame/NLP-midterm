"""Kiểm thử cho module Bước 1.C: paddle_adapter, text_aligner V2.2 và pipeline_1c_trial."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from src.step3_ocr_align.align_schema import validate_raw_bbox_input
from src.step3_ocr_align.paddle_adapter import convert_paddle_raw_to_bbox_chuan
from src.step3_ocr_align.pipeline_1c_trial import (
    run_calibration_sweep,
    run_trial_on_testbed,
    write_needs_review_csv,
)
from src.step3_ocr_align.text_aligner import DynamicProgrammingAligner


def test_paddle_adapter_filter_and_sort():
    """Kiểm tra lọc box nhiễu lề giấy rập + tách trán + gom cụm cột dọc Phải->Trái, Trên->Dưới."""
    with TemporaryDirectory() as tmp:
        raw_path = Path(tmp) / "sample_res.json"
        # Giả lập ảnh 1000x2000:
        # - Lề phải x=910..980: '2459', '北寧省...一碑三面之一' (phải bị loại)
        # - Trán bia: '後' (x=600..700, y=100..200), '佛' (x=400..500, y=100..200)
        # - Thân bia: 2 cột thơ 2 tầng:
        #     Cột phải (x=700..780): '天開' (y=400..600), '地闢' (y=700..900)
        #     Cột trái (x=500..580): '氣鍾' (y=400..600), '人稟' (y=700..900)
        raw_data = {
            "dt_polys": [
                [[910, 100], [980, 100], [980, 150], [910, 150]],    # debris ID
                [[920, 300], [990, 300], [990, 1200], [920, 1200]],  # provenance margin
                [[500, 700], [580, 700], [580, 900], [500, 900]],    # 人稟 (trái dưới)
                [[400, 100], [500, 100], [500, 200], [400, 200]],    # 佛 (trán trái)
                [[700, 400], [780, 400], [780, 600], [700, 600]],    # 天開 (phải trên)
                [[600, 100], [700, 100], [700, 200], [600, 200]],    # 後 (trán phải)
                [[500, 400], [580, 400], [580, 600], [500, 600]],    # 氣鍾 (trái trên)
                [[700, 700], [780, 700], [780, 900], [700, 900]],    # 地闢 (phải dưới)
            ],
            "rec_texts": ["2459", "北寧省扶寧社一碑三面之一", "人稟", "佛", "天開", "後", "氣鍾", "地闢"],
            "rec_scores": [0.99, 0.85, 0.96, 0.99, 0.98, 0.99, 0.97, 0.95],
        }
        raw_path.write_text(json.dumps(raw_data, ensure_ascii=False), encoding="utf-8")

        # Truyền ảnh giả định kích thước qua poly max hoặc tạo ảnh trắng
        from PIL import Image
        img_path = Path(tmp) / "sample.jpg"
        Image.new("RGB", (1000, 2000)).save(img_path)

        payload, dropped = convert_paddle_raw_to_bbox_chuan(raw_path, "02459-31", img_path)
        validate_raw_bbox_input(payload)

        assert len(dropped) == 2
        texts_ordered = [b["text_ocr"] for b in payload["boxes"]]
        regions_ordered = [b["region"] for b in payload["boxes"]]

        assert regions_ordered == ["tran", "tran", "than", "than", "than", "than"]
        assert texts_ordered == ["後", "佛", "天開", "地闢", "氣鍾", "人稟"]


def test_v22_variants_reversed_tran_and_multiface():
    """Kiểm tra dị thể/chữ kép, trán bia đọc ngược và neo đa mặt bia + chống khớp nhầm tên ngắn."""
    gt_text = (
        "后佛碑記\n"
        "慈山府東岸縣扶寧社銀子十田二鐵林八十四株"
        "五十條造成名寺培滿福堂本社事爲後佛"
        "皇朝德元萬萬年之二本社官員阮德懋撰"
    )
    boxes = [
        {"order": 1, "region": "tran", "text_ocr": "記碑佛後", "score": 0.98},   # Trán đọc ngược + dị thể 后/後
        {"order": 2, "region": "than", "text_ocr": "五十條造成名寺培滿福堂本社事為後佛", "score": 0.95},  # Mặt giữa + 為/爲
        {"order": 3, "region": "than", "text_ocr": "阮德春", "score": 0.95},     # Tên công đức ngắn vắng mặt trong sách
        {"order": 4, "region": "than", "text_ocr": "皇朝德元萬萬年之二", "score": 0.96},  # Nhảy sang mặt cuối
    ]
    aligner = DynamicProgrammingAligner(threshold=0.80)
    res = aligner.align("02459-31", boxes, gt_text)

    # Box 1: Trán bia đảo chiều khớp '后佛碑記' với điểm cao nhờ dị thể 後=后
    assert res.items[0].status == "ok"
    assert res.items[0].text_gt == "后佛碑記"
    assert res.items[0].score >= 0.95

    # Box 2: Tự neo được vào đoạn giữa của văn bản đa mặt
    assert res.items[1].status == "ok"
    assert "五十條" in res.items[1].text_gt

    # Box 3: Tên ngắn '阮德春' KHÔNG bị khớp nhầm sang '阮德懋'
    assert res.items[2].status == "needs_review"
    assert res.items[2].text_gt == ""

    # Box 4: Tiếp tục neo đúng mặt cuối
    assert res.items[3].status == "ok"
    assert "皇朝德元" in res.items[3].text_gt


def test_pipeline_1c_testbed_and_sweep():
    """Kiểm tra pipeline_1c_trial trên testbed giả lập và xuất needs_review.csv."""
    repo_root = Path(__file__).resolve().parents[1]
    records = run_trial_on_testbed(repo_root, threshold=0.80)
    assert len(records) == 4

    with TemporaryDirectory() as tmp:
        rev_csv = Path(tmp) / "needs_review.csv"
        cnt = write_needs_review_csv(records, rev_csv)
        assert rev_csv.exists()
        with open(rev_csv, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == cnt

    sweep = run_calibration_sweep(repo_root, records, use_testbed=True)
    assert len(sweep) == 5
    assert sweep[0]["ok"] >= sweep[-1]["ok"]


if __name__ == "__main__":
    test_paddle_adapter_filter_and_sort()
    test_v22_variants_reversed_tran_and_multiface()
    test_pipeline_1c_testbed_and_sweep()
    print("ALL TASK 1.C PIPELINE & ADAPTER TESTS PASSED!")
