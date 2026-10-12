# -*- coding: utf-8 -*-
"""
Flask 后端服务器 - 提供 API 路由（v0.2：SQLite 数据中心架构）

流程（依据《数据逻辑》文档）：
  上传6张导出表 → 计算（含养车卡自动调整）→ 预览并询问手动调整
  → 手动调整（整月保留，下月自动失效）→ 输出 xlsx（通报两版+附表）+ PNG
"""
import os
import sys
import json
import threading
from datetime import date
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory

# 确保项目根目录在 path 中
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from store import (logger, load_config, save_config, get_today_str, get_now_str,
                   UPLOADS_DIR, OUTPUT_DIR, CACHE_DIR, LOGS_DIR, TEMPLATES_DIR, DATA_DIR)
from v02 import db, dims
from v02 import service
from v02.dims import ADJ_TYPES

app = Flask(__name__, static_folder=str(BASE_DIR / "frontend"), static_url_path="")

# 处理状态与最近一次计算结果（内存缓存，落库 result_tongbao 作持久层）
processing_status = {"daily_report": {"status": "idle", "progress": 0, "message": "", "steps": []}}
last_result = {"data": None}
process_lock = threading.Lock()

# 启动钩子：初始化/升级数据库
_service_init = None


def ensure_ready():
    global _service_init
    if _service_init is None:
        _service_init = service.ensure_db()
        logger.info(f"[v0.2启动] 数据库就绪: {_service_init['db']}")
    return _service_init


# ===== 静态文件 =====
@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR / "frontend"), "index.html")


@app.route("/favicon.ico")
def favicon():
    icon = BASE_DIR / "app.ico"
    if icon.exists():
        return send_file(str(icon), mimetype="image/x-icon")
    return "", 404


# ===== API: 应用信息 =====
@app.route("/api/app/info")
def app_info():
    ensure_ready()
    version_file = BASE_DIR / "version.json"
    with open(version_file, "r", encoding="utf-8") as f:
        version_info = json.load(f)
    config = load_config()
    return jsonify({
        "name": version_info["name"],
        "version": version_info["version"],
        "reports": version_info["reports"],
        "report_date": get_today_str(),
        "last_run": config.get("last_run"),
        "settings": config.get("settings", {})
    })


# ===== API: 报表入口列表 =====
@app.route("/api/reports/list")
def reports_list():
    version_file = BASE_DIR / "version.json"
    with open(version_file, "r", encoding="utf-8") as f:
        version_info = json.load(f)
    return jsonify({"reports": version_info["reports"]})


# ===== API: 非油日报 - 上传（逐文件，兼容旧接口） =====
FILE_NAME_KEYWORDS = {
    "dangqi_all": ["当期全", "当期全部"],
    "tongqi_all": ["同期全", "同期全部"],
    "dangqi_ling": ["当期零", "当期零售"],
    "crm": ["CRM", "crm"],
    "dianzi_quan": ["电子券", "非油券"],
    "yangche_ka": ["养车卡", "养车"],
}
UPLOAD_FILE_NAMES = {
    "dangqi_all": "当期全部大类销售明细", "tongqi_all": "同期全部大类销售明细",
    "dangqi_ling": "当期零售明细", "crm": "CRM用券明细",
    "dianzi_quan": "电子券核销明细", "yangche_ka": "养车卡销售明细",
}


def identify_file_key(filename):
    name = str(filename)
    for key, keywords in FILE_NAME_KEYWORDS.items():
        for kw in keywords:
            if kw in name:
                return key
    return None


@app.route("/api/daily-report/upload", methods=["POST"])
def upload_files():
    """上传6张导出表（指定字段名模式）"""
    session_id = f"session_{get_today_str()}_{int(threading.get_ident())}"
    session_dir = UPLOADS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    uploaded, errors = {}, []
    for key, expected_name in UPLOAD_FILE_NAMES.items():
        if key in request.files:
            f = request.files[key]
            save_path = session_dir / f.filename
            f.save(str(save_path))
            uploaded[key] = str(save_path)
            logger.info(f"上传 {expected_name}: {f.filename}")
        else:
            errors.append({"key": key, "name": expected_name, "error": "未上传"})
    _save_session(session_id, {"session_id": session_id, "files": uploaded, "time": get_now_str()})
    return jsonify({
        "status": "success" if len(uploaded) == 6 else "partial",
        "session_id": session_id,
        "uploaded": {k: Path(v).name for k, v in uploaded.items()},
        "errors": errors,
        "message": f"已上传 {len(uploaded)}/6 个文件"
    })


