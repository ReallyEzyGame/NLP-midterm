"""Dataset 2: bộ ba Hán – Phiên âm – Dịch nghĩa, lấy câu Phiên âm làm trục (thay `sentence_aligner.py`).

Vì sao làm lại: bản cũ gióng Hán↔PA và Hán↔DN ĐỘC LẬP rồi ghép theo chỉ số (Hán trong sách không có dấu câu nên một
"câu" Hán = cả đoạn), score hằng số 0.95/0.85, thiếu `status`/`pair_id`; BertAlign khai báo nhưng không chạy (thư viện
chưa cài, nhánh code lỗi) → thực chất là DP theo độ dài. Kiểm tay: cặp đầu tiên đã lệch nghĩa.

Cách làm (kiểm tay 3 mẫu × 50 cặp ngẫu nhiên — test_debug/checklist_debug.md §9.11):
1. Hán ↔ Phiên âm: PA chuyển tự TỪNG CHỮ (1 chữ ↔ 1 âm tiết). Tự học từ điển chữ→âm từ chính các văn bản (đồng xuất hiện
   theo vị trí tỉ lệ + 3 vòng hard-EM), rồi Needleman–Wunsch chữ↔âm tiết. Ranh giới câu PA chiếu sang chuỗi Hán.
2. Phiên âm ↔ Dịch nghĩa: DP gióng câu (1-1, 1-2, 2-1, 2-2, 1-3, 3-1, bỏ câu); điểm = chồng lấn từ có trọng số IDF, mở rộng
   bằng từ điển dịch PA→DN học bằng IBM Model 1 (vd duy→kính/nghĩ, viết→rằng), trừ phạt lệch độ dài. Tỉ lệ độ dài lấy từ
   các cặp 1–1 khớp chắc (≈ 1,07) — KHÔNG lấy tổng văn bản (bị thổi phồng 2–3,5× vì DN dịch cả danh sách mà Hán lược).
   Tách câu mịn hơn; vế dẫn `Kính nghĩ:` / `Tôi đáp:` chuyển sang câu sau.
3. `status` xét cả 3 phía; lý do needs_review ghi ở reports/dataset_dich_<ngày>/needs_review.csv.
   Token MASK (chữ mất/sách lược, giảng viên 14/11/2026) đi qua cả 3 trường.
Kết quả 15/11/2026: 813 cặp (33 văn bia), 580 ok; cặp ok khớp hoàn toàn 83–86% (≈ 92–94% nếu chấp nhận lệch 1 vế ngắn).

    python -m src.step4_trans_align.build_dataset_dich
    python -m src.utils.validate --stage dataset_dich
"""
from __future__ import annotations

import collections
import csv
import json
import math
import re
import statistics
import sys
import unicodedata
from datetime import date
from pathlib import Path

from src.step3_ocr_align.text_aligner import clean_gt_text, normalize_han_str

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
CHU_HAN, PHIEN_AM, DICH_NGHIA = PROC / "Chu_Han", PROC / "Phien_am", PROC / "Dich_nghia"
OUT = ROOT / "data" / "output" / "dataset_dich"
REP = ROOT / "reports" / f"dataset_dich_{date.today():%Y%m%d}"
STATUS_MIN = 0.0         # điểm từ vựng PA↔DN KHÔNG tách được đúng/sai trên mẫu gán tay 40 cặp → không dùng làm ngưỡng
HAN_HIT_MIN = 0.6        # tỉ lệ chữ Hán khớp âm theo từ điển trong cặp
LENPEN_W = 0.15          # trọng số phạt lệch độ dài PA↔DN
BAD_RUN_MAX = 3          # ≥ 3 chữ Hán liền nhau không khớp âm nào → nghi Chu_Han sai/tráo đoạn (RC10)
LEN_BAND = (0.5, 2.0)    # DN/(PA·ratio) ngoài khoảng này → nghi thừa/thiếu câu dịch


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def syllables(line: str) -> list[str]:
    """Âm tiết của câu PA; '(?)' = 1 âm khuyết; chú thích khác trong ngoặc (vd '(tân)') bỏ đi."""
    line = re.sub(r"\(\?\)|MASK", " ？ ", nfc(line))
    line = re.sub(r"\([^)]*\)", " ", line)
    return [t.lower() for t in re.findall(r"？|[^\W\d_]+", line)]


def han_chars(text: str) -> str:
    # MASK (chữ mất/sách lược) → ký tự khuyết '？' để gióng như 1 chữ bất kỳ; xuất lại thành MASK
    return "".join(clean_gt_text(x) for x in text.replace("MASK", "？").splitlines())


