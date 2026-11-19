"""Xuất Dataset OCR (Dataset 1) theo định dạng docx — KHUNG SCRIPT (skeleton).

Đọc kết quả của các bước trước theo Data Contract v1.0 và ghi:

    data/output/dataset_ocr/<Tên>/                <Tên> = bia_id của MỘT mặt bia (vd 02329-21); --group-by doc: mã các
                                                   mặt của văn bản nối "_"
        images/      <Tên>.001.jpg            (cạnh dài ≤ 1024; mỗi thư mục 1 mặt → 1 ảnh)
        patches/     <Tên>.001.001.jpg ...    (cao ≤ 96, cột đứng xoay 90° ngược chiều kim đồng hồ)
        det_gt.txt   <Tên>/images/<file><TAB>[{"transcription": ..., "points": ...}]
        rec_gt.txt   <Tên>/patches/<file><TAB><chữ Hán sách đã gióng>
        results.xlsx Image ID | Patch ID | Bounding Box | SinoNom OCR | SinoNom Book | Similarity (%)
                     (+ sheet "summary": độ khớp OCR văn bia ↔ văn bản sách theo từng mặt và cả văn bản)

Góp ý giảng viên (18/11/2026): Patch ID không dấu cách, không tiếng Việt, đặt theo mã bia; file kết quả có 2 cột —
chữ OCR văn bia (OCR lab CLC) và chữ sách gióng hàng với box — rồi đo độ tương đồng (coi văn bản sách là đúng).

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
import csv
import json
import logging
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from rapidfuzz.distance import Levenshtein

from src.utils import file_io as fio
from src.utils import image_processing as imp

log = logging.getLogger("export_ocr")
REPO_ROOT = Path(__file__).resolve().parents[2]
IGNORE_LABEL = ""         # box chưa có nhãn: transcription rỗng theo docx (trước đây "###" → cảnh báo D10 của validator)
RESULTS_HEADER = ["Image ID", "Patch ID", "Bounding Box", "SinoNom OCR", "SinoNom Book", "Similarity (%)"]
SUMMARY_HEADER = ["Image ID", "bia_id", "Boxes", "Patches", "Patches MASK only", "Mean similarity (%)",
                  "Char similarity (%)"]
HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0002ffff]")


@dataclass
class ExportConfig:
    root: Path = REPO_ROOT
    out_dir: Path | None = None          # mặc định: <root>/data/output/dataset_ocr
    group_by: str = "bia"                # "bia": mỗi MẶT bia một thư mục (mặc định) | "doc": mỗi văn bản | "book": cả cuốn
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
    text_ocr: str = ""


@dataclass
class Stats:
    pages: int = 0
    boxes: int = 0
    patches: int = 0
    unlabeled: int = 0
    errors: list[str] = field(default_factory=list)
    summary: list[list] = field(default_factory=list)


def visual_order(box: "Box") -> tuple[str, str]:
    """(OCR, nhãn) theo thứ tự chữ TRONG ẢNH PATCH. Cột dọc: patch xoay 90° ngược chiều kim đồng hồ → trên→dưới thành
    trái→phải = thứ tự đọc. Box trán NẰM NGANG nhiều chữ (OCR lab trả cả dòng tiêu đề một box): patch giữ nguyên, chữ
    hiện trái→phải như khắc, còn thứ tự đọc trán là phải→trái → đảo lại để nhãn rec_gt khớp ảnh."""
    xs, ys = [p[0] for p in box.points], [p[1] for p in box.points]
    if box.region == "tran" and (max(xs) - min(xs)) >= (max(ys) - min(ys)) and "MASK" not in box.text_gt:   # = make_patch không xoay
        return box.text_ocr[::-1], box.text_gt[::-1]
    return box.text_ocr, box.text_gt


def similarity(ocr: str, book: str) -> float | None:
    """Độ khớp (%) chữ OCR văn bia ↔ chữ sách của box = 100·(1 − Levenshtein / độ dài chuỗi dài hơn), chỉ xét chữ Hán,
    so NGUYÊN DẠNG (dị thể khác mã tính là khác — coi sách là đúng). Nhãn chỉ có MASK (sách không chép) → None."""
    o, g = "".join(HAN.findall(ocr)), "".join(HAN.findall(book.replace("MASK", "")))
    if not g:
        return None
    return round(100 * Levenshtein.normalized_similarity(o, g), 1)


def summary_row(img_name: str, bia_id: str, n_box: int, rows: list[list]) -> list:
    """Độ khớp trung bình theo box và độ khớp theo chữ (1 − Σ Levenshtein / Σ độ dài, chỉ box có chữ sách)."""
    pairs = [("".join(HAN.findall(r[3])), "".join(HAN.findall(r[4].replace("MASK", "")))) for r in rows if r[5] is not None]
    sims = [r[5] for r in rows if r[5] is not None]
    dist = sum(Levenshtein.distance(o, g) for o, g in pairs)
    tot = sum(max(len(o), len(g)) for o, g in pairs)
    return [img_name, bia_id, n_box, len(rows), len(rows) - len(sims),
            round(sum(sims) / len(sims), 1) if sims else None, round(100 * (1 - dist / tot), 1) if tot else None]


def doc_names(root: Path) -> dict[str, str]:
    """doc_id → tên thư mục = mã các mặt bia nối "_" (cùng tên file văn bản sạch; data/metadata/van_ban_ma_bia.csv)."""
    return {r["doc_id"]: r["ten_file"] for r in fio.read_csv(root / "data" / "metadata" / "van_ban_ma_bia.csv")}


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
    names = doc_names(cfg.root)
    for row in sorted(manifest, key=lambda r: r["bia_id"]):
        if cfg.only and row["bia_id"] not in cfg.only:
            continue
        if cfg.group_by == "bia":                # Tuấn 18/11/2026: mỗi thư mục chỉ chứa đúng 1 mặt của văn bia
            name = row["bia_id"]
        elif cfg.group_by == "book":
            if not cfg.book_name:
                raise SystemExit("--book-name là bắt buộc khi --group-by book")
            name = cfg.book_name
        else:
            if row["doc_id"] not in inventory or row["doc_id"] not in names:
                raise KeyError(f"doc_id {row['doc_id']!r} (bia {row['bia_id']}) thiếu trong inventory.csv/van_ban_ma_bia.csv")
            name = names[row["doc_id"]]
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
        ocr = fio.nfc(b.get("text_ocr") or "").replace("\t", "").replace("\n", "").strip()
        boxes.append(Box(b["order"], b["region"], b["points"], text, status, ocr))
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


def write_results_xlsx(path: Path, rows: list[list], summary: list[list] | None = None) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "results"
    ws.append(RESULTS_HEADER)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    for col, w in zip("ABCDEF", (30, 34, 44, 40, 40, 14)):
        ws.column_dimensions[col].width = w
    if summary:
        ws2 = wb.create_sheet("summary")
        ws2.append(SUMMARY_HEADER)
        for c in ws2[1]:
            c.font = Font(bold=True)
        for r in summary:
            ws2.append(r)
        for col, w in zip("ABCDEFG", (30, 12, 8, 9, 18, 20, 18)):
            ws2.column_dimensions[col].width = w
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
            page_rows: list[list] = []
            for box in boxes:
                pts = imp.scale_points(box.points, ratio, page.size)
                labeled = is_labeled(box, cfg)
                ocr_v, label_v = visual_order(box)
                annots.append({"transcription": label_v if labeled else IGNORE_LABEL, "points": pts})
                st.boxes += 1
                if not labeled:
                    st.unlabeled += 1
                    continue
                patch_name = f"{folder}.{fio.pad3(page_no)}.{fio.pad3(box.order)}.jpg"
                # cắt từ ẢNH GỐC với tọa độ GỐC
                imp.make_patch(img, box.points, cfg.max_patch_height).save(
                    out / "patches" / patch_name, quality=cfg.jpeg_quality)
                rec_lines.append(f"{folder}/patches/{patch_name}\t{label_v}")
                # Patch ID KHÔNG kèm đuôi .jpg (docx: "Tên.001.001") — trước đây gây lỗi D8 ×592 của validator
                page_rows.append([img_name, patch_name.removesuffix(".jpg"), json.dumps(pts), ocr_v, label_v,
                                  similarity(ocr_v, label_v)])
                st.patches += 1
            result_rows += page_rows
            st.summary.append(summary_row(img_name, bia_id, len(boxes), page_rows))

            det_lines.append(f"{folder}/images/{img_name}\t{json.dumps(annots, ensure_ascii=False)}")
            st.pages += 1
        except Exception as e:                      # một bia lỗi không làm hỏng cả lô
            log.error("%s: %s", bia_id, e)
            st.errors.append(f"{bia_id}: {e}")

    fio.write_lines(out / "det_gt.txt", det_lines)
    fio.write_lines(out / "rec_gt.txt", rec_lines)
    if st.summary:
        st.summary.append(summary_row("TOTAL", "", sum(r[2] for r in st.summary), result_rows))
    write_results_xlsx(out / "results.xlsx", result_rows, st.summary)
    return st


def write_similarity_report(cfg: ExportConfig, rows: list[list]) -> None:
    """reports/dataset_ocr_<ngày>/do_khop_ocr_sach.csv: độ khớp OCR văn bia ↔ chữ sách theo mặt, văn bản và toàn bộ."""
    faces = [r for r in rows if r[1] != "TOTAL"]
    pairs = []
    for folder in dict.fromkeys(r[0] for r in faces):
        wb = load_workbook(cfg.out_dir / folder / "results.xlsx", read_only=True)
        pairs += [list(r) for r in wb["results"].iter_rows(min_row=2, values_only=True)]
        wb.close()
    total = summary_row("TOAN_BO", "", sum(r[3] for r in faces), pairs)
    out = cfg.root / "reports" / f"dataset_ocr_{date.today():%Y%m%d}" / "do_khop_ocr_sach.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["van_ban", *SUMMARY_HEADER])
        w.writerows(rows)
        w.writerow(["TOAN_BO", *total])
    log.info("Độ khớp OCR văn bia ↔ sách (toàn bộ): TB theo box %s%%, theo chữ %s%% → %s", total[5], total[6], out)


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
    p.add_argument("--group-by", choices=["bia", "doc", "book"], default="bia",
                   help="bia: mỗi mặt bia một thư mục (mặc định); doc: mỗi văn bản (các mặt ghép '_'); book: cả cuốn")
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
    tong_hop: list[list] = []
    for folder, rows in groups.items():
        st = export_group(folder, rows, cfg)
        tong_hop += [[folder, *r] for r in st.summary]
        log.info("[%s] %d/%d trang, %d box, %d patch, %d box chưa có nhãn, %d lỗi",
                 folder, st.pages, len(rows), st.boxes, st.patches, st.unlabeled, len(st.errors))
        total.pages += st.pages; total.boxes += st.boxes; total.patches += st.patches
        total.unlabeled += st.unlabeled; total.errors += st.errors

    if tong_hop and not cfg.only:
        write_similarity_report(cfg, tong_hop)
    if cfg.version_label:
        fio.write_text(cfg.out_dir.parent / "VERSION.txt", cfg.version_label + "\n")

    ok = run_validator(cfg)
    log.info("TỔNG: %d trang, %d box, %d patch, %d chưa nhãn, %d lỗi",
             total.pages, total.boxes, total.patches, total.unlabeled, len(total.errors))
    return 0 if (ok and not total.errors) else 1


if __name__ == "__main__":
    sys.exit(main())
