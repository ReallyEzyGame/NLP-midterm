"""Aligner v3: neo toàn cục 2 lượt + chuỗi đơn điệu (chain DP) + gióng trán theo vị trí + hỗ trợ MASK.

Khác v2.2 (`text_aligner.DynamicProgrammingAligner`), đo trên 76 mặt cùng OCR: +10% box ok, nhanh hơn
(test_debug/checklist_debug.md §9, test_debug/result/result.md):
- v2.2 dò tham lam bằng con trỏ + cửa sổ ngắn → một box lệch là cả chuỗi sau trôi; mặt 2+ khởi động lại từ 0.
- v3 lượt 1: box DÀI (≥ 5 chữ) lấy k vị trí ứng viên trên TOÀN văn sách (semi-global DP, numpy), chọn một dãy
  vị trí TĂNG DẦN theo thứ tự đọc với tổng điểm lớn nhất (chaining như căn chỉnh genome) → các "neo".
  Bỏ qua được đoạn sách lược bỏ và box không có trong sách, không trôi.
- v3 lượt 2: các box còn lại (ngắn, tên người, câu minh 4 chữ, box dài bị loại) chỉ được tìm TRONG KHE sách giữa
  hai neo kề nhau → box ngắn không thể khớp bừa ở chỗ khác trong văn bản.
- Lượt 3: box dài khớp chặt nhưng lệch thứ tự (sách/OCR sách đảo dòng).
- Trán bia: box trán (thường 1 chữ/box) ghép lại, gióng với dòng tiêu đề sách, gán nhãn theo VỊ TRÍ
  (chữ OCR sai như 低 vẫn nhận nhãn đúng 佛) khi số chữ trán khớp số chữ tiêu đề.
- MASK (giảng viên 14/11/2026: chữ mất/sách lược → "MASK"): MASK trong Chu_Han = đoạn chưa biết dài bao nhiêu, nuốt 0..n
  chữ OCR; nhãn kiểu `阮有進MASK`; dãy box kẹp giữa 2 neo chắc mà khe sách chỉ là MASK → nhãn `MASK`.
Chấm điểm/chẩn đoán dùng lại `_build_item` của v2.2 để ngưỡng ok/needs_review giữ nguyên ý nghĩa.
"""
from __future__ import annotations

import numpy as np

from src.step3_ocr_align.align_schema import WILDCARD_CHARS, AlignItem, AlignResult, sanitize_text
from src.step3_ocr_align.text_aligner import (
    DynamicProgrammingAligner,
    clean_gt_text,
    normalize_han_str,
    semi_global_align,
)

K_CAND = 6          # số ứng viên mỗi box
MIN_SIM = 0.5       # box dài: dưới mức này không là ứng viên
MIN_SIM_SHORT = 0.7  # box ngắn (≤ SHORT_LEN): cần khớp chặt hơn (như guard của v2.2)
SHORT_LEN = 4
BACK_TOL = 6        # cho phép 2 box chồng mép tối đa (box OCR hay dính chữ cột bên)
LOOKBACK = 40       # số box trước tối đa xét làm tiền nhiệm (giới hạn O(N^2))
GAP_SLACK = 12      # nới khe 2 đầu ở lượt 2
OOO_MIN_LEN, OOO_MIN_SIM = 8, 0.75   # lượt 3: box dài khớp chặt nhưng lệch thứ tự (sách/OCR sách đảo dòng)
ENDS_MIN_SIM, ENDS_MIN_LENR = 0.55, 0.85  # nới "neo 2 đầu": vị trí chắc chắn dù OCR sai giữa cột
# Giảng viên (14/11): chữ mất/sách lược `[...]` → nhãn "MASK". Trong sách token MASK (regex_filter chèn) được đổi thành
# 1 ký tự khuyết của repo để DP coi là khớp-bất-kỳ, rồi đổi lại thành "MASK" khi xuất nhãn.
MASK, PH = "MASK", "□"
MASK_NEIGHBOR_SIM = 0.8   # box nằm trong đoạn sách lược chỉ nhận nhãn MASK khi 2 box neo kề bên khớp chắc