@app.route("/api/daily-report/upload-multi", methods=["POST"])
def upload_multi_files():
    """多文件上传，自动识别文件类型（一次选择6个文件）"""
    session_id = f"session_{get_today_str()}_{int(threading.get_ident())}"
    session_dir = UPLOADS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    files = request.files.getlist("files")
    if not files:
        return jsonify({"status": "error", "message": "未收到文件"}), 400
    uploaded, matched, unmatched = {}, {}, []
    for f in files:
        fname = f.filename
        key = identify_file_key(fname)
        if key:
            save_path = session_dir / fname
            f.save(str(save_path))
            uploaded[key] = str(save_path)
            matched[key] = fname
            logger.info(f"自动识别 {fname} -> {key} ({UPLOAD_FILE_NAMES.get(key, '?')})")
        else:
            unmatched.append(fname)
            logger.warn(f"无法识别文件类型: {fname}")
    _save_session(session_id, {"session_id": session_id, "files": uploaded,
                              "matched": matched, "unmatched": unmatched, "time": get_now_str()})
    return jsonify({
        "status": "success" if len(matched) == 6 else "partial",
        "session_id": session_id,
        "uploaded": {k: Path(v).name for k, v in uploaded.items()},
        "matched": matched, "unmatched": unmatched,
        "message": f"已识别 {len(matched)}/6 个文件"
    })


def _save_session(session_id, info):
    session_file = CACHE_DIR / f"{session_id}.json"
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)


