# -*- coding: utf-8 -*-
"""
非油报表助手 - 程序入口
使用 pywebview 将 Flask 后端 + Web 前端打包为桌面应用
"""
import sys
import os
import io
import threading
import time
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))


class _NullIO(io.TextIOBase):
    """丢弃写入的空流。

    PyInstaller windowed 模式下 sys.stdout/stderr 是内部的 NullWriter（非 None），
    click/Flask 启动横幅包装该流后 flush 会抛 OSError[Errno 22]，直接杀死后端线程。
    必须在启动最早期用安全可写流替换（click 会按 encoding 属性判断流是否可直接使用）。
    """
    encoding = "utf-8"
    errors = "strict"

    def write(self, s):
        return len(s)

    def flush(self):
        pass


if getattr(sys, "frozen", False):
    # exe 环境：无条件替换（不能用 is None 判断，NullWriter 并非 None）
    sys.stdout = _NullIO()
    sys.stderr = _NullIO()


def _diag_dir():
    """诊断日志目录：exe 模式写到 exe 同级目录，开发模式写到项目根目录"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return BASE_DIR


def _write_error_log(title, text):
    """windowed 模式下 stderr 无效，异常需落盘才能被发现"""
    try:
        target = _diag_dir() / "backend_error.log"
        with open(target, "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {title}\n{text}\n")
    except Exception:
        pass


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
    try:
        from backend import run_server
        run_server(port)
    except Exception:
        _write_error_log("后端线程异常", traceback.format_exc())
        raise


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
        _write_error_log("pywebview 未安装", traceback.format_exc())
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
    except Exception:
        _write_error_log("桌面窗口异常", traceback.format_exc())
        raise


if __name__ == "__main__":
    start_app()