def est_chars(points) -> float:
    """Ước lượng số chữ trong box = cạnh dài / cạnh ngắn (chữ Hán gần vuông)."""
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    return max(w, h) / max(1.0, min(w, h))


def ends_anchored(o: str, gt: str, k: int = 3, need: int = 2) -> bool:
    """Hai đầu box khớp đầu/cuối nhãn (≥ need/k chữ, đã chuẩn hoá dị thể) → ranh giới nhãn đáng tin."""
    o, gt = normalize_han_str(o), normalize_han_str(gt)
    if min(len(o), len(gt)) < 2 * k:
        return False
    head = sum(ch in gt[: k + 1] for ch in o[:k])        # +1: chịu được OCR rớt/thừa 1 chữ ở mép
    tail = sum(ch in gt[-(k + 1):] for ch in o[-k:])
    return head >= need and tail >= need


def fit_last_row(o: str, g: str, M=2.0, X=-1.0, G=-1.5):
    """Semi-global (o khớp trọn, g tự do 2 đầu). Trả (điểm hàng cuối, vị trí bắt đầu) cho mọi điểm kết thúc."""
    m = len(g)
    garr = np.frombuffer(g.encode("utf-32-le"), dtype=np.uint32)
    gwild = np.isin(garr, [ord(c) for c in WILDCARD_CHARS])
    # MASK nuốt thêm chữ OCR không tốn điểm (đoạn lược dài chưa biết số chữ)
    up_cost = np.concatenate([[G], np.where(garr == ord(PH), 0.0, G)])
    idx = np.arange(m + 1)
    prev = np.zeros(m + 1)
    start = idx.copy()
    for ch in o:
        eq = (garr == ord(ch)) | gwild | (ch in WILDCARD_CHARS)
        diag = prev[:-1] + np.where(garr == ord(PH), 0.0, np.where(eq, M, X))
        up = prev + up_cost
        tmp, tst = up.copy(), start.copy()
        better = diag > up[1:]
        tmp[1:] = np.where(better, diag, up[1:])
        tst[1:] = np.where(better, start[:-1], start[1:])
        # cur[j] = max_{k<=j} tmp[k] + (j-k)*G  (đi ngang = gap trên o) — tính bằng max tích luỹ
        val = tmp - idx * G
        acc = np.maximum.accumulate(val)
        arg = np.maximum.accumulate(np.where(val >= acc, idx, 0))
        prev, start = acc + idx * G, tst[arg]
    return prev, start


