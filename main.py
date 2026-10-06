# -*- coding: utf-8 -*-
"""
非油报表助手 - 程序入口
使用 pywebview 将 Flask 后端 + Web 前端打包为桌面应用
"""
import sys
import os
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# 安装依赖检查
def check_dependencies():
    missing = []
    try:
        import flask
    except ImportError:
        missing.append("flask")
    try:
        import pandas
    except ImportError:
        missing.append("pandas")
    try:
        import openpyxl
    except ImportError:
        missing.append("openpyxl")
    try:
        from PIL import Image
    except ImportError:
        missing.append("Pillow")
    if missing:
        print(f"缺少依赖: {', '.join(missing)}")
        print("正在安装...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
        print("安装完成，请重新启动程序")
        sys.exit(0)


def start_server(port=18080):
    """启动Flask后端"""
    from backend import run_server
    run_server(port)


def start_app():
    """启动桌面应用"""
    check_dependencies()

    port = 18080
    # 启动后端
    server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
    server_thread.start()

    # 等待后端启动
    time.sleep(2)

    # 启动桌面窗口
    try:
        import webview
        webview.create_window(
            "非油报表助手 v0.1.0",
            f"http://127.0.0.1:{port}",
            width=1280,
            height=800,
            min_size=(1000, 600),
            resizable=True,
            text_select=True
        )
        webview.start()
    except ImportError:
        print("pywebview 未安装，使用浏览器打开...")
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{port}")
        print(f"应用已在浏览器中打开: http://127.0.0.1:{port}")
        print("按 Ctrl+C 退出")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n退出")


if __name__ == "__main__":
    start_app()
