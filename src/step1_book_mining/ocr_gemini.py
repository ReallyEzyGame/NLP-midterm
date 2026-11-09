"""OCR trang sách bằng Google AI Studio (Gemini API) — bước 1 (OCR sách thô) của T.

Công cụ đã chốt 07/11/2026: ``gemini-3.5-flash-lite`` (dự phòng: RapidOCR cục bộ).
Chỉ gửi **trang sách nhóm 3** (đã được giảng viên cho phép). KHÔNG commit key.

Key: đọc từ file ngoài repo, đường dẫn nằm trong biến môi trường ``GEMINI_API_KEY_FILE``
(biến chỉ chứa ĐƯỜNG DẪN, không chứa key). Script không bao giờ in key.

Đầu ra (mỗi trang một cặp file, chạy lại được: trang đã có thì bỏ qua):
    data/interim/sach_ocr/gemini/<model>/p<trang 3 số>.txt    nguyên văn Gemini trả về
    data/interim/sach_ocr/gemini/<model>/p<trang 3 số>.json   siêu dữ liệu (model, kind, giờ, token, prompt_sha)

Cách chạy (từ thư mục NLP-midterm, đã bật .venv):
    python -m src.step1_book_mining.ocr_gemini --pages 217:han,218:viet,219:viet
    python -m src.step1_book_mining.ocr_gemini --bia 25,27,22          # trang lấy từ muc_luc_sach.csv
    python -m src.step1_book_mining.ocr_gemini --pages 100:han --force        # chạy lại, ghi đè trang đã có
    python -m src.step1_book_mining.ocr_gemini --bia 25 --dry-run      # chỉ in kế hoạch, KHÔNG gọi API

``kind`` của prompt: ``han`` (chữ Hán phồn thể), ``viet`` (tiếng Việt có dấu) hoặc ``mixed`` (trang có cả hai;
prompt ``mixed`` CHƯA được đo CER — xem README). Với ``--bia`` kind được suy từ ``muc_luc_sach.csv``.
Giới hạn tốc độ mặc định 12 yêu cầu/phút (giữ dưới 15 RPM); gặp 429 thì lùi dần, hết hạn mức ngày thì dừng
và in lệnh chạy tiếp (đã lưu từng trang).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .ocr_scan_all import list_pages  # cùng cách cắt trang đôi tại giữa gáy như OCR cục bộ

ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = ROOT / "data/interim/sach_ocr/gemini"
MUC_LUC = ROOT / "data/interim/text_tho/muc_luc_sach.csv"
DEFAULT_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODELS = ("gemini-3.5-flash",)    # chỉ dùng cho trang mà model chính không đọc nổi (chạy tay: --model gemini-3.5-flash --pages N:han)

PROMPTS = {
    "han": ("Chép lại NGUYÊN VĂN toàn bộ chữ Hán trong ảnh trang sách này, từng dòng một, đúng thứ tự đọc "
            "(trái sang phải, trên xuống dưới). Giữ nguyên chữ PHỒN THỂ và dị thể như in, KHÔNG đổi sang giản thể, "
            "KHÔNG sửa lỗi, KHÔNG thêm bớt, KHÔNG dịch, KHÔNG giải thích, KHÔNG thêm dấu câu. "
            "Bỏ qua số trang. Chỉ trả về văn bản."),
    "viet": ("Chép lại NGUYÊN VĂN toàn bộ chữ trong ảnh trang sách này, từng dòng một. "
             "Giữ chính xác mọi dấu tiếng Việt. KHÔNG sửa lỗi, KHÔNG thêm bớt, KHÔNG dịch, KHÔNG giải thích. "
             "Bỏ qua số trang. Chỉ trả về văn bản."),
    "mixed": ("Chép lại NGUYÊN VĂN toàn bộ chữ trong ảnh trang sách này, từng dòng một, đúng thứ tự đọc. "
              "Chữ Hán: giữ nguyên PHỒN THỂ và dị thể như in, KHÔNG đổi sang giản thể. "
              "Tiếng Việt: giữ chính xác mọi dấu. "
              "KHÔNG sửa lỗi, KHÔNG thêm bớt, KHÔNG dịch, KHÔNG giải thích, KHÔNG thêm dấu câu mới. "
              "Bỏ qua số trang. Chỉ trả về văn bản."),
}


def page_map() -> dict[int, tuple[Path, str]]:
    return {p: (f, side) for f, p, side in list_pages()}


def parse_pages(spec: str) -> list[tuple[int, str]]:
    """'217:han,218:viet,203-205:mixed,100' -> [(trang, kind), ...] (kind mặc định mixed)."""
    out: list[tuple[int, str]] = []
    for tok in filter(None, (t.strip() for t in spec.split(","))):
        rng, _, kind = tok.partition(":")
        kind = kind or "mixed"
        if kind not in PROMPTS:
            sys.exit(f"kind không hợp lệ: {kind!r} (han|viet|mixed)")
        a, _, b = rng.partition("-")
        for p in range(int(a), int(b or a) + 1):
            out.append((p, kind))
    return out


def pages_from_bia(stts: list[int]) -> list[tuple[int, str]]:
    """Trang của mỗi bia từ muc_luc_sach.csv: Hán (đến trước tiêu đề Việt), trang có cả hai là mixed, còn lại Việt."""
    from .clean_book_text import page_end
    rows = {int(r["stt"]): r for r in csv.DictReader(open(MUC_LUC, encoding="utf-8", newline=""))}
    res: dict[int, str] = {}
    for s in stts:
        r = rows[s]
        hs, he = (int(r["tr_han_bat_dau"]), int(r["tr_han_ket_thuc"])) if r["tr_han_bat_dau"] else (None, None)
        vs, ve = int(r["tr_tieu_de_viet"]), int(r["tr_ket_thuc"])
        last, expect = page_end(s, rows)      # có thể thêm trang mở đầu của bia kế (cùng phạm vi với clean_book_text)
        first = hs if hs is not None else vs
        for p in range(first, last + 1):
            if p > ve or (expect and p == last and p >= vs):
                kind = "mixed"                # trang của bia kế: có thể có cả Việt (đuôi bia này) và Hán (bia kế)
            elif hs is not None and hs <= p <= he:
                kind = "han" if p < vs else "mixed"
            elif p == he and p >= vs:
                kind = "mixed"
            else:
                kind = "viet"
            # một trang có thể thuộc 2 bia liền kề: nếu đã có kind khác thì gộp thành mixed
            res[p] = kind if res.get(p, kind) == kind else "mixed"
    return sorted(res.items())


def crop_page(page: int) -> bytes:
    f, side = page_map()[page]
    im = Image.open(f).convert("RGB")
    w, h = im.size
    if side == "L":
        im = im.crop((0, 0, w // 2, h))
    elif side == "R":
        im = im.crop((w // 2, 0, w, h))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def crop_halves(page: int) -> list[bytes]:
    """Cắt trang làm hai nửa (trên/dưới) tại hàng ít mực nhất trong khoảng 35–65% chiều cao (khe giữa hai dòng chữ)."""
    import numpy as np
    f, side = page_map()[page]
    im = Image.open(f).convert("RGB")
    w, h = im.size
    if side == "L":
        im = im.crop((0, 0, w // 2, h))
    elif side == "R":
        im = im.crop((w // 2, 0, w, h))
    ink = np.convolve((255 - np.asarray(im.convert("L"), dtype=np.int32)).sum(axis=1), np.ones(9) / 9, mode="same")
    lo, hi = int(0.35 * im.height), int(0.65 * im.height)
    cut = lo + int(np.argmin(ink[lo:hi]))
    pad = 12                                         # chồng lấn nhỏ để không cắt cụt chữ sát khe
    out = []
    for box in ((0, 0, im.width, min(im.height, cut + pad)), (0, max(0, cut - pad), im.width, im.height)):
        buf = io.BytesIO()
        im.crop(box).save(buf, format="PNG")
        out.append(buf.getvalue())
    return out


def load_client():
    from google import genai
    kf = os.environ.get("GEMINI_API_KEY_FILE")
    if not kf or not Path(kf).is_file():
        sys.exit("Thiếu biến môi trường GEMINI_API_KEY_FILE (đường dẫn tới file key NGOÀI repo).")
    if Path(kf).resolve().is_relative_to(ROOT.parent):
        sys.exit("File key nằm trong thư mục dự án — chuyển ra ngoài repo rồi chạy lại.")
    return genai.Client(api_key=Path(kf).read_text(encoding="utf-8").strip())


HAN_WIN, HAN_REPEATS = 12, 4              # đoạn 12 chữ Hán lặp ≥ 4 lần trên một trang = thoái hoá
REPEAT_RE = re.compile(r"(\S{1,8}?)\1{7,}")      # một đơn vị 1–8 ký tự lặp liên tiếp ≥ 8 lần


def degenerate(txt: str) -> bool:
    """Gemini đôi khi lặp vô hạn một cụm (vd ``嘉男嘉男…``) rồi vẫn dừng bằng STOP. Đơn vị lặp phải chứa chữ/chữ Hán
    (đường kẻ ``____`` hay ``…`` là hợp lệ)."""
    t = re.sub(r"\s+", "", txt)
    if any(re.search(r"[^\W_]", m.group(1)) for m in REPEAT_RE.finditer(t)):         # chữ/số/Hán, không tính "_"
        return True
    # lặp "trôi": các dòng dài dần cùng một đuôi ⇒ cùng một đoạn 12 chữ Hán xuất hiện ≥ 4 lần trên một trang
    han = re.sub(r"[^㐀-鿿]", "", t)
    if len(han) >= 48:
        top = Counter(han[i:i + HAN_WIN] for i in range(len(han) - HAN_WIN + 1)).most_common(1)[0][1]
        if top >= HAN_REPEATS:
            return True
    return False


MAX_OUT_TOKENS = 8192                 # một trang sách chỉ cần vài trăm–nghìn token; cắt sớm khi mô hình lặp vô hạn
TEMPS = (0.0, 0.3, 0.7)               # lần đầu temperature 0 (như đã chốt); nếu bị MAX_TOKENS/rỗng thì thử lại với nhiệt độ cao hơn


def call_with_backoff(client, model: str, png: bytes, prompt: str, max_try: int = 5, temperature: float = 0.0):
    from google.genai import types
    delay = 8.0
    for k in range(1, max_try + 1):
        try:
            return client.models.generate_content(
                model=model,
                contents=[types.Part.from_bytes(data=png, mime_type="image/png"), prompt],
                config=types.GenerateContentConfig(temperature=temperature, max_output_tokens=MAX_OUT_TOKENS))
        except Exception as e:  # noqa: BLE001 — SDK ném nhiều loại lỗi
            msg = str(e)
            quota = "429" in msg or "RESOURCE_EXHAUSTED" in msg
            if quota and re.search(r"(?i)per\s*day|daily|PerDay", msg):
                raise SystemExit("HẾT HẠN MỨC NGÀY — dừng. Chạy lại cùng lệnh sau khi hạn mức làm mới (trang đã xong được bỏ qua).")
            if k == max_try or not (quota or "503" in msg or "500" in msg or "UNAVAILABLE" in msg):
                raise
            print(f"   lỗi tạm thời (lần {k}/{max_try}); chờ {delay:.0f}s", file=sys.stderr)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pages", help="vd 217:han,218:viet,203-205:mixed")
    g.add_argument("--bia", help="danh sách STT, vd 25,27,22")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--rpm", type=float, default=12.0, help="số yêu cầu tối đa mỗi phút")
    ap.add_argument("--force", action="store_true", help="ghi đè trang đã có")
    ap.add_argument("--dry-run", action="store_true", help="chỉ in kế hoạch, không gọi API")
    ap.add_argument("--khong-chia-doi", action="store_true", help="không dùng phương án cắt đôi trang khi OCR bị lặp")
    a = ap.parse_args()

    plan = parse_pages(a.pages) if a.pages else pages_from_bia([int(x) for x in a.bia.split(",")])
    pm = page_map()
    missing = [p for p, _ in plan if p not in pm]
    if missing:
        sys.exit(f"Không có ảnh cho trang: {missing}")
    out = OUT_ROOT / a.model
    def can_chay(p: int) -> bool:          # chưa có, hoặc đã lưu nhưng bị lặp (kết quả cũ)
        f = out / f"p{p:03d}.txt"
        if f.exists():
            return degenerate(f.read_text(encoding="utf-8"))
        if a.model == DEFAULT_MODEL:       # đã có bản tốt từ model dự phòng thì không gọi lại model chính (tốn lượt, vẫn hỏng)
            for m in FALLBACK_MODELS:
                g = OUT_ROOT / m / f"p{p:03d}.txt"
                if g.exists() and not degenerate(g.read_text(encoding="utf-8")):
                    return False
        return True

    todo = [(p, k) for p, k in plan if a.force or can_chay(p)]
    print(f"model={a.model}  tổng {len(plan)} trang, cần chạy {len(todo)}, bỏ qua {len(plan) - len(todo)}")
    for p, k in plan:
        print(f"  tr.{p:03d}  {k:5s} {'(đã có)' if (p, k) not in todo else ''}")
    if a.dry_run or not todo:
        return 0

    out.mkdir(parents=True, exist_ok=True)
    client = load_client()
    gap = 60.0 / a.rpm
    last = 0.0
    hong: list[int] = []
    for p, k in todo:
        wait = gap - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        last = time.time()
        prompt = PROMPTS[k]
        png = crop_page(p)
        for temp in TEMPS:
            r = call_with_backoff(client, a.model, png, prompt, temperature=temp)
            try:
                txt = unicodedata.normalize("NFC", (r.text or "")).replace("\r\n", "\n")
            except Exception:  # noqa: BLE001 — SDK có thể ném khi phản hồi bị chặn
                txt = ""
            fr = finish_reason(r)
            if txt.strip() and fr == "STOP" and not degenerate(txt):
                break
            print(f"   tr.{p:03d}: finish_reason={fr}, {len(txt)} ký tự ở temperature {temp} — thử lại", file=sys.stderr)
        um = getattr(r, "usage_metadata", None)
        meta = {
            "page": p, "kind": k, "model": a.model, "temperature": temp,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
            "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "prompt_tokens": getattr(um, "prompt_token_count", None),
            "output_tokens": getattr(um, "candidates_token_count", None),
            "chars": len(txt),
            "finish_reason": fr,
        }
        if (not txt.strip() or fr != "STOP" or degenerate(txt)) and not a.khong_chia_doi:
            # dự phòng: mọi nhiệt độ đều lặp/hỏng ⇒ cắt trang làm hai nửa, OCR từng nửa (ít nội dung hơn ⇒ ít lặp hơn)
            print(f"   tr.{p:03d}: thử cắt đôi trang (mỗi nửa một lần gọi)", file=sys.stderr)
            parts: list[str] = []
            for half in crop_halves(p):
                time.sleep(max(0.0, gap - (time.time() - last)))
                last = time.time()
                rh = call_with_backoff(client, a.model, half, prompt, temperature=0.0)
                try:
                    ph = unicodedata.normalize("NFC", rh.text or "").replace("\r\n", "\n").strip("\n")
                except Exception:  # noqa: BLE001
                    ph = ""
                parts.append(ph if finish_reason(rh) == "STOP" else "")
            if all(parts) and not degenerate("\n".join(parts)):
                txt, fr = "\n".join(parts), "STOP"
                meta["chia_doi"], meta["chars"], meta["finish_reason"] = True, len(txt), fr
        err = out / f"p{p:03d}.loi.json"
        if not txt.strip() or fr != "STOP" or degenerate(txt):
            # (sửa 2) rỗng / bị chặn / bị cắt (MAX_TOKENS, RECITATION, SAFETY…) ⇒ KHÔNG lưu .txt để lần sau chạy lại
            old_txt = out / f"p{p:03d}.txt"          # bản cũ cũng lặp ⇒ xoá, không để pipeline dùng nhầm
            if old_txt.exists() and degenerate(old_txt.read_text(encoding="utf-8")):
                old_txt.unlink()
                (out / f"p{p:03d}.json").unlink(missing_ok=True)
            err.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
            hong.append(p)
            print(f"  tr.{p:03d} {k:5s} HỎNG: finish_reason={fr}, {len(txt)} ký tự — không lưu, chạy lại sau", file=sys.stderr)
            continue
        (out / f"p{p:03d}.txt").write_text(txt, encoding="utf-8", newline="\n")
        (out / f"p{p:03d}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n",
                                            encoding="utf-8", newline="\n")
        err.unlink(missing_ok=True)
        print(f"  tr.{p:03d} {k:5s} xong: {len(txt)} ký tự, {meta['output_tokens']} token ra")
    if hong:
        print(f"{len(hong)} trang hỏng (xem p<trang>.loi.json): {hong} — chạy lại cùng lệnh để thử lại", file=sys.stderr)
        return 1
    return 0


def finish_reason(r) -> str:
    """Lý do dừng của ứng viên đầu tiên, dạng chuỗi ngắn ('STOP', 'MAX_TOKENS', 'RECITATION', 'SAFETY', 'NONE'…)."""
    try:
        fr = r.candidates[0].finish_reason
    except (AttributeError, IndexError, TypeError):
        return "NONE"
    if fr is None:
        return "NONE"
    return str(getattr(fr, "name", fr)).split(".")[-1].upper()


if __name__ == "__main__":
    raise SystemExit(main())