def fit_mask(o: str, g: str, M=2.0, X=-1.0, G=-1.5) -> tuple[str, float, int, int]:
    """Như semi_global_align của repo nhưng PH (MASK) khớp 1..n chữ OCR. sim = 2·khớp/(|o| + |nhãn| với MASK giãn
    theo số chữ nó nuốt). Nhãn không có chữ thật nào khớp → sim 0 (box 1 chữ không được 'khớp' vào MASK)."""
    n, m = len(o), len(g)
    if not n or not m:
        return "", 0.0, 0, 0
    eq = lambda a, b: b == PH or a == b or a in WILDCARD_CHARS or b in WILDCARD_CHARS
    # khớp MASK = 0 điểm (không thắng được một chữ thật / lỗi OCR 1 chữ), nuốt thêm chữ cũng 0
    sc = lambda a, b: 0.0 if b == PH else (M if eq(a, b) else X)
    dp = np.full((n + 1, m + 1), -1e9)
    dp[0, :] = 0.0
    for i in range(1, n + 1):
        dp[i, 0] = i * G
        for j in range(1, m + 1):
            up = dp[i - 1, j] + (0.0 if g[j - 1] == PH else G)
            dp[i, j] = max(dp[i - 1, j - 1] + sc(o[i - 1], g[j - 1]), up, dp[i, j - 1] + G)
    be = int(np.argmax(dp[n]))
    i, j, real, absorbed, lab = n, be, 0, 0, []
    fit_mask.skip = set()          # vị trí MASK bị nhảy qua (không nuốt chữ OCR nào) → bỏ khỏi nhãn
    while i > 0 and j > 0:
        d = dp[i - 1, j - 1] + sc(o[i - 1], g[j - 1])
        if dp[i, j] == d:
            hit = eq(o[i - 1], g[j - 1])
            real += hit and g[j - 1] != PH
            absorbed += g[j - 1] == PH
            lab.append(g[j - 1])
            i, j = i - 1, j - 1
        elif g[j - 1] == PH and dp[i, j] == dp[i - 1, j]:
            absorbed += 1
            i -= 1
        elif dp[i, j] == dp[i - 1, j] + G:
            i -= 1
        else:
            if g[j - 1] == PH:
                fit_mask.skip.add(j - 1)
            else:
                lab.append(g[j - 1])
            j -= 1
    lab = "".join(reversed(lab))
    book_real = len(lab.replace(PH, ""))
    if real < 2 or book_real < 2:
        return lab, 0.0, j, be
    # sim chỉ trên phần chữ thật (chữ OCR bị MASK nuốt không tính 2 phía) → cùng thang với v2.2
    fit_mask.absorbed = absorbed
    return lab, round(min(1.0, 2.0 * real / (n - absorbed + book_real)), 4), j, be


def candidates(o: str, g: str, lo: int = 0, hi: int | None = None, k: int = K_CAND) -> list[tuple[int, int, float]]:
    """k vị trí tốt nhất (không chồng nhau) của o trong g[lo:hi]: (start, end, sim) theo chỉ số của g."""
    hi = len(g) if hi is None else min(hi, len(g))
    lo = max(0, lo)
    sub = g[lo:hi]
    if not o or not sub:
        return []
    min_sim = MIN_SIM_SHORT if len(o) <= SHORT_LEN else MIN_SIM
    score, start = fit_last_row(o, sub)
    floor = 4.0 if PH in sub else 0.2 * 2.0 * len(o)   # có MASK: phần bị nuốt không ghi điểm → sàn = 2 chữ khớp
    out: list[tuple[int, int, float]] = []
    taken: list[tuple[int, int]] = []
    for e in np.argsort(-score, kind="stable"):
        if score[e] < floor or len(out) >= k:
            break
        s, e = int(start[e]), int(e)
        if e <= s or any(s < te and e > ts for ts, te in taken):
            continue
        taken.append((s, e))
        a = max(0, s - 2)
        win = sub[a : e + 2]
        _, sim, ms, me = fit_mask(o, win) if PH in win else semi_global_align(o, win)   # sim như v2.2
        if sim >= min_sim and me > ms:
            out.append((lo + a + ms, lo + a + me, sim))
    return out


def chain(cands: list[list[tuple[int, int, float]]], lens: list[int]) -> dict[int, int]:
    """Chọn ≤1 ứng viên/box sao cho vị trí sách tăng dần theo thứ tự box, tổng sim*len lớn nhất. Trả {box: ứng viên}."""
    n = len(cands)
    best = [[0.0] * len(c) for c in cands]
    back: list[list[tuple[int, int] | None]] = [[None] * len(c) for c in cands]
    for i in range(n):
        for ci, (s, e, sim) in enumerate(cands[i]):
            bv, bp = 0.0, None
            for j in range(max(0, i - LOOKBACK), i):
                for cj, (sj, ej, _) in enumerate(cands[j]):
                    if s < ej - BACK_TOL:
                        continue
                    v = best[j][cj] - 0.01 * min(max(s - ej, 0), 300)   # phạt nhẹ nhảy xa: phá thế hoà giữa cụm lặp
                    if v > bv:
                        bv, bp = v, (j, cj)
            best[i][ci] = sim * lens[i] + bv
            back[i][ci] = bp
    flat = [(best[i][c], i, c) for i in range(n) for c in range(len(cands[i]))]
    chosen: dict[int, int] = {}
    if flat:
        _, i, c = max(flat)
        node: tuple[int, int] | None = (i, c)
        while node is not None:
            chosen[node[0]] = node[1]
            node = back[node[0]][node[1]]
    return chosen


