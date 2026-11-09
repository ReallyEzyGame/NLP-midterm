"""Pipeline bước 1.A — một lệnh: OCR sách → tách & làm sạch → ghi theo mã bia → kiểm tra → báo cáo (→ zip).

Quy ước (giảng viên, 09/11/2026): **không tách theo mặt** — mỗi văn bia giữ nguyên bài, một bộ 3 file
``data/processed/{Chu_Han,Phien_am,Dich_nghia}/<tên>.txt``, ``<tên>`` = các ``bia_id`` có ảnh của văn bia nối bằng ``_``
theo thứ tự mặt trong ``data/metadata/stt_bia_map.csv`` (vd STT 22 → ``02440-21_02441-22``; bia 1 mặt → ``02439``).

Các bước (chạy lại được; trang đã OCR thì bỏ qua):
  1. OCR      ``ocr_gemini.py`` (gemini-3.5-flash-lite) — chỉ trang chưa OCR; ``--khong-ocr`` để không gọi API.
  2. Tách     ``clean_book_text.process`` → bản nháp ``data/interim/van_ban_nhap/<loại>/VBLN-<STT>.txt``.
     (làm sạch chung trong ``regex_filter.py``: cấu trúc + chuẩn hoá máy móc Hán/Việt; KHÔNG đối chiếu từng chữ)
  3. Ghi      ``data/processed/<loại>/<tên>.txt``.
  4. Kiểm tra checker V1–V8 + cờ tự động (tỉ lệ âm tiết Phiên âm / chữ Hán lệch → sách rút gọn hoặc OCR sót đoạn).
  5. Báo cáo ``reports/pipeline_1a_<yyyymmdd>.tsv`` (KHÔNG chứa nội dung sách); ``--zip`` để đóng gói bàn giao.
  +  File kê mã ``data/metadata/van_ban_ma_bia.csv``: mỗi văn bản đã ghi gồm những mã mặt bia nào (``danh_sach_bia_id``, nối ``|``),
     STT, trang sách, số mặt theo sách / có ảnh. Chạy một phần (``--bia``) thì chỉ cập nhật các STT vừa chạy, giữ nguyên dòng cũ.

Làm sạch chung hoàn toàn bằng quy tắc (``regex_filter.py``); KHÔNG sửa tay từng chữ, không đối chiếu ảnh.

Chạy (từ NLP-midterm):
    python -m src.step1_book_mining.pipeline_1a --bia 22,25,27            # 3 bia thử
    python -m src.step1_book_mining.pipeline_1a                           # mọi văn bia có ảnh (stt_bia_map.csv)
    python -m src.step1_book_mining.pipeline_1a --khong-ocr --zip         # không gọi API, đóng gói
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

from . import clean_book_text as sb

ROOT = Path(__file__).resolve().parents[2]
KINDS = ("Chu_Han", "Phien_am", "Dich_nghia")
MAP = ROOT / "data/metadata/stt_bia_map.csv"
KE_MA = ROOT / "data/metadata/van_ban_ma_bia.csv"
BO_SUNG = ROOT / "data/metadata/bo_sung_mat_bia.csv"      # mặt bổ sung / xác nhận số mặt trên Vietnamica
KE_MA_COLS = ["ten_file", "doc_id", "stt", "danh_sach_bia_id", "so_mat_co_anh", "so_mat_theo_sach", "trang_sach", "ghi_chu"]
OUT = ROOT / "data/processed"
HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0002ffff]")
TI_LE = (0.9, 1.15)                                    # âm tiết Phiên âm / chữ Hán ngoài khoảng này ⇒ cờ


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def read_tsv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with open(p, encoding="utf-8", newline="") as f:
        return [{k: nfc(v or "") for k, v in r.items()} for r in csv.DictReader(f, delimiter="\t")]


def read_lines(p: Path) -> list[str]:
    return [l for l in nfc(p.read_text(encoding="utf-8")).split("\n") if l] if p.exists() else []


def write_lines(p: Path, lines: list[str]) -> None:
    assert all(l and l == l.strip() for l in lines), p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(("\n".join(nfc(l) for l in lines) + "\n") if lines else "", encoding="utf-8", newline="\n")      # rỗng ⇒ 0 byte


def run(mod: str, *args: str) -> int:
    return subprocess.call([sys.executable, "-m", f"src.step1_book_mining.{mod}", *args], cwd=ROOT)


def trang_sach(row: dict) -> str:
    a = row.get("tr_han_bat_dau") or row.get("tr_tieu_de_viet") or ""
    return f"{a}-{row.get('tr_ket_thuc', '')}" if a else ""


def cap_nhat_ke_ma(rows: list[dict], stts_chay: set[int]) -> None:
    """Ghi ``van_ban_ma_bia.csv``: giữ dòng của STT không chạy lần này, thay dòng của STT vừa chạy."""
    cu = [r for r in read_tsv_csv(KE_MA) if int(r["stt"]) not in stts_chay]
    allrows = sorted(cu + rows, key=lambda r: int(r["stt"]))
    KE_MA.parent.mkdir(parents=True, exist_ok=True)
    with open(KE_MA, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=KE_MA_COLS, lineterminator="\n")
        w.writeheader(); w.writerows(allrows)


def read_tsv_csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def xoa_file_cu(out: Path, bia_ids: list[str]) -> list[str]:
    """(sửa 4) Xoá mọi file văn bản trong ``out/<loại>/`` có tên chứa một trong ``bia_ids`` (tên cũ của cùng văn bia,
    hoặc kết quả lần chạy trước) — để ``data/processed`` luôn khớp lần chạy này và file kê mã."""
    ids = set(bia_ids)
    gone = []
    for k in KINDS:
        for f in (out / k).glob("*.txt"):
            if ids & set(f.stem.split("_")):
                f.unlink(); gone.append(f"{k}/{f.name}")
    return gone


def don_file_thua(out: Path, giu: set[str]) -> list[str]:
    """(sửa 4) Chạy toàn bộ (không ``--bia``): xoá file không thuộc lần chạy này (văn bia bị loại, tên cũ…)."""
    gone = []
    for k in KINDS:
        for f in (out / k).glob("*.txt"):
            if f.stem not in giu:
                f.unlink(); gone.append(f"{k}/{f.name}")
    return gone


def kiem_dong_bo(faces: dict[int, list[str]]) -> list[str]:
    """Đối chiếu chéo: tên file trong data/processed ⇔ file kê mã ⇔ stt_bia_map.csv ⇔ ảnh trong anh_bia ⇔ inventory.csv.
    Trả về danh sách lỗi (rỗng = khớp hết)."""
    loi: list[str] = []
    expect = {ten_file(v): k for k, v in faces.items()}
    for k in KINDS:
        have = {f.stem for f in (OUT / k).glob("*.txt")}
        for n in sorted(have - set(expect)):
            loi.append(f"{k}/{n}.txt không ứng với văn bia nào trong stt_bia_map.csv")
        for n in sorted(set(expect) - have):
            loi.append(f"thiếu {k}/{n}.txt (STT {expect[n]})")
    ke = {r["ten_file"]: r for r in read_tsv_csv(KE_MA)}
    for n, stt in expect.items():
        r = ke.get(n)
        if r is None:
            loi.append(f"kê mã thiếu dòng {n} (STT {stt})")
        elif r["danh_sach_bia_id"] != "|".join(faces[stt]) or int(r["stt"]) != stt:
            loi.append(f"kê mã lệch ở {n}")
    for n in sorted(set(ke) - set(expect)):
        loi.append(f"kê mã thừa dòng {n}")
    imgs = {p.stem for p in (ROOT / "data/raw/anh_bia").glob("*.jpg")}
    mapped = [b for v in faces.values() for b in v]
    for b in sorted(imgs - set(mapped)):
        loi.append(f"ảnh {b}.jpg không thuộc văn bia nào")
    for b in sorted(set(mapped) - imgs):
        loi.append(f"stt_bia_map có {b} nhưng không có ảnh")
    for b in {b for b in mapped if mapped.count(b) > 1}:
        loi.append(f"mặt {b} thuộc nhiều văn bia")
    inv = ROOT / "data/metadata/inventory.csv"
    for r in read_tsv_csv(inv):
        m = re.search(r"bia_id=([^;]+)", r.get("ghi_chu", ""))
        stt = int(r["doc_id"][5:]) if r["doc_id"][5:].isdigit() else 0
        if stt in faces and (not m or m.group(1) != "|".join(faces[stt])):
            loi.append(f"inventory.csv lệch ở {r['doc_id']} (chạy lại build_inventory)")
    return loi


def ten_file(bia_ids: list[str]) -> str:
    """Tên file văn bản của một văn bia = các bia_id có ảnh nối bằng '_' (giả định định dạng, chờ xác nhận)."""
    return "_".join(bia_ids)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bia", help="danh sách STT, vd 22,25,27 (mặc định: mọi văn bia có ảnh trong stt_bia_map.csv)")
    ap.add_argument("--model", default=sb.DEFAULT_MODEL)
    ap.add_argument("--khong-ocr", action="store_true", help="không gọi API; chỉ dùng trang đã OCR")
    ap.add_argument("--zip", action="store_true", help="đóng gói bàn giao sau khi kiểm tra đạt")
    a = ap.parse_args()
    today = date.today().strftime("%Y%m%d")
    tail = "_mot_phan" if a.bia else ""                 # chạy một phần (--bia) ghi báo cáo riêng, không đè báo cáo đầy đủ

    faces: dict[int, list[str]] = {}
    for r in csv.DictReader(open(MAP, encoding="utf-8", newline="")):
        faces.setdefault(int(r["stt"]), []).append(r["bia_id"])
    stts = sorted(int(x) for x in a.bia.split(",")) if a.bia else sorted(faces)
    muc_luc = {int(r["stt"]): r for r in csv.DictReader(open(sb.MUC_LUC, encoding="utf-8", newline=""))}
    xac_nhan = {int(r["stt"]) for r in read_tsv_csv(BO_SUNG)}            # STT đã đối chiếu số mặt trên Vietnamica

    # ---- 1. OCR — (sửa 6) chỉ văn bia có ảnh VÀ có dòng mục lục
    can_ocr = [s for s in stts if s in faces and s in muc_luc]
    print(f"[1/5] OCR {len(can_ocr)} văn bia ({a.model})", flush=True)
    if not a.khong_ocr and can_ocr and run("ocr_gemini", "--bia", ",".join(map(str, can_ocr)), "--model", a.model) != 0:
        print("  OCR có trang lỗi/hỏng — tiếp tục với các trang đã có (bia thiếu trang sẽ báo THIEU_OCR)", flush=True)

    report: list[dict] = []
    written: list[str] = []
    ke_ma: list[dict] = []
    for stt in stts:
        doc = sb.bia_id_of(stt)
        row = muc_luc.get(stt) or {}
        name = ten_file(faces.get(stt, []))
        rec = {"stt": stt, "doc_id": doc, "ten_file": name, "danh_sach_bia_id": "|".join(faces.get(stt, [])),
               "so_mat_co_anh": len(faces.get(stt, [])),
               "so_mat_theo_sach": row.get("mat_theo_sach_ocr", "") or "NA",          # NA = sách không ghi / OCR không đọc được
               "trang_sach": trang_sach(row), "so_trang_doc": "", "model_ocr": "", "trang_model_du_phong": "",
               "trang_thai": "", "dong_han": "", "chu_han": "", "dong_phien_am": "", "am_tiet_pa": "",
               "dong_dich_nghia": "", "ti_le_pa_han": "NA",                           # NA = không tính được (thiếu Hán hoặc Phiên âm)
               "byte_chu_han": "", "byte_phien_am": "", "byte_dich_nghia": "", "file_rong": "", "ghi_chu": ""}

        def bad(status: str, note: str = "") -> None:
            report.append({**rec, "trang_thai": status, "ghi_chu": note})

        if stt not in faces:
            bad("KHONG_CO_ANH"); continue
        xoa_file_cu(OUT, faces[stt])                      # (sửa 4) bia lỗi lần này thì không còn file cũ
        if not row:
            bad("THIEU_MUC_LUC", "STT không có trong muc_luc_sach.csv"); continue
        try:                                              # (sửa 5) lỗi của một bia không làm dừng cả lần chạy
            # ---- 2. tách & làm sạch (đọc tới đầu bia kế để thấy điểm kết thúc)
            try:
                st = sb.process(stt, row, a.model, sb.page_end(stt, muc_luc))
            except SystemExit as e:
                m = re.search(r"trang (\d+)", str(e))
                bad("THIEU_OCR", f"chưa OCR trang {m.group(1) if m else '?'} — chạy lại không có --khong-ocr"); continue
            if st["loi"]:
                bad("LOI_TACH", st["loi"]); continue
            text = {k: read_lines(sb.NHAP / k / f"{doc}.txt") for k in KINDS}
            if not any(text.values()):
                bad("LOI_TACH", "không tách được loại văn bản nào — kiểm tra cấu trúc trang"); continue
            # loại nào sách không có thì vẫn ghi file RỖNG (0 byte) để đủ bộ 3 file (quyết định Tuấn 09/11)
            rong = [k for k in KINDS if not text[k]]
            # ---- 3. ghi nguyên bài theo mã bia
            for k in KINDS:
                write_lines(OUT / k / f"{name}.txt", text[k])
        except Exception as e:                            # noqa: BLE001
            xoa_file_cu(OUT, faces[stt])
            bad("LOI_XU_LY", f"{type(e).__name__}: {str(e)[:80]}"); continue
        nh = len(HAN.findall("".join(text["Chu_Han"])))
        ns = sum(len(x.split()) for x in text["Phien_am"])
        ratio = ns / nh if nh and ns else 0
        notes = list(st["canh_bao"])
        NGUON = {"Chu_Han": "sách không có chữ Hán", "Phien_am": "sách không có mục Phiên âm", "Dich_nghia": "sách không có mục Dịch nghĩa"}
        notes += [f"RONG {k} ({NGUON[k]})" for k in rong]
        if ratio and not TI_LE[0] <= ratio <= TI_LE[1]:
            notes.append("TI_LE_LECH (sách rút gọn Hán/Phiên âm, hoặc OCR sót đoạn)")
        sm = rec["so_mat_theo_sach"]
        if sm.isdigit() and int(sm) != len(faces[stt]):
            if stt in xac_nhan and int(sm) > len(faces[stt]):
                notes.append(f"sách ghi {sm} mặt; Vietnamica chỉ có {len(faces[stt])} mặt, đã xác nhận (lấy nguyên bài)")
            elif stt in xac_nhan:
                notes.append(f"sách chỉ chép {sm} mặt; Vietnamica có {len(faces[stt])} mặt, đã xác nhận "
                             "(văn bản sách có thể chỉ ứng với một phần các mặt)")
            else:
                notes.append(f"sách ghi {sm} mặt, có ảnh {len(faces[stt])} mặt (lấy nguyên bài)")
        a_tr, b_tr = (int(x) for x in str(st["trang"]).split("-"))
        du_phong = sorted({(m.group(2), int(m.group(1))) for c in st["canh_bao"] if (m := re.match(r"tr\.(\d+) lấy từ (\S+)", c))})
        report.append({**rec, "trang_thai": "OK", "dong_han": len(text["Chu_Han"]), "chu_han": nh,
                       "dong_phien_am": len(text["Phien_am"]), "am_tiet_pa": ns, "dong_dich_nghia": len(text["Dich_nghia"]),
                       "ti_le_pa_han": f"{ratio:.2f}" if ratio else "NA",
                       "so_trang_doc": b_tr - a_tr + 1, "model_ocr": a.model,
                       "trang_model_du_phong": "|".join(f"tr.{pg}:{mdl}" for mdl, pg in du_phong) or "-",
                       "byte_chu_han": (OUT / "Chu_Han" / f"{name}.txt").stat().st_size,
                       "byte_phien_am": (OUT / "Phien_am" / f"{name}.txt").stat().st_size,
                       "byte_dich_nghia": (OUT / "Dich_nghia" / f"{name}.txt").stat().st_size,
                       "file_rong": "|".join(rong) or "-", "ghi_chu": "; ".join(notes) or "-"})
        written.append(name)
        ke_ma.append({"ten_file": name, "doc_id": doc, "stt": stt, "danh_sach_bia_id": "|".join(faces[stt]),
                      "so_mat_co_anh": len(faces[stt]), "so_mat_theo_sach": sm, "trang_sach": trang_sach(row),
                      "ghi_chu": "; ".join(n for n in notes if n.startswith(("sách ghi", "RONG")))})
    if not a.bia:
        thua = don_file_thua(OUT, set(written))
        if thua:
            print(f"  dọn {len(thua)} file không thuộc lần chạy này", flush=True)
    print(f"[2-3/5] ghi {len(written)} văn bia vào data/processed", flush=True)
    cap_nhat_ke_ma(ke_ma, set(stts))
    print(f"        kê mã: {KE_MA.relative_to(ROOT).as_posix()} (+{len(ke_ma)} dòng)", flush=True)

    # ---- 4. kiểm tra
    rc = 0
    if written:
        print("[4/5] checker V1–V8", flush=True)
        rc = run("check_van_ban_sach", "--dir", "data/processed", "--bia", ",".join(written),
                 "--log", f"reports/check_van_ban_{today}{tail}.txt")
    if not a.bia:                                    # chạy toàn bộ: đối chiếu chéo mọi nơi chứa mã bia
        loi_db = kiem_dong_bo(faces)
        print(f"      đồng bộ processed ⇔ kê mã ⇔ stt_bia_map ⇔ ảnh ⇔ inventory: "
              + ("KHỚP" if not loi_db else f"{len(loi_db)} lỗi"), flush=True)
        for x in loi_db:
            print("        " + x)
        rc = rc or (1 if loi_db else 0)

    # ---- 5. báo cáo (không chứa nội dung sách)
    if not report:
        print("Không có văn bia nào để xử lý."); return 1
    rep = ROOT / f"reports/pipeline_1a_{today}{tail}.tsv"
    with open(rep, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(report[0]), delimiter="\t", lineterminator="\n")
        w.writeheader(); w.writerows(report)
    cnt = Counter(r["trang_thai"] for r in report)
    print(f"[5/5] {rep.relative_to(ROOT).as_posix()}: " + ", ".join(f"{k}={v}" for k, v in sorted(cnt.items())))
    for r in report:
        if r["trang_thai"] != "OK" or r["ghi_chu"]:
            print(f"  STT {r['stt']:>2} {r['ten_file']:<36} {r['trang_thai']:<14} {r['ghi_chu']}")
    if rc != 0:
        print("Checker còn lỗi — không đóng gói."); return 1
    if a.zip:
        return run("make_handover_zip", "--ngay", today)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
