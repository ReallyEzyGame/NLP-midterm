"""OCR ảnh thác bản cho bước 2 - Sử dụng API Lab CLC SinoNom (thay thế PaddleOCR/RapidOCR) với Polite Policy.

Đặc điểm thiết kế:
- Thay thế hoàn toàn mô hình cục bộ (PaddleOCR / RapidOCR) bằng dịch vụ API của Lab (`api/web/clc-sinonom/*`).
- Xử lý TUẦN TỰ từng ảnh một (sequential one-by-one), tuyệt đối không gửi theo batch do giới hạn của Lab.
- Polite Policy (Rate Limiting & Resilience):
  + Độ trễ lịch sự (polite delay) trước khi upload, sau khi upload, trước khi tải ảnh kết quả và giữa các file ảnh.
  + Exponential backoff kèm random jitter (±25%) khi gặp lỗi mạng, HTTP 504 Gateway Timeout hoặc Rate Limit (429 / BlockIP).
  + Adaptive delay multiplier tự động tăng độ trễ khi có lỗi và giảm dần về 1.0x khi ổn định.
  + Circuit Breaker tự động tạm nghỉ (cooldown) khi số lần lỗi liên tiếp chạm ngưỡng `MAX_CONSECUTIVE_FAILURES`.
  + Tự động thu nhỏ ảnh trên bản sao tạm (temp file) ở lần thử cuối (`attempt == 2`) nếu ảnh quá lớn gây timeout,
    KHÔNG sửa ảnh gốc trên đĩa (bảo toàn MD5) và tự động quy đổi (rescale) toạ độ polygon về kích thước ảnh gốc.
- Hỗ trợ đầu vào linh hoạt:
  + Một thư mục chứa nhiều ảnh (`--input data/raw/anh_bia` hoặc `--img-dir data/raw/anh_bia`)
  + Hoặc một file ảnh đơn lẻ (`--input data/raw/anh_bia/00270-TF1.jpg`)
- Đầu ra tương thích 100% với `step2_stele_ocr` và `step3_ocr_align.paddle_adapter`:
  + `<bia_id>_res.json` chứa `input_path`, `engine`, `variant`, `tiles`, `dt_polys`, `rec_texts`, `rec_scores`, `meta`.
  + `<bia_id>_ocr_res_img.jpg` (khi bật `--ve-anh`) vẽ minh hoạ 2 nửa giống `save_to_img` của PaddleOCR.

Cách chạy:
    # OCR toàn bộ thư mục ảnh bia (mặc định lưu vào data/interim/paddle_raw/nom_epitaph/<bia_id>_res.json)
    python -m src.step2_stele_ocr.ocr_bia --input data/raw/anh_bia

    # OCR một ảnh đơn lẻ và vẽ ảnh kết quả
    python -m src.step2_stele_ocr.ocr_bia --input data/raw/anh_bia/00270-TF1.jpg --ve-anh

    # Tương thích ngược với các tham số cũ của step2_stele_ocr
    python -m src.step2_stele_ocr.ocr_bia --img-dir data/raw/anh_bia --out data/interim/paddle_raw --only 00270-TF1 --ve-anh
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import random
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import cv2
import numpy as np
import requests
import urllib3
from PIL import Image

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from dotenv import load_dotenv
    load_dotenv(".env")
    load_dotenv()
except ImportError:
    pass

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **_kwargs):  # type: ignore[misc]
        return iterable

_HERE = Path(__file__).resolve()
ROOT = _HERE.parents[2] if len(_HERE.parents) >= 3 else _HERE.parent
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# Các cấu hình tham số gọi API Lab SinoNom: tên variant -> (ocr_id, lang_type, epitaph, reading_direction, tag)
VARIANTS: dict[str, tuple[int, int, int, int, str]] = {
    "epitaph": (5, 2, 0, 1, "det_epitaph_experimental"),
    "epitaph_1": (5, 2, 1, 1, "det_epitaph_experimental"),
    "general_nom": (1, 0, 0, 1, "general"),
}
DEFAULT_SET = ["epitaph"]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_FIREBASE_TOKEN = "YOUR_FIRE_BASE_TOKEN"


# ============================================
# LOGGER
# ============================================
_LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def get_logger(
    name: str = "NOMOCR",
    stdout: str = "INFO",
    file_level: str = "DEBUG",
    file_name: Optional[str | Path] = None,
) -> logging.Logger:
    """Khởi tạo logger hỗ trợ UTF-8 trên cả Windows và Linux."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    if stdout:
        sh = logging.StreamHandler()
        sh.setLevel(_LOG_LEVEL_MAP.get(stdout.upper(), logging.INFO))
        sh.setFormatter(formatter)
        try:
            sh.stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
        logger.addHandler(sh)

    if file_level and file_name:
        log_path = Path(file_name)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(_LOG_LEVEL_MAP.get(file_level.upper(), logging.DEBUG))
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger


# ============================================
# DATA STRUCTURES & LAB API CLIENT
# ============================================
@dataclass
class UploadImageReq:
    image: str


@dataclass
class UploadData:
    file_name: str


@dataclass
class UploadImageRes:
    is_success: bool
    code: str
    message: Optional[Any]
    data: Optional[UploadData]

    @staticmethod
    def dict2obj(d: dict[str, Any]) -> "UploadImageRes":
        raw_data = d.get("data")
        data_obj = UploadData(file_name=raw_data["file_name"]) if isinstance(raw_data, dict) and "file_name" in raw_data else None
        return UploadImageRes(
            is_success=bool(d.get("is_success", False)),
            code=str(d.get("code", "")),
            message=d.get("message"),
            data=data_obj,
        )


@dataclass
class OCRReq:
    file_name: str
    ocr_id: int = 5


@dataclass
class OCRData:
    result_file_name: str = ""
    result_ocr_text: list[Any] = field(default_factory=list)
    result_bbox: list[Any] = field(default_factory=list)
    details: list[Any] = field(default_factory=list)


@dataclass
class OCRRes:
    is_success: bool
    code: str
    message: Optional[Any]
    data: Optional[OCRData]
    raw_json: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def dict2obj(obj: dict[str, Any]) -> "OCRRes":
        raw_data = obj.get("data")
        ocr_data: Optional[OCRData] = None
        if isinstance(raw_data, dict):
            ocr_data = OCRData(
                result_file_name=str(raw_data.get("result_file_name", "")),
                result_ocr_text=list(raw_data.get("result_ocr_text") or []),
                result_bbox=list(raw_data.get("result_bbox") or []),
                details=list(raw_data.get("details") or []),
            )
        return OCRRes(
            is_success=bool(obj.get("is_success", False)),
            code=str(obj.get("code", "")),
            message=obj.get("message"),
            data=ocr_data,
            raw_json=obj,
        )


