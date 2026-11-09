"""Gộp OCR thô các trang thành ``text_tho`` rồi tách 3 loại Hán / Phiên âm / Dịch nghĩa — bước 1.A (§3–§4).

Đầu vào : ``data/interim/sach_ocr/gemini/<model>/p<NNN>.txt`` (do ``ocr_gemini.py`` sinh) + ``muc_luc_sach.csv``.
Đầu ra  :
  data/interim/text_tho/<bia_id>.txt                      OCR thô có dấu vết trang (``#BIA`` / ``##PAGE``), KHÔNG sửa tay
  data/interim/van_ban_nhap/{Chu_Han,Phien_am,Dich_nghia}/<bia_id>.txt
                                                          BẢN NHÁP sau làm sạch — CHƯA rà soát, chưa phải ``data/processed``
  data/interim/van_ban_nhap/_log/<bia_id>.log.txt         dòng đã loại / cảnh báo / số đếm, phục vụ rà soát bằng mắt

Máy trạng thái trên luồng dòng của các trang nối nhau (cấu trúc đã kiểm chứng ở 0.A):
    (rác trước Hán) -> HÁN (tiêu đề ``N.<tên Hán>``) -> ``N. TÊN`` Việt -> thông tin (bỏ) ->
    ``Phiên âm:`` -> ``Dịch nghĩa:`` -> (gặp chữ Hán của bia kế: dừng)

Ở script này ``bia_id`` = ``doc_id`` = ``VBLN-<STT 3 số>`` (khoá của ``inventory.csv``) = MỘT VĂN BẢN SÁCH.
Tên file thật của ảnh (``bia_id``, mỗi mặt một id) nằm ở ``data/metadata/stt_bia_map.csv`` (``build_stt_bia_map.py``).
Bản nháp/``text_tho`` ở đây theo văn bản sách; ``pipeline_1a.py`` ghi sang ``data/processed`` với tên = các ``bia_id``
nối ``_`` (giảng viên 09/11: không tách theo mặt) — xem README mục 1b.

Chạy (từ thư mục NLP-midterm, đã bật .venv; KHÔNG gọi API):
    python -m src.step1_book_mining.clean_book_text --bia 25,27,22
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from . import regex_filter as rf

ROOT = Path(__file__).resolve().parents[2]
MUC_LUC = ROOT / "data/interim/text_tho/muc_luc_sach.csv"
OCR_ROOT = ROOT / "data/interim/sach_ocr/gemini"
TEXT_THO = ROOT / "data/interim/text_tho"
NHAP = ROOT / "data/interim/van_ban_nhap"
DEFAULT_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODELS = ("gemini-3.5-flash",)       # trùng ocr_gemini.FALLBACK_MODELS


def bia_id_of(stt: int) -> str:
    return f"VBLN-{stt:03d}"


def page_range(row: dict) -> tuple[int, int]:
    first = int(row["tr_han_bat_dau"] or row["tr_tieu_de_viet"])
    return first, int(row["tr_ket_thuc"])


MAX_THEM = 2      # mở rộng tối đa bấy nhiêu trang sau tr_ket_thuc để gặp điểm bắt đầu của bia kế


def page_end(stt: int, rows: dict[int, dict]) -> tuple[int, bool]:
    """(sửa 3) Trang cuối cần đọc cho bia ``stt`` và có kỳ vọng gặp điểm kết thúc không.

    ``tr_ket_thuc`` trong mục lục chỉ gần đúng ⇒ đọc tới trang BẮT ĐẦU của bia kế (tối đa +MAX_THEM trang), để máy trạng
    thái thấy Hán / tiêu đề của bia kế mà dừng; nếu không thấy thì báo "có thể thiếu đoạn cuối" thay vì cắt cụt im lặng.
    Bia cuối cùng (không có bia kế) giữ ``tr_ket_thuc`` và không kỳ vọng điểm kết thúc."""
    end = int(rows[stt]["tr_ket_thuc"])
    nxt = [s for s in sorted(rows) if s > stt]
    if not nxt:
        return end, False
    r = rows[nxt[0]]
    start = r.get("tr_han_bat_dau") or r.get("tr_tieu_de_viet")
    if not start:
        return end, False
    return min(max(end, int(start)), end + MAX_THEM), True


def write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert all(l and l == l.strip() for l in lines), f"dòng trống/khoảng trắng thừa trong {path.name}"
    # loại văn bản sách không có (vd bia không có Hán / không có Phiên âm) ⇒ file RỖNG hoàn toàn (0 byte)
    path.write_text(("\n".join(rf.nfc(l) for l in lines) + "\n") if lines else "", encoding="utf-8", newline="\n")


def process(stt: int, row: dict, model: str, end: tuple[int, bool] | None = None) -> dict:
    """Trả về số đếm + ``loi`` (chuỗi rỗng nếu ổn; khác rỗng ⇒ KHÔNG dùng kết quả) + ``canh_bao`` (danh sách)."""
    bid = bia_id_of(stt)
    a, b = page_range(row)
    b_goc = b                                   # trang cuối theo mục lục; các trang sau đó chỉ để tìm điểm dừng
    expect_end = False
    if end is not None:
        b, expect_end = end
    pages = list(range(a, b + 1))
    log: list[str] = []
    body_pages: set[int] = set()              # trang có đóng góp ít nhất một dòng Phiên âm/Dịch nghĩa
    loi = ""
    canh_bao: list[str] = []

    # ---- 1. text_tho: ghép OCR thô theo trang
    raw: dict[int, str] = {}
    for p in pages:
        f = OCR_ROOT / model / f"p{p:03d}.txt"
        if not f.exists():                           # model chính không đọc nổi trang này ⇒ dùng bản của model dự phòng
            f = next((g for m in FALLBACK_MODELS if (g := OCR_ROOT / m / f"p{p:03d}.txt").exists()), f)
            if f.exists():
                canh_bao.append(f"tr.{p} lấy từ {f.parent.name} (model chính không đọc nổi)")
                log.append("[CẢNH BÁO] " + canh_bao[-1])
        if not f.exists():
            sys.exit(f"Thiếu OCR trang {p} ({f}). Chạy ocr_gemini trước.")
        raw[p] = rf.nfc(f.read_text(encoding="utf-8")).replace("\r\n", "\n")
    tho = [f"#BIA {bid} STT={stt} trang={a}-{b}"]
    for p in pages:
        tho += [f"##PAGE {p}", raw[p].rstrip("\n")]
    TEXT_THO.mkdir(parents=True, exist_ok=True)
    (TEXT_THO / f"{bid}.txt").write_text("\n".join(tho) + "\n", encoding="utf-8", newline="\n")

    # ---- 2. máy trạng thái trên luồng dòng
    state = "pre"
    han_raw: list[str] = []
    phien: list[str] = []
    dich: list[str] = []
    for p in pages:
        skip_rest = False                  # đã gặp chú thích cuối trang ⇒ bỏ phần còn lại của trang này
        n_before = len(phien) + len(dich)     # để biết trang này có đóng góp dòng văn bản nào không
        for ln in raw[p].split("\n"):
            s = ln.strip()
            tag = f"tr.{p}"
            if skip_rest and state in ("phien", "dich"):
                if s:
                    log.append(f"[chú thích cuối trang, bỏ] {tag}: {s[:60]}")
                continue
            if state == "pre":
                if rf.is_viet_header(s, stt):               # bia KHÔNG có chữ Hán trong sách: vào thẳng tiêu đề Việt
                    log.append(f"[tiêu đề Việt, bỏ — bia không có chữ Hán] {tag}: {s}")
                    state = "info"
                    continue
                if rf.has_han(s):
                    state = "han"
                else:
                    if s:
                        log.append(f"[bỏ, trước khối Hán] {tag}: {s}")
                    continue
            if state == "han":
                if rf.is_viet_header(s, stt):
                    log.append(f"[tiêu đề Việt, bỏ] {tag}: {s}")
                    state = "info"
                elif rf.has_han(s):
                    han_raw.append(s)
                elif not s:
                    han_raw.append("")
                elif rf.is_page_number(s):
                    log.append(f"[số trang, bỏ] {tag}: {s}")
                else:
                    log.append(f"[CẢNH BÁO dòng không phải Hán trong khối Hán, bỏ] {tag}: {s}")
                continue
            if state == "info":
                m1, m2 = rf.LABEL_PHIEN_AM.match(s), rf.LABEL_DICH_NGHIA.match(s)
                if m1:
                    state = "phien"
                    if m1.group(1).strip():
                        phien += [m1.group(1).strip(), ""]
                elif m2:
                    state = "dich"
                    if m2.group(1).strip():
                        dich += [m2.group(1).strip(), ""]
                elif s:
                    log.append(f"[thông tin hành chính, bỏ] {tag}: {s}")
                continue
            if state in ("phien", "dich"):
                if state == "phien" and (m := rf.LABEL_DICH_NGHIA.match(s)):
                    state = "dich"
                    if m.group(1).strip():
                        dich += [m.group(1).strip(), ""]
                    continue
                if rf.has_han(s):
                    state = "end"
                    log.append(f"[gặp chữ Hán bia kế → dừng] {tag}: {s[:30]}…")
                    continue
                if rf.is_section_heading(s) or rf.is_later_viet_header(s, stt):
                    # (sửa 1) đoạn giới thiệu di tích / tiêu đề bia kế không có Hán ⇒ hết văn bản của bia này
                    state = "end"
                    log.append(f"[gặp tiêu đề di tích / bia kế → dừng] {tag}: {s}")
                    continue
                if rf.is_page_number(s):
                    log.append(f"[số trang, bỏ] {tag}: {s}")
                    continue
                if p > b_goc and rf.is_caption(s):     # trang đọc thêm chỉ có chú thích ảnh (vd tr.199 trước bia 21)
                    log.append(f"[chú thích ảnh ở trang đọc thêm, bỏ] {tag}: {s}")
                    continue
                if rf.is_footnote(s):
                    log.append(f"[chú thích, bỏ] {tag}: {s}")
                    skip_rest = True
                    continue
                (phien if state == "phien" else dich).append(s)
                if s:                                  # dòng trống chỉ là ranh giới đoạn, không phải văn bản
                    body_pages.add(p)
                continue
            # state == "end": bỏ phần còn lại (bia kế)

    if state in ("pre", "han"):
        log.append("[LỖI] không thấy tiêu đề Việt — kiểm tra thủ công")
    # trang đọc thêm cuối cùng không đóng góp dòng nào (vd chỉ có chú thích ảnh) ⇒ không thể giấu văn bản bị thiếu
    if expect_end and state in ("phien", "dich") and not (b > b_goc and b not in body_pages):
        canh_bao.append(f"đọc hết tr.{b} chưa gặp điểm kết thúc (Hán/tiêu đề bia kế) — có thể thiếu đoạn cuối")
        log.append("[CẢNH BÁO] " + canh_bao[-1])
    # (sửa 3) số trong tiêu đề Hán ("N.<tên Hán>") phải bằng STT — sai ⇒ đã lấy nhầm khối Hán của bia khác
    first_han = next((x for x in han_raw if x), "")
    m_no = re.match(r"^\s*(\d+)", first_han)
    if first_han and m_no and int(m_no.group(1)) != stt:
        loi = f"tiêu đề Hán mang số {m_no.group(1)} ≠ STT {stt} (lấy nhầm bia)"
        log.append("[LỖI] " + loi)
    elif first_han and not m_no:
        canh_bao.append("không đọc được số ở tiêu đề Hán để đối chiếu STT")
        log.append("[CẢNH BÁO] " + canh_bao[-1])
    if not phien:
        log.append("[CẢNH BÁO] không có mục Phiên âm")
    if not dich:
        log.append("[CẢNH BÁO] không có mục Dịch nghĩa")

    # ---- 3. làm sạch từng loại
    # Hán: dòng đầu tiên = tiêu đề (bỏ số thứ tự)
    first = next((i for i, x in enumerate(han_raw) if x), None)
    han_out: list[str] = []
    removed_all: list[str] = []
    if first is not None:
        title, rem = rf.clean_han(rf.strip_han_title_number(han_raw[first]))
        removed_all += rem
        if title:
            han_out.append(title)
        body = []
        for x in han_raw[first + 1:]:
            body.append(x)
        # dọn từng dòng trước khi gộp đoạn (giữ dòng trống làm ranh giới)
        cleaned = []
        for x in body:
            c, rem = rf.clean_han(x)
            removed_all += rem
            cleaned.append(c)
        for para in rf.han_paragraphs(cleaned):
            han_out += rf.split_han(para)
    if removed_all:
        from collections import Counter
        log.append("[Hán: ký tự/chuỗi đã loại] " + ", ".join(f"{k!r}×{v}" for k, v in Counter(removed_all).items()))

    vlog: list[str] = []
    phien_out = rf.viet_items(phien, vlog)
    dich_out = rf.viet_items(dich, vlog)
    if vlog:
        from collections import Counter
        log.append("[Việt: chuẩn hoá chung] " + ", ".join(f"{k}×{v}" for k, v in Counter(vlog).items()))

    write_lines(NHAP / "Chu_Han" / f"{bid}.txt", han_out)
    write_lines(NHAP / "Phien_am" / f"{bid}.txt", phien_out)
    write_lines(NHAP / "Dich_nghia" / f"{bid}.txt", dich_out)

    n_han = sum(1 for ch in "".join(han_out) if rf.HAN.match(ch))
    n_syl = sum(len(x.split()) for x in phien_out)
    stats = {"bia_id": bid, "stt": stt, "trang": f"{a}-{b}", "dong_han": len(han_out), "chu_han": n_han,
             "dong_phien_am": len(phien_out), "am_tiet_phien_am": n_syl, "dong_dich_nghia": len(dich_out),
             "loi": loi, "canh_bao": canh_bao}
    head = [f"# {bid} (STT {stt}) trang {a}-{b} — mô hình OCR {model}", "# " + "  ".join(f"{k}={v}" for k, v in stats.items())]
    if n_han and n_syl:
        head.append(f"# tỉ lệ âm tiết phiên âm / chữ Hán (1A.3.10) = {n_syl / n_han:.2f}  (kỳ vọng ≈ 1; lệch nhiều ⇒ thiếu/thừa đoạn)")
    out = NHAP / "_log" / f"{bid}.log.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(head + log) + "\n", encoding="utf-8", newline="\n")
    return stats


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bia", required=True, help="danh sách STT, vd 25,27,22")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args()
    rows = {int(r["stt"]): r for r in csv.DictReader(open(MUC_LUC, encoding="utf-8", newline=""))}
    for s in (int(x) for x in a.bia.split(",")):
        st = process(s, rows[s], a.model, page_end(s, rows))
        print("  ".join(f"{k}={v}" for k, v in st.items()))
    print(f"-> {NHAP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
