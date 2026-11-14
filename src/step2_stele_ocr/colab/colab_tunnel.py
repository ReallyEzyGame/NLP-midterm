# Dán NGUYÊN Ô NÀY vào 1 cell Colab (Runtime → Change runtime type → T4 GPU) rồi chạy.
# Ô sẽ hỏi token: tự đặt một chuỗi bí mật (dùng lại làm COLAB_TOKEN cho colab_exec.py). KHÔNG commit token.
# Ô in ra URL https://....trycloudflare.com → đặt vào COLAB_URL. ĐỂ Ô CHẠY MÃI, không dừng (URL đổi mỗi lần chạy lại).
import getpass, json, re, subprocess, time, urllib.request, pathlib

TOKEN = getpass.getpass("JUPYTER_TOKEN: ").strip()
PORT = 8888

# 1) JupyterLab + collaboration (jupyter-mcp-server cần) — chỉ cài lần đầu của runtime
subprocess.run("pip -q install jupyterlab==4.4.1 jupyter-collaboration==4.0.2 ipykernel "
               "&& pip -q uninstall -y pycrdt datalayer_pycrdt && pip -q install datalayer_pycrdt==0.12.17",
               shell=True, check=True)

# 2) cloudflared
if not pathlib.Path("/usr/local/bin/cloudflared").exists():
    subprocess.run("wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 "
                   "-O /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared", shell=True, check=True)

# 3) notebook mà MCP mở (DOCUMENT_ID=work.ipynb)
nb = pathlib.Path("/content/work.ipynb")
if not nb.exists():
    nb.write_text(json.dumps({"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}))

# 4) Jupyter server (kernel chạy trên máy Colab → có GPU)
subprocess.run(f"pkill -f 'jupyter-lab.*{PORT}'; pkill -f cloudflared", shell=True)
jl = subprocess.Popen(
    ["jupyter", "lab", "--no-browser", f"--port={PORT}", "--ip=127.0.0.1", "--allow-root",
     f"--IdentityProvider.token={TOKEN}", "--ServerApp.root_dir=/content",
     "--ServerApp.allow_origin=*", "--ServerApp.disable_check_xsrf=True"],
    stdout=open("/content/jupyter.log", "w"), stderr=subprocess.STDOUT)
for _ in range(60):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/status?token={TOKEN}", timeout=2)
        break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("Jupyter không lên — xem /content/jupyter.log")

# 5) Tunnel cloudflare, lấy URL
# log ra file (không dùng PIPE: pipe đầy sẽ làm cloudflared treo sau vài giờ)
cf = subprocess.Popen(["cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
                      stdout=open("/content/cloudflared.log", "w"), stderr=subprocess.STDOUT)
url = None
for _ in range(60):
    m = re.search(r"https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com", pathlib.Path("/content/cloudflared.log").read_text())
    if m:
        url = m.group(0)
        break
    time.sleep(1)
print("\n==============================\nURL gửi cho Claude:", url, "\n==============================\n", flush=True)

# 6) Giữ ô chạy + báo nếu chết
while True:
    time.sleep(60)
    if jl.poll() is not None or cf.poll() is not None:
        print("Jupyter hoặc tunnel đã dừng — chạy lại ô này (URL sẽ đổi).")
        break
