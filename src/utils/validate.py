"""validate.py — cổng QA "chưa validate thì chưa giao" cho pipeline Văn bia OCR.

Kiểm tra theo Data Contract v1.0 (mục 2, 5, 6) và các ví dụ định dạng trong docx đề bài.
Mỗi luật có MÃ riêng; log chỉ ghi `vị trí + mã + mô tả`, KHÔNG chép nội dung sách/nhãn
(log nằm trong repo, nội dung sách không được đưa ra ngoài).

Chạy từ gốc repo:
    python -m src.utils.validate                        # mọi giai đoạn
    python -m src.utils.validate --stage bbox align     # chỉ một số giai đoạn
    python -m src.utils.validate --only 02459-31        # giới hạn bia_id (bbox, align)
    python -m src.utils.validate --strict               # CẢNH BÁO cũng làm thất bại
    python -m src.utils.validate --log reports/validate_20261113.txt
    python -m src.utils.validate --selftest             # file lỗi giả phải bị bắt đúng mã

Mã thoát 0 = đạt (không LỖI). Hook cho export: `validate_dataset_ocr(out_dir) -> bool`.

Bảng mã luật
  F1-F4  file text: UTF-8 không BOM · không CR · NFC · kết thúc bằng một LF
  M1-M5  metadata: file có mặt · đủ cột · bia_id duy nhất · ảnh tồn tại & đúng kích thước · doc_id có trong inventory
  TEXT-V1..V8  văn bản sạch (dùng lại check_van_ban_sach)
  B0-B8  bbox_chuan: đọc được · schema · cấu trúc box · order liên tục · region · source · 4 điểm · trong ảnh · thứ tự TL,TR,BR,BL · chồng lấn IoU
  A0-A9  align: đọc được · schema · item · status · ok phải có text_gt · khớp order với bbox_chuan · region · tỉ lệ ok · needs_review.csv
  D0-D16 dataset_ocr: cấu trúc thư mục · tên file · ảnh ≤1024 · patch cao ≤96 · det_gt · rec_gt · results.xlsx · đối soát số lượng
  Y0-Y10 dataset_dich: file rỗng · JSON · trường · bia_id · id liên tục · score · cặp thiếu trường · ký tự lạ · đối chiếu với Chu_Han
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import regex
from openpyxl import Workbook, load_workbook
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1

# ---- ngưỡng (đồng bộ với docx và Data Contract) ----
MAX_SIDE = 1024            # docx: cạnh dài ảnh trang ≤ 1024 px
PATCH_MAX_H = 96           # docx: chiều cao patch ≤ 96 px
IOU_MAX = 0.5              # Data Contract §6: không cặp box nào IoU > 0.5
MIN_OK_RATE = 0.30         # cảnh báo khi tỉ lệ box ok của một bia thấp hơn (ngưỡng tạm, nhóm tự chỉnh)
TALL_PATCH_RATIO = 1.2     # patch cao hơn rộng quá mức này ⇒ nghi chưa xoay

RESULTS_HEADER = ["Image ID", "Patch ID", "Bounding Box", "SinoNom OCR"]
REGIONS = {"tran", "than"}
ALIGN_STATUS = {"ok", "needs_review", "unmatched"}
BBOX_SOURCES = {"auto", "manual"}
NEEDS_REVIEW_COLS = ["bia_id", "order", "text_ocr", "text_gt", "score", "ly_do", "nguoi_sua", "da_sua"]
WILDCARDS = "○□◇△?？*•■"                       # ký hiệu chữ mờ/khuyết trong sách (như align_schema)
HAN_PUNCT = "。，、；：？！「」『』（）《》〈〉…·—"
HAN_OK = regex.compile(rf"(?:\p{{Han}}|[{regex.escape(HAN_PUNCT)}]|[{regex.escape(WILDCARDS)}])+")
KINDS = ("Chu_Han", "Phien_am", "Dich_nghia")


# =====================================================================  báo cáo
@dataclass
class Issue:
    level: str          # "LỖI" | "CẢNH BÁO"
    code: str
    where: str
    msg: str


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    tables: dict[str, tuple[list[str], list[list]]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def err(self, code: str, where, msg: str) -> None:
        self.issues.append(Issue("LỖI", code, str(where), msg))

    def warn(self, code: str, where, msg: str) -> None:
        self.issues.append(Issue("CẢNH BÁO", code, str(where), msg))

    @property
    def n_err(self) -> int:
        return sum(i.level == "LỖI" for i in self.issues)

    @property
    def n_warn(self) -> int:
        return sum(i.level == "CẢNH BÁO" for i in self.issues)


# =====================================================================  tiện ích
def _rel(path: Path, root: Path | None) -> str:
    try:
        return path.relative_to(root).as_posix() if root else path.as_posix()
    except ValueError:
        return path.as_posix()


def read_text_checked(path: Path, rep: Report, root: Path | None) -> str | None:
    """Đọc file text và kiểm F1–F4. Trả None nếu không đọc được."""
    where = _rel(path, root)
    raw = path.read_bytes()
    if raw == b"":
        return ""
    if raw.startswith(b"\xef\xbb\xbf"):
        rep.err("F1", where, "có BOM")
    try:
        text = raw.decode("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8")
    except UnicodeDecodeError as e:
        rep.err("F1", where, f"không phải UTF-8: {e.reason}")
        return None
    if b"\r" in raw:
        rep.err("F2", where, "có ký tự CR (\\r)")
    if text != unicodedata.normalize("NFC", text):
        rep.err("F3", where, "không ở dạng NFC")
    if not text.endswith("\n"):
        rep.err("F4", where, "không kết thúc bằng một LF")
    return text


def parse_points(v) -> list[list[float]] | None:
    try:
        if not isinstance(v, list) or len(v) != 4:
            return None
        out = []
        for p in v:
            if not isinstance(p, (list, tuple)) or len(p) != 2:
                return None
            x, y = float(p[0]), float(p[1])
            if isinstance(p[0], bool) or isinstance(p[1], bool):
                return None
            out.append([x, y])
        return out
    except (TypeError, ValueError):
        return None


def quad_problem(pts: list[list[float]]) -> str | None:
    """Kiểm thứ tự 4 điểm trên-trái, trên-phải, dưới-phải, dưới-trái (hệ tọa độ ảnh, y hướng xuống)."""
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = pts
    area2 = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
    if abs(area2) < 8:
        return "diện tích ≈ 0"
    if area2 < 0:
        return "thứ tự điểm ngược chiều kim đồng hồ (cần TL,TR,BR,BL)"
    if (y0 + y1) / 2 > (y2 + y3) / 2:
        return "hai điểm trên nằm thấp hơn hai điểm dưới"
    if (x0 + x3) / 2 > (x1 + x2) / 2:
        return "hai điểm trái nằm bên phải hai điểm phải"
    return None


def _rect(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def iou(a, b) -> float:
    ax0, ay0, ax1, ay1 = _rect(a)
    bx0, by0, bx1, by1 = _rect(b)
    iw, ih = min(ax1, bx1) - max(ax0, bx0), min(ay1, by1) - max(ay0, by0)
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / ua if ua > 0 else 0.0


def folder_name(name: str) -> str:
    """Giống sanitize_folder_name của export_ocr_dataset (để đối soát tên thư mục)."""
    name = unicodedata.normalize("NFC", name)
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, " ")
    return " ".join(name.split()).strip(" .")


def image_size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


def non_han_codes(text: str) -> list[str]:
    bad = sorted({c for c in text if not HAN_OK.fullmatch(c)})
    return [f"U+{ord(c):04X}" for c in bad]


def read_csv_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# =====================================================================  metadata
def validate_metadata(root: Path, rep: Report):
    meta = root / "data" / "metadata"
    manifest: dict[str, dict] = {}
    inventory: dict[str, dict] = {}
    inv_p, man_p = meta / "inventory.csv", meta / "bia_manifest.csv"
    if not inv_p.exists():
        rep.warn("M1", _rel(inv_p, root), "chưa có (cần cho export và đối soát số lượng)")
    else:
        rows = read_csv_rows(inv_p)
        need = {"doc_id", "ten_van_ban"}
        if rows and not need <= set(rows[0]):
            rep.err("M2", _rel(inv_p, root), f"thiếu cột: {sorted(need - set(rows[0]))}")
        inventory = {r["doc_id"]: r for r in rows if r.get("doc_id")}
    if not man_p.exists():
        rep.warn("M1", _rel(man_p, root), "chưa có (export_ocr_dataset bắt buộc có file này)")
        return manifest, inventory
    rows = read_csv_rows(man_p)
    need = {"bia_id", "file_anh", "rong_px", "cao_px", "doc_id"}
    if rows and not need <= set(rows[0]):
        rep.err("M2", _rel(man_p, root), f"thiếu cột: {sorted(need - set(rows[0]))}")
        return manifest, inventory
    for i, r in enumerate(rows, 2):
        bid = r["bia_id"]
        where = f"{_rel(man_p, root)}:{i}"
        if bid in manifest:
            rep.err("M3", where, f"bia_id trùng: {bid}")
        manifest[bid] = r
        img = root / "data" / "raw" / "anh_bia" / r["file_anh"]
        if "/" in r["file_anh"] or "\\" in r["file_anh"]:
            rep.err("M4", where, "file_anh phải là TÊN FILE, không chứa đường dẫn")
        elif not img.exists():
            rep.err("M4", where, f"không thấy ảnh data/raw/anh_bia/{r['file_anh']}")
        else:
            sz = image_size(img)
            if sz and (str(sz[0]), str(sz[1])) != (r["rong_px"], r["cao_px"]):
                rep.err("M4", where, f"kích thước ảnh {sz[0]}x{sz[1]} khác manifest {r['rong_px']}x{r['cao_px']}")
        if inventory and r["doc_id"] not in inventory:
            rep.err("M5", where, f"doc_id {r['doc_id']} không có trong inventory.csv")
    return manifest, inventory


# =====================================================================  văn bản sạch (dùng lại checker của bước 1)
def validate_text(root: Path, rep: Report) -> None:
    base = root / "data" / "processed"
    if not any((base / k).is_dir() for k in KINDS):
        rep.err("TEXT-V6", "data/processed", "thiếu cả 3 thư mục Chu_Han/Phien_am/Dich_nghia")
        return
    try:
        from src.step1_book_mining.check_van_ban_sach import check_dir
    except ImportError as e:
        rep.warn("TEXT-V0", "check_van_ban_sach", f"không import được ({e}); bỏ qua kiểm văn bản")
        return
    report, _ = check_dir(base)
    rep.notes.append("text: " + report[0].lstrip("# "))
    for line in report[1:]:
        m = re.search(r"\s(V\d)\s", line)
        rep.err(f"TEXT-{m.group(1) if m else 'V?'}", "data/processed", line)


# =====================================================================  bbox_chuan
def validate_bbox(root: Path, rep: Report, only: set[str], manifest: dict) -> dict[str, dict]:
    d = root / "data" / "processed" / "bbox_chuan"
    info: dict[str, dict] = {}
    if not d.is_dir():
        rep.warn("B0", _rel(d, root), "chưa có thư mục bbox_chuan")
        return info
    rows = []
    for p in sorted(d.glob("*.json")):
        if only and p.stem not in only:
            continue
        where = _rel(p, root)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            rep.err("B0", where, f"không đọc được JSON: {type(e).__name__}")
            continue
        if data.get("schema_version") != SCHEMA_VERSION:
            rep.err("B1", where, f"schema_version={data.get('schema_version')!r}, cần {SCHEMA_VERSION}")
        if data.get("bia_id") != p.stem:
            rep.err("B1", where, "bia_id trong file khác tên file")
        boxes = data.get("boxes")
        if not isinstance(boxes, list):
            rep.err("B2", where, "'boxes' phải là danh sách")
            continue
        size = None
        if p.stem in manifest:
            r = manifest[p.stem]
            try:
                size = (int(r["rong_px"]), int(r["cao_px"]))
            except (ValueError, KeyError):
                size = None
        if size is None:
            cand = sorted((root / "data" / "raw" / "anh_bia").glob(f"{p.stem}.*"))
            size = image_size(cand[0]) if cand else None
        if size is None:
            rep.warn("B5", where, "không tìm thấy ảnh gốc, bỏ qua kiểm tọa độ trong ảnh")
        orders, regions, rects, srcs = [], {}, [], Counter()
        for b in boxes:
            o = b.get("order")
            if not isinstance(o, int) or isinstance(o, bool):
                rep.err("B2", where, f"order không phải số nguyên: {o!r}")
                continue
            orders.append(o)
            reg = b.get("region")
            regions[o] = reg
            if reg not in REGIONS:
                rep.err("B4", f"{where} order={o}", f"region={reg!r} không thuộc {sorted(REGIONS)}")
            src = b.get("source")
            srcs[src] += 1
            if src is None:
                rep.warn("B7", f"{where} order={o}", "thiếu trường source")
            elif src not in BBOX_SOURCES:
                rep.err("B7", f"{where} order={o}", f"source={src!r} không thuộc {sorted(BBOX_SOURCES)}")
            pts = parse_points(b.get("points"))
            if pts is None:
                rep.err("B2", f"{where} order={o}", "points phải gồm đúng 4 điểm [x,y] số")
                continue
            prob = quad_problem(pts)
            if prob:
                rep.err("B6", f"{where} order={o}", prob)
            if size:
                w, h = size
                if any(not (0 <= x <= w and 0 <= y <= h) for x, y in pts):
                    rep.err("B5", f"{where} order={o}", f"tọa độ nằm ngoài ảnh {w}x{h}")
            rects.append((o, pts))
        if sorted(orders) != list(range(1, len(orders) + 1)):
            rep.err("B3", where, "order phải liên tục 1..n, không trùng, không nhảy số")
        seq = [regions[o] for o in sorted(regions)]
        if "than" in seq and "tran" in seq[seq.index("than"):]:
            rep.err("B4", where, "box tran xuất hiện sau box than (trán phải đứng trước thân)")
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                v = iou(rects[i][1], rects[j][1])
                if v > IOU_MAX:
                    rep.err("B8", where, f"order {rects[i][0]} và {rects[j][0]} chồng lấn IoU={v:.2f} > {IOU_MAX}")
        info[p.stem] = {"orders": set(orders), "regions": regions, "n": len(boxes)}
        rows.append([p.stem, len(boxes), sum(r == "tran" for r in regions.values()),
                     sum(r == "than" for r in regions.values()), srcs.get("manual", 0)])
    if rows:
        rows.append(["TỔNG", sum(r[1] for r in rows), sum(r[2] for r in rows), sum(r[3] for r in rows), sum(r[4] for r in rows)])
        rep.tables["bbox_chuan"] = (["bia_id", "box", "tran", "than", "sửa tay"], rows)
    return info


# =====================================================================  align
def validate_align(root: Path, rep: Report, only: set[str], bbox_info: dict, min_ok_rate: float) -> dict[str, dict]:
    d = root / "data" / "processed" / "align"
    stats: dict[str, dict] = {}
    if not d.is_dir():
        rep.warn("A0", _rel(d, root), "chưa có thư mục align")
        return stats
    rows, review_total = [], 0
    for p in sorted(d.glob("*.json")):
        if only and p.stem not in only:
            continue
        where = _rel(p, root)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            rep.err("A0", where, f"không đọc được JSON: {type(e).__name__}")
            continue
        if data.get("schema_version") != SCHEMA_VERSION:
            rep.err("A1", where, f"schema_version={data.get('schema_version')!r}, cần {SCHEMA_VERSION}")
        if data.get("bia_id") != p.stem:
            rep.err("A1", where, "bia_id trong file khác tên file")
        items = data.get("items")
        if not isinstance(items, list):
            rep.err("A2", where, "'items' phải là danh sách")
            continue
        orders, st = [], Counter()
        for it in items:
            o = it.get("order")
            if not isinstance(o, int) or isinstance(o, bool) or o <= 0:
                rep.err("A2", where, f"order không hợp lệ: {o!r}")
                continue
            orders.append(o)
            loc = f"{where} order={o}"
            status = it.get("status")
            st[status] += 1
            if status not in ALIGN_STATUS:
                rep.err("A3", loc, f"status={status!r} không thuộc {sorted(ALIGN_STATUS)}")
            sc = it.get("score")
            if not isinstance(sc, (int, float)) or isinstance(sc, bool) or not 0 <= sc <= 1:
                rep.err("A5", loc, f"score phải là số trong [0,1], nhận {sc!r}")
            gt, ocr = it.get("text_gt", ""), it.get("text_ocr", "")
            if not isinstance(gt, str) or not isinstance(ocr, str):
                rep.err("A2", loc, "text_gt/text_ocr phải là chuỗi")
                continue
            if any(c in gt + ocr for c in "\t\n\r"):
                rep.err("A6", loc, "text chứa tab/xuống dòng (làm hỏng file TSV khi xuất)")
            if status == "ok" and not gt.strip():
                rep.err("A4", loc, "status ok nhưng text_gt rỗng")
            if gt and status == "ok":
                bad = non_han_codes(gt)
                if bad:
                    rep.warn("A5", loc, "text_gt có ký tự ngoài Hán/dấu câu/ký hiệu khuyết: " + " ".join(bad[:6]))
        if len(orders) != len(set(orders)):
            rep.err("A2", where, "order trùng trong items")
        bb = bbox_info.get(p.stem)
        if bb is None:
            rep.err("A2", where, "không có bbox_chuan tương ứng để đối chiếu")
        else:
            if set(orders) != bb["orders"]:
                miss, extra = sorted(bb["orders"] - set(orders)), sorted(set(orders) - bb["orders"])
                rep.err("A2", where, f"order lệch bbox_chuan: thiếu {len(miss)}, thừa {len(extra)}")
            else:
                for it in items:
                    if it.get("region") and bb["regions"].get(it["order"]) not in (None, it["region"]):
                        rep.warn("A7", f"{where} order={it['order']}", "region khác bbox_chuan")
        n = len(items)
        ok_rate = st["ok"] / n if n else 0.0
        if n and ok_rate < min_ok_rate:
            rep.warn("A8", where, f"tỉ lệ ok thấp: {st['ok']}/{n} = {ok_rate:.1%} (< {min_ok_rate:.0%})")
        review_total += st["needs_review"]
        stats[p.stem] = {"n": n, "ok": st["ok"], "review": st["needs_review"], "unmatched": st["unmatched"]}
        rows.append([p.stem, n, st["ok"], st["needs_review"], st["unmatched"], f"{ok_rate:.1%}"])
    for bid in sorted(set(bbox_info) - set(stats)):
        if not only or bid in only:
            rep.warn("A2", f"data/processed/bbox_chuan/{bid}.json", "có bbox_chuan nhưng chưa có align")
    if rows:
        tn, tok = sum(r[1] for r in rows), sum(r[2] for r in rows)
        rows.append(["TỔNG", tn, tok, sum(r[3] for r in rows), sum(r[4] for r in rows), f"{(tok / tn if tn else 0):.1%}"])
        rep.tables["align"] = (["bia_id", "box", "ok", "needs_review", "unmatched", "ok%"], rows)
    nr = root / "data" / "processed" / "needs_review.csv"
    if nr.exists():
        text = read_text_checked(nr, rep, root)
        if text is not None:
            reader = list(csv.reader(text.splitlines()))
            if reader and reader[0] != NEEDS_REVIEW_COLS:
                rep.err("A9", _rel(nr, root), "header khác Data Contract §5.5")
            n_rows = max(len(reader) - 1, 0)
            if not only and n_rows != review_total:
                rep.warn("A9", _rel(nr, root), f"{n_rows} dòng nhưng align có {review_total} box needs_review "
                         "(có thể do chạy lại một phần)")
            for i, r in enumerate(reader[1:], 2):
                if len(r) == len(NEEDS_REVIEW_COLS) and r[-1] not in ("0", "1"):
                    rep.err("A9", f"{_rel(nr, root)}:{i}", "da_sua phải là 0 hoặc 1")
    return stats


# =====================================================================  dataset_ocr
def _check_dataset_ocr_dir(out_dir: Path, rep: Report, root: Path | None,
                           expected: dict[str, dict] | None = None) -> None:
    rows_tbl = []
    if not out_dir.is_dir():
        rep.err("D0", _rel(out_dir, root), "thiếu thư mục dataset_ocr")
        return
    folders = sorted(p for p in out_dir.iterdir() if p.is_dir())
    if not folders:
        rep.err("D0", _rel(out_dir, root), "dataset_ocr rỗng (chưa có thư mục văn bản nào)")
    for d in folders:
        fname = d.name
        w0 = _rel(d, root)
        for need in ("images", "patches"):
            if not (d / need).is_dir():
                rep.err("D1", w0, f"thiếu thư mục {need}/")
        for need in ("det_gt.txt", "rec_gt.txt", "results.xlsx"):
            if not (d / need).is_file():
                rep.err("D1", w0, f"thiếu file {need}")
        # ---- ảnh trang
        img_re = re.compile(rf"^{re.escape(fname)}\.(\d{{3}})\.jpg$")
        images: dict[str, tuple[int, int]] = {}
        for p in sorted((d / "images").glob("*")) if (d / "images").is_dir() else []:
            if not img_re.match(p.name):
                rep.err("D2", _rel(p, root), f"tên ảnh phải là '{fname}.NNN.jpg' (NNN 3 chữ số)")
            try:
                with Image.open(p) as im:
                    fmt, size = im.format, im.size
            except Exception:
                rep.err("D3", _rel(p, root), "không mở được ảnh")
                continue
            if fmt != "JPEG":
                rep.err("D3", _rel(p, root), f"định dạng thực là {fmt}, cần JPEG")
            if max(size) > MAX_SIDE:
                rep.err("D3", _rel(p, root), f"cạnh dài {max(size)} > {MAX_SIDE}")
            images[p.name] = size
        # ---- patch
        patch_re = re.compile(rf"^{re.escape(fname)}\.(\d{{3}})\.(\d{{3}})\.jpg$")
        patches: dict[str, tuple[int, int]] = {}
        for p in sorted((d / "patches").glob("*")) if (d / "patches").is_dir() else []:
            if not patch_re.match(p.name):
                rep.err("D2", _rel(p, root), f"tên patch phải là '{fname}.NNN.MMM.jpg'")
            try:
                with Image.open(p) as im:
                    fmt, size = im.format, im.size
            except Exception:
                rep.err("D4", _rel(p, root), "không mở được patch")
                continue
            if fmt != "JPEG":
                rep.err("D4", _rel(p, root), f"định dạng thực là {fmt}, cần JPEG")
            if size[1] > PATCH_MAX_H:
                rep.err("D4", _rel(p, root), f"chiều cao {size[1]} > {PATCH_MAX_H}")
            if size[1] > size[0] * TALL_PATCH_RATIO:
                rep.warn("D4", _rel(p, root), f"patch {size[0]}x{size[1]} cao hơn rộng: nghi chưa xoay cột đứng")
            patches[p.name] = size
        # ---- det_gt
        det_boxes: dict[str, list[tuple]] = {}
        n_box = n_ign = n_unl = 0
        det_p = d / "det_gt.txt"
        if det_p.is_file():
            text = read_text_checked(det_p, rep, root)
            seen = set()
            for i, line in enumerate((text or "").splitlines(), 1):
                loc = f"{_rel(det_p, root)}:{i}"
                if line.count("\t") != 1:
                    rep.err("D5", loc, "dòng phải có đúng 1 TAB giữa đường dẫn và JSON")
                    continue
                path, js = line.split("\t")
                if not path.startswith(f"{fname}/images/"):
                    rep.err("D5", loc, f"đường dẫn phải bắt đầu bằng '{fname}/images/'")
                img_name = path.rsplit("/", 1)[-1]
                if img_name not in images:
                    rep.err("D5", loc, "ảnh được trỏ tới không tồn tại")
                if img_name in seen:
                    rep.err("D5", loc, "ảnh xuất hiện nhiều hơn một dòng")
                seen.add(img_name)
                try:
                    arr = json.loads(js)
                except Exception:
                    rep.err("D5", loc, "JSON không hợp lệ")
                    continue
                if not isinstance(arr, list):
                    rep.err("D5", loc, "JSON phải là danh sách box")
                    continue
                size = images.get(img_name)
                for k, a in enumerate(arr):
                    pts = parse_points(a.get("points")) if isinstance(a, dict) else None
                    if pts is None or not isinstance(a.get("transcription"), str):
                        rep.err("D5", loc, f"box #{k + 1}: cần 'points' (4 điểm) và 'transcription' (chuỗi)")
                        continue
                    n_box += 1
                    if a["transcription"] == "###":
                        n_ign += 1
                    if a["transcription"] in ("###", ""):
                        n_unl += 1
                    prob = quad_problem(pts)
                    if prob:
                        rep.err("D5", loc, f"box #{k + 1}: {prob}")
                    if size and any(not (0 <= x < size[0] and 0 <= y < size[1]) for x, y in pts):
                        rep.err("D5", loc, f"box #{k + 1}: tọa độ ngoài ảnh {size[0]}x{size[1]}")
                    det_boxes.setdefault(img_name, []).append(tuple(map(tuple, pts)))
            for missing in sorted(set(images) - seen):
                rep.err("D5", _rel(det_p, root), f"ảnh {missing} không có dòng nào trong det_gt.txt")
            if n_ign:
                rep.warn("D10", _rel(det_p, root),
                         f"{n_ign}/{n_box} box có transcription '###'; docx quy định mặc định là chuỗi rỗng")
        # ---- rec_gt
        rec_text: dict[str, str] = {}
        rec_p = d / "rec_gt.txt"
        if rec_p.is_file():
            text = read_text_checked(rec_p, rep, root)
            for i, line in enumerate((text or "").splitlines(), 1):
                loc = f"{_rel(rec_p, root)}:{i}"
                if line.count("\t") != 1:
                    rep.err("D6", loc, "dòng phải có đúng 1 TAB giữa đường dẫn và nhãn")
                    continue
                path, label = line.split("\t")
                pname = path.rsplit("/", 1)[-1]
                if not path.startswith(f"{fname}/patches/") or pname not in patches:
                    rep.err("D6", loc, "đường dẫn patch sai hoặc patch không tồn tại")
                if pname in rec_text:
                    rep.err("D6", loc, "patch xuất hiện nhiều hơn một dòng")
                if not label.strip():
                    rep.err("D6", loc, "nhãn rỗng")
                else:
                    bad = non_han_codes(label)
                    if bad:
                        rep.warn("D6", loc, "nhãn có ký tự ngoài Hán/dấu câu/ký hiệu khuyết: " + " ".join(bad[:6]))
                rec_text[pname] = label
            for pn in sorted(set(patches) - set(rec_text)):
                rep.err("D7", _rel(rec_p, root), f"patch {pn} không có dòng trong rec_gt.txt")
        # ---- results.xlsx
        xl = d / "results.xlsx"
        n_rows = 0
        if xl.is_file():
            try:
                wb = load_workbook(xl, read_only=True, data_only=True)
                allrows = list(wb.active.iter_rows(values_only=True))
                wb.close()
            except Exception as e:
                rep.err("D8", _rel(xl, root), f"không đọc được xlsx: {type(e).__name__}")
                allrows = []
            if allrows:
                head = [str(c) if c is not None else "" for c in allrows[0][:4]]
                if head != RESULTS_HEADER:
                    rep.err("D8", _rel(xl, root), f"header phải là {RESULTS_HEADER}")
                last_by_img: dict[str, int] = {}
                for i, row in enumerate(allrows[1:], 2):
                    n_rows += 1
                    loc = f"{_rel(xl, root)}:{i}"
                    img_id, patch_id, bb, label = [("" if c is None else str(c)) for c in (list(row) + [None] * 4)[:4]]
                    if img_id not in images:
                        rep.err("D8", loc, "Image ID không khớp file ảnh nào (cần kèm .jpg)")
                    if patch_id.lower().endswith(".jpg"):
                        rep.err("D8", loc, "Patch ID có đuôi .jpg; docx: Patch ID KHÔNG kèm đuôi (vd 'Tên.001.001')")
                        patch_file = patch_id
                    else:
                        patch_file = patch_id + ".jpg"
                    if patch_file not in patches:
                        rep.err("D8", loc, "Patch ID không khớp patch nào")
                    m_i, m_p = img_re.match(img_id), patch_re.match(patch_file)
                    if m_i and m_p and m_i.group(1) != m_p.group(1):
                        rep.err("D8", loc, "số trang của Patch ID khác Image ID")
                    try:
                        pts = parse_points(json.loads(bb))
                    except Exception:
                        pts = None
                    if pts is None:
                        rep.err("D8", loc, "Bounding Box phải là JSON 4 điểm")
                    elif img_id in det_boxes and tuple(map(tuple, pts)) not in det_boxes[img_id]:
                        rep.err("D8", loc, "Bounding Box không có trong det_gt.txt của ảnh này")
                    if patch_file in rec_text and unicodedata.normalize("NFC", label) != rec_text[patch_file]:
                        rep.err("D8", loc, "SinoNom OCR khác nhãn trong rec_gt.txt")
                    if m_p:
                        seq = int(m_p.group(2))
                        if seq <= last_by_img.get(img_id, 0):
                            rep.warn("D9", loc, "số thứ tự patch không tăng dần theo thứ tự đọc")
                        last_by_img[img_id] = seq
        if not (len(rec_text) == len(patches) == n_rows):
            rep.err("D7", w0, f"số lượng không bằng nhau: rec_gt={len(rec_text)}, patch={len(patches)}, results.xlsx={n_rows}")
        # ---- đối soát số lượng với align
        if expected is not None:
            ex = expected.get(fname)
            if ex is None:
                rep.warn("D15", w0, "không suy ra được văn bản nguồn từ manifest/inventory, bỏ qua đối soát")
            else:
                if len(patches) < ex["ok"]:
                    rep.err("D15", w0, f"thiếu patch: {len(patches)} < {ex['ok']} box ok trong align")
                elif len(patches) > ex["ok"]:
                    rep.warn("D15", w0, f"nhiều patch hơn box ok ({len(patches)} > {ex['ok']}): có xuất cả needs_review?")
                if len(images) < ex["faces"]:
                    rep.err("D16", w0, f"thiếu ảnh trang: {len(images)} < {ex['faces']} mặt bia có align")
        rows_tbl.append([fname, len(images), n_box, n_unl, len(patches)])
    if rows_tbl:
        rows_tbl.append(["TỔNG"] + [sum(r[i] for r in rows_tbl) for i in range(1, 5)])
        rep.tables["dataset_ocr"] = (["văn bản", "ảnh", "box", "box chưa nhãn", "patch"], rows_tbl)


def validate_dataset_ocr(out_dir: Path) -> bool:
    """Hook cho export_ocr_dataset.run_validator: kiểm một thư mục dataset_ocr, in kết quả, trả True nếu không có LỖI."""
    rep = Report()
    _check_dataset_ocr_dir(Path(out_dir), rep, None)
    print_report(rep, ["dataset_ocr"], root=None, strict=False)
    return rep.n_err == 0


# =====================================================================  dataset_dich
def validate_dataset_dich(root: Path, rep: Report) -> None:
    d = root / "data" / "output" / "dataset_dich"
    if not d.is_dir():
        rep.err("Y0", _rel(d, root), "thiếu thư mục dataset_dich")
        return
    rows, schema_noted = [], False
    files = sorted(d.glob("*.jsonl"))
    if not files:
        rep.err("Y0", _rel(d, root), "không có file .jsonl nào")
    for p in files:
        where = _rel(p, root)
        if p.stat().st_size == 0:
            rep.warn("Y0", where, "file rỗng (0 cặp câu)")
            rows.append([p.stem, 0, 0])
            continue
        text = read_text_checked(p, rep, root)
        pairs, full, ids = 0, 0, []
        bad_han = bad_vi = 0
        bad_codes: set[str] = set()
        for i, line in enumerate((text or "").splitlines(), 1):
            loc = f"{where}:{i}"
            try:
                r = json.loads(line)
            except Exception:
                rep.err("Y1", loc, "JSON không hợp lệ")
                continue
            if not isinstance(r, dict) or not all(isinstance(r.get(k), str) for k in ("han", "phien_am", "dich_nghia")):
                rep.err("Y2", loc, "cần 3 trường chuỗi: han, phien_am, dich_nghia")
                continue
            pairs += 1
            if r.get("bia_id") != p.stem:
                rep.err("Y3", loc, "bia_id khác tên file")
            idk = "pair_id" if "pair_id" in r else ("sentence_id" if "sentence_id" in r else None)
            if idk is None:
                rep.err("Y4", loc, "thiếu pair_id/sentence_id")
            else:
                ids.append(r[idk])
                if idk == "sentence_id" and not schema_noted:
                    rep.warn("Y5", where, "dùng 'sentence_id', không có 'schema_version'/'status'; Data Contract quy định "
                             "pair_id + schema_version + status (báo một lần cho cả lô)")
                    schema_noted = True
            sc = r.get("score")
            if sc is not None and (not isinstance(sc, (int, float)) or isinstance(sc, bool) or not 0 <= sc <= 1):
                rep.err("Y6", loc, f"score phải là số trong [0,1], nhận {sc!r}")
            if all(r[k].strip() for k in ("han", "phien_am", "dich_nghia")):
                full += 1
            if r["han"].strip():
                bc = non_han_codes(r["han"])
                if bc:
                    bad_han += 1
                    bad_codes.update(bc)
            if regex.search(r"\p{Han}", r["phien_am"] + r["dich_nghia"]):
                bad_vi += 1
            for k in ("han", "phien_am", "dich_nghia"):
                if r[k] != unicodedata.normalize("NFC", r[k]):
                    rep.warn("Y9", loc, f"{k} không ở dạng NFC")
        if ids and ids != list(range(1, len(ids) + 1)):
            rep.err("Y4", where, "id phải liên tục từ 1")
        if pairs and full < pairs:
            rep.warn("Y7", where, f"{pairs - full}/{pairs} cặp thiếu ít nhất 1 trong 3 trường (Data Contract yêu cầu đủ 3)")
        if bad_han:
            rep.warn("Y8", where, f"{bad_han} dòng có ký tự ngoài Hán/dấu câu trong 'han': " + " ".join(sorted(bad_codes)[:8]))
        if bad_vi:
            rep.warn("Y8", where, f"{bad_vi} dòng lẫn chữ Hán trong phien_am/dich_nghia")
        rows.append([p.stem, pairs, full])
    ch = root / "data" / "processed" / "Chu_Han"
    if ch.is_dir():
        have = {p.stem for p in files}
        for p in sorted(ch.glob("*.txt")):
            if p.stem not in have:
                rep.warn("Y10", _rel(p, root), "có Chu_Han nhưng chưa có dataset_dich tương ứng")
        for s in sorted(have - {p.stem for p in ch.glob("*.txt")}):
            rep.warn("Y10", f"data/output/dataset_dich/{s}.jsonl", "không có Chu_Han tương ứng")
    if rows:
        rows.append(["TỔNG", sum(r[1] for r in rows), sum(r[2] for r in rows)])
        rep.tables["dataset_dich"] = (["văn bản", "cặp câu", "đủ 3 trường"], rows)


# =====================================================================  điều phối + in kết quả
STAGES = ["metadata", "text", "bbox", "align", "dataset_ocr", "dataset_dich"]


def run(root: Path, stages: list[str], only: set[str] | None = None, min_ok_rate: float = MIN_OK_RATE) -> Report:
    rep, only = Report(), only or set()
    manifest: dict = {}
    inventory: dict = {}
    bbox_info: dict = {}
    align_stats: dict = {}
    if "metadata" in stages or "bbox" in stages or "dataset_ocr" in stages:
        manifest, inventory = validate_metadata(root, rep) if "metadata" in stages else _quiet_metadata(root)
    if "text" in stages:
        validate_text(root, rep)
    if "bbox" in stages or "align" in stages:
        bbox_info = validate_bbox(root, rep, only, manifest) if "bbox" in stages else _quiet(validate_bbox, root, only, manifest)
    if "align" in stages:
        align_stats = validate_align(root, rep, only, bbox_info, min_ok_rate)
    if "dataset_ocr" in stages:
        expected = None
        if manifest and inventory:
            align_stats = align_stats or _quiet(validate_align, root, only, _quiet(validate_bbox, root, only, manifest), min_ok_rate)
            expected = defaultdict(lambda: {"ok": 0, "faces": 0})
            for bid, st in align_stats.items():
                row = manifest.get(bid)
                inv = inventory.get(row["doc_id"]) if row else None
                if inv:
                    e = expected[folder_name(inv["ten_van_ban"])]
                    e["ok"] += st["ok"]
                    e["faces"] += 1
            expected = dict(expected)
        _check_dataset_ocr_dir(root / "data" / "output" / "dataset_ocr", rep, root, expected)
    if "dataset_dich" in stages:
        validate_dataset_dich(root, rep)
    return rep


def _quiet(fn, root, only, *args):
    return fn(root, Report(), only, *args)


def _quiet_metadata(root):
    return validate_metadata(root, Report())


def _fmt_table(header: list[str], rows: list[list]) -> list[str]:
    cells = [[str(c) for c in header]] + [[str(c) for c in r] for r in rows]
    w = [max(len(r[i]) for r in cells) for i in range(len(header))]
    return ["  " + "  ".join(c.ljust(w[i]) for i, c in enumerate(r)) for r in cells]


def format_report(rep: Report, stages: list[str], root: Path | None, strict: bool, full: bool) -> list[str]:
    out = [f"# validate {datetime.now():%Y-%m-%d %H:%M}  root={'.' if root is None else root.name}  stage={','.join(stages)}"
           f"{'  [strict]' if strict else ''}"]
    out += [f"# {n}" for n in rep.notes]
    for name, (header, rows) in rep.tables.items():
        out.append(f"== {name} ==")
        out += _fmt_table(header, rows)
    groups: dict[tuple[str, str], list[Issue]] = defaultdict(list)
    for i in rep.issues:
        groups[(i.level, i.code)].append(i)
    out.append("== kết quả kiểm tra ==")
    for (level, code), items in sorted(groups.items(), key=lambda kv: (kv[0][0] != "LỖI", kv[0][1])):
        shown = items if full else items[:5]
        for it in shown:
            out.append(f"{level}  {code}  {it.where}  {it.msg}")
        if len(shown) < len(items):
            out.append(f"{level}  {code}  … và {len(items) - len(shown)} nơi khác (xem --log để có đủ)")
    failed = rep.n_err > 0 or (strict and rep.n_warn > 0)
    out.append(f"KẾT QUẢ: {'KHÔNG ĐẠT' if failed else 'ĐẠT'} — {rep.n_err} lỗi, {rep.n_warn} cảnh báo")
    return out


def print_report(rep: Report, stages: list[str], root: Path | None, strict: bool) -> None:
    print("\n".join(format_report(rep, stages, root, strict, full=False)))


# =====================================================================  selftest
def _build_fixture(root: Path) -> None:
    """Dựng một bộ dữ liệu HỢP LỆ nhỏ (1 văn bản, 1 mặt bia, 2 box) để làm nền cho selftest."""
    fn = "Van ban thu"
    W, H = 800, 1600
    meta, raw = root / "data/metadata", root / "data/raw/anh_bia"
    proc, out = root / "data/processed", root / "data/output"
    for p in (meta, raw, proc / "bbox_chuan", proc / "align", out / f"dataset_ocr/{fn}/images",
              out / f"dataset_ocr/{fn}/patches", out / "dataset_dich"):
        p.mkdir(parents=True, exist_ok=True)

    def wcsv(path, header, rows):
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n"); w.writerow(header); w.writerows(rows)

    wcsv(meta / "inventory.csv", ["doc_id", "ten_van_ban", "dinh_dang", "file_nguon", "ghi_chu"], [["D1", fn, "anh", "x", ""]])
    wcsv(meta / "bia_manifest.csv", ["bia_id", "nguon_url", "file_anh", "rong_px", "cao_px", "doc_id", "is_trial", "ghi_chu"],
         [["B1", "", "B1.jpg", W, H, "D1", 0, ""]])
    Image.new("RGB", (W, H), (230, 230, 230)).save(raw / "B1.jpg")
    boxes = [{"order": 1, "region": "tran", "points": [[100, 100], [700, 100], [700, 200], [100, 200]],
              "text_ocr": "後", "score": 0.9, "source": "auto"},
             {"order": 2, "region": "than", "points": [[600, 400], [700, 400], [700, 1400], [600, 1400]],
              "text_ocr": "佛", "score": 0.9, "source": "auto"}]
    (proc / "bbox_chuan/B1.json").write_text(json.dumps({"schema_version": 1, "bia_id": "B1", "boxes": boxes}, ensure_ascii=False), encoding="utf-8")
    items = [{"order": 1, "text_ocr": "後", "text_gt": "後", "score": 0.95, "status": "ok", "region": "tran"},
             {"order": 2, "text_ocr": "佛", "text_gt": "佛", "score": 0.95, "status": "ok", "region": "than"}]
    (proc / "align/B1.json").write_text(json.dumps({"schema_version": 1, "bia_id": "B1", "items": items}, ensure_ascii=False), encoding="utf-8")
    # dataset_ocr: ảnh trang đã resize (cạnh dài 800 ≤ 1024), 2 patch
    Image.new("RGB", (400, 800), (230, 230, 230)).save(out / f"dataset_ocr/{fn}/images/{fn}.001.jpg")
    for name, size in ((f"{fn}.001.001.jpg", (300, 50)), (f"{fn}.001.002.jpg", (90, 60))):
        Image.new("RGB", size, (20, 20, 20)).save(out / f"dataset_ocr/{fn}/patches/{name}")
    p1 = [[50, 50], [350, 50], [350, 100], [50, 100]]
    p2 = [[300, 200], [350, 200], [350, 700], [300, 700]]
    det = f"{fn}/images/{fn}.001.jpg\t" + json.dumps([{"transcription": "後", "points": p1}, {"transcription": "佛", "points": p2}], ensure_ascii=False) + "\n"
    (out / f"dataset_ocr/{fn}/det_gt.txt").write_text(det, encoding="utf-8", newline="\n")
    rec = f"{fn}/patches/{fn}.001.001.jpg\t後\n{fn}/patches/{fn}.001.002.jpg\t佛\n"
    (out / f"dataset_ocr/{fn}/rec_gt.txt").write_text(rec, encoding="utf-8", newline="\n")
    wb = Workbook(); ws = wb.active; ws.append(RESULTS_HEADER)
    ws.append([f"{fn}.001.jpg", f"{fn}.001.001", json.dumps(p1), "後"])
    ws.append([f"{fn}.001.jpg", f"{fn}.001.002", json.dumps(p2), "佛"])
    wb.save(out / f"dataset_ocr/{fn}/results.xlsx")
    pair = {"bia_id": "B1", "sentence_id": 1, "han": "後佛", "phien_am": "Hậu Phật", "dich_nghia": "Phật đời sau.", "score": 0.9}
    (out / "dataset_dich/B1.jsonl").write_text(json.dumps(pair, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    for kind, line in (("Chu_Han", "後佛"), ("Phien_am", "Hậu Phật bi kí."), ("Dich_nghia", "Bia Phật đời sau.")):
        (proc / kind).mkdir(parents=True, exist_ok=True)
        (proc / kind / "B1.txt").write_text(line + "\n", encoding="utf-8", newline="\n")


def selftest() -> int:
    import shutil
    FN = "Van ban thu"

    def edit_json(rel, fn):
        def go(root):
            p = root / rel
            d = json.loads(p.read_text(encoding="utf-8")); fn(d)
            p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return go

    def edit_text(rel, old, new):
        def go(root):
            p = root / rel
            p.write_bytes(p.read_bytes().replace(old.encode(), new.encode()))
        return go

    def img(rel, size):
        return lambda root: Image.new("RGB", size).save(root / rel)

    def xlsx_patch_id(root):
        p = root / f"data/output/dataset_ocr/{FN}/results.xlsx"
        wb = load_workbook(p); ws = wb.active; ws["B2"] = ws["B2"].value + ".jpg"; wb.save(p)

    def drop_rec_line(root):
        p = root / f"data/output/dataset_ocr/{FN}/rec_gt.txt"
        p.write_text(p.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8", newline="\n")

    ocr = f"data/output/dataset_ocr/{FN}"
    cases = [
        ("bbox order nhảy số", "B3", edit_json("data/processed/bbox_chuan/B1.json", lambda d: d["boxes"][1].update(order=5))),
        ("bbox tọa độ ngoài ảnh", "B5", edit_json("data/processed/bbox_chuan/B1.json", lambda d: d["boxes"][0].update(points=[[100, 100], [9000, 100], [9000, 200], [100, 200]]))),
        ("bbox sai thứ tự điểm", "B6", edit_json("data/processed/bbox_chuan/B1.json", lambda d: d["boxes"][0].update(points=[[700, 100], [100, 100], [100, 200], [700, 200]]))),
        ("bbox chồng lấn", "B8", edit_json("data/processed/bbox_chuan/B1.json", lambda d: d["boxes"][1].update(points=[[100, 110], [700, 110], [700, 190], [100, 190]]))),
        ("bbox region sai", "B4", edit_json("data/processed/bbox_chuan/B1.json", lambda d: d["boxes"][0].update(region="giua"))),
        ("align thiếu order", "A2", edit_json("data/processed/align/B1.json", lambda d: d["items"].pop())),
        ("align status lạ", "A3", edit_json("data/processed/align/B1.json", lambda d: d["items"][0].update(status="xong"))),
        ("align ok mà text_gt rỗng", "A4", edit_json("data/processed/align/B1.json", lambda d: d["items"][0].update(text_gt=""))),
        ("align score ngoài [0,1]", "A5", edit_json("data/processed/align/B1.json", lambda d: d["items"][0].update(score=1.7))),
        ("ảnh trang > 1024", "D3", img(f"{ocr}/images/{FN}.001.jpg", (1500, 900))),
        ("patch cao > 96", "D4", img(f"{ocr}/patches/{FN}.001.001.jpg", (300, 200))),
        ("rec_gt thiếu dòng", "D7", drop_rec_line),
        ("Patch ID có .jpg (docx)", "D8", xlsx_patch_id),
        ("det_gt có ###", "D10", edit_text(f"{ocr}/det_gt.txt", '"transcription": "後"', '"transcription": "###"')),
        ("dataset_dich thiếu trường", "Y2",
         lambda root: (root / "data/output/dataset_dich/B1.jsonl").write_text(
             '{"bia_id":"B1","sentence_id":1,"han":"後"}\n', encoding="utf-8", newline="\n")),
        ("dataset_dich bia_id sai", "Y3", edit_text("data/output/dataset_dich/B1.jsonl", '"bia_id": "B1"', '"bia_id": "X9"')),
        ("file có BOM", "F1", lambda root: (root / f"{ocr}/rec_gt.txt").write_bytes(b"\xef\xbb\xbf" + (root / f"{ocr}/rec_gt.txt").read_bytes())),
        ("file có CRLF", "F2", lambda root: (root / f"{ocr}/rec_gt.txt").write_bytes((root / f"{ocr}/rec_gt.txt").read_bytes().replace(b"\n", b"\r\n"))),
        ("manifest sai kích thước", "M4", edit_text("data/metadata/bia_manifest.csv", ",800,1600,", ",801,1600,")),
    ]
    ok_all = True
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "base"
        _build_fixture(base)
        rep = run(base, STAGES)
        clean = rep.n_err == 0
        ok_all &= clean
        print(f"  {'OK ' if clean else 'MISS'} bộ hợp lệ → 0 lỗi (nhận {rep.n_err} lỗi: {sorted({i.code for i in rep.issues if i.level == 'LỖI'})})")
        for k, (name, code, mutate) in enumerate(cases):
            work = Path(td) / f"case{k}"
            shutil.copytree(base, work)
            mutate(work)
            got = {i.code for i in run(work, STAGES).issues}
            hit = code in got
            ok_all &= hit
            print(f"  {'OK ' if hit else 'MISS'} {name:32s} kỳ vọng {code}, bắt được {sorted(got)}")
    print("selftest:", "ĐẠT" if ok_all else "KHÔNG ĐẠT")
    return 0 if ok_all else 1


# =====================================================================  CLI
def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT, help="gốc repo (mặc định: tự suy ra)")
    ap.add_argument("--stage", nargs="*", choices=STAGES, default=STAGES, help="các giai đoạn cần kiểm (mặc định: tất cả)")
    ap.add_argument("--only", nargs="*", default=[], help="chỉ kiểm các bia_id này (bbox, align)")
    ap.add_argument("--strict", action="store_true", help="CẢNH BÁO cũng làm thất bại")
    ap.add_argument("--min-ok-rate", type=float, default=MIN_OK_RATE, help="cảnh báo bia có tỉ lệ ok thấp hơn mức này")
    ap.add_argument("--log", type=Path, help="ghi báo cáo đầy đủ ra file (UTF-8, LF)")
    ap.add_argument("--selftest", action="store_true", help="file lỗi giả phải bị bắt đúng mã")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    rep = run(a.root, a.stage, set(a.only), a.min_ok_rate)
    print("\n".join(format_report(rep, a.stage, a.root, a.strict, full=False)))
    if a.log:
        a.log.parent.mkdir(parents=True, exist_ok=True)
        a.log.write_text("\n".join(format_report(rep, a.stage, a.root, a.strict, full=True)) + "\n", encoding="utf-8", newline="\n")
    return 1 if (rep.n_err or (a.strict and rep.n_warn)) else 0


if __name__ == "__main__":
    raise SystemExit(main())