# -*- coding: utf-8 -*-
"""
v0.2 维度管理：站点代码 / 券匹配 / 县区轻油 / 累月数据 / 手动调整

维度来源（口径依据 2026-10-11 日报逆向验证）：
- dim_station.dept_name：站点代码表 Sheet1"站点名称"（养车卡"所属部门"、
  电子券"用券站点名称"的部门名格式别名）
- dim_station.standard_code：Sheet2 标准编码（附表"标准编码"列）
- dim_quan_coefficient：参考表/日通报简表"券匹配"工作表
  （non_oil=考核剔非非（不含洗衣洗车），weiqi=尾气劵；按规则编码去重）
- dim_county_fuel_sales：通报C列县区月轻油（与站级轻油两套口径）
- dim_monthly_cumulative：累月区 1-12 月目标/完成（基础品类+毛利）
- fact_adjustment：手动调整（销售/毛利/零售 × 增/减，整月保留）
"""
from datetime import date

import pandas as pd

from store import logger
from v02.common import clean_station_name, match_column, to_num
from v02 import db

# 固定业务常量（口径经 10-11 日报验证）
TOBACCO_CATEGORY_CODE = "20"        # 零售剔烟草：编码|品类 = 20
WASH_QUAN_KEYWORD = "河南油非互动洗车券15元1张"  # 洗车券商品（当期全名称|商品）
WASH_QUAN_RATIO = 0.4              # 洗车券考核剔除系数（附表J列验证：76515×0.4=30606）
COUNTIES = ["淇县", "浚县", "市区经营部", "商客"]  # 通报主体县区（鹤壁另行单独行）
HEBI_COUNTY = "鹤壁"
ADJ_TYPES = ["sales_add", "sales_sub", "profit_add", "profit_sub",
             "retail_add", "retail_sub"]

# 站点代码表县区名 -> 通报标准县区名（Sheet1 用"淇县公司/浚县公司"）
_COUNTY_NAME_MAP = {"淇县公司": "淇县", "浚县公司": "浚县", "鹤山经营部": "市区经营部"}


def _norm_county(raw):
    """站点代码表县区名规范化为通报标准县区名"""
    s = str(raw).strip() if raw else ""
    return _COUNTY_NAME_MAP.get(s, s)


# ===== 站点代码导入 =====

def import_station_codes(path, sheet1=0, sheet2=1):
    """从站点代码.xlsx 重建/补全 dim_station（upsert，不删既有站）

    Sheet1: 加油站代码 / 便利店名 / 加油站名称 / 县区 / 站点名称(部门名)
    Sheet2: 名称|组织 / 标准编码
    返回 {stations, updated, warnings}
    """
    df1 = pd.read_excel(path, sheet_name=sheet1)
    df2 = pd.read_excel(path, sheet_name=sheet2)
    c_shop = match_column(df1, ["便利店名", "名称|组织"])
    c_county = match_column(df1, ["县区", "片区"])
    c_dept = match_column(df1, ["站点名称", "所属部门"])
    c_code = match_column(df2, ["标准编码"])
    c_name2 = match_column(df2, ["名称|组织"])
    if not c_shop:
        return {"status": "error", "message": "站点代码 Sheet1 缺少便利店名列"}

    std_map = {}
    if c_code and c_name2:
        for _, r in df2.iterrows():
            if pd.notna(r[c_name2]) and pd.notna(r[c_code]):
                std_map[str(r[c_name2]).strip()] = str(r[c_code]).strip()

    updated = inserted = 0
    warnings = []
    conn = db.get_conn()
    try:
        with conn:
            alias_old = {r["station_name"] for r in
                         conn.execute("SELECT station_name FROM dim_station")}
            for _, r in df1.iterrows():
                shop = r[c_shop]
                if pd.isna(shop) or not str(shop).strip():
                    continue  # 无便利站的加油站不进站维表
                name = str(shop).strip()
                county = _norm_county(r[c_county])
                dept = str(r[c_dept]).strip() if pd.notna(r[c_dept]) else None
                std_code = std_map.get(name) or std_map.get(clean_station_name(name))
                exists = name in alias_old
                conn.execute(
                    """INSERT INTO dim_station (station_name, region, county, dept_name, standard_code)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(station_name) DO UPDATE SET
                           region=excluded.region, county=excluded.county,
                           dept_name=excluded.dept_name, standard_code=excluded.standard_code,
                           updated_at=datetime('now','localtime')""",
                    (name, county, county, dept, std_code))
                updated += 1
                if not exists:
                    inserted += 1
        n = conn.execute("SELECT COUNT(*) FROM dim_station").fetchone()[0]
    finally:
        conn.close()
    logger.info(f"[v0.2维度] 站点代码导入: 更新{updated}站(新增{inserted}), 库内共{n}站")
    return {"status": "ok", "stations": updated, "inserted": inserted, "total": n,
            "warnings": warnings}