SPLIT = re.compile(r'(?<=[.!?:;])\s+(?=["“(\[]?[A-ZÀ-ỸĐ])')   # ranh giới câu: dấu câu + chữ HOA đầu câu kế


def split_units(lines: list[str]) -> list[str]:
    """Tách 1 dòng sách thành các câu (vd DN '…tu sửa chùa. Kính nghĩ:' → 2 đơn vị) để DP tự gộp lại khi cần.
    Kiểm tay 50 cặp: lỗi còn lại chủ yếu là dòng DN chứa câu mở đầu của câu PA kế tiếp."""
    return [u.strip() for x in lines for u in SPLIT.split(x) if u.strip()]


def load_docs() -> list[dict]:
    docs = []
    for f in sorted(CHU_HAN.glob("*.txt")):
        rd = lambda d: split_units([nfc(x).strip() for x in (d / f.name).read_text(encoding="utf-8").splitlines()
                                    if x.strip()]) if (d / f.name).exists() else []
        docs.append({"id": f.stem, "han": han_chars(f.read_text(encoding="utf-8")),
                     "pa": rd(PHIEN_AM), "dn": rd(DICH_NGHIA)})
    return docs


# ------------------------------------------------------------------ 1. Hán ↔ Phiên âm
def learn_lexicon(docs: list[dict]) -> dict[str, set[str]]:
    """Từ điển chữ→âm học không giám sát: ghép theo vị trí tỉ lệ (±1) ở văn bản có tỉ lệ âm/chữ ≈ 1, lấy âm trội."""
    cnt: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for d in docs:
        h = normalize_han_str(d["han"])
        s = [x for line in d["pa"] for x in syllables(line)]
        if not h or not s or not 0.95 <= len(s) / len(h) <= 1.05:
            continue
        r = len(s) / len(h)
        for i, ch in enumerate(h):
            j = round(i * r)
            for k in (j - 1, j, j + 1):
                if 0 <= k < len(s):
                    cnt[ch][s[k]] += 2 if k == j else 1
    return lex_from_counts(cnt)


def lex_from_counts(cnt: dict[str, collections.Counter], min_n: int = 3) -> dict[str, set[str]]:
    lex = {}
    for ch, c in cnt.items():
        top = c.most_common(1)[0][1]
        keep = {syl for syl, n in c.items() if n >= max(min_n, 0.25 * top)}
        if keep:
            lex[ch] = keep
    return lex


def refine_lexicon(docs: list[dict], lex: dict[str, set[str]], rounds: int = 3) -> dict[str, set[str]]:
    """Hard-EM: gióng NW bằng từ điển hiện tại trên MỌI văn bản → đếm cặp (chữ, âm) ở bước chéo → học lại từ điển."""
    for r in range(rounds):
        cnt: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        tot = 0.0
        for d in docs:
            if d["han"] and d["pa"]:
                _, hp = align_han_pa(d["han"], d["pa"], lex, cnt)
                tot += hp
        lex = lex_from_counts(cnt, min_n=2)
        print(f"  EM vòng {r + 1}: khớp TB {tot / len(docs):.3f}, từ điển {len(lex)} chữ", flush=True)
    return lex