def get_firebase_token(explicit_token: Optional[str] = None) -> str:
    """Lấy Firebase Bearer token từ tham số, biến môi trường hoặc giá trị mặc định của dự án."""
    tok = (
        explicit_token
        or os.environ.get("SN_TOKEN")
        or os.environ.get("FIREBASE_TOKEN")
        or DEFAULT_FIREBASE_TOKEN
    )
    return tok.strip()


class LabOCRClient:
    """Client giao tiếp với dịch vụ OCR Hán Nôm của Lab (`api/web/clc-sinonom/*`)."""

    def __init__(
        self,
        domain: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 120.0,
        proxies: Optional[dict[str, str]] = None,
    ) -> None:
        raw_domain = (domain or os.environ.get("SN_DOMAIN") or "kimhannom.fit.hcmus.edu.vn").strip().rstrip("/")
        if raw_domain.startswith("http://") or raw_domain.startswith("https://"):
            self.base_url = f"{raw_domain}/"
        else:
            self.base_url = f"https://{raw_domain}/"
        self.token = get_firebase_token(token)
        self.timeout = timeout
        self.client = requests.Session()
        if proxies:
            self.client.proxies.update(proxies)

    def _headers(self, agent: Optional[str] = None, json_content: bool = False) -> dict[str, str]:
        headers = {
            "User-Agent": agent or DEFAULT_USER_AGENT,
            "Authorization": f"Bearer {self.token}",
        }
        if json_content:
            headers["Content-Type"] = "application/json"
        return headers

    def upload_image(self, req: UploadImageReq, agent: Optional[str] = None) -> UploadImageRes:
        url = self.base_url + "api/web/clc-sinonom/image-upload"
        if not os.path.exists(req.image):
            raise FileNotFoundError(f"File not found: {req.image}")

        with open(req.image, "rb") as f:
            files = {"image_file": f}
            response = self.client.post(
                url,
                files=files,
                headers=self._headers(agent=agent, json_content=False),
                verify=False,
                timeout=self.timeout,
            )

        if response.status_code != 200:
            raise RuntimeError(f"Failed to upload image (HTTP {response.status_code}): {response.text}")

        resp_json = response.json()
        if not resp_json.get("is_success", False):
            msg = resp_json.get("message", "BlockIP")
            err_title = msg.get("title", str(msg)) if isinstance(msg, dict) else str(msg)
            raise RuntimeError(f"Upload rejected by server: {err_title}")

        return UploadImageRes.dict2obj(resp_json)

    def ocr(
        self,
        req: OCRReq,
        agent: Optional[str] = None,
        output_file: Optional[str | Path] = None,
        ocr_id: Optional[int] = None,
        lang_type: Optional[int] = None,
        epitaph: Optional[int] = None,
        reading_direction: int = 1,
        tag: str = "det_epitaph_experimental",
    ) -> OCRRes:
        url = self.base_url + "api/web/clc-sinonom/image-ocr"
        body_ocr_id = int(
            ocr_id
            if ocr_id is not None
            else (req.ocr_id if req.ocr_id is not None else os.environ.get("TYPE_OCR", 5))
        )
        body_lang_type = int(lang_type if lang_type is not None else os.environ.get("TYPE_LANG", 2))
        body_epitaph = epitaph if epitaph is not None else os.environ.get("EPITAPH", 0)

        body = {
            "file_name": req.file_name,
            "ocr_id": body_ocr_id,
            "lang_type": body_lang_type,
            "epitaph": str(body_epitaph),
            "reading_direction": int(reading_direction),
            "tag": str(tag),
        }

        response = self.client.post(
            url,
            headers=self._headers(agent=agent, json_content=True),
            json=body,
            verify=False,
            timeout=self.timeout,
        )
        response.encoding = "utf-8"

        if response.status_code == 504:
            raise TimeoutError("Gateway Timeout (HTTP 504)")
        if response.status_code != 200:
            raise RuntimeError(f"OCR HTTP {response.status_code}: {response.text}")

        resp_json = response.json()
        if not resp_json.get("is_success", False):
            errors = json.dumps(resp_json.get("message", "BlockIP"), ensure_ascii=False)
            raise RuntimeError(f"OCR failed: {errors}")

        if output_file is not None:
            out_path = Path(output_file)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(resp_json, f, ensure_ascii=False, indent=4)

        return OCRRes.dict2obj(resp_json)

    def download_image(self, file_name: str, save_path: str | Path, agent: Optional[str] = None) -> Optional[Path]:
        url = f"{self.base_url}api/web/clc-sinonom/image-download?file_name={file_name}"
        headers = self._headers(agent=agent, json_content=True)
        headers["Content-Type"] = "application/json; charset=utf-8"

        response = self.client.get(url, headers=headers, verify=False, timeout=self.timeout)
        if "image" not in response.headers.get("Content-Type", ""):
            raise RuntimeError(f"Response is not an image (Content-Type={response.headers.get('Content-Type')})")
        response.raise_for_status()

        target = Path(save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return target


# ============================================
# POLITE POLICY & RATE LIMITING CONFIGURATION
# ============================================
@dataclass
class RateLimitConfig:
    """Cấu hình Polite Policy (Rate Limiting, Exponential Backoff, Circuit Breaker, Adaptive Delay)."""

    # Base delays (seconds)
    DELAY_BEFORE_UPLOAD: float = float(os.getenv("DELAY_BEFORE_UPLOAD", "2.0"))
    DELAY_AFTER_UPLOAD: float = float(os.getenv("DELAY_AFTER_UPLOAD", "3.0"))
    DELAY_BEFORE_DOWNLOAD: float = float(os.getenv("DELAY_BEFORE_DOWNLOAD", "2.0"))
    DELAY_BETWEEN_FILES: float = float(os.getenv("DELAY_BETWEEN_FILES", "3.0"))

    # Retry configuration
    MAX_RETRIES: int = int(os.getenv("OCR_MAX_RETRIES", "3"))
    INITIAL_RETRY_DELAY: float = float(os.getenv("INITIAL_RETRY_DELAY", "5.0"))
    MAX_RETRY_DELAY: float = float(os.getenv("MAX_RETRY_DELAY", "60.0"))

    # Circuit breaker
    MAX_CONSECUTIVE_FAILURES: int = int(os.getenv("MAX_CONSECUTIVE_FAILURES", "5"))
    CIRCUIT_BREAKER_COOLDOWN: float = float(os.getenv("CIRCUIT_BREAKER_COOLDOWN", "30.0"))

    # Adaptive delay
    ENABLE_ADAPTIVE_DELAY: bool = os.getenv("ENABLE_ADAPTIVE_DELAY", "true").lower() == "true"
    ADAPTIVE_DELAY_MULTIPLIER: float = float(os.getenv("ADAPTIVE_DELAY_MULTIPLIER", "1.5"))

    # Resize fallback threshold on final retry
    RESIZE_MAX_SUM_DIM: int = int(os.getenv("RESIZE_MAX_SUM_DIM", "1200"))


def exponential_backoff(
    attempt: int,
    base_delay: float = 5.0,
    max_delay: float = 60.0,
    jitter: bool = True,
) -> float:
    """Tính thời gian chờ exponential backoff kèm random jitter (±25%) để tránh thundering herd."""
    delay = min(base_delay * (2**attempt), max_delay)
    if jitter:
        jitter_range = delay * 0.25
        delay += random.uniform(-jitter_range, jitter_range)
    return max(delay, 0.0)


def smart_sleep(
    seconds: float,
    reason: str = "",
    logger: Optional[logging.Logger] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    """Chờ có ghi log phục vụ Polite Policy."""
    if seconds <= 0:
        return
    if logger:
        logger.debug(f"Polite sleep {seconds:.2f}s - {reason}")
    sleep_fn(seconds)


def resize_image_to_temp(
    image_path: str | Path,
    max_size: int = 1200,
) -> tuple[Path, float, float, bool]:
    """Thu nhỏ ảnh vào một file tạm nếu (width + height) > max_size.

    Tuyệt đối KHÔNG ghi đè ảnh gốc (để bảo toàn MD5 của bộ dữ liệu văn bia).
    Trả về: (đường_dẫn_ảnh_dùng_upload, scale_x, scale_y, đã_resize_hay_chưa)
    Trong đó:
        new_w = orig_w * scale_x  =>  orig_x = new_x / scale_x
        new_h = orig_h * scale_y  =>  orig_y = new_y / scale_y
    """
    src_path = Path(image_path)
    with Image.open(src_path) as img:
        orig_w, orig_h = img.size
        total_size = orig_w + orig_h
        if total_size <= max_size:
            return src_path, 1.0, 1.0, False

        scale_factor = max_size / float(total_size)
        new_w = max(1, int(orig_w * scale_factor))
        new_h = max(1, int(orig_h * scale_factor))
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        if resized.mode == "RGBA":
            resized = resized.convert("RGB")

        suffix = src_path.suffix if src_path.suffix.lower() in {".jpg", ".jpeg", ".png"} else ".jpg"
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=f"nom_ocr_{src_path.stem}_", suffix=suffix)
        os.close(tmp_fd)
        tmp_path = Path(tmp_name)
        resized.save(tmp_path)
        return tmp_path, new_w / float(orig_w), new_h / float(orig_h), True


# ============================================
# CHUYỂN ĐỔI ĐẦU RA LAB API -> ĐỊNH DẠNG *_res.json
# ============================================
def _normalize_poly(
    raw_box: Any,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> Optional[list[list[int]]]:
    """Chuẩn hoá một bounding box từ API Lab về polygon 4 đỉnh [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] trên ảnh gốc."""
    if raw_box is None:
        return None

    if isinstance(raw_box, dict):
        raw_box = (
            raw_box.get("points")
            or raw_box.get("bbox")
            or raw_box.get("box")
            or raw_box.get("poly")
            or raw_box.get("polygon")
        )
        if raw_box is None:
            return None

    if not isinstance(raw_box, (list, tuple)) or len(raw_box) == 0:
        return None

    sx = scale_x if scale_x > 0 else 1.0
    sy = scale_y if scale_y > 0 else 1.0

    # Trường hợp [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
    if isinstance(raw_box[0], (list, tuple)) and len(raw_box[0]) >= 2:
        pts: list[list[int]] = []
        for pt in raw_box:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                x = int(round(float(pt[0]) / sx))
                y = int(round(float(pt[1]) / sy))
                pts.append([x, y])
        if len(pts) >= 4:
            return pts[:4]
        if len(pts) == 2:
            x0, y0 = pts[0]
            x1, y1 = pts[1]
            return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        return None

    # Trường hợp danh sách số phẳng: [xmin, ymin, xmax, ymax] hoặc [x1, y1, x2, y2, x3, y3, x4, y4]
    if all(isinstance(v, (int, float)) for v in raw_box):
        nums = [float(v) for v in raw_box]
        if len(nums) == 4:
            x0 = int(round(nums[0] / sx))
            y0 = int(round(nums[1] / sy))
            x1 = int(round(nums[2] / sx))
            y1 = int(round(nums[3] / sy))
            return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        if len(nums) >= 8:
            return [
                [int(round(nums[0] / sx)), int(round(nums[1] / sy))],
                [int(round(nums[2] / sx)), int(round(nums[3] / sy))],
                [int(round(nums[4] / sx)), int(round(nums[5] / sy))],
                [int(round(nums[6] / sx)), int(round(nums[7] / sy))],
            ]

    return None


def _extract_text_and_score(raw_text_item: Any, default_score: float = 0.90) -> tuple[str, float]:
    """Trích xuất chuỗi chữ Hán Nôm và điểm tin cậy từ phần tử trả về của API."""
    if raw_text_item is None:
        return "", default_score
    if isinstance(raw_text_item, str):
        return raw_text_item, default_score
    if isinstance(raw_text_item, (list, tuple)):
        if len(raw_text_item) >= 2 and isinstance(raw_text_item[0], str):
            try:
                return raw_text_item[0], float(raw_text_item[1])
            except (TypeError, ValueError):
                return raw_text_item[0], default_score
        if len(raw_text_item) == 1:
            return str(raw_text_item[0]), default_score
    if isinstance(raw_text_item, dict):
        txt = (
            raw_text_item.get("text")
            or raw_text_item.get("ocr_text")
            or raw_text_item.get("transcription")
            or raw_text_item.get("label")
            or ""
        )
        sc = (
            raw_text_item.get("score")
            or raw_text_item.get("confidence")
            or raw_text_item.get("prob")
            or default_score
        )
        try:
            return str(txt), float(sc)
        except (TypeError, ValueError):
            return str(txt), default_score
    return str(raw_text_item), default_score


def extract_paddle_compatible_items(
    ocr_res: OCRRes | dict[str, Any],
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    default_score: float = 0.90,
) -> tuple[list[list[list[int]]], list[str], list[float]]:
    """Chuyển kết quả trả về từ API Lab SinoNom sang bộ 3 `(dt_polys, rec_texts, rec_scores)` chuẩn PaddleOCR."""
    if isinstance(ocr_res, OCRRes):
        raw_obj = ocr_res.raw_json or {}
        data_obj = raw_obj.get("data") if isinstance(raw_obj.get("data"), dict) else {}
        bboxes = ocr_res.data.result_bbox if ocr_res.data else data_obj.get("result_bbox", [])
        texts = ocr_res.data.result_ocr_text if ocr_res.data else data_obj.get("result_ocr_text", [])
        details = ocr_res.data.details if ocr_res.data else data_obj.get("details", [])
    else:
        data_obj = ocr_res.get("data") if isinstance(ocr_res.get("data"), dict) else ocr_res
        bboxes = data_obj.get("result_bbox") or data_obj.get("dt_polys") or data_obj.get("rec_polys") or []
        texts = data_obj.get("result_ocr_text") or data_obj.get("rec_texts") or []
        details = data_obj.get("details") or []

    polys_out: list[list[list[int]]] = []
    texts_out: list[str] = []
    scores_out: list[float] = []

    # Trường hợp 1: result_bbox và result_ocr_text song hành
    if bboxes and texts and len(bboxes) == len(texts):
        for idx, (raw_b, raw_t) in enumerate(zip(bboxes, texts)):
            if (
                isinstance(raw_b, (list, tuple))
                and len(raw_b) == 2
                and isinstance(raw_b[0], (list, tuple))
                and len(raw_b[0]) == 4
                and isinstance(raw_b[0][0], (list, tuple))
            ):
                poly = _normalize_poly(raw_b[0], scale_x=scale_x, scale_y=scale_y)
                txt, sc = _extract_text_and_score(raw_t, default_score=default_score)
            else:
                poly = _normalize_poly(raw_b, scale_x=scale_x, scale_y=scale_y)
                txt, sc = _extract_text_and_score(raw_t, default_score=default_score)

            if idx < len(details) and isinstance(details[idx], dict):
                det_sc = details[idx].get("score") or details[idx].get("confidence")
                if det_sc is not None:
                    try:
                        sc = float(det_sc)
                    except (TypeError, ValueError):
                        pass

            if poly is not None:
                polys_out.append(poly)
                texts_out.append(txt)
                scores_out.append(round(float(sc), 4))
        return polys_out, texts_out, scores_out

    # Trường hợp 2: result_bbox chứa trực tiếp cấu trúc [poly, [text, score]] hoặc dict
    if bboxes and not texts:
        for raw_item in bboxes:
            if isinstance(raw_item, dict):
                poly = _normalize_poly(raw_item, scale_x=scale_x, scale_y=scale_y)
                txt, sc = _extract_text_and_score(raw_item, default_score=default_score)
            elif (
                isinstance(raw_item, (list, tuple))
                and len(raw_item) >= 2
                and isinstance(raw_item[0], (list, tuple))
                and len(raw_item[0]) >= 4
                and isinstance(raw_item[0][0], (list, tuple))
            ):
                poly = _normalize_poly(raw_item[0], scale_x=scale_x, scale_y=scale_y)
                txt, sc = _extract_text_and_score(raw_item[1], default_score=default_score)
            else:
                poly = _normalize_poly(raw_item, scale_x=scale_x, scale_y=scale_y)
                txt, sc = "", default_score
            if poly is not None:
                polys_out.append(poly)
                texts_out.append(txt)
                scores_out.append(round(float(sc), 4))
        return polys_out, texts_out, scores_out

    # Trường hợp 3: Chỉ có details
    if details and isinstance(details, list):
        for det in details:
            if isinstance(det, dict):
                poly = _normalize_poly(det, scale_x=scale_x, scale_y=scale_y)
                txt, sc = _extract_text_and_score(det, default_score=default_score)
                if poly is not None:
                    polys_out.append(poly)
                    texts_out.append(txt)
                    scores_out.append(round(float(sc), 4))
        return polys_out, texts_out, scores_out

    # Trường hợp 4: Độ dài bboxes và texts lệch nhau -> ghép theo độ dài nhỏ nhất
    n = min(len(bboxes), len(texts))
    for idx in range(n):
        poly = _normalize_poly(bboxes[idx], scale_x=scale_x, scale_y=scale_y)
        txt, sc = _extract_text_and_score(texts[idx], default_score=default_score)
        if poly is not None:
            polys_out.append(poly)
            texts_out.append(txt)
            scores_out.append(round(float(sc), 4))

    return polys_out, texts_out, scores_out


def build_paddle_res_payload(
    input_path: str,
    engine: str,
    variant: str,
    polys: list[list[list[int]]],
    texts: list[str],
    scores: list[float],
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Đóng gói dictionary đúng chuẩn `<bia_id>_res.json` của `step2_stele_ocr`."""
    payload: dict[str, Any] = {
        "input_path": input_path,
        "engine": engine,
        "variant": variant,
        "tiles": 1,
        "dt_polys": polys,
        "rec_texts": texts,
        "rec_scores": scores,
    }
    if meta:
        payload["meta"] = meta
    return payload


# ============================================
# VẼ ẢNH MINH HOẠ (<bia_id>_ocr_res_img.jpg) NHƯ PADDLEOCR
# ============================================
FONTS = [
    Path.home() / ".paddlex" / "fonts" / "simfang.ttf",
    Path("C:/Windows/Fonts/simfang.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
]


def _font(size: int):
    from PIL import ImageFont
    for f in FONTS:
        if f.exists():
            return ImageFont.truetype(str(f), max(6, size))
    return ImageFont.load_default()


def _text_tile(w: int, h: int, txt: str):
    """Ảnh chữ kích thước w×h (như draw_box_txt_fine của PaddleX): box dọc (cao > 2·rộng) -> chữ xếp dọc từng chữ;
    còn lại -> 1 dòng ngang; cỡ chữ vừa khít box."""
    from PIL import ImageDraw
    w, h = max(1, w), max(1, h)
    img = Image.new("RGB", (w, h), (255, 255, 255))
    if not txt:
        return img
    d = ImageDraw.Draw(img)
    if h > 2 * w and h > 30:
        size = int(min(w * 0.99, h / max(1, len(txt)) * 0.99))
        font, y = _font(size), 0
        for ch in txt:
            x0, y0, x1, y1 = d.textbbox((0, 0), ch, font=font)
            d.text(((w - (x1 - x0)) / 2 - x0, y - y0), ch, fill=(0, 0, 0), font=font)
            y += size + 2
    else:
        size = int(h * 0.99)
        font = _font(size)
        while size > 6 and d.textlength(txt, font=font) > w:
            size = int(size * w / max(1.0, d.textlength(txt, font=font)) * 0.98) or size - 1
            font = _font(size)
        d.text((0, 0), txt, fill=(0, 0, 0), font=font)
    return img


def draw_ocr_result(img_rgb: Image.Image, polys: list, texts: list) -> Image.Image:
    """Ảnh minh hoạ giống `save_to_img` của PaddleOCR (<bia_id>_ocr_res_img.jpg): nửa trái = ảnh gốc phủ màu bán trong
    suốt từng box; nửa phải = nền trắng, viền box cùng màu + chữ OCR vẽ vào box. Màu ngẫu nhiên seed 0 như PaddleX."""
    from PIL import ImageDraw
    w, h = img_rgb.size
    left = img_rgb.copy()
    dl = ImageDraw.Draw(left)
    right = np.full((h, w, 3), 255, np.uint8)
    rng = random.Random(0)
    for poly, txt in zip(polys, texts):
        color = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
        pts = np.asarray(poly, dtype=np.float32).reshape(-1, 2)
        dl.polygon([tuple(p) for p in pts.tolist()], fill=color)
        if len(pts) == 4:
            bw = max(1, int(np.hypot(*(pts[0] - pts[1]))))
            bh = max(1, int(np.hypot(*(pts[0] - pts[3]))))
            tile = np.asarray(_text_tile(bw, bh, txt))
            m = cv2.getPerspectiveTransform(
                np.float32([[0, 0], [bw, 0], [bw, bh], [0, bh]]),
                pts,
            )
            warped = cv2.warpPerspective(
                tile,
                m,
                (w, h),
                flags=cv2.INTER_NEAREST,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(255, 255, 255),
            )
            right = cv2.bitwise_and(right, warped)
        cv2.polylines(right, [pts.astype(np.int32).reshape(-1, 1, 2)], True, color, 1)
    out = Image.new("RGB", (w * 2, h), (255, 255, 255))
    out.paste(Image.blend(img_rgb, left, 0.5), (0, 0))
    out.paste(Image.fromarray(right), (w, 0))
    return out


def save_ocr_image(res_json: Path, img_path: Path, out_jpg: Path) -> None:
    with open(res_json, encoding="utf-8") as fh:
        r = json.load(fh)
    with Image.open(img_path) as im:
        draw_ocr_result(
            im.convert("RGB"),
            r.get("rec_polys") or r.get("dt_polys") or [],
            r.get("rec_texts") or [],
        ).save(out_jpg, quality=75)


def fetch_images(list_csv: Path, img_dir: Path) -> list[str]:
    """(Colab) tải ảnh gốc từ Vietnamica theo danh sách bia_id,url,md5; bỏ ảnh lệch md5 so với bản nhóm."""
    img_dir.mkdir(parents=True, exist_ok=True)
    ok, bad = [], []
    with open(list_csv, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            f = img_dir / f"{r['bia_id']}.jpg"
            if not f.exists():
                req = urllib.request.Request(r["url"], headers={"User-Agent": "VanBia-course-downloader/1.0"})
                f.write_bytes(urllib.request.urlopen(req, timeout=120).read())
            (ok if hashlib.md5(f.read_bytes()).hexdigest() == r["md5"] else bad).append(r["bia_id"])
    print(f"ảnh: {len(ok) + len(bad)} | lệch md5 so với bản nhóm: {bad or 'không'}", flush=True)
    return ok


# ============================================
# XỬ LÝ ĐẦU VÀO (1 ẢNH HOẶC THƯ MỤC) & SEQUENTIAL POLITE OCR
# ============================================
def resolve_input_images(
    input_path: Path,
    only_ids: Optional[list[str]] = None,
) -> list[Path]:
    """Nhận vào đường dẫn 1 file ảnh hoặc 1 thư mục chứa ảnh, trả về danh sách các file ảnh cần xử lý."""
    if not input_path.exists():
        raise FileNotFoundError(f"Đường dẫn đầu vào không tồn tại: {input_path}")

    if input_path.is_file():
        if input_path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(f"File đầu vào không phải định dạng ảnh hỗ trợ ({IMAGE_EXTENSIONS}): {input_path}")
        if only_ids and input_path.stem not in set(only_ids):
            return []
        return [input_path]

    files = sorted(
        p for p in input_path.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )
    if only_ids:
        allowed = set(only_ids)
        files = [p for p in files if p.stem in allowed]
    return files


def _format_rel_input_path(img_path: Path) -> str:
    """Format `input_path` trong JSON theo chuẩn tương đối từ ROOT (vd: `data/raw/anh_bia/00270-TF1.jpg`)."""
    try:
        return img_path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return f"data/raw/anh_bia/{img_path.name}"


def run_sequential_nom_ocr(
    image_paths: list[Path],
    output_dir: Path,
    engine: str = "nom",
    variant: str = "epitaph",
    ocr_id: int = 5,
    lang_type: int = 2,
    epitaph: int = 0,
    reading_direction: int = 1,
    tag: str = "det_epitaph_experimental",
    default_score: float = 0.90,
    force: bool = False,
    ve_anh: bool = False,
    download_server_img: bool = False,
    start: int = 0,
    config: Optional[RateLimitConfig] = None,
    client_factory: Optional[Callable[[], LabOCRClient]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    logger: Optional[logging.Logger] = None,
) -> dict[str, int]:
    """Thực thi OCR tuần tự từng ảnh một (sequential one-by-one) với Polite Policy đầy đủ.

    Trả về thống kê: `{"total": ..., "processed": ..., "skipped": ..., "failed": ...}`
    """
    cfg = config or RateLimitConfig()
    log = logger or get_logger("NOMOCR")
    output_dir.mkdir(parents=True, exist_ok=True)

    total = len(image_paths)
    start_idx = max(0, int(start or 0))
    skipped = 0
    processed = 0
    total_failures = 0
    consecutive_failures = 0
    adaptive_delay_multiplier = 1.0

    previously_processed = len(list(output_dir.glob("*_res.json")))

    log.info("===== OCR SESSION START (SEQUENTIAL POLITE POLICY) =====")
    log.info(f"Total target images: {total} | Output dir: {output_dir}")
    log.info(
        f"Rate limit config: before_upload={cfg.DELAY_BEFORE_UPLOAD}s, "
        f"after_upload={cfg.DELAY_AFTER_UPLOAD}s, between_files={cfg.DELAY_BETWEEN_FILES}s, "
        f"max_retries={cfg.MAX_RETRIES}, circuit_breaker={cfg.MAX_CONSECUTIVE_FAILURES}"
    )

    make_client = client_factory or (lambda: LabOCRClient())
    resize_log_path = output_dir / "resized_retry_log.txt"

    for idx, img_path in enumerate(tqdm(image_paths, desc=f"OCR [{engine}_{variant}]"), start=1):
        if idx < start_idx:
            continue

        bid = img_path.stem
        out_json_path = output_dir / f"{bid}_res.json"
        out_vis_path = output_dir / f"{bid}_ocr_res_img.jpg"

        # 1. Kiểm tra file đã có kết quả OCR chưa (tránh gọi lại API không cần thiết)
        if out_json_path.exists() and not force:
            skipped += 1
            log.info(f"[SKIP] Đã có kết quả OCR: {img_path.name} (skipped={skipped}, processed={processed})")
            if ve_anh and not out_vis_path.exists():
                try:
                    save_ocr_image(out_json_path, img_path, out_vis_path)
                except Exception as vis_err:
                    log.warning(f"Không thể vẽ ảnh minh hoạ cho {bid}: {vis_err}")
            if progress_callback:
                try:
                    progress_callback(
                        f"OCR Hán Nôm: {skipped + processed}/{total} (Skip: {skipped}, New: {processed})",
                        skipped + processed,
                        total,
                    )
                except Exception:
                    pass
            continue

        # 2. Kiểm tra Circuit Breaker trước khi gửi request mới
        if consecutive_failures >= cfg.MAX_CONSECUTIVE_FAILURES:
            log.error(
                f"CIRCUIT BREAKER ACTIVATED! {consecutive_failures} lỗi liên tiếp. "
                f"Tạm nghỉ {cfg.CIRCUIT_BREAKER_COOLDOWN}s..."
            )
            if progress_callback:
                try:
                    progress_callback(
                        f"Rate limit detected. Cooling down {cfg.CIRCUIT_BREAKER_COOLDOWN}s...",
                        skipped + processed,
                        total,
                    )
                except Exception:
                    pass
            smart_sleep(cfg.CIRCUIT_BREAKER_COOLDOWN, "Circuit breaker cooldown", log, sleep_fn=sleep_fn)
            consecutive_failures = 0
            adaptive_delay_multiplier = min(adaptive_delay_multiplier * cfg.ADAPTIVE_DELAY_MULTIPLIER, 3.0)

        log.info(f"Processing [{idx}/{total}]: {img_path.name} (Skipped={skipped}, Processed={processed}, Failed={total_failures})")
        if progress_callback:
            try:
                progress_callback(
                    f"OCR Hán Nôm: {skipped + processed + 1}/{total} (Processing: {img_path.name})",
                    skipped + processed,
                    total,
                )
            except Exception:
                pass

        ocr_client = make_client()
        upload_success = False
        ocr_success = False
        resize_attempted = False
        scale_x, scale_y = 1.0, 1.0
        temp_resized_path: Optional[Path] = None
        active_upload_path: Path = img_path
        upload_res: Optional[UploadImageRes] = None
        ocr_res: Optional[OCRRes] = None

        try:
            # 3. Vòng lặp Retry với Exponential Backoff + Jitter
            for attempt in range(cfg.MAX_RETRIES):
                try:
                    # Thu nhỏ ảnh vào file tạm trước lần thử thứ 3 (attempt == 2) nếu các lần trước thất bại
                    if attempt == 2 and not resize_attempted and not (upload_success and ocr_success):
                        try:
                            tmp_path, sx, sy, did_resize = resize_image_to_temp(
                                img_path, max_size=cfg.RESIZE_MAX_SUM_DIM
                            )
                            resize_attempted = True
                            if did_resize:
                                temp_resized_path = tmp_path
                                active_upload_path = tmp_path
                                scale_x, scale_y = sx, sy
                                upload_success = False  # Bắt buộc upload lại bản thu nhỏ
                                with open(resize_log_path, "a", encoding="utf-8") as log_f:
                                    log_f.write(f"{img_path.name}\tscale=({sx:.4f},{sy:.4f})\n")
                                log.warning(
                                    f"Resized temp image before retry {attempt + 1}: {img_path.name} "
                                    f"(scale_x={sx:.3f}, scale_y={sy:.3f})"
                                )
                        except Exception as resize_err:
                            log.error(f"Resize temp fallback failed on attempt {attempt + 1}: {resize_err}")

                    # Bước 3a: Upload ảnh lên server Lab
                    if not upload_success:
                        delay = cfg.DELAY_BEFORE_UPLOAD * adaptive_delay_multiplier
                        smart_sleep(delay, f"Before upload (attempt {attempt + 1})", log, sleep_fn=sleep_fn)

                        log.info(f"[Attempt {attempt + 1}/{cfg.MAX_RETRIES}] Uploading image: {img_path.name}")
                        upload_res = ocr_client.upload_image(
                            UploadImageReq(image=str(active_upload_path)),
                            agent=DEFAULT_USER_AGENT,
                        )
                        if not upload_res.data or not upload_res.data.file_name:
                            raise RuntimeError("Upload response missing server file_name")
                        log.info(f"Upload success: {upload_res.data.file_name}")
                        upload_success = True

                        delay = cfg.DELAY_AFTER_UPLOAD * adaptive_delay_multiplier
                        smart_sleep(delay, "After upload", log, sleep_fn=sleep_fn)

                    # Bước 3b: Gọi endpoint OCR trên file đã upload
                    if upload_success and not ocr_success and upload_res and upload_res.data:
                        log.info(f"[Attempt {attempt + 1}/{cfg.MAX_RETRIES}] Requesting OCR: {img_path.name}")
                        ocr_res = ocr_client.ocr(
                            OCRReq(file_name=upload_res.data.file_name, ocr_id=ocr_id),
                            agent=DEFAULT_USER_AGENT,
                            output_file=None,
                            ocr_id=ocr_id,
                            lang_type=lang_type,
                            epitaph=epitaph,
                            reading_direction=reading_direction,
                            tag=tag,
                        )
                        log.info(
                            f"OCR success: {ocr_res.data.result_file_name if ocr_res.data else 'ok'}"
                        )
                        ocr_success = True

                    if upload_success and ocr_success:
                        break

                except Exception as err:
                    err_msg = str(err).lower()
                    is_rate_limit = any(
                        kw in err_msg for kw in ("rate", "limit", "too many", "429", "quota", "blockip")
                    )
                    log.error(f"Error on attempt {attempt + 1}/{cfg.MAX_RETRIES} for {img_path.name}: {err}")
                    if is_rate_limit:
                        log.warning("Rate limit / BlockIP signal detected from server!")
                        adaptive_delay_multiplier = min(
                            adaptive_delay_multiplier * cfg.ADAPTIVE_DELAY_MULTIPLIER, 3.0
                        )

                    if attempt == cfg.MAX_RETRIES - 1:
                        log.error(f"All {cfg.MAX_RETRIES} attempts failed for {img_path.name}")
                        consecutive_failures += 1
                        total_failures += 1
                        break

                    backoff_delay = exponential_backoff(
                        attempt,
                        base_delay=cfg.INITIAL_RETRY_DELAY,
                        max_delay=cfg.MAX_RETRY_DELAY,
                        jitter=True,
                    )
                    log.warning(f"Retrying {img_path.name} in {backoff_delay:.2f}s...")
                    if progress_callback:
                        try:
                            progress_callback(
                                f"Error: {img_path.name}. Retry {attempt + 1}/{cfg.MAX_RETRIES} in {backoff_delay:.0f}s",
                                skipped + processed,
                                total,
                            )
                        except Exception:
                            pass
                    smart_sleep(
                        backoff_delay,
                        f"Exponential backoff (attempt {attempt + 1})",
                        log,
                        sleep_fn=sleep_fn,
                    )
        finally:
            # Xoá file ảnh thu nhỏ tạm (nếu có)
            if temp_resized_path is not None and temp_resized_path.exists():
                try:
                    temp_resized_path.unlink()
                except OSError:
                    pass

        if not (upload_success and ocr_success and ocr_res is not None):
            log.error(f"FAILED: {img_path.name} after {cfg.MAX_RETRIES} attempts")
            continue

        # 4. Reset bộ đếm lỗi liên tiếp và điều chỉnh giảm nhẹ adaptive delay khi thành công
        consecutive_failures = 0
        if cfg.ENABLE_ADAPTIVE_DELAY:
            adaptive_delay_multiplier = max(adaptive_delay_multiplier * 0.95, 1.0)

        # 5. Chuyển đổi dữ liệu trả về sang chuẩn `*_res.json` của `step2_stele_ocr`
        polys, texts, scores = extract_paddle_compatible_items(
            ocr_res,
            scale_x=scale_x,
            scale_y=scale_y,
            default_score=default_score,
        )
        server_result_file = ocr_res.data.result_file_name if ocr_res.data else None
        meta = {
            "ocr_id": int(ocr_id),
            "lang_type": int(lang_type),
            "epitaph": int(epitaph),
            "reading_direction": int(reading_direction),
            "tag": str(tag),
            "processed_file": server_result_file,
            "resized_on_retry": bool(scale_x != 1.0 or scale_y != 1.0),
            "scale_x": round(float(scale_x), 6),
            "scale_y": round(float(scale_y), 6),
        }
        payload = build_paddle_res_payload(
            input_path=_format_rel_input_path(img_path),
            engine=engine,
            variant=variant,
            polys=polys,
            texts=texts,
            scores=scores,
            meta=meta,
        )
        with open(out_json_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False)

        # 6. Vẽ ảnh minh hoạ `<bia_id>_ocr_res_img.jpg` hoặc tải ảnh từ server nếu được yêu cầu
        if ve_anh:
            try:
                save_ocr_image(out_json_path, img_path, out_vis_path)
            except Exception as vis_err:
                log.warning(f"Không thể vẽ ảnh minh hoạ {out_vis_path.name}: {vis_err}")

        if download_server_img and server_result_file:
            server_img_path = output_dir / f"{bid}_server_ocr.jpeg"
            smart_sleep(
                cfg.DELAY_BEFORE_DOWNLOAD * adaptive_delay_multiplier,
                "Before server image download",
                log,
                sleep_fn=sleep_fn,
            )
            for dl_attempt in range(cfg.MAX_RETRIES):
                try:
                    ocr_client.download_image(server_result_file, server_img_path, agent=DEFAULT_USER_AGENT)
                    break
                except Exception as dl_err:
                    log.warning(f"Download server image attempt {dl_attempt + 1} error: {dl_err}")
                    if dl_attempt < cfg.MAX_RETRIES - 1:
                        smart_sleep(
                            exponential_backoff(dl_attempt, base_delay=2.0, max_delay=10.0),
                            "Download retry",
                            log,
                            sleep_fn=sleep_fn,
                        )

        processed += 1
        log.info(
            f"SUCCESS: {img_path.name} -> {len(polys)} boxes "
            f"(Processed={processed}, Skipped={skipped}, Failures={total_failures})"
        )

        # 7. Polite delay giữa các file ảnh (chỉ chờ nếu chưa phải ảnh cuối cùng)
        if idx < total:
            between_delay = cfg.DELAY_BETWEEN_FILES * adaptive_delay_multiplier
            smart_sleep(
                between_delay,
                f"Between files (multiplier={adaptive_delay_multiplier:.2f})",
                log,
                sleep_fn=sleep_fn,
            )

        if progress_callback:
            try:
                progress_callback(
                    f"OCR: {skipped + processed}/{total} (New: {processed}, Skip: {skipped})",
                    skipped + processed,
                    total,
                )
            except Exception:
                pass

    log.info(
        f"===== OCR FINISHED: total={total}, processed={processed}, "
        f"skipped={skipped}, failed={total_failures}, pre_existing={previously_processed} ====="
    )
    return {
        "total": total,
        "processed": processed,
        "skipped": skipped,
        "failed": total_failures,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "target",
        nargs="?",
        type=Path,
        default=None,
        help="Đường dẫn tuỳ chọn tới 1 thư mục ảnh hoặc 1 file ảnh đơn lẻ",
    )
    ap.add_argument(
        "--input",
        "--img-dir",
        dest="input_path",
        type=Path,
        default=None,
        help="Đường dẫn tới 1 thư mục chứa ảnh HOẶC 1 file ảnh đơn lẻ cần OCR (mặc định: data/raw/anh_bia)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "interim" / "paddle_raw",
        help="Thư mục gốc lưu kết quả *_res.json (mặc định: data/interim/paddle_raw)",
    )
    ap.add_argument(
        "--flat",
        action="store_true",
        help="Lưu trực tiếp <bia_id>_res.json vào --out thay vì tạo thư mục con <engine>_<variant>",
    )
    ap.add_argument(
        "--engine",
        default="nom",
        help="Tên định danh engine ghi trong file *_res.json (mặc định: nom)",
    )
    ap.add_argument(
        "--variant",
        nargs="*",
        default=None,
        help=f"Các cấu hình API cần chạy (mặc định: {DEFAULT_SET}; hỗ trợ: {list(VARIANTS)})",
    )
    ap.add_argument(
        "--device",
        default="api",
        help="Giữ tương thích ngược với CLI cũ (API chạy từ xa nên không phụ thuộc gpu/cpu cục bộ)",
    )
    ap.add_argument("--only", nargs="*", help="Chỉ OCR các bia_id trong danh sách này")
    ap.add_argument(
        "--tai-anh",
        type=Path,
        help="(Colab) CSV bia_id,url,md5 - tải ảnh vào thư mục --input trước khi OCR",
    )
    ap.add_argument("--start", type=int, default=0, help="Bắt đầu xử lý từ chỉ số file thứ N (1-indexed)")
    ap.add_argument("--force", action="store_true", help="OCR lại cả những ảnh đã có file *_res.json")
    ap.add_argument(
        "--ve-anh",
        action="store_true",
        help="Vẽ thêm <bia_id>_ocr_res_img.jpg giống save_to_img của PaddleOCR",
    )
    ap.add_argument(
        "--download-server-img",
        action="store_true",
        help="Tải thêm ảnh kết quả do server Lab vẽ (<bia_id>_server_ocr.jpeg)",
    )
    # Tham số cấu hình API Lab & Polite Policy
    ap.add_argument("--domain", default=None, help="Domain của server SinoNom (mặc định lấy từ SN_DOMAIN)")
    ap.add_argument("--token", default=None, help="Bearer token xác thực (mặc định lấy từ SN_TOKEN)")
    ap.add_argument("--ocr-id", type=int, default=None, help="Ghi đè ocr_id gửi lên API (mặc định theo variant: 5)")
    ap.add_argument("--lang-type", type=int, default=None, help="Ghi đè lang_type gửi lên API (mặc định: 2)")
    ap.add_argument("--epitaph", type=int, default=None, help="Ghi đè tham số epitaph (mặc định: 0)")
    ap.add_argument("--reading-direction", type=int, default=None, help="Hướng đọc: 1 = dọc phải sang trái")
    ap.add_argument("--tag", default=None, help="Tag cấu hình detector trên server (mặc định: det_epitaph_experimental)")
    ap.add_argument("--delay-before-upload", type=float, default=None, help="Polite delay trước khi upload (giây)")
    ap.add_argument("--delay-after-upload", type=float, default=None, help="Polite delay sau khi upload (giây)")
    ap.add_argument("--delay-between-files", type=float, default=None, help="Polite delay giữa 2 ảnh liên tiếp (giây)")
    ap.add_argument("--max-retries", type=int, default=None, help="Số lần thử lại tối đa cho mỗi ảnh")

    a = ap.parse_args(argv)
    effective_input = a.input_path or a.target or (ROOT / "data" / "raw" / "anh_bia")

    if a.tai_anh:
        target_img_dir = effective_input if not effective_input.suffix else effective_input.parent
        valid_ids = fetch_images(a.tai_anh, target_img_dir)
        only_ids = [i for i in valid_ids if not a.only or i in a.only]
        image_paths = resolve_input_images(target_img_dir, only_ids=only_ids)
    else:
        image_paths = resolve_input_images(effective_input, only_ids=a.only)

    if not image_paths:
        print(f"Không tìm thấy ảnh cần OCR tại: {effective_input}", flush=True)
        return 1

    cfg = RateLimitConfig()
    if a.delay_before_upload is not None:
        cfg.DELAY_BEFORE_UPLOAD = a.delay_before_upload
    if a.delay_after_upload is not None:
        cfg.DELAY_AFTER_UPLOAD = a.delay_after_upload
    if a.delay_between_files is not None:
        cfg.DELAY_BETWEEN_FILES = a.delay_between_files
    if a.max_retries is not None:
        cfg.MAX_RETRIES = a.max_retries

    variants = a.variant or DEFAULT_SET
    total_failed = 0

    for v in variants:
        v_ocr_id, v_lang, v_epitaph, v_dir, v_tag = VARIANTS.get(
            v, (5, 2, 0, 1, "det_epitaph_experimental")
        )
        ocr_id = a.ocr_id if a.ocr_id is not None else v_ocr_id
        lang_type = a.lang_type if a.lang_type is not None else v_lang
        epitaph = a.epitaph if a.epitaph is not None else v_epitaph
        reading_direction = a.reading_direction if a.reading_direction is not None else v_dir
        tag = a.tag if a.tag is not None else v_tag

        out_dir = a.out if a.flat else (a.out / f"{a.engine}_{v}")
        t0 = time.time()
        stats = run_sequential_nom_ocr(
            image_paths=image_paths,
            output_dir=out_dir,
            engine=a.engine,
            variant=v,
            ocr_id=ocr_id,
            lang_type=lang_type,
            epitaph=epitaph,
            reading_direction=reading_direction,
            tag=tag,
            force=a.force,
            ve_anh=a.ve_anh,
            download_server_img=a.download_server_img,
            start=a.start,
            config=cfg,
            client_factory=lambda: LabOCRClient(domain=a.domain, token=a.token),
        )
        elapsed = time.time() - t0
        print(
            f"{a.engine}_{v}: {stats['total']} mặt "
            f"(mới: {stats['processed']}, skip: {stats['skipped']}, lỗi: {stats['failed']}), "
            f"{elapsed:.1f}s -> {out_dir}",
            flush=True,
        )
        total_failed += stats["failed"]

    return 1 if total_failed > 0 and len(image_paths) == total_failed else 0


def _selftest() -> None:
    """Kiểm thử nội bộ: chuyển đổi toạ độ, polite rate-limiting, xử lý 1 ảnh & thư mục ảnh."""
    # 1. Kiểm thử quy đổi toạ độ (rescale) từ ảnh resize về ảnh gốc
    mock_res = OCRRes.dict2obj(
        {
            "is_success": True,
            "code": "200",
            "message": "OK",
            "data": {
                "result_file_name": "res_00270.jpg",
                "result_bbox": [
                    [[10, 20], [30, 20], [30, 100], [10, 100]],
                    [50, 60, 70, 140],
                ],
                "result_ocr_text": ["皇朝", ["萬歲", 0.96]],
                "details": [{"score": 0.92}, {"score": 0.96}],
            },
        }
    )
    polys, texts, scores = extract_paddle_compatible_items(mock_res, scale_x=0.5, scale_y=0.5)
    assert len(polys) == 2 and texts == ["皇朝", "萬歲"] and scores == [0.92, 0.96]
    assert polys[0] == [[20, 40], [60, 40], [60, 200], [20, 200]]
    assert polys[1] == [[100, 120], [140, 120], [140, 280], [100, 280]]

    # 2. Kiểm thử luồng chạy tuần tự (1 ảnh đơn lẻ & cả thư mục) với mock client + ghi nhận polite sleep
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        img_dir = tmp_dir / "images"
        out_dir = tmp_dir / "out"
        img_dir.mkdir()
        for name in ("00270-TF1.jpg", "00270-TF2.jpg"):
            Image.new("RGB", (800, 1200), (20, 20, 20)).save(img_dir / name)

        sleep_calls: list[float] = []

        class _DummyClient:
            def upload_image(self, req: UploadImageReq, agent: Optional[str] = None) -> UploadImageRes:
                return UploadImageRes(True, "200", "OK", UploadData(file_name=Path(req.image).name))

            def ocr(self, req: OCRReq, **_kw: Any) -> OCRRes:
                return mock_res

        cfg = RateLimitConfig(
            DELAY_BEFORE_UPLOAD=0.5,
            DELAY_AFTER_UPLOAD=0.75,
            DELAY_BETWEEN_FILES=1.25,
            MAX_RETRIES=3,
        )
        # Chạy đầu vào 1 file ảnh duy nhất
        single_files = resolve_input_images(img_dir / "00270-TF1.jpg")
        assert len(single_files) == 1
        stats_single = run_sequential_nom_ocr(
            image_paths=single_files,
            output_dir=out_dir,
            config=cfg,
            ve_anh=True,
            client_factory=lambda: _DummyClient(),  # type: ignore[return-value]
            sleep_fn=lambda s: sleep_calls.append(s),
        )
        assert stats_single["processed"] == 1 and (out_dir / "00270-TF1_res.json").exists()
        assert (out_dir / "00270-TF1_ocr_res_img.jpg").exists()

        # Chạy đầu vào cả thư mục (00270-TF1 phải được skip, chỉ OCR thêm 00270-TF2)
        folder_files = resolve_input_images(img_dir)
        assert len(folder_files) == 2
        stats_folder = run_sequential_nom_ocr(
            image_paths=folder_files,
            output_dir=out_dir,
            config=cfg,
            client_factory=lambda: _DummyClient(),  # type: ignore[return-value]
            sleep_fn=lambda s: sleep_calls.append(s),
        )
        assert stats_folder["skipped"] == 1 and stats_folder["processed"] == 1
        saved = json.loads((out_dir / "00270-TF2_res.json").read_text(encoding="utf-8"))
        assert set(saved.keys()) >= {"input_path", "engine", "variant", "tiles", "dt_polys", "rec_texts", "rec_scores"}
        assert len(sleep_calls) >= 4  # Đảm bảo polite sleep được gọi tuần tự

    print("ocr_bia (Lab SinoNom API + Polite Policy) selftest: ĐẠT")


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        _selftest()
        sys.exit(0)
    sys.exit(main())