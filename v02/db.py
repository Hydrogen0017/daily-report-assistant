# -*- coding: utf-8 -*-
"""
v0.2 数据层：SQLite 统一数据模型（响应评审 R3/R5/R8/R9 补强版）

可靠性设计：
- WAL 模式 + busy_timeout=5000ms（评审 R8：并发写安全）
- 事务原子性：导入的删除+插入由调用方包在 with 事务中（评审 R3）
- 锁等待指数退避重试：run_with_retry（评审 R5）
- Schema 版本化迁移：PRAGMA user_version + MIGRATIONS 注册表（评审 R9）
"""
import sqlite3
import time

from store import DATA_DIR

DB_PATH = DATA_DIR / "database.db"

BUSY_TIMEOUT_MS = 5000
MAX_LOCK_RETRIES = 3


def get_conn():
    """获取数据库连接（建议 with 使用，with 块即事务：正常 COMMIT / 异常 ROLLBACK）"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return conn


def run_with_retry(fn, retries=MAX_LOCK_RETRIES, base_delay=0.2):
    """锁竞争指数退避重试（评审 R5：可重试错误处理）

    仅对 'database is locked' 类错误重试（可重试错误分类），
    其他 OperationalError 立即抛出（不可重试错误分类见方案第13节）。
    """
    for attempt in range(retries + 1):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() or attempt == retries:
                raise
            time.sleep(base_delay * (2 ** attempt))


# ===== Schema 版本化迁移机制（评审 R9）=====
# 迁移注册表：版本号 -> SQL 语句列表。
# 铁律：已发布版本的 SQL 禁止修改；后续表结构变更必须追加新版本。

MIGRATIONS = [
    (1, [
        # ===== 事实表（快照式导入：同日重传覆盖，见 ingest.py）=====
        """CREATE TABLE IF NOT EXISTS fact_sales_detail (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date   TEXT NOT NULL,
            period_tag    TEXT NOT NULL,
            station_name  TEXT NOT NULL,
            region        TEXT,
            county        TEXT,
            category      TEXT,
            qty           REAL DEFAULT 0,
            amount        REAL DEFAULT 0,
            profit        REAL DEFAULT 0,
            created_at    TEXT DEFAULT (datetime('now','localtime'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_fsd_lookup ON fact_sales_detail(report_date, period_tag)",
        "CREATE INDEX IF NOT EXISTS idx_fsd_station ON fact_sales_detail(station_name, report_date)",
        """CREATE TABLE IF NOT EXISTS fact_adjustment (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date   TEXT NOT NULL,
            station_name  TEXT NOT NULL,
            adj_type      TEXT NOT NULL,
            value         REAL NOT NULL,
            reason        TEXT,
            created_at    TEXT DEFAULT (datetime('now','localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS fact_crm (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date   TEXT NOT NULL,
            station_name  TEXT NOT NULL,
            rule_name     TEXT,
            category      TEXT,
            qty           REAL DEFAULT 0,
            amount        REAL DEFAULT 0,
            quan_amount   REAL DEFAULT 0,
            pay_amount    REAL DEFAULT 0,
            region        TEXT,
            county        TEXT,
            created_at    TEXT DEFAULT (datetime('now','localtime'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_crm_lookup ON fact_crm(report_date)",
        """CREATE TABLE IF NOT EXISTS fact_electron_quan (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date   TEXT NOT NULL,
            station_name  TEXT NOT NULL,
            rule_name     TEXT,
            quan_type     TEXT,
            quan_amount   REAL DEFAULT 0,
            sales_amount  REAL DEFAULT 0,
            profit        REAL DEFAULT 0,
            region        TEXT,
            county        TEXT,
            created_at    TEXT DEFAULT (datetime('now','localtime'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_quan_lookup ON fact_electron_quan(report_date)",
        """CREATE TABLE IF NOT EXISTS fact_yangche_ka (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date   TEXT NOT NULL,
            station_name  TEXT NOT NULL,
            category      TEXT,
            product_name  TEXT,
            qty           REAL DEFAULT 0,
            amount        REAL DEFAULT 0,
            region        TEXT,
            county        TEXT,
            created_at    TEXT DEFAULT (datetime('now','localtime'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_yck_lookup ON fact_yangche_ka(report_date)",
        # ===== 维度表 =====
        """CREATE TABLE IF NOT EXISTS dim_station (
            station_name  TEXT PRIMARY KEY,
            region        TEXT NOT NULL,
            county        TEXT NOT NULL,
            status        TEXT DEFAULT 'active',
            updated_at    TEXT DEFAULT (datetime('now','localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS dim_quan_coefficient (
            rule_key      TEXT PRIMARY KEY,
            non_oil       REAL DEFAULT 0,
            weiqi         REAL DEFAULT 0,
            remark        TEXT,
            updated_at    TEXT DEFAULT (datetime('now','localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS dim_light_oil_sales (
            station_name  TEXT NOT NULL,
            year_month    TEXT NOT NULL,
            tons          REAL NOT NULL,
            updated_at    TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (station_name, year_month)
        )""",
        """CREATE TABLE IF NOT EXISTS dim_monthly_target (
            year_month    TEXT NOT NULL,
            county        TEXT NOT NULL,
            sales_target  REAL DEFAULT 0,
            profit_target REAL DEFAULT 0,
            updated_at    TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (year_month, county)
        )""",
        # ===== 结果表 =====
        """CREATE TABLE IF NOT EXISTS result_tongbao (
            report_date   TEXT PRIMARY KEY,
            pipeline      TEXT DEFAULT 'v02',
            rows_json     TEXT NOT NULL,
            summary_json  TEXT,
            created_at    TEXT DEFAULT (datetime('now','localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS ingest_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id      TEXT NOT NULL,
            source_id     TEXT NOT NULL,
            file_name     TEXT NOT NULL,
            report_date   TEXT,
            row_count     INTEGER DEFAULT 0,
            status        TEXT DEFAULT 'ok',
            message       TEXT,
            created_at    TEXT DEFAULT (datetime('now','localtime'))
        )""",
    ]),
    # ===== v2（P2 计算管道）：列扩展 + 新维度表 =====
    # 口径依据（2026-10-11 日报公式逆向验证）：
    # - fact_crm.non_oil_ratio：CRM券 = 拆分后用券金额 × 非油分摊比例
    # - fact_electron_quan.rule_code：电子券按规则编码匹配券匹配表(考核剔非非+尾气劵)
    # - fact_sales_detail.product_name：洗车券 = 当期全"河南油非互动洗车券15元1张"×0.4
    # - fact_sales_detail.category_code：零售剔烟草按 编码|品类=20 过滤
    # - dim_station.dept_name/standard_code：养车卡"所属部门"、电子券站名别名、附表标准编码
    #   （来源：参考表/站点代码.xlsx Sheet1 站点名称/便利店名 + Sheet2 标准编码）
    # - dim_county_fuel_sales：通报C列县区月轻油（与站级轻油表口径不同，日报硬编码值）
    # - dim_monthly_cumulative：累月区（1-12月目标/完成，基础品类+毛利双指标）
    (2, [
        "ALTER TABLE fact_crm ADD COLUMN non_oil_ratio REAL DEFAULT 0",
        "ALTER TABLE fact_electron_quan ADD COLUMN rule_code TEXT",
        "ALTER TABLE fact_sales_detail ADD COLUMN product_name TEXT",
        "ALTER TABLE fact_sales_detail ADD COLUMN category_code TEXT",
        "ALTER TABLE dim_station ADD COLUMN dept_name TEXT",
        "ALTER TABLE dim_station ADD COLUMN standard_code TEXT",
        """CREATE TABLE IF NOT EXISTS dim_county_fuel_sales (
            year_month  TEXT NOT NULL,
            county      TEXT NOT NULL,
            tons        REAL NOT NULL,
            updated_at  TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (year_month, county)
        )""",
        """CREATE TABLE IF NOT EXISTS dim_monthly_cumulative (
            year_month   TEXT NOT NULL,
            county       TEXT NOT NULL,
            month_no     INTEGER NOT NULL,
            sales_target REAL DEFAULT 0,
            sales_actual REAL DEFAULT 0,
            profit_target REAL DEFAULT 0,
            profit_actual REAL DEFAULT 0,
            updated_at   TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (year_month, county, month_no)
        )""",
    ]),
]

TABLES = ["fact_sales_detail", "fact_adjustment", "fact_crm",
          "fact_electron_quan", "fact_yangche_ka", "dim_station",
          "dim_quan_coefficient", "dim_light_oil_sales",
          "dim_monthly_target", "result_tongbao", "ingest_log",
          "dim_county_fuel_sales", "dim_monthly_cumulative"]


def get_schema_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def init_db():
    """初始化/升级数据库（幂等）：按版本号应用未执行的迁移

    返回 {db_path, schema_version, applied}；applied=0 表示已最新。
    注意：库中已有 v1 结构但 user_version 为 0 的历史库（本轮之前创建），
    通过 IF NOT EXISTS 幂等升级到 v1，不破坏既有数据。
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        current = get_schema_version(conn)
        applied = 0
        for version, statements in MIGRATIONS:
            if version <= current:
                continue
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version={version}")
            applied += 1
    return {"db_path": str(DB_PATH), "schema_version": MIGRATIONS[-1][0],
            "applied": applied}


def validate_datasource_config():
    """配置校验启动钩子（评审 R4）：数据源注册表合法性检查

    在应用启动时发现配置错误（引用不存在的表/非法 period_tag/id重复），
    而非运行到一半才失败。
    """
    from v02.datasources import DATA_SOURCES
    valid_tables = set(TABLES)
    errors = []
    ids = set()
    for ds in DATA_SOURCES:
        if ds.id in ids:
            errors.append(f"数据源 id 重复: {ds.id}")
        ids.add(ds.id)
        if ds.target_table not in valid_tables:
            errors.append(f"{ds.id}: target_table 不存在 ({ds.target_table})")
        if not ds.file_keywords:
            errors.append(f"{ds.id}: file_keywords 为空")
        if not ds.station_col:
            errors.append(f"{ds.id}: station_col 为空")
        if ds.target_table == "fact_sales_detail" and \
                ds.period_tag not in ("current", "same_period", "retail"):
            errors.append(f"{ds.id}: period_tag 非法 ({ds.period_tag})")
    return errors


def db_stats():
    """库概况（诊断/界面展示用）"""
    out = {"db_path": str(DB_PATH), "exists": DB_PATH.exists()}
    if DB_PATH.exists():
        with get_conn() as conn:
            out["schema_version"] = get_schema_version(conn)
            for t in TABLES:
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
    errs = validate_datasource_config()
    print("配置校验:", "全部通过" if not errs else errs)
    for k, v in db_stats().items():
        print(f"  {k}: {v}")
