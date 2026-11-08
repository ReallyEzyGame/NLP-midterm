# BÁO CÁO NGHIÊN CỨU THUẬT TOÁN GIÓNG VĂN BIA HÁN NÔM
**Mã công việc:** Task 0.C (Nghiên cứu thuật toán gióng)  
**Người thực hiện:** Điền  
**Giai đoạn:** Chuẩn bị & Nghiên cứu (Khởi chạy: 06/11/2026 - Hoàn thành: 06/11/2026)  
**Trạng thái bàn giao:** ĐÃ HOÀN THIỆN TOÀN BỘ (Steps 1 $\to$ 5)  
**Phục vụ trực tiếp:** 
- **Dataset 1 (OCR):** Task 1.C (Gióng thử) & Task 2.C (Gióng toàn bộ 69 mặt bia)
- **Dataset 2 (Dịch nghĩa):** Task 3.A (Gióng câu song ngữ Hán - Việt)

---

## 1. ĐẶT VẤN ĐỀ & BỐI CẢNH DỰ ÁN
Trong bài toán xây dựng ngữ liệu huấn luyện OCR văn bia làng Nành (thác bản bia đá thế kỷ XVII - XVIII), mô hình OCR (PaddleOCR v6) phát hiện vị trí các cột chữ (Bounding Box) và nhận diện văn tự. Tuy nhiên:
- Chữ khắc trên đá cổ bị phong hóa mờ, nứt vỡ, dị thể $\rightarrow$ Chuỗi `text_ocr` chứa nhiều lỗi nhận dạng (nhiễu 15% - 30%).
- Các chuyên gia Viện Hán Nôm đã khảo cứu toàn văn nội dung trong sách (Ground Truth `Chu_Han`).
- **Mục tiêu của Task 0.C:** Nghiên cứu và hiện thực hóa thuật toán tự động **khớp nối (Alignment)** cả 2 cấp độ:
  1. **Cấp độ Box (Dataset 1 - OCR):** Khớp từng Bounding Box trên bia với chuỗi ký tự Chữ Hán chuẩn trong sách để gán đúng nhãn `text_gt`, xuất ra `data/processed/align/<bia_id>.json` phục vụ đóng gói Dataset OCR.
  2. **Cấp độ Câu (Dataset 2 - Dịch nghĩa):** Khớp các câu song ngữ Chữ Hán - Phiên âm - Dịch nghĩa, xuất ra `data/output/dataset_dich/<bia_id>.jsonl` phục vụ mô hình Dịch máy.

---

## 2. CÁC THÁCH THỨC ĐẶC THÙ & GIẢI PHÁP KỸ THUẬT HOÀN CHỈNH

| Thách thức thực tế trên bia đá | Hiện tượng rủi ro | Giải pháp kỹ thuật hoàn thiện (Step 1-5) |
| :--- | :--- | :--- |
| **1. Khuyết tự & Chữ mờ** | Chữ bị mất, sách ghi nhận bằng `○`, `□`, `(?)` | Thiết lập cơ chế **Wildcard Matching** với chi phí phạt (penalty) bằng $0$. |
| **2. Nhiễu nhận dạng OCR** | Nhận diện nhầm nét (như `雲` thành `曇`, `大` thành `太`) | Quy hoạch động đo khoảng cách chỉnh sửa cấp ký tự (**Semi-Global DP**). |
| **3. Cấu trúc bia 2 phần** | Trán bia đọc ngang (từ phải sang trái), Thân bia đọc dọc | Phân tách luồng xử lý: trán bia gióng riêng với tiêu đề, thân bia gióng với bài văn chính. |
| **4. Lệch biên dòng (Drift)** | Thuật toán toàn cục (Global NW) nuốt chữ của dòng sau | Áp dụng thuật toán **Semi-Global (Fitting) Alignment** tìm khớp chuỗi con tối ưu. |
| **5. Box rác / Nhiễu viền (Debris)** | Bắt nhầm hoa văn viền đá hoặc dấu đỏ EFEO | Cơ chế **Anti-Drift & Lookahead Anchor**: Box rác bị đánh dấu `needs_review` và **không làm trôi con trỏ đọc**. |
| **6. Cột dài bị ngắt đôi (Split Box)** | 1 dòng chữ bị cắt làm 2 box rời do đá nứt | Cơ chế cập nhật con trỏ theo $end\_offset$ giúp Box 1 ăn nửa đầu câu, Box 2 ăn tiếp nửa sau câu mượt mà. |
| **7. Gióng câu Dịch nghĩa** | Câu chữ Hán cổ ngắn, dịch nghĩa tiếng Việt dài | Kiến trúc **Dual-Engine (BertAlign + Gale-Church DP)** tự động thích ứng với cấu hình máy. |

