# -*- coding: utf-8 -*-
"""
v0.2 服务编排层：上传导入 → 计算管道 → 输出渲染 的完整流程

流程设计（依据《数据逻辑》文档）：
  上传6张导出表 → 计算全部完成 → 展示预览并询问是否手动调整
  →（手动调整整月保留，自动调整=养车卡每次覆盖）→ 输出 xlsx + PNG
"""
from datetime import date

from store import logger, OUTPUT_DIR
from v02 import db, dims
from v02.ingest import ingest_files
from v02.pipeline import run_pipeline
from v02.render import render_all


def ensure_db():
    """启动时初始化/升级数据库 + 配置校验"""
    info = db.init_db()
    errs = db.validate_datasource_config()
    if errs:
        logger.warn(f"[v0.2] 数据源配置校验问题: {errs}")
    return {"db": info, "config_errors": errs}


def process_daily(file_paths, report_date=None, progress_cb=None, render=True):
    """完整处理：导入6表 → 算管道 → 渲染输出

    file_paths:  上传文件路径列表（空列表 = 仅用库内当日数据重算，如调整后重算）
    report_date: 报表日（默认今天）
    progress_cb(step, total, message)：进度回调
    返回 {status, ingest, result, outputs, message}
    """
    report_date = report_date or date.today().isoformat()
    total = 9 if file_paths else 3

    def prog(step, msg):
        if progress_cb:
            progress_cb({"step": step, "total": total, "progress": int(step / total * 100),
                         "message": msg, "status": "processing"})

    # ---- 1) 导入（逐文件进度） ----
    ingest_res = None
    if file_paths:
        from v02.ingest import ingest_file
        import uuid
        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        results = []
        failed = []
        for idx, fp in enumerate(file_paths, 1):
            from pathlib import Path as _P
            prog(idx - 1, f"正在导入第 {idx}/{len(file_paths)} 个文件：{_P(fp).name}")
            try:
                r = ingest_file(fp, report_date=report_date, batch_id=batch_id)
            except Exception as e:
                logger.error(f"[v0.2流程] {fp} 导入异常: {e}")
                r = {"status": "error", "source_id": None, "rows": 0, "message": f"{fp}: {e}"}
            results.append(r)
            if r["status"] != "ok":
                failed.append(r)
        ingest_res = {"batch_id": batch_id, "total": len(results),
                      "ok": len([r for r in results if r["status"] == "ok"]),
                      "results": results}
        if failed:
            msgs = "; ".join(f"{r.get('source_id')}: {r.get('message')}" for r in failed)
            logger.error(f"[v0.2流程] 导入未全部成功({len(results) - len(failed)}/{len(file_paths)}): {msgs}")
            return {"status": "error", "stage": "ingest",
                    "ingest": ingest_res, "message": f"导入未全部成功: {msgs}"}
        warns = [w for r in results for w in (r.get("warnings") or [])]
        if warns:
            logger.warn("[v0.2流程] 导入告警: " + "；".join(warns[:6]))

    # ---- 2) 计算管道 ----
    step0 = 6 if file_paths else 0
    prog(step0 + 1, "正在计算站级附表与县区通报...")
    result = run_pipeline(report_date)
    prog(step0 + 2, "计算完成")

    # ---- 3) 渲染输出 ----
    outputs = None
    if render:
        prog(step0 + 3, "正在生成 xlsx 与通报图片...")
        outputs = render_all(result, OUTPUT_DIR)
        prog(total, "输出完成")

    return {"status": "success", "ingest": ingest_res, "result": result,
            "outputs": outputs, "report_date": report_date,
            "message": "处理完成"}


def recompute_after_adjustment(report_date=None):
    """手动调整后重算（库内当日数据，秒级）并重新渲染"""
    report_date = report_date or date.today().isoformat()
    result = run_pipeline(report_date)
    outputs = render_all(result, OUTPUT_DIR)
    return {"status": "success", "result": result, "outputs": outputs,
            "report_date": report_date}


# ===== 预览数据结构（供前端渲染，键名与旧版兼容） =====

def preview_payload(result, outputs):
    """把管道结果转为前端预览结构（excl_hebi 5行版 + 排名 + 附表摘要）"""
    rows = result["tongbao"]["excl_hebi"]["rows"]
    ranking = result["tongbao"]["excl_hebi"]["ranking"]

    def fmt(r):
        return {
            "序号": "合计" if r["name"] == "合计" else None,  # 占位，前端按行渲染
            "单位": r["name"],
            "日均吨油": r["C"], "门零吨油销售额": r["D"], "门零销售": r["E"],
            "基础品类目标": r["G"], "基础品类完成含非非": r["H"],
            "基础品类完成剔除非非": r["I"], "基础品类完成率": r["J"],
            "同期": r["K"], "增减量": r["L"], "增幅": r["M"],
            "毛利目标": r["O"], "毛利完成含非非": r["P"],
            "毛利完成剔除非非": r["Q"], "毛利完成率": r["R"], "毛利率": r["S"],
            "名次": None, "综合完成率": r["V"],
            "_排名块": [{"名次": x["rank"], "单位": x["unit"], "完成率": x["rate"]}
                       for x in ranking],
            "_累月完成率": r["AA"],
        }

    # 序号：合计行无序号，县区行 1..n
    # 排名块（与日报 T/U/V 一致）：县区行 i 显示第 i 名的单位与完成率
    rank_only = [x for x in ranking if x["rank"] is not None]
    unranked = [x for x in ranking if x["rank"] is None]
    block = list(rank_only) + list(unranked)

    out_rows = []
    for i, r in enumerate(rows):
        d = fmt(r)
        if r["name"] == "合计":
            d["序号"] = "合计"
            d["名次"] = "合计"
            d["排名单位"] = ""
            d["排名完成率"] = r["V"]
        else:
            d["序号"] = i
            b = block[i - 1] if 0 < i <= len(block) else None
            d["名次"] = b["rank"] if b else "-"
            d["排名单位"] = b["unit"] if b else ""
            d["排名完成率"] = b["rate"] if b else None
        out_rows.append(d)

    fuhe_rows = []
    for s in result["station_rows"]:
        fuhe_rows.append([
            s["seq"], s["station"], round(s["sales"], 2), round(s["adj_sales"], 2),
            round(s["sales_after"], 2), round(s["adj_profit"], 2),
            round(s["profit_after"], 2), round(s["adj_retail"], 2),
            s["county"], round(s["per_ton_oil"], 2) if s["per_ton_oil"] is not None else None,
        ])

    return {
        "tongbao_rows": out_rows,
        "ranking": [{"名次": x["rank"], "单位": x["unit"], "完成率": x["rate"]}
                    for x in ranking],
        "fuhe": fuhe_rows,
        "report_date": result["report_date"],
        "report_day": result["report_day"],
        "month_days": result["month_days"],
        "time_progress": result["time_progress"],
        "outputs": outputs,
        "stations": len(result["station_rows"]),
    }
