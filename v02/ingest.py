# -*- coding: utf-8 -*-
"""
v0.2 导入器内核：Excel → SQLite 统一数据模型
（响应评审 R3/R4/R5/R6 补强版）

流程：识别数据源 → pandas 读取 → 结构校验（硬性门禁）
     → 列映射 → 行级校验清洗（软性，全量记录）
     → 站名标准化 → 挂接维度 → 事务化快照覆盖入库
     → 审计日志（ingest_log）+ 会话日志

错误处理（方案第13节）：
- 锁等待（可重试）→ run_with_retry 指数退避
- 结构/校验错误（不可重试）→ 拒绝导入并明确报告
- 任何失败 → 事务自动回滚，库保持旧快照
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


def _write_log(batch_id, ds_id, file_name, report_date, row_count, status, message):
    """审计日志（独立连接，保证失败记录也能落库）"""
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO ingest_log (batch_id, source_id, file_name, report_date, row_count, status, message) "
            "VALUES (?,?,?,?,?,?,?)",
            (batch_id, ds_id, file_name, report_date, row_count, status, message))
        conn.commit()
    finally:
        conn.close()


def _ingest_once(ds, file_path, report_date, batch_id):
    """单文件导入的一次完整尝试（含事务，可整体重跑）"""
    # ---- 1) 读取 + 结构校验（硬性门禁，不入库）----
    try:
        df = pd.read_excel(file_path)
    except Exception as e:
        _write_log(batch_id, ds.id, str(file_path), report_date, 0, "error", f"文件无法读取: {e}")
        return {"status": "error", "source_id": ds.id, "rows": 0,
                "message": f"文件无法读取: {e}"}

    if df.empty:
        _write_log(batch_id, ds.id, str(file_path), report_date, 0, "error", "文件为空")
        return {"status": "error", "source_id": ds.id, "rows": 0, "message": "文件为空"}

    mapping = {}
    missing = []
    for std_field, candidates in ds.fields.items():
        col = match_column(df, candidates)
        if col:
            mapping[std_field] = col
        elif std_field in ds.required:
            missing.append(f"{std_field}(候选: {', '.join(candidates)})")
    station_col = match_column(df, ds.station_col) if ds.station_col else None
    if not station_col:
        missing.append("station(站名列)")
    if missing:
        msg = f"缺少必需列: {'; '.join(missing)}"
        _write_log(batch_id, ds.id, str(file_path), report_date, 0, "error", msg)
        logger.warn(f"[v0.2导入] {ds.name} 结构校验失败: {msg}")
        return {"status": "error", "source_id": ds.id, "rows": 0, "message": msg}

    # ---- 2) 行级构造 + 软性校验（全量记录，不中断）----
    skipped_station = 0        # 站名无效被跳过的行
    nonnumeric_fixed = 0       # 空/非数值字段按0处理计数
    negative_rows = 0          # 负金额行
    unmatched_stations = set() # 未挂到维度的站名

    rows = []
    for _, r in df.iterrows():
        raw = r[station_col]
        station = clean_station_name(str(raw).strip()) if pd.notna(raw) else ""
        if not station or station == "nan":
            skipped_station += 1
            continue
        row = {"report_date": report_date, "station_name": station}
        for std_field, src_col in mapping.items():
            row[std_field] = r[src_col] if pd.notna(r[src_col]) else None
        rows.append(row)

    if not rows:
        _write_log(batch_id, ds.id, str(file_path), report_date, 0, "error", "无有效数据行（站名全为空）")
        return {"status": "error", "source_id": ds.id, "rows": 0,
                "message": "无有效数据行（站名全为空）"}

    std_df = pd.DataFrame(rows)
    for std_field in ds.fields:
        if std_field in std_df.columns:
            before_nan = std_df[std_field].isna().sum()
            std_df[std_field] = to_num(std_df[std_field])
            nonnumeric_fixed += int(before_nan)

    # 负金额告警（退货合法，仅记录不拒绝）
    if "amount" in std_df.columns:
        negative_rows = int((std_df["amount"] < 0).sum())
        if negative_rows:
            logger.warn(f"[v0.2导入] {ds.name}: {negative_rows} 行金额为负（可能是退货，请关注）")

    # ---- 3) 事务化快照入库：删除+插入原子提交，异常整体回滚 ----
    inserted = 0
    conn = db.get_conn()
    try:
        with conn:  # 事务块：正常 COMMIT，任何异常 ROLLBACK（库保持旧快照）
            direct, cleaned = _station_dim_map(conn)
            if ds.dedup:
                if ds.target_table == "fact_sales_detail":
                    conn.execute("DELETE FROM fact_sales_detail WHERE report_date=? AND period_tag=?",
                                 (report_date, ds.period_tag))
                else:
                    conn.execute(f"DELETE FROM {ds.target_table} WHERE report_date=?", (report_date,))

            for row in std_df.to_dict("records"):
                region, county = _lookup_dim(row["station_name"], direct, cleaned)
                if region is None:
                    unmatched_stations.add(row["station_name"])
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
    finally:
        conn.close()

    # ---- 4) 审计日志 + 汇总报告 ----
    warns = []
    if skipped_station:
        warns.append(f"跳过空站名 {skipped_station} 行")
    if nonnumeric_fixed:
        warns.append(f"{nonnumeric_fixed} 个空/非数值字段按0处理")
    if negative_rows:
        warns.append(f"{negative_rows} 行负金额")
    if unmatched_stations:
        warns.append(f"{len(unmatched_stations)} 个站名未匹配维度: "
                     f"{', '.join(sorted(unmatched_stations)[:5])}")

    _write_log(batch_id, ds.id, str(file_path), report_date, inserted,
               "ok" if not warns else "ok_warn", "; ".join(warns) or None)
    logger.info(f"[v0.2导入] {ds.name} -> {ds.target_table}: {inserted}行 "
                f"(报表日 {report_date}, 批次 {batch_id})" +
                (f" | {'; '.join(warns)}" if warns else ""))

    return {"status": "ok", "source_id": ds.id, "rows": inserted,
            "message": f"{ds.name}: {inserted} 行已入库" +
                       (f"（{'；'.join(warns)}）" if warns else ""),
            "batch_id": batch_id, "warnings": warns}


def ingest_file(file_path, report_date=None, batch_id=None, source_id=None):
    """导入单个 Excel 文件到数据库（含结构校验与锁重试）。

    参数：
        file_path:   文件路径
        report_date: 数据所属报表日（默认今天；补录历史时指定）
        batch_id:    批次号（多文件一次上传共用）
        source_id:   显式指定数据源（缺省按文件名识别）
    """
    report_date = report_date or date.today().isoformat()
    batch_id = batch_id or f"batch_{uuid.uuid4().hex[:12]}"

    fname = file_path.name if hasattr(file_path, "name") else str(file_path)
    ds = get_source(source_id) if source_id else identify_file(fname)
    if ds is None:
        _write_log(batch_id, "(unknown)", fname, report_date, 0, "error", "无法识别数据源")
        return {"status": "error", "source_id": None, "rows": 0,
                "message": f"无法识别数据源: {fname}"}

    # 锁竞争（可重试错误）→ 指数退避整体重跑；其他错误直接抛出由上层分类
    return db.run_with_retry(lambda: _ingest_once(ds, file_path, report_date, batch_id))


def ingest_files(file_paths, report_date=None, batch_id=None):
    """多文件导入（一次上传的完整批次）"""
    batch_id = batch_id or f"batch_{uuid.uuid4().hex[:12]}"
    results = []
    for fp in file_paths:
        try:
            results.append(ingest_file(fp, report_date=report_date, batch_id=batch_id))
        except Exception as e:
            # 致命/未知错误：记录并继续后续文件（方案第13节：致命错误告警不中断批次）
            logger.error(f"[v0.2导入] {fp} 导入异常: {e}")
            results.append({"status": "error", "source_id": None, "rows": 0,
                            "message": f"{fp}: {e}"})
    ok = [r for r in results if r["status"] == "ok"]
    return {"batch_id": batch_id, "total": len(results), "ok": len(ok),
            "results": results}


# ===== 查询接口（P2 计算层的数据入口，也可用于界面校验） =====

def query_sales(report_date, period_tag):
    """查询某报表日某期间的销售明细（自动带出维度）"""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM fact_sales_detail WHERE report_date=? AND period_tag=?",
            (report_date, period_tag)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_sales_summary(report_date, period_tag, by="county"):
    """按县区/片区汇总（快速校验导入正确性）"""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            f"""SELECT {by} AS grp, COUNT(DISTINCT station_name) AS n_stations,
                       ROUND(SUM(amount),2) AS total_amount,
                       ROUND(SUM(profit),2) AS total_profit
                FROM fact_sales_detail
                WHERE report_date=? AND period_tag=? AND {by} IS NOT NULL
                GROUP BY {by} ORDER BY total_amount DESC""",
            (report_date, period_tag)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
