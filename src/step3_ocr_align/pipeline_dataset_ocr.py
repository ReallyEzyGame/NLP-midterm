"""Pipeline bước 3 (Dataset 1) trên toàn bộ dữ liệu thật: OCR thô → gióng v3 → gộp nguồn theo mặt → MASK → xử lý needs_review.

Đầu vào : data/interim/paddle_raw/<nguồn>/<bia_id>_res.json (mỗi nguồn OCR một thư mục, xem step2_stele_ocr/ocr_bia.py),
          data/processed/Chu_Han/*.txt (có token MASK), data/raw/anh_bia/*.jpg
Đầu ra  : data/processed/bbox_chuan/<bia_id>.json, data/processed/align/<bia_id>.json,
          data/processed/needs_review.csv (CHỈ box còn needs_review — luật A9 của validator; mỗi box có `ly_do` + gợi ý),
          reports/dataset_ocr_<yyyymmdd>/{nguon_ocr_tung_mat.csv, mask_khong_chep.csv, xu_ly_needs_review.csv, metrics.csv}
Rồi:      python -m src.step3_ocr_align.export_ocr_dataset && python -m src.utils.validate --stage bbox align dataset_ocr

Các bước (đo trên 76 mặt — test_debug/result/result.md; mọi ngưỡng đã kiểm bằng mắt trên mẫu):
  1. Mỗi nguồn OCR: paddle_adapter (lọc rác + sort thứ tự đọc) → AlignerV3 (config `aligner.algo: v3`).
  2. Gộp theo mặt: mỗi mặt lấy nguồn có nhiều chữ Hán có nhãn `ok` nhất (cùng aligner/ngưỡng → không nới độ chính xác);
     hoà → nguồn đứng trước trong danh sách (`raw_2560` = cấu hình gốc đứng đầu).
  3. MASK cho phần sách không chép (giảng viên 14/11/2026): dãy box chưa khớp kẹp giữa 2 neo mà khe sách không còn chữ
     nào chưa có box nhận, và OCR không giống đoạn sách quanh đó.
  4. Xử lý needs_review: gióng cục bộ kẹp 2 neo; MASK khi OCR tự tin mà không giống chỗ nào trong sách; box 1–2 chữ theo
     ngữ cảnh; còn lại phân loại `ly_do` để người sửa.

    python -m src.step3_ocr_align.pipeline_dataset_ocr
    python -m src.step3_ocr_align.pipeline_dataset_ocr --nguon paddle_raw_2560 paddle_inv_clahe_tile
"""
from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from PIL import Image
from rapidfuzz.distance import Indel, Levenshtein

from src.step3_ocr_align.aligner_v3 import MASK, PH
from src.step3_ocr_align.paddle_adapter import convert_paddle_raw_to_bbox_chuan
from src.step3_ocr_align.text_aligner import (
    clean_gt_text,
    find_gt_file_for_bia,
    get_aligner,
    normalize_han_str,
    semi_global_align,
)
from src.utils import file_io as fio

ROOT = Path(__file__).resolve().parents[2]
HAN = re.compile(r"[㐀-鿿\U00020000-\U0002EBEF]")
# thứ tự ưu tiên khi hoà (giữ đúng kết quả đã kiểm ở test_debug); nguồn khác xếp sau theo tên
NGUON_UU_TIEN = ["paddle_raw_2560", "rapid_inv_clahe_tile", "paddle_inv_clahe_tile", "paddle_inv_clahe_tile_3200",
                 "paddle_raw_tile", "paddle_raw_tile_3200"]

# --- MASK cho phần sách không chép (bước 3)
TOL = 3              # chữ sách "lệch mép" cho phép giữa 2 neo
EDGE = 0.04          # dải mép ảnh trái/phải bị loại (chữ ghi địa điểm rập, số hiệu thư viện)
IN_BOOK_SIM = 0.5    # OCR giống đoạn sách quanh neo ≥ mức này → là chữ sách (OCR sai), không MASK
NEAR = 40            # cửa sổ sách quanh 2 neo
ANCHOR_MIN = 4       # nhãn ≥ 4 chữ mới làm neo (nhãn ngắn như 生/阮公 khớp bừa chỗ khác)
# --- xử lý needs_review (bước 4)
SIM_LOCAL = 0.6
SIM_ACCEPT = 0.75    # gióng cục bộ: nhận làm nhãn ĐỀ XUẤT (box ≥ 3 chữ)
SIM_SURE = 0.8       # tự nhận ok (kiểm tay 21 nhãn: 2 sai đều < 0,8 — danh sách ruộng lặp mẫu 一所X處Y高)
LEN_RATIO = 0.85     # độ dài lát sách / OCR — chặn nhãn cụt (kiểm tay 30 mẫu ở ngưỡng 0,6: chỉ ~9 đúng)
SIM_WINDOW = 0.7
WINDOW = 60
SIM_NOT_IN_BOOK = 0.4  # < mốc p1 (0,61) của box ok đúng; kiểm tay 30/30 mẫu là chữ bia sách không chép
OCR_CONF_MIN = 0.5     # OCR phải đọc tự tin thì "không giống sách" mới là bằng chứng
MAX_SEG = 1500


