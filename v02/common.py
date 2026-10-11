# -*- coding: utf-8 -*-
"""
v0.2 公共工具：站名清洗、数值转换、候选列匹配
（自 processor.py 抽取的通用逻辑，P2 迁移后旧模块退役）
"""
import pandas as pd

# 站点名后缀清洗规则（_t / _z_t / _z_w_t 等为内部标识，不影响聚合）
STATION_SUFFIXES = ["_z_w_t", "_z_t", "_w_t", "_t", "_z", "_w"]


def clean_station_name(name):
    """清洗站点名称，去除内部标识后缀用于匹配"""
    if not isinstance(name, str):
        return name
    for suffix in STATION_SUFFIXES:
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def safe_float(val, default=0.0):
    """安全转换为浮点数"""
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def match_column(df, candidates):
    """按候选列名列表匹配第一个命中的列（列名强耦合的解耦点：
    源表列名变化只需改数据源定义里的候选列表）"""
    cols = set(df.columns)
    for cand in candidates:
        if cand in cols:
            return cand
    return None


def to_num(series):
    """整列数值化（非数转 0）"""
    return pd.to_numeric(series, errors="coerce").fillna(0)
