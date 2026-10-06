# -*- coding: utf-8 -*-
"""
基础参照数据模块
从原报表提取的默认数据：站点片区映射、轻油销量、券系数表、月度目标
后续可通过维护接口更新（会覆盖到配置文件，配置文件优先于本默认值）
"""
import json
from pathlib import Path

# 基础数据JSON文件路径（打包后随程序分发）
BASE_DATA_FILE = Path(__file__).parent / "base_data.json"

# ===== 内置默认月度目标（2026年10月，从原日报提取） =====
DEFAULT_MONTHLY_TARGETS = {
    "2026-10": {
        "淇县": {"sales": 95.92, "profit": 17.876},
        "浚县": {"sales": 95.48, "profit": 17.794},
        "市区经营部": {"sales": 248.6, "profit": 46.33},
        "商客": {"sales": 0, "profit": 0}
    }
}


def load_base_data():
    """加载基础参照数据"""
    data = {"station_regions": {}, "light_oil_sales": {}, "quan_coefficients": {}}
    if BASE_DATA_FILE.exists():
        with open(BASE_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    return data


def get_station_regions(config):
    """获取站点片区映射：配置优先，否则用内置数据"""
    configured = config.get("station_regions", {})
    if configured:
        return configured
    return load_base_data().get("station_regions", {})


def get_light_oil_sales(config):
    """获取轻油销量：配置优先，否则用内置数据"""
    configured = config.get("light_oil_sales", {})
    if configured:
        return configured
    return load_base_data().get("light_oil_sales", {})


def get_quan_coefficients(config):
    """获取券系数：配置优先，否则用内置数据"""
    configured = config.get("quan_coefficients", {})
    if configured:
        return configured
    return load_base_data().get("quan_coefficients", {})


def get_monthly_targets(config, year, month):
    """获取月度目标：配置优先，否则用内置默认"""
    month_key = f"{year}-{month:02d}"
    configured = config.get("monthly_targets", {}).get(month_key)
    if configured:
        return configured
    return DEFAULT_MONTHLY_TARGETS.get(month_key, {})