# ============================================================================ tiện ích
def book_key(s: str) -> str:
    """Chuỗi Hán đã làm sạch + chuẩn hoá dị thể (token MASK bị bỏ) — để định vị/đo phủ."""
    return normalize_han_str(clean_gt_text(s))


def norm(s: str) -> str:
    """Như book_key nhưng giữ MASK thành 1 ký tự khuyết (vị trí khớp 1–1 với chuỗi sách có MASK)."""
    return normalize_han_str(clean_gt_text(s.replace(MASK, PH)))


def anchor_positions(labels: list[tuple[int, str]], g: str) -> dict[int, tuple[int, int]]:
    """Vị trí trong `g` của các nhãn ok theo thứ tự đọc: chỉ nhãn ≥ ANCHOR_MIN chữ và CHỈ tìm tiến (quay về đầu văn
    bản tạo 'neo đảo thứ tự' giả; nhãn ngắn khớp nhầm tạo 'đoạn sách trống' ảo — lỗi đã gặp khi debug)."""
    pos, p = {}, 0
    for k, t in labels:
        if len(t) < ANCHOR_MIN:
            continue
        s = g.find(t, p)
        if s >= 0:
            pos[k] = (s, s + len(t))
            p = s + len(t)
    return pos


def labeled_chars(items: list[dict]) -> int:
    """Số chữ Hán có nhãn ok (không tính token MASK) — tiêu chí chọn nguồn OCR cho mỗi mặt."""
    return sum(len(book_key(i["text_gt"])) for i in items if i["status"] == "ok")


def candidate(it: dict, box: dict, width: int) -> bool:
    """Box thân chưa có nhãn, OCR ≥ 3 chữ Hán (≥ 70%), không sát mép ảnh → có thể là chữ bia sách không chép."""
    if it["status"] == "ok" or it["text_gt"] or box.get("region") == "tran":
        return False
    t = it["text_ocr"].replace(" ", "")
    nh = len(HAN.findall(t))
    if nh < 3 or nh < 0.7 * len(t):
        return False
    cx = sum(p[0] for p in box["points"]) / 4
    return EDGE * width < cx < (1 - EDGE) * width


def in_book(ocr: str, book_n: str) -> bool:
    o = book_key(ocr)
    if len(o) < 2:
        return False
    return semi_global_align(o, book_n)[1] >= IN_BOOK_SIM


