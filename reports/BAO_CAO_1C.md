# Báo cáo Bước 1.C — Gióng thử & Hiệu chuẩn tham số (Trial Alignment)

Người thực hiện: Điền (C) · Ngày chạy: 12/11/2026 · Nguồn dữ liệu: **Dữ liệu OCR thật (1.A + 1.B)** · Ngưỡng hiệu chuẩn: `0.80`

## 1. Tổng hợp kết quả chuyển đổi & gióng hàng

- **Tổng số mặt bia chạy thử**: 3 mặt bia
- **Lọc box nhiễu/lề giấy rập (`paddle_adapter`)**: 114 box thô → loại 15 box rác/lề thư viện → giữ **99 box nội dung chuẩn**
- **Kết quả gióng chuẩn (`ok`)**: **48/99** (48.5%)
- **Danh sách cần rà soát (`needs_review.csv`)**: **51 box**

### Bảng chi tiết từng mặt bia

| Mã bia (`bia_id`) | File Chữ Hán (1.A) | Raw boxes | Nhiễu lề loại | Box chuẩn | Trán/Thân | OK | Needs Review | Điểm TB |
|---|---|---:|---:|---:|---|---:|---:|---:|
| `02459-31` | `02459-31_02460-32_02461-33.txt` | 58 | 5 | 53 | 4 / 49 | **35** | 18 | 0.692 |
| `02460-32` | `02459-31_02460-32_02461-33.txt` | 14 | 5 | 9 | 0 / 9 | **9** | 0 | 0.951 |
| `02461-33` | `02459-31_02460-32_02461-33.txt` | 42 | 5 | 37 | 0 / 37 | **4** | 33 | 0.177 |

## 2. Kết quả Chỉnh thử (Calibration Sweep theo ngưỡng `threshold`)

| Ngưỡng (`threshold`) | Tổng box chuẩn | OK | Needs Review | Tỷ lệ OK (%) | Điểm TB | Nhận xét |
|---:|---:|---:|---:|---:|---:|---|
| `0.60` | 99 | 49 | 50 | 49.5% | 0.5230 | Dễ lọt box trùng tên họ ngắn (2/3 chữ) |
| `0.70` | 99 | 48 | 51 | 48.5% | 0.5230 | Dễ lọt box trùng tên họ ngắn (2/3 chữ) |
| `0.75` | 99 | 48 | 51 | 48.5% | 0.5230 | Dễ lọt box trùng tên họ ngắn (2/3 chữ) |
| `0.80` | 99 | 48 | 51 | 48.5% | 0.5230 | Khuyến nghị chuẩn (Data Contract v1.0) |
| `0.85` | 99 | 45 | 54 | 45.5% | 0.5230 | Quá khắt khe với chữ bị mòn nhẹ |

## 3. Phân tích các phát hiện & hiệu chuẩn kỹ thuật

1. **Lọc nhiễu lề ảnh thư viện**: Loại bỏ **15/114** box rác/lề ngoài bản rập (ví dụ: `36`, `2459`, `2459`, `246D`, `24`, `2461`).
2. **Thứ tự đọc & gom cụm cột dọc**: Tự động gom các cụm cột dọc từ phải sang trái và sắp xếp từ trên xuống dưới trong từng cột; nhận diện trán bia đọc ngược Trái↔Phải.
3. **Hiệu chuẩn dị thể & chữ kép (`V2.2`)**: Bổ sung bảng ánh xạ dị thể (`後/后`, `脩/修`, `為/爲`, `顕/顯`, `鐵/鉄`, `稱/称`, `盡/尽`, `監/鑒`, `橫/横`) và chữ số kép (`拾/十`, `貳/二`) giúp không phạt nhầm các biến thể khắc đá.
4. **Hỗ trợ đa mặt bia (`Multi-Face Anchor`)**: Kích hoạt **2** lần tự động dò neo lại để định vị đúng từng mặt bia nằm giữa/cuối trong file văn bản gộp nhiều mặt của Tuấn.
5. **Cảnh báo chất lượng dữ liệu phát hiện trên lô thử nghiệm (Bia 2: `02459-31`, `02460-32`, `02461-33`)**:
   - **Đoạn đảo dòng từ OCR sách (1.A)**: Trên mặt `02459-31` (box 8–12), Gemini OCR sách đọc đảo cột 5 dòng chữ Hán trang 44–45 (`line 2–6` trong `Chu_Han`), trong khi bản `Phien_am` vẫn đúng thứ tự.
   - **Danh sách công đức lược bỏ**: Các cụm tên người công đức trên `02459-31` (13 box) và `02461-33` (33 box) không có trong sách đã được giữ an toàn trong `needs_review.csv` với **0 trường hợp khớp nhầm dây chuyền**.
