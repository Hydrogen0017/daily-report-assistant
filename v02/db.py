# -*- coding: utf-8 -*-
"""
v0.2 数据层：SQLite 统一数据模型
- 事实表：销售明细 / 手动调整 / 专项数据（CRM、电子券、养车卡）
- 维度表：站点映射 / 券系数 / 轻油销量 / 月度目标
- 结果表：通报快照（按报表日期存档，支持回溯与双跑比对）

设计原则：
- 所有表带 created_at 便于追溯
- 事实表以业务主键 upsert（同日重传覆盖）
- 维度表支持版本（轻油销量/月度目标按年月）
"""
import sqlite3
from pathlib import Path

from store import DATA_DIR

DB_PATH = DATA_DIR / "database.db"

SCHEMA = """
-- ===== 事实表（快照式导入：同日重传覆盖，见 ingest.py）=====
-- 销售明细（当期全/同期全/当期零 统一入库，行级）
CREATE TABLE IF NOT EXISTS fact_sales_detail (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date   TEXT NOT NULL,          -- 数据所属报表日（累计口径截止日）
    period_tag    TEXT NOT NULL,          -- current当期 / same_period同期 / retail零售
    station_name  TEXT NOT NULL,          -- 标准化站名
    region        TEXT,                   -- 片区（导入时从 dim_station 挂接）
    county        TEXT,                   -- 县区
    category      TEXT,                   -- 大类/品类
    qty           REAL DEFAULT 0,         -- 销售数量
    amount        REAL DEFAULT 0,         -- 含税销售金额
    profit        REAL DEFAULT 0,         -- 含税毛利金额
    created_at    TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_fsd_lookup ON fact_sales_detail(report_date, period_tag);
CREATE INDEX IF NOT EXISTS idx_fsd_station ON fact_sales_detail(station_name, report_date);

-- 手动调整记录（销售/毛利 调增调减）
CREATE TABLE IF NOT EXISTS fact_adjustment (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date   TEXT NOT NULL,
    station_name  TEXT NOT NULL,
    adj_type      TEXT NOT NULL,          -- sales_add/sales_sub/profit_add/profit_sub
    value         REAL NOT NULL,
    reason        TEXT,
    created_at    TEXT DEFAULT (datetime('now','localtime'))
);

-- CRM 用券明细（行级）
CREATE TABLE IF NOT EXISTS fact_crm (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date   TEXT NOT NULL,
    station_name  TEXT NOT NULL,
    rule_name     TEXT,                   -- 券规则名称
    category      TEXT,                   -- 大类
    qty           REAL DEFAULT 0,         -- 销售数量
    amount        REAL DEFAULT 0,         -- 订单销售金额（含券）
    quan_amount   REAL DEFAULT 0,         -- 拆分后用券金额
    pay_amount    REAL DEFAULT 0,         -- 拆分后实际支付（不含券）
    region        TEXT,
    county        TEXT,
    created_at    TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_crm_lookup ON fact_crm(report_date);

-- 电子券核销明细（行级）
CREATE TABLE IF NOT EXISTS fact_electron_quan (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date   TEXT NOT NULL,
    station_name  TEXT NOT NULL,          -- 用券站点名称
    rule_name     TEXT,                   -- 电子券规则名称
    quan_type     TEXT,                   -- 券类型
    quan_amount   REAL DEFAULT 0,         -- 拆分后商品用券金额
    sales_amount  REAL DEFAULT 0,         -- 订单优惠后销售金额
    profit        REAL DEFAULT 0,         -- 含税毛利额
    region        TEXT,
    county        TEXT,
    created_at    TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_quan_lookup ON fact_electron_quan(report_date);

-- 养车卡销售明细（行级）
CREATE TABLE IF NOT EXISTS fact_yangche_ka (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date   TEXT NOT NULL,
    station_name  TEXT NOT NULL,          -- 店铺名称
    category      TEXT,                   -- 一级类目
    product_name  TEXT,                   -- 商品名称
    qty           REAL DEFAULT 0,         -- 销售数量
    amount        REAL DEFAULT 0,         -- 商品销售金额
    region        TEXT,
    county        TEXT,
    created_at    TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_yck_lookup ON fact_yangche_ka(report_date);

-- ===== 维度表 =====
CREATE TABLE IF NOT EXISTS dim_station (
    station_name  TEXT PRIMARY KEY,       -- 标准化站名
    region        TEXT NOT NULL,          -- 片区
    county        TEXT NOT NULL,          -- 县区
    status        TEXT DEFAULT 'active',
    updated_at    TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS dim_quan_coefficient (
    rule_key      TEXT PRIMARY KEY,       -- 规则键（如 DJ-001753856162841）
    non_oil       REAL DEFAULT 0,         -- 非油系数
    weiqi         REAL DEFAULT 0,         -- 尾气处理液系数
    remark        TEXT,
    updated_at    TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS dim_light_oil_sales (
    station_name  TEXT NOT NULL,
    year_month    TEXT NOT NULL,          -- 2026-10
    tons          REAL NOT NULL,
    updated_at    TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (station_name, year_month)
);

CREATE TABLE IF NOT EXISTS dim_monthly_target (
    year_month    TEXT NOT NULL,          -- 2026-10
    county        TEXT NOT NULL,          -- 县区
    sales_target  REAL DEFAULT 0,         -- 万元
    profit_target REAL DEFAULT 0,         -- 万元
    updated_at    TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (year_month, county)
);

-- ===== 结果表 =====
-- 通报结果快照（JSON 存每行数据，支持任意列扩展与回溯）
CREATE TABLE IF NOT EXISTS result_tongbao (
    report_date   TEXT PRIMARY KEY,
    pipeline      TEXT DEFAULT 'v02',      -- 产生该结果的管道版本
    rows_json     TEXT NOT NULL,          -- 通报数据行（JSON 数组）
    summary_json  TEXT,                   -- 汇总口径信息
    created_at    TEXT DEFAULT (datetime('now','localtime'))
);

-- 导入批次记录（追溯每次上传）
CREATE TABLE IF NOT EXISTS ingest_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id      TEXT NOT NULL,          -- 本次上传批次
    source_id     TEXT NOT NULL,          -- 数据源 id
    file_name     TEXT NOT NULL,
    report_date   TEXT,                   -- 导入归属的报表日
    row_count     INTEGER DEFAULT 0,
    status        TEXT DEFAULT 'ok',      -- ok / partial / error
    message       TEXT,
    created_at    TEXT DEFAULT (datetime('now','localtime'))
);
"""


def get_conn():
    """获取数据库连接（建议 with 使用）"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化所有表（幂等）"""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    return str(DB_PATH)


def db_stats():
    """库概况（诊断/界面展示用）"""
    tables = ["fact_sales_detail", "fact_adjustment", "fact_crm",
              "fact_electron_quan", "fact_yangche_ka", "dim_station",
              "dim_quan_coefficient", "dim_light_oil_sales",
              "dim_monthly_target", "result_tongbao", "ingest_log"]
    out = {"db_path": str(DB_PATH), "exists": DB_PATH.exists()}
    if DB_PATH.exists():
        with get_conn() as conn:
            for t in tables:
                try:
                    out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                except sqlite3.OperationalError:
                    out[t] = None
        out["db_size_kb"] = round(DB_PATH.stat().st_size / 1024, 1)
    return out


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("初始化数据库:", init_db())
    for k, v in db_stats().items():
        print(f"  {k}: {v}")