# ===== 券匹配导入 =====

def import_quan_match(path, sheet="券匹配"):
    """从参考表（日通报简表）券匹配工作表重建 dim_quan_coefficient（全量覆盖）

    列：电子券规则编码 / 尾气劵 / 考核剔非非（不含洗衣洗车）
    规则编码重复时保留首条并告警（10-11 验证：591 行含重复编码）。
    """
    df = pd.read_excel(path, sheet_name=sheet)
    c_key = match_column(df, ["电子券规则编码", "规则编码"])
    c_non = match_column(df, ["考核剔非非（不含洗衣洗车）", "考核剔非非"])
    c_weiqi = match_column(df, ["尾气劵", "尾气券"])
    if not c_key or not c_non:
        return {"status": "error", "message": "券匹配表缺少规则编码或考核剔非非列"}

    dup = df[c_key].astype(str).str.strip().duplicated().sum()
    df = df.drop_duplicates(subset=c_key, keep="first")
    conn = db.get_conn()
    try:
        with conn:
            conn.execute("DELETE FROM dim_quan_coefficient")
            for _, r in df.iterrows():
                key = r[c_key]
                if pd.isna(key) or not str(key).strip():
                    continue
                conn.execute(
                    """INSERT INTO dim_quan_coefficient (rule_key, non_oil, weiqi)
                       VALUES (?,?,?)
                       ON CONFLICT(rule_key) DO UPDATE SET
                           non_oil=excluded.non_oil, weiqi=excluded.weiqi,
                           updated_at=datetime('now','localtime')""",
                    (str(key).strip(),
                     float(to_num(pd.Series([r[c_non]])).iloc[0]),
                     float(to_num(pd.Series([r[c_weiqi]])).iloc[0]) if c_weiqi else 0.0))
        n = conn.execute("SELECT COUNT(*) FROM dim_quan_coefficient").fetchone()[0]
    finally:
        conn.close()
    warns = [f"重复规则编码已去重 {dup} 条"] if dup else []
    logger.info(f"[v0.2维度] 券匹配导入: {n} 条规则" + ("；" + "；".join(warns) if warns else ""))
    return {"status": "ok", "rules": n, "warnings": warns}


# ===== 县区月轻油 =====

def upsert_county_fuel_sales(year_month, rows):
    """rows: [{county, tons}, ...] 通报C列口径的县区月轻油"""
    conn = db.get_conn()
    try:
        with conn:
            for r in rows:
                conn.execute(
                    """INSERT INTO dim_county_fuel_sales (year_month, county, tons)
                       VALUES (?,?,?)
                       ON CONFLICT(year_month, county) DO UPDATE SET
                           tons=excluded.tons, updated_at=datetime('now','localtime')""",
                    (year_month, r["county"], float(r["tons"])))
    finally:
        conn.close()
    logger.info(f"[v0.2维度] 县区轻油 {year_month}: {len(rows)} 条")
    return {"status": "ok", "rows": len(rows)}


def get_county_fuel_sales(year_month):
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT county, tons FROM dim_county_fuel_sales WHERE year_month=?",
            (year_month,)).fetchall()
        return {r["county"]: r["tons"] for r in rows}
    finally:
        conn.close()


# ===== 累月数据 =====

