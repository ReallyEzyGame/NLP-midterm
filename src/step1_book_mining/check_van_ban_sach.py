"""Checker độc lập cho văn bản sạch Chu_Han / Phien_am / Dich_nghia — CHECKLIST_1A §7 (luật V1–V8).

Chờ Phong tích hợp vào ``src/utils/validate.py``; đến lúc đó đây là cổng "chưa validate thì chưa giao".

Chạy (từ thư mục NLP-midterm):
    python -m src.step1_book_mining.check_van_ban_sach                       # kiểm bản nháp data/interim/van_ban_nhap
    python -m src.step1_book_mining.check_van_ban_sach --dir data/processed  # kiểm bản chính thức
    python -m src.step1_book_mining.check_van_ban_sach --log reports/check_van_ban_20261109.txt
    python -m src.step1_book_mining.check_van_ban_sach --selftest            # 1A.6.4: file lỗi giả phải bị bắt

Mã thoát 0 = không lỗi. Log chỉ ghi ``file:dòng:luật`` + mô tả, KHÔNG chép nội dung sách (log nằm trong repo).
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path

import regex

ROOT = Path(__file__).resolve().parents[2]
KINDS = ("Chu_Han", "Phien_am", "Dich_nghia")
HAN_PUNCT = "。，、；：？！「」『』（）《》〈〉…·—"          # chốt tập cuối cùng với Phong
HAN_RE = regex.compile(rf"(?:\p{{Han}}|[{regex.escape(HAN_PUNCT)}]|MASK)+")   # MASK = chữ mất/sách lược (GV 14/11/2026)
JUNK_RE = regex.compile("[□�□■​ ﻿]")
LABEL_RE = re.compile(r"(?i)\b(phiên\s*âm|dịch\s*nghĩa)\s*:")
PATH_RE = re.compile(r"(?i)\.(jpe?g|png|tiff?)\b|[\\/]")
NOTE_RE = re.compile(r"(?i)\(\s*xem\s|xem\s+chú\s+thích")
PAGENO_RE = re.compile(r"^\d{1,3}$")


def check_file(path: Path, kind: str) -> list[tuple[int, str, str]]:
    """Trả về [(dòng, luật, mô tả)]. dòng 0 = lỗi cả file."""
    errs: list[tuple[int, str, str]] = []
    raw = path.read_bytes()
    if raw == b"":                       # rỗng HOÀN TOÀN (0 byte) = sách không có loại văn bản này (chủ ý) ⇒ hợp lệ
        return errs
    if raw.startswith(b"\xef\xbb\xbf"):
        errs.append((0, "V1", "có BOM"))
    try:
        text = raw.decode("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8")
    except UnicodeDecodeError as e:
        return errs + [(0, "V1", f"không phải UTF-8: {e.reason}")]
    if b"\r" in raw:
        errs.append((0, "V2", "có ký tự CR (\\r)"))
    if text != unicodedata.normalize("NFC", text):
        errs.append((0, "V3", "không ở dạng NFC"))
    if not text.endswith("\n"):
        errs.append((0, "V4", "không kết thúc bằng một LF"))
    lines = text.replace("\r", "").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    if not lines:
        errs.append((0, "V4", "file rỗng"))
    for i, ln in enumerate(lines, 1):
        if not ln.strip():
            errs.append((i, "V4", "dòng trống"))
            continue
        if ln != ln.strip():
            errs.append((i, "V4", "khoảng trắng đầu/cuối dòng"))
        if JUNK_RE.search(ln):
            errs.append((i, "V8", "ký tự rác/lỗi mã hoá (□, U+FFFD, NBSP, zero-width…)"))
        if kind == "Chu_Han":
            if not HAN_RE.fullmatch(ln):
                bad = sorted({c for c in ln.replace("MASK", "") if not (regex.match(r"\p{Han}", c) or c in HAN_PUNCT)})
                errs.append((i, "V5", "ký tự ngoài Hán/dấu câu cho phép: " + " ".join(f"U+{ord(c):04X}" for c in bad)))
        else:
            if PAGENO_RE.match(ln.strip()):
                errs.append((i, "V7", "dòng chỉ là số (số trang?)"))
            if PATH_RE.search(ln):
                errs.append((i, "V7", "có đường dẫn/đuôi ảnh hoặc dấu / \\"))
            if LABEL_RE.search(ln):
                errs.append((i, "V7", "còn nhãn 'Phiên âm:'/'Dịch nghĩa:'"))
            if NOTE_RE.search(ln):
                errs.append((i, "V7", "còn chú thích '(xem …)'"))
            if regex.search(r"\p{Han}", ln):
                errs.append((i, "V8", "lẫn chữ Hán trong văn bản Việt"))
    return errs


def check_dir(base: Path, ids: list[str] | None = None) -> tuple[list[str], int]:
    found = {k: {p.stem for p in (base / k).glob("*.txt")} for k in KINDS}
    all_ids = sorted(set().union(*found.values())) if ids is None else ids
    report, n_err = [], 0
    for bid in all_ids:
        for k in KINDS:
            p = base / k / f"{bid}.txt"
            if not p.exists():
                report.append(f"{bid}  {k}  V6  thiếu file")
                n_err += 1
                continue
            for line, rule, msg in check_file(p, k):
                report.append(f"{k}/{bid}.txt:{line or '-'}  {rule}  {msg}")
                n_err += 1
    rong = [f"{k}/{b}.txt" for b in all_ids for k in KINDS
            if (base / k / f"{b}.txt").exists() and (base / k / f"{b}.txt").stat().st_size == 0]
    report.insert(0, f"# {len(all_ids)} bia × 3 loại = {len(all_ids) * 3} file; {n_err} lỗi"
                  + (f"; {len(rong)} file rỗng có chủ ý: {', '.join(rong)}" if rong else ""))
    return report, n_err


def selftest() -> int:
    """1A.6.4: tạo file lỗi giả, mỗi file phải bị bắt đúng luật."""
    cases = {
        ("Chu_Han", b"\xef\xbb\xbf\xe5\xbe\x8c\n"): "V1",
        ("Chu_Han", "後\r\n佛\r\n".encode()): "V2",
        ("Phien_am", unicodedata.normalize("NFD", "Hậu Phật\n").encode()): "V3",
        ("Phien_am", "Hậu\n\nPhật\n".encode()): "V4",
        ("Chu_Han", "後 佛\n".encode()): "V5",
        ("Chu_Han", "後佛abc\n".encode()): "V5",
        ("Dich_nghia", "Phiên âm: Hậu\n".encode()): "V7",
        ("Dich_nghia", "123\n".encode()): "V7",
        ("Dich_nghia", "xem hình 01.jpg\n".encode()): "V7",
        ("Dich_nghia", "Hậu � Phật\n".encode()): "V8",
        ("Phien_am", b"\n"): "V4",                       # chỉ có dòng trống: vẫn là lỗi (khác file 0 byte hợp lệ)
    }
    ok = True
    with tempfile.TemporaryDirectory() as td:
        for n, ((kind, data), rule) in enumerate(cases.items()):
            p = Path(td) / f"{n}.txt"
            p.write_bytes(data)
            got = {r for _, r, _ in check_file(p, kind)}
            hit = rule in got
            ok &= hit
            print(f"  {'OK ' if hit else 'MISS'} {kind:10s} kỳ vọng {rule}, bắt được {sorted(got)}")
        (Path(td) / "Chu_Han").mkdir()
        (Path(td) / "Phien_am").mkdir()
        (Path(td) / "Dich_nghia").mkdir()
        (Path(td) / "Chu_Han" / "X.txt").write_text("後\n", encoding="utf-8", newline="\n")
        rep, n = check_dir(Path(td))
        hit = any("V6" in r for r in rep)
        ok &= hit
        print(f"  {'OK ' if hit else 'MISS'} thiếu file → V6 ({n} lỗi)")
        (Path(td) / "Phien_am" / "X.txt").write_text("Hậu Phật bi kí.\n", encoding="utf-8", newline="\n")
        (Path(td) / "Dich_nghia" / "X.txt").write_text("Bia Hậu Phật.\n", encoding="utf-8", newline="\n")
        _, n = check_dir(Path(td))
        ok &= n == 0
        print(f"  {'OK ' if n == 0 else 'MISS'} bộ hợp lệ → 0 lỗi (nhận {n})")
    print("selftest:", "ĐẠT" if ok else "KHÔNG ĐẠT")
    return 0 if ok else 1


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="data/interim/van_ban_nhap", help="thư mục chứa Chu_Han/Phien_am/Dich_nghia")
    ap.add_argument("--bia", help="danh sách bia_id cách nhau dấu phẩy (mặc định: mọi bia tìm thấy)")
    ap.add_argument("--log", help="ghi báo cáo ra file (UTF-8, LF)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    base = (ROOT / a.dir) if not Path(a.dir).is_absolute() else Path(a.dir)
    rep, n = check_dir(base, a.bia.split(",") if a.bia else None)
    head = f"# check_van_ban_sach {datetime.now():%Y-%m-%d %H:%M}  dir={a.dir}"
    out = [head] + rep + ["KẾT QUẢ: " + ("ĐẠT (0 lỗi)" if n == 0 else f"KHÔNG ĐẠT ({n} lỗi)")]
    print("\n".join(out))
    if a.log:
        p = Path(a.log)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    return 0 if n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