def align_han_pa(han: str, pa_lines: list[str], lex: dict[str, set[str]], pairs: dict | None = None) -> tuple[list[str], float]:
    """NW chữ↔âm; trả đoạn Hán cho từng câu PA và tỉ lệ khớp từ điển (độ tin cậy Hán↔PA)."""
    h = normalize_han_str(han)
    sy, owner = [], []
    for li, line in enumerate(pa_lines):
        for x in syllables(line):
            sy.append(x)
            owner.append(li)
    n, m = len(h), len(sy)
    if not n or not m:
        return [""] * len(pa_lines), 0.0
    M, X, G = 2.0, -0.5, -1.0
    # điểm bằng mảng phẳng; n*m ≤ ~1.1e6 với văn bản dài nhất → chấp nhận được trong Python thuần? dùng list hàng.
    prev = [j * G for j in range(m + 1)]
    ptr = [bytearray(m + 1) for _ in range(n + 1)]   # 0 chéo, 1 lên (chữ Hán thừa), 2 trái (âm thừa)
    for j in range(1, m + 1):
        ptr[0][j] = 2
    for i in range(1, n + 1):
        cur = [i * G] + [0.0] * m
        ptr[i][0] = 1
        lx = lex.get(h[i - 1], ())
        wild = h[i - 1] in "？○"
        for j in range(1, m + 1):
            d = prev[j - 1] + (M if (sy[j - 1] in lx or wild or sy[j - 1] == "？") else X)
            u = prev[j] + G
            l = cur[j - 1] + G
            if d >= u and d >= l:
                cur[j] = d
            elif u >= l:
                cur[j], ptr[i][j] = u, 1
            else:
                cur[j], ptr[i][j] = l, 2
        prev = cur
    seg = [[] for _ in pa_lines]
    line_hit = [0] * len(pa_lines)
    bad_run = [0] * len(pa_lines)             # chuỗi chữ Hán liền nhau dài nhất KHÔNG khớp âm (nghi Chu_Han sai/tráo)
    run = 0
    i, j, hit = n, m, 0
    last_owner = owner[-1]
    while i > 0 or j > 0:
        p = ptr[i][j]
        if p == 0:
            seg[owner[j - 1]].append(han[i - 1])
            ok_ = sy[j - 1] in lex.get(h[i - 1], ())
            hit += ok_
            line_hit[owner[j - 1]] += ok_
            run = 0 if (ok_ or h[i - 1] in "？○" or sy[j - 1] == "？") else run + 1
            bad_run[owner[j - 1]] = max(bad_run[owner[j - 1]], run)
            if pairs is not None:
                pairs[h[i - 1]][sy[j - 1]] += 1
            last_owner = owner[j - 1]
            i, j = i - 1, j - 1
        elif p == 1:
            seg[last_owner].append(han[i - 1])     # chữ Hán thừa: gán cho câu PA đang xét
            run += 1
            bad_run[last_owner] = max(bad_run[last_owner], run)
            i -= 1
        else:
            last_owner = owner[j - 1]
            j -= 1
    align_han_pa.line_hit = line_hit          # độ khớp từng câu PA (đọc ngay sau lần gọi)
    align_han_pa.bad_run = bad_run
    return ["".join(reversed(s)) for s in seg], hit / max(n, m)