def upsert_monthly_cumulative(year_month, rows):
    """rows: [{county, month_no, sales_target, sales_actual, profit_target, profit_actual}, ...]

    year_month = 归属报表月（如 '2026-10'），month_no = 数据月份(1-12)。
    """
    conn = db.get_conn()
    try:
        with conn:
            for r in rows:
                conn.execute(
                    """INSERT INTO dim_monthly_cumulative
                       (year_month, county, month_no, sales_target, sales_actual, profit_target, profit_actual)
                       VALUES (?,?,?,?,?,?,?)
                       ON CONFLICT(year_month, county, month_no) DO UPDATE SET
                           sales_target=excluded.sales_target, sales_actual=excluded.sales_actual,
                           profit_target=excluded.profit_target, profit_actual=excluded.profit_actual,
                           updated_at=datetime('now','localtime')""",
                    (year_month, r["county"], int(r["month_no"]),
                     float(r.get("sales_target") or 0), float(r.get("sales_actual") or 0),
                     float(r.get("profit_target") or 0), float(r.get("profit_actual") or 0)))
    finally:
        conn.close()
    logger.info(f"[v0.2维度] 累月数据 {year_month}: {len(rows)} 行")
    return {"status": "ok", "rows": len(rows)}


def get_monthly_cumulative(year_month):
    """返回 {county: {month_no: {sales_target, sales_actual, profit_target, profit_actual}}}"""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            """SELECT county, month_no, sales_target, sales_actual, profit_target, profit_actual
               FROM dim_monthly_cumulative WHERE year_month=?""", (year_month,)).fetchall()
    finally:
        conn.close()
    out = {}
    for r in rows:
        out.setdefault(r["county"], {})[int(r["month_no"])] = {
            "sales_target": r["sales_target"], "sales_actual": r["sales_actual"],
            "profit_target": r["profit_target"], "profit_actual": r["profit_actual"]}
    return out


# ===== 手动调整（整月保留）=====

def add_adjustment(report_date, station, adj_type, value, reason=""):
    """添加手动调整。report_date=操作日；同一报表月内所有调整均生效，
    下月自动不再引用（"下月1号清除"由月份过滤自然实现）。"""
    assert adj_type in ADJ_TYPES, f"非法调整类型: {adj_type}"
    conn = db.get_conn()
    try:
        with conn:
            conn.execute(
                "INSERT INTO fact_adjustment (report_date, station_name, adj_type, value, reason) "
                "VALUES (?,?,?,?,?)",
                (report_date, station, adj_type, float(value), reason or None))
    finally:
        conn.close()
    logger.info(f"[v0.2调整] {station} {adj_type}={value} ({reason})")
    return {"status": "ok"}


def get_month_adjustments(year_month):
    """某报表月的全部手动调整 [{report_date, station_name, adj_type, value, reason}]"""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM fact_adjustment WHERE report_date LIKE ? ORDER BY id",
            (year_month + "-%",)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_adjustment(adj_id):
    conn = db.get_conn()
    try:
        with conn:
            conn.execute("DELETE FROM fact_adjustment WHERE id=?", (adj_id,))
    finally:
        conn.close()
    return {"status": "ok"}


def station_adjustment_map(year_month):
    """月内手动调整聚合成 {(station, adj_type): value}"""
    out = {}
    for r in get_month_adjustments(year_month):
        key = (r["station_name"], r["adj_type"])
        out[key] = out.get(key, 0) + float(r["value"] or 0)
    return out


# ===== 维度查询（管道用）=====

def get_station_dim():
    """返回 [(station_name, region, county, dept_name, standard_code)]"""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT station_name, region, county, dept_name, standard_code "
            "FROM dim_station WHERE status='active'").fetchall()
        return [tuple(r) for r in rows]
    finally:
        conn.close()


def get_light_oil_map(year_month):
    """站级月轻油 {station_name: tons}（附表 Y/Z/AA 列口径）"""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT station_name, tons FROM dim_light_oil_sales WHERE year_month=?",
            (year_month,)).fetchall()
        return {r["station_name"]: r["tons"] for r in rows}
    finally:
        conn.close()


def get_monthly_target(year_month):
    """当月目标 {county: {sales_target, profit_target}}（商客/鹤壁无目标则缺省0）"""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT county, sales_target, profit_target FROM dim_monthly_target "
            "WHERE year_month=?", (year_month,)).fetchall()
        return {r["county"]: {"sales_target": r["sales_target"] or 0,
                              "profit_target": r["profit_target"] or 0} for r in rows}
    finally:
        conn.close()


def get_quan_coefficient_map():
    """{rule_code: (non_oil, weiqi)}"""
    conn = db.get_conn()
    try:
        rows = conn.execute("SELECT rule_key, non_oil, weiqi FROM dim_quan_coefficient").fetchall()
        return {r["rule_key"]: (r["non_oil"] or 0, r["weiqi"] or 0) for r in rows}
    finally:
        conn.close()
