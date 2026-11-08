"""Tạo bộ dữ liệu kiểm thử thực chiến (Testbed) từ văn bia thật làng Nành.

Bao gồm 4 kịch bản kiểm thử:
1. BIA01_clean: OCR lý tưởng, độ chính xác ~98%.
2. BIA01_noisy: OCR thực tế có nhiễu (chữ mòn, nét khắc mờ, sai 15-20% chữ).
3. BIA01_wildcard: Chữ trên bia bị sứt mẻ/mất nét (khớp với ○, □ trong sách).
4. BIA02_realistic: Văn bia dài (Bia 2: Hậu Phật bi kí - 2459) với 18 cột chữ.
"""
from __future__ import annotations

import json
from pathlib import Path
from src.utils import file_io as fio

TESTBED_DIR = Path(__file__).resolve().parent / "testbed"
BBOX_DIR = TESTBED_DIR / "bbox_simulated"
GT_DIR = TESTBED_DIR / "gt_han"


def generate_bia01_testbeds():
    # 1. Bia 1 Clean
    # Cấu trúc: 1 trán bia + 16 cột thân bia
    cols_clean = [
        ("tran", "重修法雲寺碑銘", 0.98),
        ("than", "銘曰扶寧勝地寺創法雲", 0.95),
        ("than", "○○幾代報應孔神", 0.92),
        ("than", "陳修樓殿字勒碑文", 0.96),
        ("than", "莫朝○○名勝僧恩", 0.90),
        ("than", "陳氏之女比丘號眞", 0.97),
        ("than", "柱持淨土遠脫凡塵", 0.94),
        ("than", "焚香供佛積善○○", 0.91),
        ("than", "恭勤貴顯普及庶民", 0.95),
        ("than", "規模革舊制度鼎新", 0.96),
        ("than", "功德無量永久不泯", 0.97),
        ("than", "撰其○○銘之貞珉", 0.92),
        ("than", "皇上萬萬年", 0.99),
        ("than", "范氏玉琨古錢參貫莫氏玉揚莫氏玉清古錢貳貫", 0.93),
        ("than", "福成公主古錢貳貫黃氏玉豪錢貳貫", 0.94),
        ("than", "岸郡公古錢參貫達郡公莫敬愼木郡公阮純端亮公當郡公", 0.92),
        ("than", "會主順安府文江縣丕烈社比丘眞儒陳氏玉瓶應天府山明縣花陰社比丘道", 0.89),
        ("than", "本社仕妮阮奎阮師魯陳文運扶寧社上下官員大小等", 0.93),
        ("than", "延成六年二月初五日本府扶寧社校生阮壽臺桂山撰阮克直阮文東寫安山縣敬主社校生高文可刊", 0.91),
    ]

    boxes_clean = []
    for idx, (reg, txt, sc) in enumerate(cols_clean, start=1):
        boxes_clean.append({
            "order": idx,
            "region": reg,
            "points": [[100 + idx * 50, 100], [140 + idx * 50, 100], [140 + idx * 50, 900], [100 + idx * 50, 900]],
            "text_ocr": txt,
            "score": sc,
            "source": "auto"
        })

    fio.write_json(BBOX_DIR / "BIA01_clean.json", {
        "schema_version": 1,
        "bia_id": "BIA01_clean",
        "boxes": boxes_clean
    })

    # 2. Bia 1 Noisy (mô phỏng OCR thực tế nhận diện sai nét / chữ dị thể)
    noisy_replacements = {
        "重修法雲寺碑銘": "重修法曇寺碑銘",      # 雲 -> 曇
        "銘曰扶寧勝地寺創法雲": "銘日扶寜勝地寺剏法曇", # 曰->日, 寧->寜, 創->剏, 雲->曇
        "陳修樓殿字勒碑文": "陳修樓殿宇勒碑文",      # 字 -> 宇
        "柱持淨土遠脫凡塵": "柱持凈土逺脱凡塵",      # 淨->凈, 遠->逺, 脫->脱
        "規模革舊制度鼎新": "規摸革舊制度鼎新",      # 模 -> 摸
        "皇上萬萬年": "皇上萬萬年",
        "福成公主古錢貳貫黃氏玉豪錢貳貫": "福成公主古錢貳貫黄氏玉豪錢貳貫", # 黃 -> 黄
    }

    boxes_noisy = []
    for b in boxes_clean:
        txt = b["text_ocr"]
        noisy_txt = noisy_replacements.get(txt, txt)
        # Mô phỏng một số ký tự bị nhận diện mờ thành dấu ?
        if "○○" in noisy_txt:
            noisy_txt = noisy_txt.replace("○○", "??")
        boxes_noisy.append({
            "order": b["order"],
            "region": b["region"],
            "points": b["points"],
            "text_ocr": noisy_txt,
            "score": round(b["score"] * 0.9, 2),
            "source": "auto"
        })

    fio.write_json(BBOX_DIR / "BIA01_noisy.json", {
        "schema_version": 1,
        "bia_id": "BIA01_noisy",
        "boxes": boxes_noisy
    })

    # 3. Bia 1 Wildcard Heavy (chữ bị mòn đá nặng, chuyên gia ghi nhận ○ hoặc ?)
    boxes_wildcard = []
    for b in boxes_clean:
        txt = b["text_ocr"]
        if "參貫" in txt:
            txt = txt.replace("參貫", "??")
        if "比丘" in txt:
            txt = txt.replace("比丘", "○○")
        boxes_wildcard.append({
            "order": b["order"],
            "region": b["region"],
            "points": b["points"],
            "text_ocr": txt,
            "score": round(b["score"] * 0.85, 2),
            "source": "auto"
        })

    fio.write_json(BBOX_DIR / "BIA01_wildcard.json", {
        "schema_version": 1,
        "bia_id": "BIA01_wildcard",
        "boxes": boxes_wildcard
    })


