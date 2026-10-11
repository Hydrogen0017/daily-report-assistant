# -*- coding: utf-8 -*-
"""
v0.2 导入器内核：Excel → SQLite 统一数据模型

流程：识别数据源 → pandas 读取 → 候选列映射 → 站名标准化
     → 挂接维度（片区/县区）→ 快照式覆盖入库 → ingest_log 记录

快照语义：同一 report_date + 数据源 重复导入时先删旧快照再插入，
保证"每次上传 = 该日该源的完整数据"，无需人工去重。
"""
import uuid
from datetime import date

import pandas as pd

from store import logger
from v02.common import clean_station_name, match_column, to_num
from v02.datasources import identify_file, get_source
from v02 import db


def _station_dim_map(conn):
    """站名 -> (region, county) 映射（含清洗后名称的兜底匹配）"""
    rows = conn.execute("SELECT station_name, region, county FROM dim_station").fetchall()
    direct = {r["station_name"]: (r["region"], r["county"]) for r in rows}
    cleaned = {clean_station_name(k): v for k, v in direct.items()}
    return direct, cleaned


def _lookup_dim(station, direct, cleaned):
    if station in direct:
        return direct[station]
    c = clean_station_name(station)
    return cleaned.get(c, (None, None))


def ingest_file(file_path, report_date=None, batch_id=None, source_id=None):
    """导入单个 Excel 文件到数据库。

    参数：
        file_path:   文件路径
        report_date: 数据所属报表日（默认今天；补录历史时指定）
        batch_id:    批次号（多文件一次上传共用）
        source_id:   显式指定数据源（缺省按文件名识别）

    返回：dict(status, source_id, rows, message)
    """
    report_date = report_date or date.today().isoformat()
    batch_id = batch_id or f"batch_{uuid.uuid4().hex[:12]}"

    ds = get_source(source_id) if source_id else identify_file(file_path.name
                                                                if hasattr(file_path, "name") else str(file_path))
    if ds is None:
        return {"status": "error", "source_id": None, "rows": 0,
                "message": f"无法识别数据源: {file_path}"}

    # 1) 读取
    df = pd.read_excel(file_path)
    if df.empty:
        return {"status": "error", "source_id": ds.id, "rows": 0, "message": "文件为空"}

    # 2) 列映射（候选列名解耦点）
    mapping = {}
    missing_required = []
    for std_field, candidates in ds.fields.items():
        col = match_column(df, candidates)
        if col:
            mapping[std_field] = col
        elif std_field in ds.required:
            missing_required.append(std_field)
    station_col = match_column(df, ds.station_col) if ds.station_col else None
    if not station_col:
        missing_required.append("station")
    if missing_required:
        return {"status": "error", "source_id": ds.id, "rows": 0,
                "message": f"缺少必需列: {', '.join(missing_required)}"}

    # 3) 构造标准行
    rows = []
    for _, r in df.iterrows():
        station_raw = r[station_col]
        station = clean_station_name(str(station_raw).strip()) if pd.notna(station_raw) else ""
        if not station:
            continue
        row = {"report_date": report_date, "station_name": station}
        for std_field, src_col in mapping.items():
            row[std_field] = r[src_col] if pd.notna(r[src_col]) else None
        rows.append(row)
    if not rows:
        return {"status": "error", "source_id": ds.id, "rows": 0, "message": "无有效数据行"}

    # 4) 数值字段清洗
    std_df = pd.DataFrame(rows)
    for std_field in ds.fields:
        if std_field in std_df.columns:
            std_df[std_field] = to_num(std_df[std_field])

    # 5) 入库（事务：快照覆盖 + 插入）
    with db.get_conn() as conn:
        direct, cleaned = _station_dim_map(conn)
        if ds.dedup:
            if ds.target_table == "fact_sales_detail":
                conn.execute(
                    "DELETE FROM fact_sales_detail WHERE report_date=? AND period_tag=?",
                    (report_date, ds.period_tag))
            else:
                conn.execute(
                    f"DELETE FROM {ds.target_table} WHERE report_date=?",
                    (report_date,))

        inserted = 0
        for row in std_df.to_dict("records"):
            region, county = _lookup_dim(row["station_name"], direct, cleaned)
            cols = ["report_date", "station_name", "region", "county"] + list(ds.fields.keys())
            vals = [row.get("report_date"), row.get("station_name"), region, county] + \
                   [row.get(f) for f in ds.fields.keys()]
            if ds.target_table == "fact_sales_detail":
                cols.insert(2, "period_tag")
                vals.insert(2, ds.period_tag)
            ph = ",".join("?" * len(cols))
            conn.execute(
                f"INSERT INTO {ds.target_table} ({','.join(cols)}) VALUES ({ph})", vals)
            inserted += 1

        conn.execute(
            "INSERT INTO ingest_log (batch_id, source_id, file_name, report_date, row_count, status, message) "
            "VALUES (?,?,?,?,?,?,?)",
            (batch_id, ds.id, str(file_path), report_date, inserted, "ok", None))

    logger.info(f"[v0.2导入] {ds.name} -> {ds.target_table}: {inserted}行 (报表日 {report_date}, 批次 {batch_id})")
    return {"status": "ok", "source_id": ds.id, "rows": inserted,
            "message": f"{ds.name}: {inserted} 行已入库", "batch_id": batch_id}


def ingest_files(file_paths, report_date=None, batch_id=None):
    """多文件导入（一次上传的完整批次）"""
    batch_id = batch_id or f"batch_{uuid.uuid4().hex[:12]}"
    results = []
    for fp in file_paths:
        try:
            results.append(ingest_file(fp, report_date=report_date, batch_id=batch_id))
        except Exception as e:
            results.append({"status": "error", "source_id": None, "rows": 0,
                            "message": f"{fp}: {e}"})
    ok = [r for r in results if r["status"] == "ok"]
    return {"batch_id": batch_id, "total": len(results), "ok": len(ok),
            "results": results}


# ===== 查询接口（P2 计算层的数据入口，也可用于界面校验） =====

def query_sales(report_date, period_tag):
    """查询某报表日某期间的销售明细（自动带出维度）"""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM fact_sales_detail WHERE report_date=? AND period_tag=?",
            (report_date, period_tag)).fetchall()
        return [dict(r) for r in rows]


def query_sales_summary(report_date, period_tag, by="county"):
    """按县区/片区汇总（快速校验导入正确性）"""
    with db.get_conn() as conn:
        rows = conn.execute(
            f"""SELECT {by} AS grp, COUNT(*) AS n_stations,
                       ROUND(SUM(amount),2) AS total_amount,
                       ROUND(SUM(profit),2) AS total_profit
                FROM fact_sales_detail
                WHERE report_date=? AND period_tag=? AND {by} IS NOT NULL
                GROUP BY {by} ORDER BY total_amount DESC""",
            (report_date, period_tag)).fetchall()
        return [dict(r) for r in rows]
