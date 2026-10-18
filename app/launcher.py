"""Start the local web app and open its visual setup page."""

import json
import socket
import threading
import time
import urllib.request
import webbrowser

import uvicorn
from dotenv import load_dotenv

from app.settings import ENV_FILE


def _is_our_server(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
            data = json.load(response)
        return "database" in data and "model_configured" in data
    except Exception:
        return False


def _open_when_ready(port):
    url = f"http://127.0.0.1:{port}/setup"
    for _ in range(80):
        if _is_our_server(port):
            if not webbrowser.open(url):
                print(f"浏览器未自动打开，请访问 {url}", flush=True)
            return
        time.sleep(0.25)
    print(f"服务启动中；就绪后请访问 {url}", flush=True)


def main():
    load_dotenv(ENV_FILE)
    import os
    try:
        port = int(os.getenv("APP_PORT", "8000"))
    except ValueError as exc:
        raise SystemExit("APP_PORT 必须是数字") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("APP_PORT 需在 1 到 65535 之间")
    url = f"http://127.0.0.1:{port}/setup"
    if _is_our_server(port):
        webbrowser.open(url)
        print(f"已打开运行中的数据质量 Agent：{url}")
        return
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"端口 {port} 已被其他程序占用，请在 .env 修改 APP_PORT")
    print(f"数据质量 Agent 正在启动：{url}。关闭此终端可停止服务。", flush=True)
    threading.Thread(target=_open_when_ready, args=(port,), daemon=True).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