def map_positions(o: str, g: str, M=2.0, X=-1.0, G=-1.5) -> tuple[list[int | None], float]:
    """Global NW giữa o và g: trả vị trí trong g của từng chữ o (None nếu o-chữ là gap) và tỉ lệ khớp."""
    n, m = len(o), len(g)
    dp = np.zeros((n + 1, m + 1))
    dp[:, 0] = np.arange(n + 1) * G
    dp[0, :] = np.arange(m + 1) * G
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i, j] = max(dp[i - 1, j - 1] + (M if o[i - 1] == g[j - 1] else X), dp[i - 1, j] + G, dp[i, j - 1] + G)
    pos: list[int | None] = [None] * n
    i, j, hit = n, m, 0
    while i > 0 and j > 0:
        if dp[i, j] == dp[i - 1, j - 1] + (M if o[i - 1] == g[j - 1] else X):
            pos[i - 1] = j - 1
            hit += o[i - 1] == g[j - 1]
            i, j = i - 1, j - 1
        elif dp[i, j] == dp[i - 1, j] + G:
            i -= 1
        else:
            j -= 1
    return pos, (2 * hit / (n + m) if n + m else 0.0)


class AlignerV3(DynamicProgrammingAligner):
    def _align_tran(self, boxes, ocrs, title_o: str, title: str) -> dict[int, AlignItem]:
        """Gióng các box trán với dòng tiêu đề, gán nhãn theo vị trí chữ."""
        idx = [i for i, b in enumerate(boxes) if b.get("region") == "tran" and ocrs[i]]
        out: dict[int, AlignItem] = {}
        if not idx or not title:
            return out
        joined = "".join(ocrs[i] for i in idx)
        best = None
        for seq, rev in ((joined, False), (joined[::-1], True)):
            pos, sim = map_positions(normalize_han_str(seq), title)
            if best is None or sim > best[1]:
                best = (pos, sim, rev)
        pos, sim, rev = best
        if rev:
            pos = pos[::-1]
        same_len = len(joined) == len(title)
        k = 0
        for i in idx:
            b, n = boxes[i], len(ocrs[i])
            p = [x for x in pos[k : k + n] if x is not None]
            k += n
            label = "".join(title_o[x] for x in sorted(p)) if len(p) == n else ""
            exact = label and normalize_han_str(label) == normalize_han_str(ocrs[i])
            conf = float(b.get("score", 0.9))
            if label and (exact or (same_len and sim >= 0.5)):
                note = "V3_TRAN_POSITIONAL" + (" | đảo chiều" if rev else "")
                out[i] = AlignItem(order=b["order"], text_ocr=sanitize_text(b.get("text_ocr", "")), text_gt=label,
                                   score=round(max(sim, 0.8 if exact else sim), 4), status="ok", region="tran", note=note)
        return out

    def align(self, bia_id: str, boxes: list[dict], gt_text: str) -> AlignResult:
        gt_text = gt_text.replace(MASK, PH)
        lines = [clean_gt_text(x) for x in gt_text.splitlines() if clean_gt_text(x)]
        g_orig = "".join(lines)
        g = normalize_han_str(g_orig)          # chuẩn hoá dị thể 1 chữ ↔ 1 chữ nên vị trí trùng với g_orig
        title_o = lines[0] if lines else ""
        boxes = sorted(boxes, key=lambda b: b["order"])
        ocrs = [clean_gt_text(sanitize_text(b.get("text_ocr", ""))) for b in boxes]
        norm = [normalize_han_str(o) for o in ocrs]

        tran_items = self._align_tran(boxes, ocrs, title_o, normalize_han_str(title_o))
        body = [i for i, b in enumerate(boxes) if i not in tran_items and ocrs[i]]

        # Lượt 1: neo bằng box dài, tìm toàn văn
        longs = [i for i in body if len(ocrs[i]) > SHORT_LEN]
        c1 = [candidates(norm[i], g) for i in longs]
        picked = {longs[a]: c1[a][c] for a, c in chain(c1, [len(ocrs[i]) for i in longs]).items()}
        ooo: set[int] = set()

        # Lượt 2: các box chưa neo, tìm trong khe sách giữa 2 neo kề nhau
        anchors = sorted(picked)
        run: list[int] = []
        for pos_i, i in enumerate(body + [None]):
            if i is not None and i not in picked:
                run.append(i)
                continue
            if run:
                prev = max((a for a in anchors if a < run[0]), default=None)
                nxt = min((a for a in anchors if a > run[-1]), default=None)
                lo = picked[prev][1] - GAP_SLACK if prev is not None else 0
                need = sum(len(ocrs[r]) for r in run)
                hi = picked[nxt][0] + GAP_SLACK if nxt is not None else lo + 2 * need + 2 * GAP_SLACK
                c2 = [candidates(norm[r], g, lo, hi) for r in run]
                for a, c in chain(c2, [len(ocrs[r]) for r in run]).items():
                    picked[run[a]] = c2[a][c]
                run = []

        # Lượt 3: box dài vẫn chưa khớp → tìm toàn văn, không buộc tăng dần, chỉ nhận khi khớp chặt và không đè nhãn đã gán
        used = [(s_, e_) for s_, e_, _ in picked.values()]
        for i in body:
            if i in picked or len(ocrs[i]) < OOO_MIN_LEN:
                continue
            for s_, e_, sim in candidates(norm[i], g, k=1):
                if sim >= OOO_MIN_SIM and not any(min(e_, ue) - max(s_, us) > 0.3 * (e_ - s_) for us, ue in used):
                    picked[i] = (s_, e_, sim)
                    used.append((s_, e_))
                    ooo.add(i)

        # Lượt 4 (MASK): dãy box chưa khớp kẹp giữa 2 neo chắc mà khe sách giữa 2 neo chỉ là MASK → các box đó là phần
        # sách lược/chữ mất → nhãn "MASK". Dãy ở cuối chỉ nhận khi văn bản sách KẾT THÚC bằng MASK.
        mask_box: dict[int, float] = {}
        seq = [i for i in body]
        k = 0
        while k < len(seq):
            if seq[k] in picked:
                k += 1
                continue
            j = k
            while j < len(seq) and seq[j] not in picked:
                j += 1
            prev = seq[k - 1] if k > 0 else None
            nxt = seq[j] if j < len(seq) else None
            if prev is not None and picked[prev][2] >= MASK_NEIGHBOR_SIM:
                pe = picked[prev][1]
                if nxt is not None and picked[nxt][2] >= MASK_NEIGHBOR_SIM:
                    gap, conf_ = g[max(0, pe - 1) : picked[nxt][0] + 1], min(picked[prev][2], picked[nxt][2])
                elif nxt is None:
                    gap, conf_ = g[max(0, pe - 1) :], picked[prev][2]
                else:
                    gap = ""
                # gap gồm 1 chữ mép của mỗi neo + MASK: không còn chữ sách nào chưa có box nhận
                if PH in gap and len(gap.replace(PH, "")) <= (2 if nxt is not None else 1):
                    for r in seq[k:j]:
                        mask_box[r] = conf_
            k = j

        items = []
        for i, b in enumerate(boxes):
            if i in tran_items:
                items.append(tran_items[i])
                continue
            if i in mask_box:
                items.append(AlignItem(order=b["order"], text_ocr=sanitize_text(b.get("text_ocr", "")), text_gt=MASK,
                                       score=round(mask_box[i], 4), status="ok", region=b.get("region", "than"),
                                       note="V3_MASK_DOAN_SACH_LUOC"))
                continue
            ocr = sanitize_text(b.get("text_ocr", ""))
            conf = float(b.get("score", 0.9))
            region = b.get("region", "than")
            if i in picked:
                s, e, sim = picked[i]
                gt = g_orig[s:e]           # nhãn = chữ GỐC của sách, không phải dạng chuẩn hoá
                ocr_eff, gt_eff = ocr, gt
                if PH in gt:               # MASK mà bia không thiếu chữ nào ở đó → bỏ khỏi nhãn
                    fit_mask.absorbed = 0
                    fit_mask(norm[i], g[s:e])
                    gt = "".join(c for k, c in enumerate(gt) if k not in fit_mask.skip)
                    # điểm tổng (phạt lệch độ dài) chỉ xét phần chữ thật: bỏ chữ OCR bị MASK nuốt và chính MASK
                    ocr_eff = ocr[: max(1, len(ocr) - fit_mask.absorbed)]
                    gt_eff = gt.replace(PH, "") or gt
                it = self._build_item(b["order"], ocr_eff, gt_eff, sim, conf, region,
                                      "V3_OUT_OF_ORDER" if i in ooo else "V3_CHAIN")
                it.text_ocr, it.text_gt = ocr, gt
                lr = min(len(ocrs[i]), len(gt)) / max(len(ocrs[i]), len(gt))
                # Spot-check 20 mẫu: chỉ 12/20 nhãn sạch (nhiều chỗ Chu_Han bị tráo đoạn) → KHÔNG tự nâng lên ok,
                # chỉ đánh dấu: vị trí chắc chắn, giữa cột lệch → ưu tiên sửa tay + nghi Chu_Han sai (RC10)
                if it.status != "ok" and sim >= ENDS_MIN_SIM and lr >= ENDS_MIN_LENR and ends_anchored(ocrs[i], gt):
                    it.note += " | V3_ENDS_ANCHORED_NGHI_CHU_HAN_SAI"
                # box chứa nhiều chữ hơn hẳn số chữ OCR đọc được → nhãn sẽ thiếu chữ (spot-check #24 bản gộp)
                if it.status == "ok" and "points" in b and est_chars(b["points"]) >= 1.8 * max(1, len(ocrs[i])) + 0.5:
                    it.status, it.note = "needs_review", it.note + " | V3_BOX_NHIEU_CHU_HON_OCR"
                it.text_gt = it.text_gt.replace(PH, MASK)
                items.append(it)
            else:
                items.append(self._build_item(b["order"], ocr, "", 0.0, conf, region, "V3_NOT_IN_BOOK"))
        return AlignResult(bia_id=bia_id, items=items)


