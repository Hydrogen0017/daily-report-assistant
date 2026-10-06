# -*- coding: utf-8 -*-
"""
数据存储、配置管理与日志模块
负责持久化所有运行时数据，为后续维护预留接口
"""
import json
import os
import time
from datetime import datetime, date
from pathlib import Path

# 项目根目录（store.py 所在目录即为项目根目录）
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = DATA_DIR / "config"
LOGS_DIR = DATA_DIR / "logs"
CACHE_DIR = DATA_DIR / "cache"
OUTPUT_DIR = DATA_DIR / "output"
UPLOADS_DIR = DATA_DIR / "uploads"
TEMPLATES_DIR = DATA_DIR / "templates"

for d in [CONFIG_DIR, LOGS_DIR, CACHE_DIR, OUTPUT_DIR, UPLOADS_DIR, TEMPLATES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = CONFIG_DIR / "app_config.json"


def load_config():
    """加载应用配置，不存在则初始化默认配置"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    config = {
        "app_name": "非油报表助手",
        "version": "0.1.0",
        "current_report": "daily_report",
        "last_run": None,
        "report_date": None,
        "monthly_targets": {},
        "light_oil_sales": {},
        "adjustments": {},
        "stations": [],
        "settings": {
            "output_xlsx": True,
            "output_image": True,
            "auto_open_output": False,
            "confirm_steps": True
        }
    }
    save_config(config)
    return config


def save_config(config):
    """保存配置"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_today_str():
    return date.today().strftime("%Y-%m-%d")


def get_now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Logger:
    """日志管理器 - 每次运行生成独立日志文件"""

    def __init__(self):
        self.current_log_file = None
        self.session_id = None
        self.entries = []

    def start_session(self, report_id="daily_report"):
        """开始新的日志会话"""
        self.session_id = f"{report_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.current_log_file = LOGS_DIR / f"{self.session_id}.log"
        self.entries = []
        self.log("INFO", f"会话开始: {report_id}")
        return self.session_id

    def log(self, level, message, step=None):
        """写入日志"""
        ts = get_now_str()
        prefix = f"[{ts}]"
        if step:
            prefix += f" [步骤{step}]"
        line = f"{prefix} [{level}] {message}"
        self.entries.append(line)
        if self.current_log_file:
            with open(self.current_log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return line

    def info(self, message, step=None):
        return self.log("INFO", message, step)

    def warn(self, message, step=None):
        return self.log("WARN", message, step)

    def error(self, message, step=None):
        return self.log("ERROR", message, step)

    def get_recent_logs(self, n=50):
        """获取最近N条日志"""
        return self.entries[-n:]

    def get_all_logs(self):
        return self.entries

    def save_session_summary(self, summary):
        """保存会话摘要到日志"""
        self.log("INFO", f"会话摘要: {json.dumps(summary, ensure_ascii=False)}")


logger = Logger()
