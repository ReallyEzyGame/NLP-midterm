"""Từ điển của giảng viên cho dóng hàng Hán Nôm ↔ dịch âm (``Hướng dẫn dóng hàng - dịch âm.docx``, ``dict.zip``).

- ``QuocNgu_SinoNom_TongHop3.csv`` (cột ``QuocNgu``, ``SinoNom``): một âm Quốc ngữ → các chữ Hán Nôm có thể đọc âm đó (S2).
- ``SinoNom_Similar_Dic_v2.csv`` (cột ``Input Character``, ``Top 20 Similar Characters``): chữ có hình dáng giống (S1).

Thư mục từ điển: ``configs/config.yml`` → ``dong_hang.dict_dir`` (mặc định ``../dict`` = ``GK/dict``, NGOÀI repo — từ điển
là tài nguyên lab, không commit). Âm được so theo ``am_key``: bỏ khác biệt chính tả cùng một âm (``hoà``/``hòa``,
``thuỷ``/``thủy``, ``kì``/``kỳ``, ``quí``/``quý``) mà từ điển ghi lẫn lộn và sách dùng kiểu cũ.

    python -m src.step4_trans_align.tu_dien_han_viet      # selftest + thống kê
"""
from __future__ import annotations

import ast
import csv
import re
import sys
import unicodedata
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TONES = {"̀": "2", "́": "1", "̉": "3", "̃": "4", "̣": "5"}   # huyền sắc hỏi ngã nặng
_Y_AS_I = re.compile(r"^(ch|gh|kh|ngh|ng|nh|ph|th|tr|qu|[bcdđghklmnpqrstvx])y$")


def dict_dir(root: Path = ROOT) -> Path:
    try:
        import yaml
        cfg = yaml.safe_load((root / "configs" / "config.yml").read_text(encoding="utf-8")) or {}
        d = (cfg.get("dong_hang") or {}).get("dict_dir")
    except (OSError, ImportError):
        d = None
    p = Path(d) if d else Path("../dict")
    return p if p.is_absolute() else (root / p).resolve()


def am_key(s: str) -> str:
    """Khoá so âm: chữ thường, dấu thanh tách khỏi vị trí đặt dấu, 'y' cuối sau phụ âm = 'i' (kỳ = kì, quý = quí)."""
    d = unicodedata.normalize("NFD", s.strip().lower())
    tone = "".join(TONES.get(c, "") for c in d)
    base = unicodedata.normalize("NFC", "".join(c for c in d if c not in TONES))
    base = _Y_AS_I.sub(lambda m: m.group(1) + "i", base)
    return base + (tone[:1] or "0")


@lru_cache(maxsize=2)
def load_readings(path: str | None = None) -> dict[str, frozenset[str]]:
    """chữ Hán Nôm → tập khoá âm (``am_key``) đọc được theo từ điển giảng viên."""
    p = Path(path) if path else dict_dir() / "QuocNgu_SinoNom_TongHop3.csv"
    out: dict[str, set[str]] = defaultdict(set)
    with open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            ch, qn = unicodedata.normalize("NFC", r["SinoNom"].strip()), r["QuocNgu"]
            if ch and qn.strip():
                out[ch].add(am_key(qn))
    return {k: frozenset(v) for k, v in out.items()}


@lru_cache(maxsize=2)
def load_similar(path: str | None = None) -> dict[str, tuple[str, ...]]:
    """chữ → các chữ có hình dáng tương đồng (S1, theo thứ tự giống nhất trước)."""
    p = Path(path) if path else dict_dir() / "SinoNom_Similar_Dic_v2.csv"
    out = {}
    with open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                out[r["Input Character"]] = tuple(ast.literal_eval(r["Top 20 Similar Characters"]))
            except (ValueError, SyntaxError):
                continue
    return out


def reads_as(ch: str, am: str, readings: dict[str, frozenset[str]], variants=None) -> bool:
    """Chữ ``ch`` đọc được âm ``am`` (xét cả dị thể cùng nhóm chuẩn hoá nếu truyền ``variants``: chữ → nhóm chữ)."""
    k = am_key(am)
    if k in readings.get(ch, ()):
        return True
    return bool(variants) and any(k in readings.get(v, ()) for v in variants.get(ch, ()))


def _selftest() -> None:
    assert am_key("hoà") == am_key("hòa") == am_key("Hoà")
    assert am_key("kì") == am_key("kỳ") and am_key("quí") == am_key("quý") and am_key("thuỷ") == am_key("thủy")
    assert am_key("hoa") != am_key("hòa") and am_key("y") != am_key("i") and am_key("tuy") != am_key("tui")
    if not (dict_dir() / "QuocNgu_SinoNom_TongHop3.csv").exists():
        print(f"selftest: ĐẠT (bỏ qua phần từ điển — chưa có {dict_dir()})")
        return
    rd, sim = load_readings(), load_similar()
    assert reads_as("佛", "Phật", rd) and reads_as("碑", "bi", rd) and not reads_as("碑", "phật", rd)
    assert reads_as("記", "kí", rd) and reads_as("記", "ký", rd)
    assert "已" in sim.get("己", ())
    print(f"selftest: ĐẠT — {len(rd)} chữ có âm, {len(sim)} chữ có danh sách giống hình ({dict_dir()})")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    _selftest()