def partition(ocrs: list[str], seg: str) -> list[tuple[int, int, float] | None]:
    """DP: gán mỗi box (theo thứ tự đọc) một lát liền nhau của seg hoặc bỏ; tối đa tổng sim·len."""
    n, m = len(ocrs), len(seg)
    NEG = -1e18
    best = [[NEG] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    for i in range(n + 1):
        row = best[i]
        for j in range(m + 1):
            v = row[j]
            if v == NEG:
                continue
            if j < m and v > best[i][j + 1]:                       # bỏ 1 chữ sách (bia không có/OCR sót)
                best[i][j + 1], back[i][j + 1] = v, ("skipc", i, j)
            if i == n:
                continue
            if v > best[i + 1][j]:                                 # bỏ box (không có trong đoạn này)
                best[i + 1][j], back[i + 1][j] = v, ("skipb", i, j)
            o = ocrs[i]
            lo_ = len(o)
            if lo_ == 0:
                continue
            slack = max(2, int(0.35 * lo_))
            for L in range(max(1, lo_ - slack), min(m - j, lo_ + slack) + 1):
                sl = seg[j : j + L]
                sim = Indel.normalized_similarity(o, sl)
                if not ((sim >= SIM_LOCAL and lo_ >= 3) or (lo_ <= 2 and o == sl)):
                    continue
                w = v + sim * lo_
                if w > best[i + 1][j + L]:
                    best[i + 1][j + L], back[i + 1][j + L] = w, ("take", i, j, sim)
    out: list = [None] * n
    i, j = n, max(range(m + 1), key=lambda x: best[n][x])
    while (i, j) != (0, 0):
        b = back[i][j]
        if b[0] == "take":
            out[b[1]] = (b[2], j, b[3])
        i, j = b[1], b[2]
    return out


# ============================================================================ các bước
def align_source(raw_dir: Path, faces: list[str], aligner, img_dir: Path, chu_han: Path) -> dict[str, tuple[dict, list]]:
    out = {}
    for bid in faces:
        rf = raw_dir / f"{bid}_res.json"
        if not rf.exists():
            continue
        payload, _ = convert_paddle_raw_to_bbox_chuan(rf, bid, img_dir / f"{bid}.jpg")
        g = find_gt_file_for_bia(bid, chu_han)
        gt = g.read_text(encoding="utf-8") if g else ""
        out[bid] = (payload, [it.to_contract_dict() for it in aligner.align(bid, payload["boxes"], gt).items])
    return out


def fuse(per_src: dict[str, dict], order: list[str]) -> tuple[dict[str, tuple[dict, list]], list[list]]:
    chosen, log = {}, []
    for bid in sorted({b for d in per_src.values() for b in d}):
        best = None
        for s in order:
            if bid in per_src[s]:
                m3 = labeled_chars(per_src[s][bid][1])
                if best is None or m3 > best[0]:
                    best = (m3, s)
        chosen[bid] = per_src[best[1]][bid]
        log.append([bid, best[1], best[0]])
    return chosen, log


def group_docs(faces: list[str], chu_han: Path) -> dict[str, list[str]]:
    docs: dict[str, list[str]] = defaultdict(list)
    for bid in faces:
        g = find_gt_file_for_bia(bid, chu_han)
        docs[g.name if g else f"__{bid}"].append(bid)
    return docs


def mask_unmatched(data: dict, docs: dict, chu_han: Path, widths: dict) -> list[list]:
    """Bước 3: box sách không chép → MASK (sửa tại chỗ trong `data`). Trả log từng dãy."""
    log = []
    for doc, faces in docs.items():
        if doc.startswith("__"):
            continue
        book = book_key((chu_han / doc).read_text(encoding="utf-8"))
        if not book:
            continue                                   # bia không có Hán trong sách (bia 52): không đoán
        bb = {bid: {b["order"]: b for b in data[bid][0]["boxes"]} for bid in faces}
        seq = [(bid, it, bb[bid][it["order"]], widths[bid]) for bid in faces
               for it in sorted(data[bid][1], key=lambda x: x["order"])]
        lab = {k: book_key(it["text_gt"]) for k, (_, it, _, _) in enumerate(seq) if it["status"] == "ok" and it["text_gt"]}
        pos = anchor_positions(sorted(lab.items()), book)
        anchors = sorted(pos)
        k = 0
        while k < len(seq):
            if k in pos or seq[k][1]["status"] == "ok":
                k += 1
                continue
            j = k
            while j < len(seq) and j not in pos and seq[j][1]["status"] != "ok":
                j += 1
            prev = max((x for x in anchors if x < k), default=None)
            nxt = min((x for x in anchors if x >= j), default=None)
            lo = pos[prev][1] if prev is not None else 0
            hi = pos[nxt][0] if nxt is not None else len(book)
            a0 = prev if prev is not None else -1
            b0 = nxt if nxt is not None else len(seq)
            # chữ sách chưa box nào nhận giữa 2 neo (trừ chữ của box ok ngắn không làm neo); < 0: neo đảo thứ tự
            free = hi - lo - sum(len(lab.get(x, "")) for x in range(a0 + 1, b0) if x not in pos)
            near = book[max(0, min(lo, hi) - NEAR) : max(lo, hi) + NEAR]
            cands = [x for x in range(k, j) if candidate(seq[x][1], seq[x][2], seq[x][3])
                     and not in_book(seq[x][1]["text_ocr"], near)]
            hit = bool(cands) and 0 <= free <= TOL
            if hit:
                sc = min([seq[x][1]["score"] for x in (prev, nxt) if x is not None] or [0.8])
                for x in cands:
                    it = seq[x][1]
                    it.update(text_gt=MASK, status="ok", score=round(max(0.8, sc), 4),
                              note=(it.get("note", "") + " | V3_MASK_SACH_KHONG_CHEP").strip(" |"))
            log.append([doc, seq[k][0], seq[k][1]["order"], j - k, len(cands), free,
                        "MASK" if hit else "giu_needs_review"])
            k = j
    return log


def resolve_review(data: dict, docs: dict, chu_han: Path, widths: dict) -> list[list]:
    """Bước 4: quyết định từng box needs_review theo bằng chứng (sửa tại chỗ). Trả [bia_id, order, ocr, gt, score,
    mã quyết định, gợi ý, đã xử lý] cho MỌI box đã xét."""
    rows = []
    for doc, faces in docs.items():
        raw = (chu_han / doc).read_text(encoding="utf-8") if not doc.startswith("__") else ""
        g_orig = "".join(clean_gt_text(x) for x in raw.replace(MASK, PH).splitlines())
        g = normalize_han_str(g_orig)
        boxes = {bid: {b["order"]: b for b in data[bid][0]["boxes"]} for bid in faces}
        seq = [(bid, it) for bid in faces for it in sorted(data[bid][1], key=lambda x: x["order"])]
        decided: dict[int, str] = {}
        hint: dict[int, str] = {}
        if g:
            pos = anchor_positions([(k, norm(it["text_gt"])) for k, (_, it) in enumerate(seq)
                                    if it["status"] == "ok" and it["text_gt"] != MASK], g)
            anchors = sorted(pos)
            k = 0
            while k < len(seq):
                if seq[k][1]["status"] == "ok":
                    k += 1
                    continue
                j = k
                while j < len(seq) and seq[j][1]["status"] != "ok":
                    j += 1
                run = list(range(k, j))
                prev = max((x for x in anchors if x < k), default=None)
                nxt = min((x for x in anchors if x >= j), default=None)
                lo = pos[prev][1] if prev is not None else 0
                hi = pos[nxt][0] if nxt is not None else len(g)
                ocrs = [norm(seq[x][1]["text_ocr"]) for x in run]
                if 0 < hi - lo <= MAX_SEG:
                    # 4a. gióng cục bộ kẹp 2 neo
                    for x, r, o in zip(run, partition(ocrs, g[lo:hi]), ocrs):
                        if r and not (len(o) <= 2 or (r[2] >= SIM_ACCEPT and
                                                      min(len(o), r[1] - r[0]) / max(len(o), r[1] - r[0]) >= LEN_RATIO)):
                            r = None
                        if r:
                            s, e, sim = r
                            sure = len(o) <= 2 or sim >= SIM_SURE
                            seq[x][1].update(text_gt=g_orig[lo + s : lo + e].replace(PH, MASK),
                                             status="ok" if sure else "needs_review", score=round(sim, 4),
                                             note=f"RV_GIONG_CUC_BO (sim={sim:.2f}, kẹp giữa 2 neo)")
                            decided[x] = "GIONG_CUC_BO" if sure else "SUA_TAY_XAC_NHAN_NHAN_DE_XUAT"
                elif hi < lo:
                    # 4b. neo đảo thứ tự → tìm trong cửa sổ, đòi hỏi không mơ hồ
                    a_, b_ = max(0, hi - WINDOW), min(len(g), lo + WINDOW)
                    for x, o in zip(run, ocrs):
                        if len(o) < 4:
                            continue
                        _, sim, ms, me = semi_global_align(o, g[a_:b_])
                        if sim < SIM_WINDOW or me <= ms:
                            continue
                        rest = g[a_:b_][:ms] + "　" * (me - ms) + g[a_:b_][me:]
                        sim2 = semi_global_align(o, rest)[1]
                        if sim - sim2 < 0.2:
                            continue
                        seq[x][1].update(text_gt=g_orig[a_ + ms : a_ + me].replace(PH, MASK), status="ok",
                                         score=round(sim, 4), note=f"RV_CUA_SO_NEO_DAO (sim={sim:.2f}, nhì={sim2:.2f})")
                        decided[x] = "CUA_SO_NEO_DAO"
                free = hi - lo
                for x in run:
                    if x in decided:
                        continue
                    o = ocrs[run.index(x)]
                    bid_x, it_x = seq[x]
                    box_x = boxes[bid_x][it_x["order"]]
                    if len(o) <= 2:
                        decided[x] = "BOX_NGAN"
                        continue
                    # 4c. OCR tự tin mà không giống chỗ nào trong cả văn bản sách → chữ bia sách không chép → MASK
                    m_, smax, _, _ = semi_global_align(o, g)
                    hint[x] = f"gợi ý sách gần nhất: {m_} ({smax:.2f})"
                    if (smax < SIM_NOT_IN_BOOK and float(box_x.get("score", 0)) >= OCR_CONF_MIN
                            and candidate(it_x, box_x, widths[bid_x])):
                        it_x.update(text_gt=MASK, status="ok", score=round(1 - smax, 4),
                                    note=f"RV_MASK_KHONG_GIONG_SACH (sim_max={smax:.2f})")
                        decided[x] = "MASK_KHONG_GIONG_SACH"
                    elif smax < SIM_NOT_IN_BOOK:
                        decided[x] = "SUA_TAY_KHONG_GIONG_SACH_NHUNG_OCR_KEM_HOAC_SAT_MEP"
                    elif free < 0:
                        decided[x] = "SUA_TAY_NEO_DAO_THU_TU"
                    elif free == 0:
                        decided[x] = "SUA_TAY_SACH_DA_HET_CHU_NHUNG_KHONG_DU_DIEU_KIEN_MASK"
                    else:
                        decided[x] = "SUA_TAY_CO_DOAN_SACH_NHUNG_OCR_QUA_SAI"
                k = j
            # 4d. box 1–2 chữ (kiểm tay: phần lớn là CHỮ THẬT ngắn — 碑, 計, 儒生 — không phải rác): 2 box dài kề bên
            # đều MASK → MASK; còn lại sửa tay
            longs = [x for x, (_, it) in enumerate(seq) if len(norm(it["text_ocr"])) >= 3]
            for x, code in list(decided.items()):
                if code != "BOX_NGAN":
                    continue
                it = seq[x][1]
                pv = max((y for y in longs if y < x), default=None)
                nx = min((y for y in longs if y > x), default=None)
                if not HAN.search(it["text_ocr"]):
                    decided[x] = "LOAI_KHONG_CO_CHU_HAN"
                elif pv is not None and nx is not None and all(
                        seq[y][1]["status"] == "ok" and seq[y][1]["text_gt"] == MASK for y in (pv, nx)):
                    it.update(text_gt=MASK, status="ok", score=0.8, note="RV_MASK_BOX_NGAN_GIUA_VUNG_MASK")
                    decided[x] = "MASK_BOX_NGAN_GIUA_VUNG_MASK"
                else:
                    decided[x] = "SUA_TAY_BOX_NGAN_1_2_CHU"
        for x, (bid, it) in enumerate(seq):
            if it["status"] == "ok" and x not in decided:
                continue
            code = decided.get(x, "SUA_TAY_BIA_KHONG_CO_HAN_TRONG_SACH" if not g else "SUA_TAY_KHAC")
            rows.append([bid, it["order"], it["text_ocr"], it["text_gt"], f"{it['score']:.4f}", code,
                         hint.get(x, "") if code.startswith("SUA_TAY") else "",
                         int(it["status"] == "ok" or code.startswith("LOAI_"))])
    return rows


def metrics(data: dict, chu_han: Path) -> dict:
    """M1 tỉ lệ ok, M2 phủ văn bản sách bằng box ok, M3 số chữ Hán có nhãn, M5 CER trung vị, số box nhãn chỉ MASK."""
    doc_len, doc_cov = {}, {}
    total = ok = chars = masked = 0
    cers = []
    for bid, (_, items) in data.items():
        f = find_gt_file_for_bia(bid, chu_han)
        book = book_key(f.read_text(encoding="utf-8")) if f else ""
        if not book:
            continue
        doc_len[f.name] = len(book)
        cov = doc_cov.setdefault(f.name, set())
        p = 0
        for it in items:
            total += 1
            if it["status"] != "ok" or not it["text_gt"]:
                continue
            ok += 1
            gk = book_key(it["text_gt"])
            if not gk:
                masked += 1
                continue
            chars += len(gk)
            cers.append(Levenshtein.normalized_distance(book_key(it["text_ocr"]), gk))
            s = book.find(gk, p)
            s = book.find(gk) if s < 0 else s
            if s >= 0:
                cov.update(range(s, s + len(gk)))
                p = s + len(gk)
    bt = sum(doc_len.values())
    return {"box": total, "ok": ok, "M1_ok_rate": round(ok / total, 4) if total else 0.0,
            "M2_phu_sach": round(sum(len(v) for v in doc_cov.values()) / bt, 4) if bt else 0.0,
            "M3_chu_co_nhan": chars, "M5_cer_trung_vi": round(statistics.median(cers), 4) if cers else None,
            "ok_chi_MASK": masked}


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--nguon", nargs="*", help="thư mục con của data/interim/paddle_raw (mặc định: tất cả, theo thứ tự ưu tiên)")
    a = ap.parse_args(argv)
    raw = a.root / "data" / "interim" / "paddle_raw"
    img_dir = a.root / "data" / "raw" / "anh_bia"
    chu_han = a.root / "data" / "processed" / "Chu_Han"
    proc = a.root / "data" / "processed"
    rep = a.root / "reports" / f"dataset_ocr_{date.today():%Y%m%d}"
    have = sorted(d.name for d in raw.iterdir() if d.is_dir() and any(d.glob("*_res.json"))) if raw.exists() else []
    order = a.nguon or [s for s in NGUON_UU_TIEN if s in have] + [s for s in have if s not in NGUON_UU_TIEN]
    if not order:
        print(f"Không có nguồn OCR trong {raw}/<nguồn>/ — chạy step2_stele_ocr/ocr_bia.py trước.")
        return 1
    faces = sorted(p.stem for p in img_dir.glob("*.jpg"))
    widths = {b: Image.open(img_dir / f"{b}.jpg").size[0] for b in faces}
    aligner = get_aligner(root=a.root)
    print(f"Aligner: {type(aligner).__name__} | {len(faces)} mặt | nguồn: {order}", flush=True)

    per_src, mrows = {}, []
    for s in order:
        per_src[s] = align_source(raw / s, faces, aligner, img_dir, chu_han)
        m = metrics(per_src[s], chu_han)
        mrows.append([s, *m.values()])
        print(f"  {s}: {m}", flush=True)
    data, src_log = fuse(per_src, order)
    docs = group_docs(sorted(data), chu_han)
    mrows.append(["gop_theo_mat", *metrics(data, chu_han).values()])
    mlog = mask_unmatched(data, docs, chu_han, widths)
    mrows.append(["+ MASK sach khong chep", *metrics(data, chu_han).values()])
    rv = resolve_review(data, docs, chu_han, widths)
    final = metrics(data, chu_han)
    mrows.append(["+ xu ly needs_review (cuoi)", *final.values()])

    for bid, (payload, items) in data.items():
        fio.write_json(proc / "bbox_chuan" / f"{bid}.json", payload)
        fio.write_json(proc / "align" / f"{bid}.json", {"schema_version": 1, "bia_id": bid, "items": items})
    # needs_review.csv: CHỈ box còn needs_review (validator A9: số dòng = số box needs_review)
    nr = [[r[0], r[1], r[2], r[3], r[4], r[5] + (f" | {r[6]}" if r[6] else ""), "", r[7]]
          for r in rv if any(it["order"] == r[1] and it["status"] == "needs_review" for it in data[r[0]][1])]
    write_csv(proc / "needs_review.csv", ["bia_id", "order", "text_ocr", "text_gt", "score", "ly_do", "nguoi_sua", "da_sua"], nr)
    write_csv(rep / "nguon_ocr_tung_mat.csv", ["bia_id", "nguon", "chu_co_nhan"], src_log)
    write_csv(rep / "mask_khong_chep.csv",
              ["van_ban", "mat_bat_dau", "order_bat_dau", "so_box_day", "so_ung_vien", "chu_sach_chua_nhan", "ket_qua"], mlog)
    write_csv(rep / "xu_ly_needs_review.csv",
              ["bia_id", "order", "text_ocr", "text_gt", "score", "quyet_dinh", "goi_y", "da_xu_ly"], rv)
    write_csv(rep / "metrics.csv", ["buoc", *final.keys()], mrows)
    stat = defaultdict(int)
    for r in rv:
        stat[r[5]] += 1
    print("Xử lý needs_review:", dict(sorted(stat.items(), key=lambda t: -t[1])))
    print(f"KẾT QUẢ: {final} | needs_review.csv: {len(nr)} dòng | báo cáo: {rep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
