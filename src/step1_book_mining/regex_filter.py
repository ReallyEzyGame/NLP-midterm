"""Quy tắc làm sạch văn bản sách (CHECKLIST_1A §4.2–4.3) — hàm thuần, không đọc/ghi file.

Được ``clean_book_text.py`` gọi. Mọi quy ước còn chờ nhóm chốt (Q1–Q13) được gom thành hằng số ở đầu file
để đổi một chỗ:
  * ``ORNAMENT``  — ký hiệu trang trí ``○`` và chuỗi ``。。`` (Q3: đề xuất bỏ);
  * ``HAN_PUNCT`` — dấu câu của sách được giữ trong ``Chu_Han``;
  * ``HAN_CUT``   — dấu mà sau đó cắt dòng ``Chu_Han``.
"""
from __future__ import annotations

import re
import statistics
import unicodedata

import regex

HAN = regex.compile(r"\p{Han}")
HAN_PUNCT = "。，、；：？！"
HAN_CUT = "。！？；"
ORNAMENT = re.compile(r"[○◯]+|。{2,}")          # Q3 (đề xuất): bỏ
BULLET = re.compile(r"^[-–—•]\s+")
LABEL_PHIEN_AM = re.compile(r"(?i)^\s*phiên\s*âm\s*:\s*(.*)$")
LABEL_DICH_NGHIA = re.compile(r"(?i)^\s*dịch\s*nghĩa\s*:\s*(.*)$")
SUPERSCRIPT = "¹²³⁴⁵⁶⁷⁸⁹⁰"
# Dòng ĐẦU của chú thích cuối trang: chỉ số trên (¹ ²…), số + chữ HOA (``1 Chính giác:``, ``3 Phạm Kính Trai tức…``),
# "xem (thêm) chú thích", ``(*)`` / ``* ``. Số + chữ thường (``1 sào ở xứ…``) là nội dung, KHÔNG phải chú thích.
FOOTNOTE = re.compile(rf"(?i)xem\s+(?:thêm\s+)?chú\s+thích|^\s*chú\s+thích\b|^\s*\(\*\)|^\s*\*\s|^\s*[{SUPERSCRIPT}]"
                      r"|^\s*\d{1,2}\s+(?-i:[A-ZÀ-Ỵ])|^\s*[_\-–—=]{5,}\s*$")        # dòng cuối: đường kẻ ngăn chú thích


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def has_han(line: str, n: int = 1) -> bool:
    return len(HAN.findall(line)) >= n


def is_page_number(line: str) -> bool:
    """Dòng chỉ gồm 1–3 chữ số (số trang còn sót lại)."""
    return bool(re.fullmatch(r"\d{1,3}", line.strip()))


def is_footnote(line: str) -> bool:
    return bool(FOOTNOTE.search(line))


CAPTION = re.compile(r"^(?:Bia|Hình|Ảnh|Thác bản|Bản dập)(?: [^,.;:?!()\d]{1,50})?$")


def is_caption(line: str) -> bool:
    """Chú thích ảnh một dòng, không dấu câu/số (vd ``Bia chùa Khánh Ninh``). CHỈ áp dụng ở các trang đọc thêm sang bia kế,
    nơi không có văn bản của bia đang xét ngoài phần đuôi (xem ``clean_book_text``)."""
    s = line.strip()
    return bool(CAPTION.match(s)) and len(s.split()) <= 7


def is_viet_header(line: str, stt: int) -> bool:
    """Tiêu đề Việt của bia: ``25. KHÁNH NINH TỰ ...`` (số = STT, không chứa chữ Hán)."""
    return (not has_han(line)) and bool(re.match(rf"^\s*{stt}\s*[.．]\s*\S", line))


# ---------------------------------------------------------------- Chu_Han
def strip_han_title_number(line: str) -> str:
    """``22 后佛碑記`` / ``25. 慶寧寺后佛碑記`` -> bỏ số thứ tự đứng trước (quy ước: bỏ tiền tố ``N.``)."""
    return re.sub(r"^\s*\d+\s*[.．]?\s*", "", line)