def _selftest() -> None:
    a = AlignerV3(threshold=0.8)
    book = "后佛碑記\n" + "天開南越地闢北京縣名東岸社號扶寧" + "甲" * 50 + "氣鍾山岳人稟精英挺生貴將出佐聖明"
    boxes = [
        {"order": 1, "region": "tran", "text_ocr": "記", "score": 0.9},
        {"order": 2, "region": "tran", "text_ocr": "碑", "score": 0.9},
        {"order": 3, "region": "tran", "text_ocr": "低", "score": 0.9},                  # OCR sai, vị trí đúng
        {"order": 4, "region": "tran", "text_ocr": "後", "score": 0.9},
        {"order": 5, "region": "than", "text_ocr": "天開南越地闢北京", "score": 0.9},
        {"order": 6, "region": "than", "text_ocr": "一所東良處一高", "score": 0.9},      # không có trong sách
        {"order": 7, "region": "than", "text_ocr": "縣名東岸社號扶寧", "score": 0.9},
        {"order": 8, "region": "than", "text_ocr": "氣鍾山岳人禀精英", "score": 0.9},    # sau đoạn sách lược
        {"order": 9, "region": "than", "text_ocr": "挺生貴將", "score": 0.9},             # box ngắn đúng khe
        {"order": 10, "region": "than", "text_ocr": "天開", "score": 0.9},                # box ngắn lạc chỗ
    ]
    st = {it.order: it for it in a.align("T", boxes, book).items}
    assert st[3].status == "ok" and st[3].text_gt == "佛", st[3]
    assert st[5].status == "ok" and st[5].text_gt == "天開南越地闢北京"
    assert st[6].status == "needs_review"
    assert st[7].text_gt == "縣名東岸社號扶寧"
    assert st[8].status == "ok" and st[8].text_gt == "氣鍾山岳人稟精英"   # nhãn giữ chữ gốc sách (鍾, 稟)
    assert st[9].status == "ok" and st[9].text_gt == "挺生貴將"
    assert st[10].status == "needs_review"
    # MASK: '？' 1 chữ khuyết khớp bất kỳ; đoạn sách lược kẹp giữa 2 neo → box giữa nhận nhãn MASK
    book2 = "后佛碑記\n天開南越地闢北京縣MASK東岸社號扶寧\n監生阮克宅MASK全村上下等爲保后佛事"
    boxes2 = [
        {"order": 1, "region": "than", "text_ocr": "天開南越地闢北京縣名東岸社號扶寧", "score": 0.9},
        {"order": 2, "region": "than", "text_ocr": "監生阮克宅", "score": 0.9},
        {"order": 3, "region": "than", "text_ocr": "阮文甲阮文乙阮文丙", "score": 0.9},     # tên bị sách lược
        {"order": 4, "region": "than", "text_ocr": "全村上下等爲保后佛事", "score": 0.9},
    ]
    st = {it.order: it for it in a.align("T", boxes2, book2).items}
    assert st[1].status == "ok" and st[1].text_gt == "天開南越地闢北京縣MASK東岸社號扶寧", st[1]
    assert st[3].status == "ok" and st[3].text_gt == "MASK", st[3]
    assert st[4].text_gt == "全村上下等爲保后佛事", st[4]
    boxes3 = [dict(boxes2[0]), {"order": 2, "region": "than", "text_ocr": "監生阮克宅儒院有賓", "score": 0.9},
              {"order": 3, "region": "than", "text_ocr": "全村上下等爲保后佛事", "score": 0.9},
              {"order": 4, "region": "tran", "text_ocr": "流", "score": 0.9}]
    st = {it.order: it for it in a.align("T", boxes3, book2).items}
    assert st[2].text_gt == "監生阮克宅MASK", st[2]          # MASK nuốt 4 chữ tên bị lược, không lấn sang 全村上
    assert st[3].text_gt == "全村上下等爲保后佛事", st[3]
    assert st[4].status == "needs_review", st[4]             # box 1 chữ không được khớp vào MASK
    assert fit_mask("流", PH)[1] == 0.0
    assert fit_mask("行禮祭畢官貝貳具", "行禮祭畢" + PH + "官員二具")[0] == "行禮祭畢官員二具"
    assert fit_mask("村長石伯疆", "村長石伯暄" + PH)[0] == "村長石伯暄"
    assert ends_anchored("鄉黨迺於溪丑年分賜今社使錢陛拾貫并田五高酒自錢肆", "鄉党遰於癸丑年公賜本社使錢三十貫並田五高酒肉錢四")
    assert not ends_anchored("阮廷紳阮碩寳全社上下小等為立碑敘", "譚仕厚阮登貴仝社上下巨小等為立碑敘")
    assert est_chars([[0, 0], [300, 0], [300, 100], [0, 100]]) == 3.0
    print("aligner_v3 selftest: ĐẠT")


if __name__ == "__main__":
    _selftest()