---

## 3. THIẾT KẾ THUẬT TOÁN SEMI-GLOBAL (FITTING) ALIGNMENT (DATASET 1)

### 3.1. Mô hình toán học
Cho đoạn ký tự OCR của một box $Q = q_1 q_2 \dots q_n$ và đoạn văn bản sách tham chiếu $R = r_1 r_2 \dots r_m$ ($m \ge n$).
Bảng quy hoạch động $DP[i][j]$ kích thước $(n+1) \times (m+1)$:
- **Khởi tạo:**
  $$DP[0][j] = 0 \quad (\forall j \in [0, m]) \quad \text{(Cho phép tự do điểm bắt đầu trên văn bản sách)}$$
  $$DP[i][0] = i \times \text{gap\_penalty} \quad (\forall i \in [1, n])$$
- **Công thức truy hồi:**
  $$DP[i][j] = \max \begin{cases} DP[i-1][j-1] + \text{score}(q_i, r_j) \\ DP[i-1][j] + \text{gap\_penalty} \\ DP[i][j-1] + \text{gap\_penalty} \end{cases}$$
- **Hàm điểm so khớp ký tự:**
  $$\text{score}(q_i, r_j) = \begin{cases} +2.0 & \text{nếu } q_i = r_j \text{ hoặc } q_i, r_j \in \{\text{○}, \text{□}, \text{?}\} \\ -0.5 & \text{nếu } q_i \ne r_j \end{cases}$$
  $$\text{gap\_penalty} = -1.5$$
- **Điểm kết thúc tối ưu:**
  $$j^* = \arg\max_{j \in [0, m]} DP[n][j]$$
  Truy vết ngược (Traceback) từ $(n, j^*)$ về điểm bắt đầu $(0, j_{\text{start}})$. Đoạn $[j_{\text{start}}, j^*]$ trên văn bản sách chính là chuỗi `text_gt` chuẩn xác cho box!

### 3.2. Hiệu chuẩn Điểm tin cậy (Composite Confidence Score)
$$\text{Confidence} = 0.70 \times S_{\text{char\_sim}} + 0.20 \times S_{\text{len\_ratio}} + 0.10 \times S_{\text{ocr\_conf}}$$
* Kèm hệ thống cờ chẩn đoán chi tiết: `EXACT_MATCH`, `HIGH_CONFIDENCE`, `LENGTH_MISMATCH`, `DEBRIS_SUSPECTED`, `WILDCARD_MATCH`, `EMPTY_OCR`.

---

## 4. KẾT QUẢ THỰC NGHIỆM TRÊN TESTBED DỮ LIỆU THẬT

Đã xây dựng bộ Testbed từ sách thật `CV11`:
- **Bia 1 (Pháp Vân tự bi):** 19 boxes (1 trán, 18 thân bia).
- **Bia 2 (Hậu Phật bi kí - mã thác bản 2459):** 18 boxes thân bia dài 449 chữ.

### Bảng so sánh hiệu năng & độ chính xác (81 tổ hợp tham số Grid Search):