# Dấu câu ASCII/nửa khổ do OCR trả ra → dấu toàn khổ của sách (chuẩn hoá chung, không đoán chữ)
HAN_PUNCT_MAP = str.maketrans({",": "，", ".": "。", ";": "；", ":": "：", "?": "？", "!": "！", "､": "、", "｡": "。"})


def clean_han(text: str) -> tuple[str, list[str]]:
    """Giữ chữ Hán + dấu câu của sách. Trả về (chuỗi sạch, danh sách ký tự/chuỗi đã loại).
    Chuẩn hoá chung: NFC (chữ Hán dạng tương thích U+F900–FAFF → dạng chuẩn), dấu câu nửa khổ → toàn khổ."""
    removed: list[str] = []

    def drop(m: re.Match) -> str:
        removed.append(m.group(0))
        return ""

    s = ORNAMENT.sub(drop, nfc(text).translate(HAN_PUNCT_MAP))
    s = re.sub(r"\s+", "", s)
    keep = []
    for ch in s:
        if HAN.match(ch) or ch in HAN_PUNCT:
            keep.append(ch)
        else:
            removed.append(ch)
    return "".join(keep), removed


def han_paragraphs(lines: list[str]) -> list[str]:
    """Gộp dòng Hán thành đoạn. Ranh giới đoạn: dòng trống, hoặc dòng NGẮN (< 0,6 × trung vị độ dài dòng)
    — dòng cuối đoạn trong sách thường chưa đầy khổ. Dòng '' = dòng trống do OCR giữ lại."""
    body = [len(re.sub(r"\s+", "", x)) for x in lines if x.strip()]
    med = statistics.median(body) if body else 0
    paras: list[str] = []
    cur: list[str] = []

    def flush() -> None:
        if cur:
            paras.append("".join(cur))
            cur.clear()

    for ln in lines:
        s = re.sub(r"\s+", "", ln)
        if not s:
            flush()
            continue
        cur.append(s)
        if len(s) < 0.6 * med:
            flush()
    flush()
    return paras


def split_han(paragraph: str) -> list[str]:
    """Cắt sau dấu câu thật của sách (``。！？；``); không tự thêm dấu."""
    out, cur = [], ""
    for ch in paragraph:
        cur += ch
        if ch in HAN_CUT:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------- Phien_am / Dich_nghia
SENT_END = re.compile(r"[.;:?!…)\]\"']\s*$")
LATER_VIET_HEADER = re.compile(r"^\s*(\d{1,3})\s*[.．]\s*(\S.*)$")


def is_section_heading(line: str) -> bool:
    """(sửa 1) Tiêu đề đoạn giới thiệu di tích giữa các bia (vd ``TỪ ĐƯỜNG HỌ NGUYỄN``, ``CHÙA ĐẠI BI``):
    toàn chữ IN HOA, không chữ số, không chữ Hán, 2–10 từ."""
    s = line.strip()
    words = s.split()
    return (2 <= len(words) <= 10 and len(s) <= 60 and any(c.isalpha() for c in s)
            and not any(c.islower() or c.isdigit() for c in s) and not has_han(s))


def is_later_viet_header(line: str, stt: int) -> bool:
    """Tiêu đề Việt của một bia SAU bia đang xét (``N. TÊN BIA`` in hoa, N > stt) — dùng làm điểm dừng."""
    m = LATER_VIET_HEADER.match(line)
    return bool(m) and int(m.group(1)) > stt and not any(c.islower() for c in m.group(2)) and not has_han(line)


INVISIBLE = re.compile("[​-‏­﻿⁠ 　\t]")
JUNK_V = re.compile(r"[|¦§¶•●■□◆◇※＊]")