# ------------------------------------------------------------------ 2. Phiên âm ↔ Dịch nghĩa
def toks(s: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[^\W_]+", nfc(s))]


def train_ibm1(pairs: list[tuple[list[str], list[str]]], iters: int = 8) -> dict[str, dict[str, float]]:
    """IBM Model 1 t(dn_tok | pa_tok) học từ các cặp đã khớp chắc → từ điển dịch PA→DN (vd quyến/duy→kính/nghĩ)."""
    t: dict[str, dict[str, float]] = collections.defaultdict(dict)
    for a, b in pairs:
        for x in a + [None]:
            for y in b:
                t[x][y] = 1.0
    for _ in range(iters):
        cnt: dict = collections.defaultdict(lambda: collections.defaultdict(float))
        for a, b in pairs:
            src = a + [None]
            for y in b:
                z = sum(t[x][y] for x in src)
                for x in src:
                    cnt[x][y] += t[x][y] / z
        t = collections.defaultdict(dict)
        for x, row in cnt.items():
            s = sum(row.values())
            t[x] = {y: v / s for y, v in row.items()}
    return t


def trans_dict(t: dict, min_p: float = 0.12, top: int = 4) -> dict[str, list[tuple[str, float]]]:
    out = {}
    for x, row in t.items():
        if x is None:
            continue
        cand = sorted(((y, p) for y, p in row.items() if p >= min_p and y != x), key=lambda z: -z[1])[:top]
        if cand:
            out[x] = cand
    return out


def align_pa_dn(pa: list[str], dn: list[str], idf: dict[str, float], ratio: float,
                lenpen_w: float = LENPEN_W, tdict: dict | None = None) -> list[tuple[list[int], list[int], float]]:
    """ratio = số từ DN / số âm tiết PA điển hình của CẶP ĐÚNG (ước lượng ở main). Trước đây lấy tổng DN/tổng PA của
    cả văn bản → bị thổi phồng 2–3× vì DN dịch cả phần danh sách mà Hán/PA lược → DP gộp thừa câu dịch (9/39 cặp ok).
    tdict: từ điển dịch PA→DN (IBM1) — mở rộng túi từ PA bằng bản dịch có trọng số để khớp được câu diễn ý."""
    pt, dt = [toks(x) for x in pa], [toks(x) for x in dn]

    def sim(pi: list[int], di: list[int]) -> float:
        a = collections.Counter(t for i in pi for t in pt[i])
        b = collections.Counter(t for i in di for t in dt[i])
        w = lambda c: sum(idf.get(t, 1.0) * k for t, k in c.items())
        if tdict:
            ax: dict[str, float] = collections.defaultdict(float, a)
            for x, k in a.items():
                for y, p in tdict.get(x, ()):
                    ax[y] = max(ax[y], min(k, ax[y] + p * k))     # thêm bản dịch, không vượt số lần PA có
            inter = sum(idf.get(y, 1.0) * min(v, b[y]) for y, v in ax.items() if y in b)
        else:
            inter = w(a & b)
        lex = 2 * inter / (w(a) + w(b)) if a and b else 0.0
        la, lb = sum(a.values()) * ratio, sum(b.values())
        lenpen = abs(math.log((la + 1) / (lb + 1)))
        return lex - lenpen_w * lenpen

    n, m = len(pa), len(dn)
    moves = [(1, 1), (1, 2), (2, 1), (2, 2), (1, 3), (3, 1), (1, 0), (0, 1)]
    SKIP = -0.05
    best = [[-math.inf] * (m + 1) for _ in range(n + 1)]
    bp = [[None] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if best[i][j] == -math.inf:
                continue
            for di, dj in moves:
                a, b = i + di, j + dj
                if a > n or b > m:
                    continue
                s = SKIP if 0 in (di, dj) else sim(list(range(i, a)), list(range(j, b)))
                v = best[i][j] + s
                if v > best[a][b]:
                    best[a][b], bp[a][b] = v, (i, j)
    out = []
    i, j = n, m
    while (i, j) != (0, 0):
        pi, pj = bp[i][j]
        out.append((list(range(pi, i)), list(range(pj, j)),
                    sim(list(range(pi, i)), list(range(pj, j))) if pi < i and pj < j else 0.0))
        i, j = pi, pj
    out = out[::-1]
    # Vế dẫn ngắn kết thúc bằng ':' (Kính nghĩ: / Tôi đáp: / …biết được rằng:) dẫn vào câu SAU → chuyển sang cặp kế
    # (kiểm tay: dính vế dẫn là lỗi còn lại phổ biến nhất sau khi sửa tỉ lệ độ dài)
    for k in range(len(out) - 1):
        pi, di, _ = out[k]
        if len(di) >= 2 and dn[di[-1]].rstrip().endswith(":") and len(dt[di[-1]]) <= 8 \
                and not pa[pi[-1]].rstrip().endswith(":"):
            nk = next((q for q in range(k + 1, len(out)) if out[q][0] and out[q][1]), None)
            if nk is not None and out[nk][1][0] == di[-1] + 1:
                out[nk] = (out[nk][0], [di[-1]] + out[nk][1], sim(out[nk][0], [di[-1]] + out[nk][1]))
                out[k] = (pi, di[:-1], sim(pi, di[:-1]))
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    docs = load_docs()
    lex = refine_lexicon(docs, learn_lexicon(docs))
    df = collections.Counter(t for d in docs for line in d["dn"] + d["pa"] for t in set(toks(line)))
    nlines = sum(len(d["dn"]) + len(d["pa"]) for d in docs)
    idf = {t: math.log(nlines / c) for t, c in df.items()}
    OUT.mkdir(parents=True, exist_ok=True)
    REP.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.jsonl"):          # bỏ file của lần chạy/pipeline cũ (khác schema)
        old.unlink()
    # Lượt 1: tỉ lệ DN/PA từ các cặp 1–1 khớp chắc (từ vựng ≥ 0,3) → median mỗi văn bản (≥ 4 mẫu), không thì median chung
    samples: dict[str, list[float]] = {}
    for d in docs:
        if d["pa"] and d["dn"]:
            pt = [len(toks(x)) for x in d["pa"]]
            dt = [len(toks(x)) for x in d["dn"]]
            for pi, di, sc in align_pa_dn(d["pa"], d["dn"], idf, ratio=1.5):
                if len(pi) == 1 == len(di) and sc >= 0.3 and pt[pi[0]] >= 4:
                    samples.setdefault(d["id"], []).append(dt[di[0]] / pt[pi[0]])
    glob_r = statistics.median([x for v in samples.values() for x in v])
    ratio_of = {k: (statistics.median(v) if len(v) >= 4 else glob_r) for k, v in samples.items()}
    print(f"tỉ lệ DN/PA của cặp đúng: median chung {glob_r:.2f}")
    # Lượt 2: học từ điển dịch PA→DN (IBM1) từ các cặp khớp chắc của lượt gióng chỉ-dùng-từ-trùng
    train = []
    for d in docs:
        if d["pa"] and d["dn"]:
            for pi, di, sc in align_pa_dn(d["pa"], d["dn"], idf, ratio=ratio_of.get(d["id"], glob_r)):
                if pi and di and sc >= 0.2:
                    train.append(([t for i in pi for t in toks(d["pa"][i])], [t for i in di for t in toks(d["dn"][i])]))
    tdict = trans_dict(train_ibm1(train))
    print(f"từ điển dịch PA→DN: {len(tdict)} mục từ {len(train)} cặp; vd " +
          ", ".join(f"{k}→{'/'.join(y for y, _ in tdict[k][:2])}" for k in ("quyến", "duy", "viết", "ngã", "vân", "tất")
                    if k in tdict))
    rep, calib, review = [], [], []
    for d in docs:
        row = {"bia_id": d["id"], "han_chars": len(d["han"]), "pa_lines": len(d["pa"]), "dn_lines": len(d["dn"]),
               "han_pa_match": "", "pairs": 0, "ok": 0, "dn_unpaired": 0, "ghi_chu": ""}
        if not d["han"] or not d["pa"] or not d["dn"]:
            row["ghi_chu"] = "thiếu Hán/Phiên âm/Dịch nghĩa trong sách → không tạo cặp"
            rep.append(row)
            continue
        han_seg, hp = align_han_pa(d["han"], d["pa"], lex)
        line_hit, bad_run = align_han_pa.line_hit, align_han_pa.bad_run
        row["han_pa_match"] = round(hp, 3)
        r_doc = ratio_of.get(d["id"], glob_r)
        recs = []
        for pi, di, sc in align_pa_dn(d["pa"], d["dn"], idf, ratio=r_doc, tdict=tdict):
            if not pi or not di:
                row["dn_unpaired"] += len(di)
                continue
            han = "".join(han_seg[i] for i in pi)
            if not han:
                continue
            npa = sum(len(syllables(d["pa"][i])) for i in pi)
            han_hit = sum(line_hit[i] for i in pi) / max(1, npa, len(han))   # Hán↔PA của riêng cặp này
            pa_txt = " ".join(d["pa"][i] for i in pi)
            dn_txt = " ".join(d["dn"][i] for i in di)
            lr = len(toks(dn_txt)) / max(1.0, len(toks(pa_txt)) * r_doc)       # độ dài DN so với kỳ vọng
            why = []
            if han_hit < HAN_HIT_MIN:
                why.append(f"HAN_LECH_PHIEN_AM (khớp {han_hit:.2f})")
            if max(bad_run[i] for i in pi) >= BAD_RUN_MAX:
                why.append(f"NGHI_CHU_HAN_SAI ({max(bad_run[i] for i in pi)} chữ liền không khớp âm)")
            if not LEN_BAND[0] <= lr <= LEN_BAND[1]:
                why.append(f"DICH_NGHIA_{'THUA' if lr > 1 else 'THIEU'}_CAU (dài {lr:.2f}× kỳ vọng)")
            if "MASK" in pa_txt and "MASK" not in dn_txt and lr > 1.3:
                why.append("DICH_NGHIA_DAY_DU_HON_HAN (sách lược Hán, bản dịch đủ)")
            status = "needs_review" if why else "ok"
            if why:
                review.append([d["id"], len(recs) + 1, " ; ".join(why), pa_txt[:80], dn_txt[:80]])
            recs.append({"schema_version": 1, "bia_id": d["id"], "pair_id": len(recs) + 1,
                         "han": han.replace("？", "MASK"),
                         "phien_am": " ".join(d["pa"][i] for i in pi), "dich_nghia": " ".join(d["dn"][i] for i in di),
                         "score": round(max(0.0, sc), 4), "status": status})
            calib.append({"bia_id": d["id"], "pair_id": len(recs), "han_hit": round(han_hit, 3)})
        with open(OUT / f"{d['id']}.jsonl", "w", encoding="utf-8", newline="\n") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        row["pairs"], row["ok"] = len(recs), sum(r["status"] == "ok" for r in recs)
        rep.append(row)
    with open(REP / "report.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rep[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rep)
    with open(REP / "needs_review.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["bia_id", "pair_id", "ly_do", "phien_am_dau", "dich_nghia_dau"])
        w.writerows(review)
    with open(REP / "han_hit.csv", "w", encoding="utf-8", newline="") as f:   # để hiệu chuẩn lại
        w = csv.DictWriter(f, fieldnames=["bia_id", "pair_id", "han_hit"], lineterminator="\n")
        w.writeheader()
        w.writerows(calib)
    tp, tk = sum(r["pairs"] for r in rep), sum(r["ok"] for r in rep)
    print(f"từ điển: {len(lex)} chữ | văn bản: {len(rep)} | cặp: {tp} | ok: {tk} | DN không cặp: "
          f"{sum(r['dn_unpaired'] for r in rep)} dòng | -> {OUT} | báo cáo {REP}")


if __name__ == "__main__":
    main()