@app.route("/api/daily-report/uploads/<session_id>")
def get_uploads(session_id):
    session_file = CACHE_DIR / f"{session_id}.json"
    if session_file.exists():
        with open(session_file, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({"status": "error", "message": "会话不存在"}), 404


# ===== API: 非油日报 - 执行处理（导入+计算+渲染） =====
@app.route("/api/daily-report/process", methods=["POST"])
def process_report():
    """执行日报处理（后台线程）：导入6表 → 计算管道 → 渲染输出"""
    ensure_ready()
    data = request.json or {}
    session_id = data.get("session_id")
    report_date = data.get("report_date") or get_today_str()

    if not session_id:
        return jsonify({"status": "error", "message": "缺少 session_id"}), 400
    session_file = CACHE_DIR / f"{session_id}.json"
    if not session_file.exists():
        return jsonify({"status": "error", "message": "会话不存在，请先上传文件"}), 400
    with open(session_file, "r", encoding="utf-8") as f:
        session_info = json.load(f)
    file_paths = list(session_info.get("files", {}).values())
    if not file_paths:
        return jsonify({"status": "error", "message": "会话无文件，请重新上传"}), 400

    def progress_cb(info):
        processing_status["daily_report"] = {
            "status": "processing",
            "progress": min(info["progress"], 99),
            "message": info["message"],
            "step": info["step"],
            "total": info["total"],
            "time": get_now_str()
        }

    def run_process():
        try:
            processing_status["daily_report"] = {"status": "processing", "progress": 0,
                "message": "开始处理...", "step": 0, "total": 9, "time": get_now_str()}
            logger.start_session("daily_report")
            res = service.process_daily(file_paths, report_date=report_date,
                                        progress_cb=progress_cb)
            if res["status"] == "success":
                last_result["data"] = res
                config = load_config()
                config["last_run"] = get_now_str()
                config["report_date"] = report_date
                save_config(config)
            processing_status["daily_report"] = {
                "status": "done" if res["status"] == "success" else "error",
                "progress": 100,
                "message": res.get("message", "处理完成"),
                "result": {"status": res["status"], "outputs": res.get("outputs"),
                           "report_date": report_date,
                           "ingest": [{"source": r.get("source_id"), "rows": r.get("rows"),
                                       "status": r.get("status"), "warnings": r.get("warnings")}
                                      for r in (res.get("ingest") or {}).get("results", [])]},
                "time": get_now_str()
            }
        except Exception as e:
            logger.error(f"处理异常: {e}")
            processing_status["daily_report"] = {
                "status": "error", "progress": 100,
                "message": f"处理异常: {e}", "time": get_now_str()
            }

    thread = threading.Thread(target=run_process, daemon=True)
    thread.start()
    return jsonify({"status": "started", "session_id": session_id, "message": "处理已启动"})


@app.route("/api/daily-report/status")
def process_status():
    return jsonify(processing_status.get("daily_report", {"status": "idle"}))


# ===== API: 非油日报 - 预览（来自最近一次计算结果） =====
@app.route("/api/daily-report/preview")
def preview_data():
    res = last_result["data"]
    if res is None:
        # 尝试从库中恢复当天结果（程序重启后仍可预览）
        rd = request.args.get("report_date") or get_today_str()
        conn = db.get_conn()
        try:
            row = conn.execute("SELECT rows_json FROM result_tongbao WHERE report_date=?",
                               (rd,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return jsonify({"status": "error", "message": "暂无计算结果，请先执行处理"})
        res = {"result": json.loads(row["rows_json"]), "outputs": None, "report_date": rd}
    payload = service.preview_payload(res["result"], res.get("outputs"))
    payload["status"] = "success"
    # 输出文件列表（渲染可能发生在更早的进程中）
    if not payload.get("outputs"):
        payload["outputs"] = None
    pngs = sorted(OUTPUT_DIR.glob(f"每日通报{payload['report_date']}*.png"),
                  key=lambda p: p.stat().st_mtime)
    payload["image_url"] = f"/api/serve/{pngs[0].name}" if pngs else None
    payload["image_url_hebi"] = f"/api/serve/{pngs[1].name}" if len(pngs) > 1 else None
    return jsonify(payload)


# ===== API: 手动调整（月度保留，库存储） =====
@app.route("/api/daily-report/adjustments", methods=["GET"])
def list_adjustments():
    ensure_ready()
    ym = request.args.get("month") or get_today_str()[:7]
    rows = dims.get_month_adjustments(ym)
    return jsonify({"month": ym, "adjustments": rows,
                    "types": [{"id": t, "label": _adj_label(t)} for t in ADJ_TYPES]})


@app.route("/api/daily-report/adjustments", methods=["POST"])
def add_adjustment():
    ensure_ready()
    data = request.json or {}
    station = (data.get("station") or "").strip()
    adj_type = data.get("type") or data.get("adj_type")
    value = data.get("value")
    reason = data.get("reason", "")
    report_date = data.get("report_date") or get_today_str()
    if not station or adj_type not in ADJ_TYPES:
        return jsonify({"status": "error", "message": f"参数错误（station/type 必填，type ∈ {ADJ_TYPES}）"}), 400
    try:
        value = float(value)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "value 必须为数字"}), 400
    dims.add_adjustment(report_date, station, adj_type, value, reason)
    # 调整后立即重算 + 重渲染（秒级，同步返回新结果）
    res = service.recompute_after_adjustment(report_date)
    last_result["data"] = res
    payload = service.preview_payload(res["result"], res["outputs"])
    payload["status"] = "success"
    payload["message"] = f"已添加调整并重算：{station} {_adj_label(adj_type)} {value}"
    return jsonify(payload)


@app.route("/api/daily-report/adjustments/<int:adj_id>", methods=["DELETE"])
def delete_adjustment(adj_id):
    ensure_ready()
    dims.delete_adjustment(adj_id)
    rd = request.args.get("report_date") or get_today_str()
    res = service.recompute_after_adjustment(rd)
    last_result["data"] = res
    payload = service.preview_payload(res["result"], res["outputs"])
    payload["status"] = "success"
    payload["message"] = "已删除调整并重算"
    return jsonify(payload)


def _adj_label(t):
    return {"sales_add": "销售增加", "sales_sub": "销售减少",
            "profit_add": "毛利增加", "profit_sub": "毛利减少",
            "retail_add": "零售增加", "retail_sub": "零售减少"}.get(t, t)


# ===== API: 下载/打开输出文件 =====
@app.route("/api/download/<path:filename>")
def download_file(filename):
    file_path = OUTPUT_DIR / filename
    if file_path.exists():
        return send_file(str(file_path), as_attachment=True)
    return jsonify({"status": "error", "message": "文件不存在"}), 404


@app.route("/api/serve/<path:filename>")
def serve_file(filename):
    file_path = OUTPUT_DIR / filename
    if file_path.exists():
        return send_file(str(file_path), as_attachment=False)
    return jsonify({"status": "error", "message": "文件不存在"}), 404


@app.route("/api/open/<path:filename>", methods=["POST"])
def open_file(filename):
    import subprocess, platform
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        return jsonify({"status": "error", "message": "文件不存在"}), 404
    try:
        if platform.system() == "Windows":
            os.startfile(str(file_path))
        else:
            subprocess.call(["open" if platform.system() == "Darwin" else "xdg-open", str(file_path)])
        return jsonify({"status": "success", "message": "已打开"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/outputs/list")
def list_outputs():
    files = []
    for f in sorted(OUTPUT_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
        files.append({"name": f.name, "size": f.stat().st_size,
                      "time": f.stat().st_mtime, "path": str(f)})
    return jsonify({"files": files})


# ===== API: 日志 =====
@app.route("/api/logs/recent")
def recent_logs():
    n = request.args.get("n", 50, type=int)
    return jsonify({"logs": logger.get_recent_logs(n)})


@app.route("/api/logs/list")
def list_log_files():
    files = []
    for f in sorted(LOGS_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
        files.append({"name": f.name, "size": f.stat().st_size, "time": f.stat().st_mtime})
    return jsonify({"files": files})


# ===== API: 维护 - 站级轻油销量（SQLite 维度） =====
@app.route("/api/maintenance/light-oil", methods=["GET", "POST"])
def maintenance_light_oil():
    ensure_ready()
    ym = (request.values.get("year_month") if request.values.get("year_month")
          else get_today_str()[:7])
    if request.method == "GET":
        conn = db.get_conn()
        try:
            rows = conn.execute("SELECT station_name, tons FROM dim_light_oil_sales "
                                "WHERE year_month=?", (ym,)).fetchall()
        finally:
            conn.close()
        return jsonify({"year_month": ym,
                        "light_oil_sales": {r["station_name"]: r["tons"] for r in rows}})
    data = request.json or {}
    station_sales = data.get("station_sales", {})
    conn = db.get_conn()
    try:
        with conn:
            for st, tons in station_sales.items():
                conn.execute(
                    """INSERT INTO dim_light_oil_sales (station_name, year_month, tons)
                       VALUES (?,?,?) ON CONFLICT(station_name, year_month) DO UPDATE SET
                       tons=excluded.tons, updated_at=datetime('now','localtime')""",
                    (st, ym, float(tons or 0)))
    finally:
        conn.close()
    logger.info(f"[v0.2维护] 站级轻油 {ym} 更新 {len(station_sales)} 站")
    return jsonify({"status": "success", "updated": len(station_sales), "year_month": ym})


# ===== API: 维护 - 县区月轻油（通报C列口径） =====
@app.route("/api/maintenance/county-fuel", methods=["GET", "POST"])
def maintenance_county_fuel():
    ensure_ready()
    ym = (request.values.get("year_month") if request.values.get("year_month")
          else get_today_str()[:7])
    if request.method == "GET":
        return jsonify({"year_month": ym, "county_fuel": dims.get_county_fuel_sales(ym)})
    data = request.json or {}
    rows = data.get("rows", [])
    if not rows:
        return jsonify({"status": "error", "message": "缺少 rows"}), 400
    dims.upsert_county_fuel_sales(ym, rows)
    return jsonify({"status": "success", "updated": len(rows), "year_month": ym})


# ===== API: 维护 - 月度目标 =====
@app.route("/api/maintenance/targets", methods=["GET", "POST"])
def maintenance_targets():
    ensure_ready()
    ym = (request.values.get("year_month") if request.values.get("year_month")
          else get_today_str()[:7])
    if request.method == "GET":
        return jsonify({"year_month": ym, "monthly_targets": dims.get_monthly_target(ym)})
    data = request.json or {}
    rows = []
    for county, t in (data.get("targets") or {}).items():
        rows.append((ym, county, float(t.get("sales_target") or 0), float(t.get("profit_target") or 0)))
    conn = db.get_conn()
    try:
        with conn:
            for ym_, county, s, p in rows:
                conn.execute(
                    """INSERT INTO dim_monthly_target (year_month, county, sales_target, profit_target)
                       VALUES (?,?,?,?) ON CONFLICT(year_month, county) DO UPDATE SET
                       sales_target=excluded.sales_target, profit_target=excluded.profit_target,
                       updated_at=datetime('now','localtime')""",
                    (ym_, county, s, p))
    finally:
        conn.close()
    logger.info(f"[v0.2维护] 月度目标 {ym} 更新 {len(rows)} 县区")
    return jsonify({"status": "success", "updated": len(rows), "year_month": ym})


# ===== API: 维护 - 站点片区映射（调整界面的二级下拉） =====
@app.route("/api/maintenance/station-regions", methods=["GET"])
def maintenance_station_regions():
    ensure_ready()
    stations = dims.get_station_dim()
    return jsonify({"station_regions": {s[0]: s[2] for s in stations}})


# ===== API: 维护 - 站点代码表导入（站名/县区/部门名/标准编码） =====
@app.route("/api/maintenance/import-station-codes", methods=["POST"])
def maintenance_import_station_codes():
    ensure_ready()
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "缺少文件"}), 400
    f = request.files["file"]
    save_path = UPLOADS_DIR / f"station_codes_{get_today_str()}.xlsx"
    f.save(str(save_path))
    res = dims.import_station_codes(save_path)
    return jsonify(res)


# ===== API: 维护 - 券匹配表导入（省公司参考表） =====
@app.route("/api/maintenance/import-quan-match", methods=["POST"])
def maintenance_import_quan_match():
    ensure_ready()
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "缺少文件"}), 400
    f = request.files["file"]
    save_path = UPLOADS_DIR / f"quan_match_{get_today_str()}.xlsx"
    f.save(str(save_path))
    res = dims.import_quan_match(save_path)
    return jsonify(res)


@app.route("/api/maintenance/quan-coefficients", methods=["GET"])
def maintenance_quan_coefficients():
    ensure_ready()
    conn = db.get_conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM dim_quan_coefficient").fetchone()[0]
        rows = conn.execute("SELECT rule_key, non_oil, weiqi FROM dim_quan_coefficient "
                            "ORDER BY rule_key").fetchall()
    finally:
        conn.close()
    return jsonify({"count": n,
                    "quan_coefficients": {r["rule_key"]: {"non_oil": r["non_oil"], "weiqi": r["weiqi"]}
                                          for r in rows}})


# ===== API: 维护 - 累月数据（1-12月目标/完成，基础品类+毛利） =====
@app.route("/api/maintenance/monthly-cumulative", methods=["GET", "POST"])
def maintenance_monthly_cumulative():
    ensure_ready()
    ym = (request.values.get("year_month") if request.values.get("year_month")
          else get_today_str()[:7])
    if request.method == "GET":
        data = dims.get_monthly_cumulative(ym)
        counties = dims.get_station_dim()
        county_list = []
        for _, _, c, _, _ in counties:
            if c not in county_list:
                county_list.append(c)
        return jsonify({"year_month": ym, "cumulative": data, "counties": county_list})
    data = request.json or {}
    rows = []
    for county, months in (data.get("cumulative") or {}).items():
        for m_no, v in (months or {}).items():
            rows.append({"county": county, "month_no": int(m_no),
                         "sales_target": v.get("sales_target", 0),
                         "sales_actual": v.get("sales_actual", 0),
                         "profit_target": v.get("profit_target", 0),
                         "profit_actual": v.get("profit_actual", 0)})
    if not rows:
        return jsonify({"status": "error", "message": "缺少 cumulative 数据"}), 400
    dims.upsert_monthly_cumulative(ym, rows)
    return jsonify({"status": "success", "updated": len(rows), "year_month": ym})


# ===== API: 维护 - 站点清单 =====
@app.route("/api/maintenance/stations", methods=["GET"])
def maintenance_stations():
    ensure_ready()
    stations = dims.get_station_dim()
    return jsonify({"stations": [{"name": s[0], "county": s[2], "dept": s[3],
                                 "standard_code": s[4]} for s in stations]})


# ===== API: 数据库概况 =====
@app.route("/api/maintenance/db-stats")
def maintenance_db_stats():
    ensure_ready()
    return jsonify(db.db_stats())


# ===== API: 版本信息 =====
@app.route("/api/version")
def version_info():
    version_file = BASE_DIR / "version.json"
    with open(version_file, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


def run_server(port=18080):
    """启动Flask服务器"""
    ensure_ready()
    print(f"非油报表助手后端启动: http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run_server()
