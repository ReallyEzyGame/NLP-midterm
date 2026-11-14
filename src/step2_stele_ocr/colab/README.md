# Chạy PaddleOCR GPU trên Google Colab (bước 2)

Máy nhóm không có GPU; PaddleOCR CPU rất chậm. Trên Colab T4, cấu hình gốc của nhóm (`raw_2560`) chạy 76 mặt trong ~2 phút và
cho kết quả **trùng khớp từng con số** với bản CPU (đối chứng). Colab chỉ tải ảnh thác bản **công khai** từ Vietnamica
(kiểm md5 trùng ảnh nhóm đang dùng); **không đưa văn bản sách hay tài liệu lab lên cloud**. Gióng/xuất chạy ở máy local.

## Các bước (từ `NLP-midterm/`, `.venv` đã bật)

1. **Mở tunnel:** Colab → Runtime → Change runtime type → *T4 GPU*. Dán toàn bộ `colab_tunnel.py` vào một cell và chạy;
   nhập một token tự chọn. Ô in `URL …trycloudflare.com` — **để ô chạy liên tục** (URL đổi mỗi lần chạy lại).
2. **Biến môi trường** (PowerShell): `$env:COLAB_URL = "https://….trycloudflare.com"; $env:COLAB_TOKEN = "<token>"`
3. **Chuẩn bị:**
   ```powershell
   python -m src.step2_stele_ocr.colab.colab_exec danh-sach-anh            # data/interim/anh_bia_list.csv
   python -m src.step2_stele_ocr.colab.colab_exec cai-dat                  # paddle-gpu 3.2 + paddleocr, gỡ torch
   python -m src.step2_stele_ocr.colab.colab_exec day data/interim/anh_bia_list.csv vb/anh_bia_list.csv
   python -m src.step2_stele_ocr.colab.colab_exec day src/step2_stele_ocr/ocr_bia.py vb/ocr_bia.py
   ```
4. **OCR** (chạy nền trên Colab để không phụ thuộc kết nối; 5 cấu hình ~15 phút):
   ```powershell
   python -m src.step2_stele_ocr.colab.colab_exec chay "import subprocess; subprocess.Popen(['setsid','nohup','bash','-c','cd /content/vb && python ocr_bia.py --engine paddle --device gpu --img-dir anh_bia --out out --tai-anh anh_bia_list.csv > run.log 2>&1 && cd out && zip -qr ../paddle_raw.zip . && echo ALL_DONE >> ../run.log'])"
   python -m src.step2_stele_ocr.colab.colab_exec chay "print(open('/content/vb/run.log').read()[-600:])"   # xem tiến độ
   ```
5. **Kéo kết quả về** rồi giải nén vào `data/interim/paddle_raw/` (mỗi cấu hình một thư mục `paddle_<variant>/`):
   ```powershell
   python -m src.step2_stele_ocr.colab.colab_exec keo vb/paddle_raw.zip data/interim/paddle_raw.zip
   Expand-Archive data/interim/paddle_raw.zip data/interim/paddle_raw -Force
   ```
6. RapidOCR (CPU, không cần Colab, ~30 phút): `python -m src.step2_stele_ocr.ocr_bia --engine rapid`

## Lỗi đã gặp
- `ImportError … libtorch_cuda.so: undefined symbol: ncclCommResume`: `paddlex` import `torch` có sẵn của Colab, NCCL xung đột
  với paddle → `cai-dat` gỡ torch (kể cả thư mục sót lại).
- MCP `jupyter-mcp-server` có thể trả 403 dù REST chạy được → dùng `colab_exec.py` (REST + websocket) thay thế.