def generate_bia02_testbeds():
    # Bia 2 (Hậu Phật bi kí) - Mặt 1 (mã thác bản 2459)
    cols_bia02 = [
        ("tran", "后佛碑記", 0.98),
        ("than", "慈山府東岸縣扶寧社前特進金紫榮祿大夫司禮監都太監參掌監事富郡公", 0.93),
        ("than", "石相公字英毅謚福仁府君爲許本社銀田鐵林橫子創脩名寺碑文事", 0.91),
        ("than", "洪惟我朝聖御乾龍賢從坤馬茲惟令公人中俊傑心上經倫遇主奇緣", 0.89),
        ("than", "侍鳳幄則大言傳命承天異寵儋公爵則華袞耀桓鼎鍾祿厚土田印受彩光門戶", 0.88),
        ("than", "仕顯三朝益老益壽增延歲月宦成數等加恩惠樂與鄉鄰所許本社", 0.92),
        ("than", "上中下三村銀子十佚田二畝鐵林八十四株橫子五十條造成名寺培滿福堂", 0.90),
        ("than", "本社事爲后佛壽康曰壽康富貴年年富貴萬世久稱生佛九天可等上仙河沙功德昭示於無窮矣", 0.87),
        ("than", "當日全社官員鄉老社村長上下巨小等皆起敬情遞年祈福對忌常先供養有光祀典與天地同其悠久", 0.89),
        ("than", "日月性其光明信其永矣顧不題歟但願恒久克鍾如初則天福之來全歸吾社", 0.91),
        ("than", "倘或有一反原爲薄則地獄之設正爲彼人是語也天地鬼神鑒臨之中外臣民關感之情因立碑永傳萬代云銘曰", 0.86),
        ("than", "天開南越地闢北京縣名東岸社號扶寧", 0.94),
        ("than", "氣鍾山岳人稟精英挺生貴將出佐聖明", 0.95),
        ("than", "顯洪門戶奉侍宮庭盡忠家國仰荷朝廷", 0.93),
        ("than", "司禮鑿掌郡爵品榮世所稱重時不添名", 0.92),
        ("than", "銀田厚意鄉社敬情事爲后佛禮洪先誠", 0.93),
        ("than", "億年奉事萬世香馨碑立銓石後謁施聲", 0.91),
        ("than", "共敷全社不忘此銘上村陳得綿○○○", 0.88),
    ]

    boxes = []
    for idx, (reg, txt, sc) in enumerate(cols_bia02, start=1):
        boxes.append({
            "order": idx,
            "region": reg,
            "points": [[80 + idx * 45, 120], [120 + idx * 45, 120], [120 + idx * 45, 950], [80 + idx * 45, 950]],
            "text_ocr": txt,
            "score": sc,
            "source": "auto"
        })

    fio.write_json(BBOX_DIR / "BIA02_realistic.json", {
        "schema_version": 1,
        "bia_id": "BIA02_realistic",
        "boxes": boxes
    })


if __name__ == "__main__":
    generate_bia01_testbeds()
    generate_bia02_testbeds()
    print("TESTBED GENERATION COMPLETE: 4 testbeds generated in tests/testbed/bbox_simulated/")
