"""Tiện ích đọc/ghi file dùng chung — theo Data Contract v1.0 (mục 2).

Quy ước: UTF-8 không BOM, xuống dòng LF, Unicode NFC, ghi file nguyên tử
(ghi ra file tạm rồi thay thế) để không bao giờ để lại file ghi dở.
"""
from __future__ import annotations

import csv
import json
import os
import unicodedata
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1   # phải khớp `schema_version` trong mọi file JSON (Data Contract mục 8)
ENCODING = "utf-8"


def pad3(n: int) -> str:
    """Số thứ tự 3 chữ số: 1 -> '001'. Quá 999 thì báo lỗi thay vì âm thầm thành 4 chữ số."""
    if not 0 <= n <= 999:
        raise ValueError(f"Số thứ tự {n} vượt quá 3 chữ số (Data Contract nguyên tắc 8)")
    return f"{n:03d}"


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def read_json(path: Path) -> Any:
    with open(path, encoding=ENCODING) as f:
        return json.load(f)


def check_schema(obj: dict, path: Path) -> None:
    """Từ chối file có schema_version khác bản hiện hành."""
    got = obj.get("schema_version")
    if got != SCHEMA_VERSION:
        raise ValueError(f"{path}: schema_version={got!r}, cần {SCHEMA_VERSION}")


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, encoding=ENCODING, newline="") as f:
        return list(csv.DictReader(f))


def write_text(path: Path, text: str) -> None:
    """Ghi file text UTF-8, LF, nguyên tử."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding=ENCODING, newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def write_json(path: Path, obj: Any) -> None:
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def write_lines(path: Path, lines: list[str]) -> None:
    write_text(path, "".join(line + "\n" for line in lines))