def clean_viet(s: str, log: list[str] | None = None) -> str:
    """Chuẩn hoá chung một dòng tiếng Việt — chỉ sửa máy móc, không đoán chữ, giữ chính tả sách.
    Ghi tên quy tắc đã áp vào ``log`` (để thống kê)."""
    def sub(name: str, pat: str, rep: str, x: str) -> str:
        y = re.sub(pat, rep, x)
        if y != x and log is not None:
            log.append(name)
        return y

    s = nfc(s)
    s = sub("ký tự vô hình", INVISIBLE.pattern, " ", s)
    s = sub("ký tự rác", JUNK_V.pattern, "", s)
    s = sub("chỉ số trên (số chú thích)", f"[{SUPERSCRIPT}]+", "", s)
    s = sub("LaTeX chỉ số trên", r"\$\^\{?\d+\}?\$|\$\{?\^\{?\d+\}?\}?\$", "", s)
    s = sub("ký hiệu $ / ^ lẻ", r"[$^]", "", s)
    s = sub("định dạng markdown", r"\*+|`+|(?<!\w)_{1,2}(?=\S)|(?<=\S)_{1,2}(?!\w)", "", s)
    s = sub("chữ Hán lọt vào (in xuyên trang)", r"[㐀-鿿豈-﫿]+", "", s)
    s = sub("dấu ba chấm", "…", "...", s)
    s = sub("ngoặc kép cong", "[“”„‟]", '"', s)
    s = sub("nháy cong", "[‘’‚‛]", "'", s)
    s = sub("khoảng trắng trước dấu câu", r"\s+([,.;:?!)\]])", r"\1", s)
    s = sub("khoảng trắng sau ngoặc mở", r"([(\[])\s+", r"\1", s)
    s = sub("dấu câu lặp", r"([,;:?!])\1+", r"\1", s)
    s = sub("thiếu khoảng trắng sau dấu câu", r"([,;:?!])(?=[^\W\d_])", r"\1 ", s)
    s = sub("thiếu khoảng trắng sau dấu chấm", r"(?<!\.)\.(?=[A-ZÀ-Ỹ][a-zà-ỹ])", ". ", s)
    s = sub("khoảng trắng thừa", r"\s{2,}", " ", s)
    return s.strip()


def split_sentences(text: str) -> list[str]:
    """Cắt sau ``. ; : ? !`` đứng trước khoảng trắng (không cắt trong ``0,85``, ``(1717)``).
    ``...`` giữa câu (sau đó là chữ thường) không phải hết câu."""
    parts = re.split(r"(?<=[.;:?!])\s+", text.strip())
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        if out and out[-1].endswith("...") and p[0].islower():
            out[-1] += " " + p
        else:
            out.append(p)
    return out


def viet_items(lines: list[str], log: list[str] | None = None) -> list[str]:
    """Gộp dòng bị ngắt do khổ giấy rồi cắt câu. ``''`` = dòng trống; dòng bắt đầu ``- `` mở mục mới
    (bỏ ``- `` theo 1A.3.11). Mỗi mục một hoặc nhiều câu, mỗi câu một dòng."""
    paras: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        s = nfc(ln).strip()
        if not s:
            if cur:
                paras.append(cur)
                cur = []
            continue
        if BULLET.match(s):
            if cur:
                paras.append(cur)
            cur = [BULLET.sub("", s)]
        elif not cur and paras and not SENT_END.search(paras[-1][-1]) and s[:1].islower():
            # (sửa 7) dòng trống ở cuối trang OCR cắt ngang câu: đoạn trước chưa hết câu + dòng này viết thường ⇒ nối tiếp
            cur = paras.pop()
            cur.append(s)
            if log is not None:
                log.append("nối câu bị ngắt giữa trang")
        else:
            cur.append(s)
    if cur:
        paras.append(cur)
    out: list[str] = []
    for p in paras:
        for sent in split_sentences(clean_viet(" ".join(p), log)):
            sent = BULLET.sub("", sent).strip()
            if sent:
                out.append(sent)
    return out
