"""Định nghĩa Data Schema và Validation cho module Gióng hàng (Alignment).

Tuân thủ nghiêm ngặt Data Contract v1.0 của dự án (mục 2 & 8).
Khớp nối dữ liệu giữa:
    - Input: data/processed/bbox_chuan/<bia_id>.json (từ B)
    - Input: data/processed/Chu_Han/<bia>.txt        (từ A)
    - Output: data/processed/align/<bia_id>.json     (cho D)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.utils import file_io as fio

# Trạng thái hợp lệ của một box sau khi gióng
AlignStatus = Literal["ok", "needs_review", "unmatched"]

# Tập các ký tự đại diện cho chữ bị mất / mờ / khuyết trên văn bia trong sách khảo cứu
WILDCARD_CHARS = frozenset({"○", "□", "◇", "△", "?", "？", "*", "•", "■"})


def sanitize_text(text: str | None) -> str:
    """Làm sạch chuỗi văn bản theo chuẩn Data Contract:
    - Chuẩn hóa Unicode NFC.
    - Xóa các ký tự tab và xuống dòng (tránh làm hỏng file TSV det_gt.txt / rec_gt.txt).
    - Cắt khoảng trắng đầu và cuối.
    """
    if not text:
        return ""
    text = fio.nfc(text)
    return text.replace("\t", " ").replace("\r", "").replace("\n", " ").strip()


@dataclass
class AlignItem:
    """Đại diện cho kết quả gióng của một Bounding Box."""
    order: int
    text_ocr: str
    text_gt: str
    score: float
    status: AlignStatus
    region: str = "than"          # "tran" | "than"
    note: str = ""                # Ghi chú kỹ thuật (nếu có, phục vụ debug / review)

    def __post_init__(self) -> None:
        if self.order <= 0:
            raise ValueError(f"order phải là số nguyên dương (> 0), nhận được {self.order}")
        if not (0.0 <= self.score <= 1.0):
            raise ValueError(f"score phải nằm trong khoảng [0.0, 1.0], nhận được {self.score}")
        if self.status not in ("ok", "needs_review", "unmatched"):
            raise ValueError(f"status không hợp lệ: {self.status!r}")
        
        # Luôn làm sạch text để bảo đảm an toàn dữ liệu
        self.text_ocr = sanitize_text(self.text_ocr)
        self.text_gt = sanitize_text(self.text_gt)
        self.score = round(float(self.score), 4)

    def to_contract_dict(self) -> dict[str, Any]:
        """Chuyển thành dict đúng định dạng mà export_ocr_dataset.py yêu cầu."""
        d: dict[str, Any] = {
            "order": self.order,
            "text_ocr": self.text_ocr,
            "text_gt": self.text_gt,
            "score": self.score,
            "status": self.status,
        }
        if self.region:
            d["region"] = self.region
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class AlignResult:
    """Đại diện cho toàn bộ file data/processed/align/<bia_id>.json."""
    bia_id: str
    items: list[AlignItem] = field(default_factory=list)
    schema_version: int = fio.SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.bia_id or not self.bia_id.strip():
            raise ValueError("bia_id không được để trống")
        if self.schema_version != fio.SCHEMA_VERSION:
            raise ValueError(
                f"schema_version={self.schema_version} không khớp với chuẩn hệ thống {fio.SCHEMA_VERSION}"
            )
        # Sắp xếp các items luôn theo thứ tự order tăng dần
        self.items = sorted(self.items, key=lambda it: it.order)

    @property
    def total_boxes(self) -> int:
        return len(self.items)

    @property
    def ok_count(self) -> int:
        return sum(1 for it in self.items if it.status == "ok")

    @property
    def review_count(self) -> int:
        return sum(1 for it in self.items if it.status == "needs_review")

    @property
    def unmatched_count(self) -> int:
        return sum(1 for it in self.items if it.status == "unmatched")

    @property
    def average_score(self) -> float:
        if not self.items:
            return 0.0
        return round(sum(it.score for it in self.items) / len(self.items), 4)

    def to_contract_dict(self) -> dict[str, Any]:
        """Xuất dict hoàn chỉnh theo chuẩn schema_version=1."""
        return {
            "schema_version": self.schema_version,
            "bia_id": self.bia_id,
            "items": [it.to_contract_dict() for it in self.items],
        }

    def save(self, out_path: Path) -> None:
        """Ghi ra file JSON nguyên tử (atomic write) theo chuẩn fio.write_json."""
        fio.write_json(out_path, self.to_contract_dict())

    @classmethod
    def load(cls, path: Path) -> AlignResult:
        """Đọc và validate từ một file JSON đã tồn tại."""
        data = fio.read_json(path)
        fio.check_schema(data, path)
        bia_id = data["bia_id"]
        items = [
            AlignItem(
                order=it["order"],
                text_ocr=it.get("text_ocr", ""),
                text_gt=it.get("text_gt", ""),
                score=float(it.get("score", 0.0)),
                status=it.get("status", "needs_review"),
                region=it.get("region", "than"),
                note=it.get("note", ""),
            )
            for it in data.get("items", [])
        ]
        return cls(bia_id=bia_id, items=items, schema_version=data["schema_version"])


def validate_raw_bbox_input(data: dict, path: Path | None = None) -> None:
    """Kiểm tra tính hợp lệ của file input data/processed/bbox_chuan/<bia_id>.json."""
    if path:
        fio.check_schema(data, path)
    else:
        if data.get("schema_version") != fio.SCHEMA_VERSION:
            raise ValueError(f"schema_version={data.get('schema_version')}, cần {fio.SCHEMA_VERSION}")

    if "bia_id" not in data or not data["bia_id"]:
        raise ValueError(f"Thiếu trường bia_id trong dữ liệu bbox_chuan ({path})")

    if "boxes" not in data or not isinstance(data["boxes"], list):
        raise ValueError(f"Trường 'boxes' phải là danh sách trong ({path})")

    seen_orders = set()
    for b in data["boxes"]:
        if "order" not in b:
            raise ValueError(f"Box thiếu trường 'order' trong ({path})")
        o = b["order"]
        if o in seen_orders:
            raise ValueError(f"Trùng lặp thứ tự order={o} trong ({path})")
        seen_orders.add(o)

        if "points" not in b or len(b["points"]) != 4:
            raise ValueError(f"Box order={o} phải có đúng 4 điểm tọa độ trong ({path})")
