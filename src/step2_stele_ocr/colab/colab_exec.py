"""Điều khiển Jupyter trên Colab qua REST + websocket (không cần MCP): chạy code, đẩy/kéo file, chuẩn bị runtime.

Biến môi trường: COLAB_URL (https://xxx.trycloudflare.com, in ra bởi colab_tunnel.py), COLAB_TOKEN. Không ghi token vào file.

    python -m src.step2_stele_ocr.colab.colab_exec danh-sach-anh            # data/interim/anh_bia_list.csv (url + md5)
    python -m src.step2_stele_ocr.colab.colab_exec cai-dat                  # paddle-gpu + paddleocr, gỡ torch (xung đột NCCL)
    python -m src.step2_stele_ocr.colab.colab_exec day <file_local> <duong_dan_tren_colab>
    python -m src.step2_stele_ocr.colab.colab_exec chay "print(1)"  |  chay --file job.py --timeout 3600
    python -m src.step2_stele_ocr.colab.colab_exec keo <duong_dan_tren_colab> <file_local>
Quy trình đầy đủ: README.md cùng thư mục.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import hashlib
import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KFILE = ROOT / "data" / "interim" / "colab_kernel.txt"


def _cfg() -> tuple[str, str]:
    return os.environ["COLAB_URL"].rstrip("/"), os.environ["COLAB_TOKEN"]


def rest(method: str, path: str, body: dict | None = None, timeout: int = 120):
    url, tok = _cfg()
    req = urllib.request.Request(f"{url}{path}", method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"token {tok}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def kernel_id() -> str:
    alive = {k["id"] for k in rest("GET", "/api/kernels")}
    if KFILE.exists() and KFILE.read_text().strip() in alive:
        return KFILE.read_text().strip()
    kid = rest("POST", "/api/kernels", {"name": "python3"})["id"]
    KFILE.parent.mkdir(parents=True, exist_ok=True)
    KFILE.write_text(kid)
    return kid


async def _run(code: str, timeout: float) -> int:
    import websockets
    url, tok = _cfg()
    ws_url = url.replace("https://", "wss://") + f"/api/kernels/{kernel_id()}/channels"
    msg_id = uuid.uuid4().hex
    msg = {"header": {"msg_id": msg_id, "msg_type": "execute_request", "username": "", "session": uuid.uuid4().hex,
                      "version": "5.3"}, "parent_header": {}, "metadata": {}, "channel": "shell",
           "content": {"code": code, "silent": False, "store_history": False, "user_expressions": {},
                       "allow_stdin": False, "stop_on_error": True}}
    rc = 0
    async with websockets.connect(ws_url, additional_headers={"Authorization": f"token {tok}"},
                                  max_size=None, ping_interval=20) as ws:
        await ws.send(json.dumps(msg))

        async def loop():
            nonlocal rc
            while True:
                m = json.loads(await ws.recv())
                if m.get("parent_header", {}).get("msg_id") != msg_id:
                    continue
                t, c = m["msg_type"], m["content"]
                if t == "stream":
                    print(c["text"], end="", flush=True)
                elif t in ("execute_result", "display_data"):
                    print(c["data"].get("text/plain", ""), flush=True)
                elif t == "error":
                    print("\n".join(c["traceback"]), file=sys.stderr)
                    rc = 1
                elif t == "status" and c["execution_state"] == "idle":
                    return
        await asyncio.wait_for(loop(), timeout)
    return rc


def run(code: str, timeout: float = 600) -> int:
    return asyncio.run(_run(code, timeout))


def push(local: Path, remote: str) -> None:
    """Đẩy file lên Colab (API contents, base64)."""
    parts = remote.strip("/").split("/")
    for k in range(1, len(parts)):
        try:
            rest("PUT", "/api/contents/" + "/".join(parts[:k]), {"type": "directory"})
        except Exception:
            pass                                         # thư mục đã có
    rest("PUT", f"/api/contents/{remote.strip('/')}",
         {"type": "file", "format": "base64", "content": base64.b64encode(local.read_bytes()).decode()}, timeout=600)


def pull(remote: str, local: Path) -> None:
    """Kéo file từ Colab về thẳng đĩa (không qua bộ nhớ trung gian khác)."""
    url, tok = _cfg()
    req = urllib.request.Request(f"{url}/files/{remote.strip('/')}", headers={"Authorization": f"token {tok}"})
    local.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, timeout=600) as r, open(local, "wb") as f:
        f.write(r.read())


def image_list(out: Path) -> int:
    """bia_id,url,md5 cho mọi ảnh trong data/raw/anh_bia (url lấy từ download_log.csv) — Colab tự tải ảnh CÔNG KHAI
    từ Vietnamica và kiểm md5 trùng bản nhóm; không đẩy ảnh/ văn bản sách lên cloud."""
    urls = {}
    for r in csv.DictReader(open(ROOT / "data" / "metadata" / "download_log.csv", encoding="utf-8")):
        if r["source_url"]:
            urls[r["file"].replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]] = r["source_url"]
    rows = []
    for f in sorted((ROOT / "data" / "raw" / "anh_bia").glob("*.jpg")):
        if f.stem not in urls:
            raise SystemExit(f"thiếu URL trong download_log.csv cho {f.stem}")
        rows.append([f.stem, urls[f.stem], hashlib.md5(f.read_bytes()).hexdigest()])
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["bia_id", "url", "md5"])
        w.writerows(rows)
    print(f"{len(rows)} ảnh -> {out}")
    return 0


SETUP = r'''
import subprocess
def sh(c):
    r = subprocess.run(c, shell=True, capture_output=True, text=True); print(r.stdout[-800:], r.stderr[-800:])
sh("pip -q install paddlepaddle-gpu==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/ && pip -q install paddleocr")
# torch có sẵn của Colab xung đột NCCL với paddle (ImportError ncclCommResume) → gỡ; modelscope cần cài lại sau khi gỡ torch
sh("pip -q uninstall -y torch torchvision torchaudio torchao torchtune torchdata torchcodec torchsummary; "
   "rm -rf /usr/local/lib/python3*/dist-packages/torch; pip -q install --force-reinstall --no-deps modelscope")
r = subprocess.run(["python", "-c", "from paddleocr import PaddleOCR; import paddle; print('OK', paddle.device.get_device())"],
                   capture_output=True, text=True); print(r.stdout, r.stderr[-500:])
'''


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("chay")
    p.add_argument("code", nargs="?")
    p.add_argument("--file", type=Path)
    p.add_argument("--timeout", type=float, default=600)
    sub.add_parser("cai-dat")
    p = sub.add_parser("day")
    p.add_argument("local", type=Path)
    p.add_argument("remote")
    p = sub.add_parser("keo")
    p.add_argument("remote")
    p.add_argument("local", type=Path)
    p = sub.add_parser("danh-sach-anh")
    p.add_argument("--out", type=Path, default=ROOT / "data" / "interim" / "anh_bia_list.csv")
    a = ap.parse_args(argv)
    if a.cmd == "chay":
        return run(a.file.read_text(encoding="utf-8") if a.file else a.code, a.timeout)
    if a.cmd == "cai-dat":
        return run(SETUP, 1800)
    if a.cmd == "day":
        push(a.local, a.remote)
        return 0
    if a.cmd == "keo":
        pull(a.remote, a.local)
        return 0
    return image_list(a.out)


if __name__ == "__main__":
    sys.exit(main())