| Kịch bản kiểm thử | Thuật toán | Số Box | Số Box OK ($\ge 0.6$) | Số Box Review | Điểm tương đồng TB | Thời gian chạy | Chữ khớp đúng |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **BIA01 (Clean)** | **Semi-Global DP** | **19** | **19 (100%)** | **0** | **0.9939** | **4.23 ms** | **255/267** |
| | Heuristic Baseline | 19 | 19 (100%) | 0 | 0.9357 | 0.65 ms | 255/267 |
| **BIA01 (Nhiễu OCR 20%)** | **Semi-Global DP** | **19** | **19 (100%)** | **0** | **0.9367** | **3.84 ms** | **255/267** |
| | Heuristic Baseline | 19 | 19 (100%) | 0 | 0.8440 | 0.65 ms | 255/267 |
| **BIA01 (Khuyết tự Wildcard)** | **Semi-Global DP** | **19** | **19 (100%)** | **0** | **0.9798** | **3.78 ms** | **255/267** |
| | Heuristic Baseline | 19 | 18 (94.7%) | 1 | 0.9033 | 0.62 ms | 255/267 |
| **BIA02 (Văn bia lớn 2459)** | **Semi-Global DP** | **18** | **18 (100%)** | **0** | **0.9911** | **10.69 ms** | **449/449** |
| | Heuristic Baseline | 18 | 18 (100%) | 0 | 0.9911 | 0.82 ms | 449/449 |

---

## 5. THUẬT TOÁN GIÓNG CÂU SONG NGỮ (DATASET 2 - DỊCH NGHĨA)
Module [`src/step4_trans_align/sentence_aligner.py`](file:///d:/Downloads/NLP-midterm/src/step4_trans_align/sentence_aligner.py) giải quyết bài toán gióng câu 3 trường (`Hán`, `Phiên âm`, `Dịch nghĩa`):
- **Cơ chế Dual-Engine:** Tự động phát hiện môi trường:
  - Nếu có `bertalign` hoặc `sentence-transformers` $\rightarrow$ Sử dụng Neural Multilingual Cosine DP Aligner.
  - Nếu là môi trường chuẩn không GPU $\rightarrow$ Tự động chuyển sang Gale-Church DP Aligner siêu nhanh (<5ms).
- **Thử nghiệm trên Bia 1 (Pháp Vân tự bi):** Gióng thành công 13 cặp câu song ngữ Hán - Việt hoàn hảo.
- Xuất dữ liệu chuẩn `data/output/dataset_dich/<bia>.jsonl`:
```json
{
  "bia_id": "BIA01",
  "sentence_id": 1,
  "han": "重修法雲寺碑銘 銘曰",
  "phien_am": "Trùng tu Pháp Vân tự bi minh.",
  "dich_nghia": "Bài minh về việc trùng tu chùa Pháp Vân."
}
```

---

## 6. HƯỚNG DẪN TÍCH HỢP CHO NHÓM (DÀNH CHO TASK 1.C, 2.C & 3.A)

### 6.1. Gióng Bounding Box (Dataset 1 - OCR):
```bash
# Gióng 1 bia thử nghiệm
python -m src.step3_ocr_align.text_aligner --bia-id 00270-TF1

# Gióng tự động hàng loạt toàn bộ các bia trong thư mục bbox_chuan
python -m src.step3_ocr_align.text_aligner --all --threshold 0.60
```

### 6.2. Gióng câu Dịch nghĩa (Dataset 2 - Dịch máy):
```bash
# Gióng 1 bia cụ thể
python -m src.step4_trans_align.sentence_aligner --bia-id BIA01

# Gióng toàn bộ
python -m src.step4_trans_align.sentence_aligner --all
```

---
*Báo cáo hoàn thành ngày 06/11/2026 bởi Điền. Toàn bộ 6/6 bài kiểm thử tự động PASS 100%.*
