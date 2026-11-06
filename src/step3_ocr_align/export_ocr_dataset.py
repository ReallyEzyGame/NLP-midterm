"""Xuất Dataset OCR (Dataset 1) theo định dạng docx — KHUNG SCRIPT (skeleton).

Đọc kết quả của các bước trước theo Data Contract v1.0 và ghi:

    data/output/dataset_ocr/<Tên bia>/
        images/      <Tên bia>.001.jpg ...        (cạnh dài ≤ 1024)
        patches/     <Tên bia>.001.001.jpg ...    (cao ≤ 96, cột đứng xoay 90° ngược chiều kim đồng hồ)
        det_gt.txt   <Tên bia>/images/<file><TAB>[{"transcription": ..., "points": ...}]
        rec_gt.txt   <Tên bia>/patches/<file><TAB><chữ Hán>
        results.xlsx Image ID | Patch ID | Bounding Box | SinoNom OCR

Đầu vào (đã có hoặc sẽ có khi các bước trước hoàn thiện):
    data/metadata/bia_manifest.csv, data/metadata/inventory.csv
    data/raw/anh_bia/<file_anh>
    data/processed/bbox_chuan/<bia_id>.json     (B)
    data/processed/align/<bia_id>.json          (C)

Chạy từ gốc repo:
    python -m src.step3_ocr_align.export_ocr_dataset
    python -m src.step3_ocr_align.export_ocr_dataset --only 00270-TF1 --allow-missing-align
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from src.utils import file_io as fio
from src.utils import image_processing as imp

log = logging.getLogger("export_ocr")
REPO_ROOT = Path(__file__).resolve().parents[2]
IGNORE_LABEL = "###"      # quy ước PaddleOCR cho box không có nhãn (bị bỏ qua khi huấn luyện detection)


@dataclass
class ExportConfig:
    root: Path = REPO_ROOT
    out_dir: Path | None = None          # mặc định: <root>/data/output/dataset_ocr
    group_by: str = "doc"                # "doc": mỗi văn bản một thư mục | "book": cả cuốn một thư mục
    book_name: str | None = None         # bắt buộc khi group_by == "book"
    max_side: int = 1024
    max_patch_height: int = 96
    jpeg_quality: int = 95
    include_review: bool = False         # True: xuất cả box needs_review nếu đã có text_gt
    allow_missing_align: bool = False    # True: chưa có align/ vẫn xuất det_gt (nhãn ###), không patch
    clean: bool = True                   # xóa thư mục đích trước khi xuất để chạy lại tái lập được
    only: set[str] = field(default_factory=set)
    version_label: str | None = None     # ghi vào data/output/VERSION.txt (v0 / v1 / final)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.out_dir = Path(self.out_dir) if self.out_dir else self.root / "data" / "output" / "dataset_ocr"


@dataclass
class Box:
    order: int
    region: str
    points: list[list[float]]
    text_gt: str
    status: str


@dataclass
class Stats:
    pages: int = 0
    boxes: int = 0
    patches: int = 0
    unlabeled: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- đọc đầu vào
def sanitize_folder_name(name: str) -> str:
    """Giữ tiếng Việt có dấu (docx yêu cầu), bỏ ký tự cấm của hệ điều hành."""
    name = fio.nfc(name)
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, " ")
    return " ".join(name.split()).strip(" .")


def load_metadata(cfg: ExportConfig) -> tuple[list[dict], dict[str, dict]]:
    meta = cfg.root / "data" / "metadata"
    manifest = fio.read_csv(meta / "bia_manifest.csv")
    inventory = {r["doc_id"]: r for r in fio.read_csv(meta / "inventory.csv")}
    return manifest, inventory


def group_pages(manifest: list[dict], inventory: dict[str, dict], cfg: ExportConfig) -> dict[str, list[dict]]:
    """Gom các mặt bia thành thư mục output. Số trang = vị trí trong nhóm, xếp theo bia_id."""
    groups: dict[str, list[dict]] = {}
    for row in sorted(manifest, key=lambda r: r["bia_id"]):
        if cfg.only and row["bia_id"] not in cfg.only:
            continue
        if cfg.group_by == "book":
            if not cfg.book_name:
                raise SystemExit("--book-name là bắt buộc khi --group-by book")
            name = cfg.book_name
        else:
            inv = inventory.get(row["doc_id"])
            if inv is None:
                raise KeyError(f"doc_id {row['doc_id']!r} (bia {row['bia_id']}) không có trong inventory.csv")
            name = inv["ten_van_ban"]
        groups.setdefault(sanitize_folder_name(name), []).append(row)
    return groups


def load_boxes(bia_id: str, cfg: ExportConfig) -> list[Box]:
    """Ghép bbox_chuan (B) với align (C) theo `order`."""
    proc = cfg.root / "data" / "processed"
    bb_path = proc / "bbox_chuan" / f"{bia_id}.json"
    bb = fio.read_json(bb_path)
    fio.check_schema(bb, bb_path)

    al_path = proc / "align" / f"{bia_id}.json"
    align: dict[int, dict] = {}
    if al_path.exists():
        al = fio.read_json(al_path)
        fio.check_schema(al, al_path)
        align = {it["order"]: it for it in al["items"]}
    elif not cfg.allow_missing_align:
        raise FileNotFoundError(f"thiếu {al_path} (dùng --allow-missing-align nếu chỉ muốn xuất det_gt)")

    boxes: list[Box] = []
    for b in sorted(bb["boxes"], key=lambda x: x["order"]):
        if len(b["points"]) != 4:
            raise ValueError(f"{bia_id} order={b['order']}: box phải có đúng 4 điểm")
        item = align.get(b["order"])
        if item is None:
            if not cfg.allow_missing_align:
                raise ValueError(f"{bia_id}: align thiếu order={b['order']}")
            text, status = "", "needs_review"
        else:
            text, status = item.get("text_gt") or "", item["status"]
        # tab/xuống dòng sẽ làm hỏng file TSV
        text = fio.nfc(text).replace("\t", "").replace("\n", "").strip()
        boxes.append(Box(b["order"], b["region"], b["points"], text, status))
    return boxes


# ---------------------------------------------------------------- xuất
def prepare_dir(out: Path, cfg: ExportConfig) -> None:
    if cfg.clean and out.exists():
        # chỉ xóa bên trong out_dir để không bao giờ lỡ tay xóa chỗ khác
        assert cfg.out_dir in out.parents, f"từ chối xóa {out}"
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "patches").mkdir(parents=True, exist_ok=True)


def is_labeled(box: Box, cfg: ExportConfig) -> bool:
    return bool(box.text_gt) and (box.status == "ok" or cfg.include_review)


def write_results_xlsx(path: Path, rows: list[list[str]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "results"
    ws.append(["Image ID", "Patch ID", "Bounding Box", "SinoNom OCR"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    for col, w in zip("ABCD", (28, 32, 44, 40)):
        ws.column_dimensions[col].width = w
    wb.save(path)


def export_group(folder: str, rows: list[dict], cfg: ExportConfig) -> Stats:
    st = Stats()
    out = cfg.out_dir / folder
    prepare_dir(out, cfg)
    det_lines: list[str] = []
    rec_lines: list[str] = []
    result_rows: list[list[str]] = []

    for page_no, row in enumerate(rows, start=1):
        bia_id = row["bia_id"]
        try:
            boxes = load_boxes(bia_id, cfg)
            img = imp.load_rgb(cfg.root / "data" / "raw" / "anh_bia" / row["file_anh"])
            if (str(img.width), str(img.height)) != (row.get("rong_px"), row.get("cao_px")):
                log.warning("%s: kích thước ảnh %sx%s khác manifest %sx%s",
                            bia_id, img.width, img.height, row.get("rong_px"), row.get("cao_px"))

            ratio = imp.page_scale(img.width, img.height, cfg.max_side)
            page = imp.resize_page(img, ratio)
            img_name = f"{folder}.{fio.pad3(page_no)}.jpg"
            page.save(out / "images" / img_name, quality=cfg.jpeg_quality)

            annots = []
            for box in boxes:
                pts = imp.scale_points(box.points, ratio, page.size)
                labeled = is_labeled(box, cfg)
                annots.append({"transcription": box.text_gt if labeled else IGNORE_LABEL, "points": pts})
                st.boxes += 1
                if not labeled:
                    st.unlabeled += 1
                    continue
                patch_name = f"{folder}.{fio.pad3(page_no)}.{fio.pad3(box.order)}.jpg"
                # cắt từ ẢNH GỐC với tọa độ GỐC
                imp.make_patch(img, box.points, cfg.max_patch_height).save(
                    out / "patches" / patch_name, quality=cfg.jpeg_quality)
                rec_lines.append(f"{folder}/patches/{patch_name}\t{box.text_gt}")
                result_rows.append([img_name, patch_name, json.dumps(pts), box.text_gt])
                st.patches += 1

            det_lines.append(f"{folder}/images/{img_name}\t{json.dumps(annots, ensure_ascii=False)}")
            st.pages += 1
        except Exception as e:                      # một bia lỗi không làm hỏng cả lô
            log.error("%s: %s", bia_id, e)
            st.errors.append(f"{bia_id}: {e}")

    fio.write_lines(out / "det_gt.txt", det_lines)
    fio.write_lines(out / "rec_gt.txt", rec_lines)
    write_results_xlsx(out / "results.xlsx", result_rows)
    return st


def run_validator(cfg: ExportConfig) -> bool:
    """Móc nối với validate.py (D viết ở GĐ1). Chưa có thì bỏ qua, không làm hỏng export."""
    try:
        from src.utils import validate           # type: ignore[attr-defined]
    except ImportError:
        log.warning("src/utils/validate.py chưa có — bỏ qua bước kiểm tra sau xuất")
        return True
    return bool(validate.validate_dataset_ocr(cfg.out_dir))      # TODO(D): chốt tên hàm khi viết validate.py


# ---------------------------------------------------------------- CLI
def parse_args(argv: list[str] | None) -> ExportConfig:
    p = argparse.ArgumentParser(description="Xuất Dataset OCR theo Data Contract v1.0")
    p.add_argument("--root", type=Path, default=REPO_ROOT, help="gốc repo (mặc định: tự suy ra)")
    p.add_argument("--out", type=Path, default=None, help="thư mục đích (mặc định data/output/dataset_ocr)")
    p.add_argument("--group-by", choices=["doc", "book"], default="doc",
                   help="doc: mỗi văn bản một thư mục; book: cả cuốn một thư mục (chờ xác nhận 'Tên sách')")
    p.add_argument("--book-name", default=None)
    p.add_argument("--only", nargs="*", default=[], help="chỉ xuất các bia_id này (để thử)")
    p.add_argument("--include-review", action="store_true", help="xuất cả box needs_review đã có text_gt")
    p.add_argument("--allow-missing-align", action="store_true", help="chưa có align/ vẫn xuất det_gt")
    p.add_argument("--no-clean", action="store_true", help="không xóa thư mục đích trước khi xuất")
    p.add_argument("--version-label", default=None, help="v0 | v1 | final -> data/output/VERSION.txt")
    a = p.parse_args(argv)
    return ExportConfig(root=a.root, out_dir=a.out, group_by=a.group_by, book_name=a.book_name,
                        include_review=a.include_review, allow_missing_align=a.allow_missing_align,
                        clean=not a.no_clean, only=set(a.only), version_label=a.version_label)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = parse_args(argv)
    manifest, inventory = load_metadata(cfg)
    groups = group_pages(manifest, inventory, cfg)
    if not groups:
        log.error("không có bia nào để xuất (kiểm tra manifest / --only)")
        return 1

    total = Stats()
    for folder, rows in groups.items():
        st = export_group(folder, rows, cfg)
        log.info("[%s] %d/%d trang, %d box, %d patch, %d box chưa có nhãn, %d lỗi",
                 folder, st.pages, len(rows), st.boxes, st.patches, st.unlabeled, len(st.errors))
        total.pages += st.pages; total.boxes += st.boxes; total.patches += st.patches
        total.unlabeled += st.unlabeled; total.errors += st.errors

    if cfg.version_label:
        fio.write_text(cfg.out_dir.parent / "VERSION.txt", cfg.version_label + "\n")

    ok = run_validator(cfg)
    log.info("TỔNG: %d trang, %d box, %d patch, %d chưa nhãn, %d lỗi",
             total.pages, total.boxes, total.patches, total.unlabeled, len(total.errors))
    return 0 if (ok and not total.errors) else 1


if __name__ == "__main__":
    sys.exit(main())
