# -*- coding: utf-8 -*-
"""
v0.2 计算管道：SQLite 统一数据模型 → 站级附表 → 县区通报（两个版本）

全部口径经 2026-10-11 日报公式逆向验证（剔除非零差异项）：
- 调整后销售 = 销售 + (养车卡+手动增) - 手动减
- 扣券合计 = CRM券 + 剔除(0) + 洗车券 + 新零售电子券
  · CRM券 = Σ(拆分后用券金额 × 非油分摊比例)
  · 洗车券 = Σ(当期全"河南油非互动洗车券15元1张" 含税销售金额) × 0.4
  · 新零售电子券 = Σ(拆分后商品用券金额 × (考核剔非非 + 尾气劵))（按规则编码匹配）
- 销售券后 = 调整后销售 - 扣券合计；毛利卷后 = 调整后毛利 - 扣券合计（同额）
- 调整后零售 = 当期零(销售-烟草品类20) + 手动增 - 手动减
- 日均轻油 = 站级月轻油 / 当月天数；门零吨油 = 调整后零售 / (日均轻油 × 报表日)
- 通报：
  · C 日均吨油 = 县区月轻油(县区表口径) / 当月天数
  · E 门零销售 = 县区调整后零售 / 1e4（用户确认：不÷7）
  · D 门零吨油 = E×1e4 / (C × 报表日)
  · J = I/G；R = Q/O；S = Q/I；K=同期销售；L=I-K；M=L/K
  · V 综合完成率 = min(J,130%)×0.4 + R×0.5 + 累月含当期完成率×0.1
    累月含当期完成率 = (1-9月完成合计 + 当期完成I) / (1-9月目标合计)
  · AA 累月完成率 = (累月基础品类完成率 + 累月毛利完成率) / 2（均不含当期）
- 两个版本：excl_hebi 5行（合计不含鹤壁）；incl_hebi 6行（含鹤壁行，合计含鹤壁）
"""
import calendar
import json
from datetime import datetime

from store import logger
from v02 import db, dims
from v02.common import safe_float
from v02.dims import (COUNTIES, HEBI_COUNTY, TOBACCO_CATEGORY_CODE,
                      WASH_QUAN_KEYWORD, WASH_QUAN_RATIO)

# 通报行顺序
COUNTY_ORDER_5 = ["淇县", "浚县", "市区经营部", "商客"]                      # 5行版
COUNTY_ORDER_6 = ["淇县", "浚县", "市区经营部", "商客", HEBI_COUNTY]          # 6行版（鹤壁行在商客后，同加超欠进度表）
RANKED_COUNTIES = ["淇县", "浚县", "市区经营部"]                              # 参与排名的县区
# 排名块顺序：3县区按V降序 + 未排名县区（6行版鹤壁在商客前，同加超欠进度表）
UNRANKED_5 = ["商客"]
UNRANKED_6 = [HEBI_COUNTY, "商客"]


def _month_days(year_month):
    y, m = int(year_month[:4]), int(year_month[5:7])
    return calendar.monthrange(y, m)[1]


def _round2(x):
    return None if x is None else round(float(x), 2)


class Pipeline:
    """一次报表计算的完整上下文"""

    def __init__(self, report_date):
        self.report_date = report_date
        self.year_month = report_date[:7]
        self.report_day = int(report_date[8:10])       # 报表日 N（累计 1-N 日）
        self.month_days = _month_days(self.year_month)

    # ---------- 数据加载 ----------

    def load(self):
        rd, ym = self.report_date, self.year_month
        conn = db.get_conn()
        try:
            # 当期全：站级销售/毛利
            self.sales_map = dict(conn.execute(
                "SELECT station_name, SUM(amount) FROM fact_sales_detail "
                "WHERE report_date=? AND period_tag='current' GROUP BY station_name",
                (rd,)).fetchall())
            self.profit_map = dict(conn.execute(
                "SELECT station_name, SUM(profit) FROM fact_sales_detail "
                "WHERE report_date=? AND period_tag='current' GROUP BY station_name",
                (rd,)).fetchall())
            # 洗车券：当期全特定商品行
            self.wash_map = dict(conn.execute(
                "SELECT station_name, SUM(amount) FROM fact_sales_detail "
                "WHERE report_date=? AND period_tag='current' "
                "AND product_name LIKE ? GROUP BY station_name",
                (rd, f"%{WASH_QUAN_KEYWORD}%")).fetchall())
            # 当期零：零售总额 + 烟草金额
            self.retail_map = dict(conn.execute(
                "SELECT station_name, SUM(amount) FROM fact_sales_detail "
                "WHERE report_date=? AND period_tag='retail' GROUP BY station_name",
                (rd,)).fetchall())
            self.tobacco_map = dict(conn.execute(
                "SELECT station_name, SUM(amount) FROM fact_sales_detail "
                "WHERE report_date=? AND period_tag='retail' "
                "AND (category_code=? OR category=?) GROUP BY station_name",
                (rd, TOBACCO_CATEGORY_CODE, "烟草")).fetchall())
            # 同期全：站级同期销售
            self.tongqi_map = dict(conn.execute(
                "SELECT station_name, SUM(amount) FROM fact_sales_detail "
                "WHERE report_date=? AND period_tag='same_period' GROUP BY station_name",
                (rd,)).fetchall())
            # CRM：Σ(用券金额×非油比例)
            self.crm_map = dict(conn.execute(
                "SELECT station_name, SUM(quan_amount*non_oil_ratio) FROM fact_crm "
                "WHERE report_date=? GROUP BY station_name", (rd,)).fetchall())
            # 电子券：Σ(用券金额)（比例在管道内按规则编码匹配）
            self.ecoupon_raw = conn.execute(
                "SELECT station_name, rule_code, SUM(quan_amount) AS amt "
                "FROM fact_electron_quan WHERE report_date=? "
                "GROUP BY station_name, rule_code", (rd,)).fetchall()
            # 养车卡：自动调整（销售与毛利同额）
            self.yangche_map = dict(conn.execute(
                "SELECT station_name, SUM(amount) FROM fact_yangche_ka "
                "WHERE report_date=? GROUP BY station_name", (rd,)).fetchall())
        finally:
            conn.close()

        # 维度
        self.stations = dims.get_station_dim()          # [(name, region, county, dept, std_code)]
        self.light_oil = dims.get_light_oil_map(ym)     # 站级
        self.county_fuel = dims.get_county_fuel_sales(ym)   # 县区级（通报C列）
        self.targets = dims.get_monthly_target(ym)
        self.quan_coef = dims.get_quan_coefficient_map()
        self.cumulative = dims.get_monthly_cumulative(ym)
        self.adj_map = dims.station_adjustment_map(ym)  # {(station, type): value}

        # 电子券按规则编码计算剔除额
        self.ecoupon_map = {}
        unmatched_rules = set()
        for r in self.ecoupon_raw:
            code = (r["rule_code"] or "").strip()
            ratio = self.quan_coef.get(code)
            if ratio is None:
                if r["amt"]:
                    unmatched_rules.add(code)
                ratio = (0.0, 0.0)
            val = (r["amt"] or 0) * (ratio[0] + ratio[1])
            self.ecoupon_map[r["station_name"]] = self.ecoupon_map.get(r["station_name"], 0) + val
        if unmatched_rules:
            logger.warn(f"[v0.2管道] {len(unmatched_rules)} 个电子券规则编码未匹配券匹配表(按0比例)，"
                        f"如: {', '.join(sorted(unmatched_rules)[:3])}")

    # ---------- 站级计算（附表）----------

    def build_station_rows(self):
        rows = []
        for idx, (name, region, county, dept, std_code) in enumerate(self.stations, 1):
            adj = lambda t: safe_float(self.adj_map.get((name, t)))
            yangche = safe_float(self.yangche_map.get(name))
            sales = safe_float(self.sales_map.get(name))
            profit = safe_float(self.profit_map.get(name))
            crm = safe_float(self.crm_map.get(name))
            wash = safe_float(self.wash_map.get(name)) * WASH_QUAN_RATIO
            ecoupon = safe_float(self.ecoupon_map.get(name))
            quan_total = crm + wash + ecoupon           # 剔除列恒为 0
            adj_add = yangche + adj("sales_add")
            adj_sub = adj("sales_sub")
            adj_sales = sales + adj_add - adj_sub
            p_adj_add = yangche + adj("profit_add")
            p_adj_sub = adj("profit_sub")
            adj_profit = profit + p_adj_add - p_adj_sub
            retail_raw = safe_float(self.retail_map.get(name))
            tobacco = safe_float(self.tobacco_map.get(name))
            tobacco_retail = retail_raw - tobacco
            r_adj_add = adj("retail_add")
            r_adj_sub = adj("retail_sub")
            adj_retail = tobacco_retail + r_adj_add - r_adj_sub
            oil = safe_float(self.light_oil.get(name))
            avg_oil = oil / self.month_days if oil else 0
            per_ton = adj_retail / (avg_oil * self.report_day) if avg_oil else None
            rows.append({
                "seq": idx, "station": name, "standard_code": std_code,
                "sales": sales, "adj_add": adj_add, "adj_sub": adj_sub,
                "adj_sales": adj_sales,
                "crm": crm, "tic": 0, "wash": wash, "ecoupon": ecoupon,
                "quan_total": quan_total, "sales_after": adj_sales - quan_total,
                "profit": profit, "p_adj_add": p_adj_add, "p_adj_sub": p_adj_sub,
                "adj_profit": adj_profit, "profit_after": adj_profit - quan_total,
                "tobacco_retail": tobacco_retail,
                "r_adj_add": r_adj_add, "r_adj_sub": r_adj_sub,
                "adj_retail": adj_retail,
                "county": county, "light_oil": oil, "avg_oil": avg_oil,
                "per_ton_oil": per_ton,
            })
        self.station_rows = rows
        return rows

    # ---------- 县区聚合 ----------

    def _county_sums(self, county):
        rs = [r for r in self.station_rows if r["county"] == county]
        return {
            "n_stations": len(rs),
            "adj_sales": sum(r["adj_sales"] for r in rs),
            "sales_after": sum(r["sales_after"] for r in rs),
            "adj_profit": sum(r["adj_profit"] for r in rs),
            "profit_after": sum(r["profit_after"] for r in rs),
            "adj_retail": sum(r["adj_retail"] for r in rs),
            "tongqi": sum(safe_float(self.tongqi_map.get(r["station"])) for r in rs),
        }

    def build_county_data(self):
        self.county = {}
        for c in set(COUNTY_ORDER_6):
            self.county[c] = self._county_sums(c)
        # 县区月轻油（通报C列口径）
        for c in self.county:
            self.county[c]["county_fuel"] = safe_float(self.county_fuel.get(c))
            self.county[c]["avg_fuel"] = (self.county[c]["county_fuel"] / self.month_days
                                          if self.county[c]["county_fuel"] else None)
            t = self.targets.get(c, {})
            self.county[c]["sales_target"] = safe_float(t.get("sales_target"))
            self.county[c]["profit_target"] = safe_float(t.get("profit_target"))

    # ---------- 累月 ----------

    def _cum_series(self, county):
        """县区累月序列（1-12月）：目标/实际（基础品类+毛利）。缺月为 0。"""
        data = self.cumulative.get(county, {})
        s_t = [safe_float(data.get(m, {}).get("sales_target")) for m in range(1, 13)]
        s_a = [safe_float(data.get(m, {}).get("sales_actual")) for m in range(1, 13)]
        p_t = [safe_float(data.get(m, {}).get("profit_target")) for m in range(1, 13)]
        p_a = [safe_float(data.get(m, {}).get("profit_actual")) for m in range(1, 13)]
        return {"sales_target": s_t, "sales_actual": s_a,
                "profit_target": p_t, "profit_actual": p_a}

    def build_cumulative(self, included_counties):
        """合计累月 = 各县区之和（目标=有目标县区之和；实际=included 县区之和）"""
        cum = {c: self._cum_series(c) for c in set(COUNTY_ORDER_6)}
        total = {k: [0.0] * 12 for k in
                 ("sales_target", "sales_actual", "profit_target", "profit_actual")}
        for c in set(COUNTY_ORDER_6):
            for k in total:
                for m in range(12):
                    if k.endswith("target"):
                        total[k][m] += cum[c][k][m]
                    elif c in included_counties:
                        total[k][m] += cum[c][k][m]
        cum["合计"] = total
        self.cumulative_series = cum
        return cum

    # ---------- 通报构建 ----------

    def _tongbao_row(self, name, sums, cum, is_total=False, included=None):
        """构建一个通报行。is_total=True 时合计行 G/O/C 取三县区之和。"""
        G = sums["sales_target"] if not is_total else \
            sum(safe_float(self.county[c]["sales_target"]) for c in RANKED_COUNTIES)
        O = sums["profit_target"] if not is_total else \
            sum(safe_float(self.county[c]["profit_target"]) for c in RANKED_COUNTIES)
        C = sums["avg_fuel"] if not is_total else \
            (sum(safe_float(self.county[c]["avg_fuel"] or 0) for c in RANKED_COUNTIES) or None)
        H = sums["adj_sales"] / 1e4
        I = sums["sales_after"] / 1e4
        P = sums["adj_profit"] / 1e4
        Q = sums["profit_after"] / 1e4
        E = sums["adj_retail"] / 1e4
        D = E * 1e4 / (C * self.report_day) if C else None
        J = I / G if G else None
        K = sums["tongqi"] / 1e4
        L = I - K
        M = (L / K) if K else None
        R = Q / O if O else None
        S = Q / I if I else None
        # 累月：已完成月份（本月之前）目标/完成合计
        # 依据日报公式：AL(合计目标)=AB+..+AJ 即 1-9月目标列之和；
        # AY(合计销售)=SUM(AM:AX) 1-12月完成，月内 10-12月完成恒为 0
        month_before = int(self.year_month[5:7])          # 本月月号（10月报表 → 完成月份 1-9）
        def csum(key, upto=None):
            vals = cum[key]
            return sum(safe_float(vals[m - 1]) for m in range(1, (upto or month_before)))
        st_sum = csum("sales_target")     # 已完成月份目标合计
        pt_sum = csum("profit_target")
        sa_sum = csum("sales_actual")    # 已完成月份完成合计（不含当期）
        pa_sum = csum("profit_actual")
        AY = sa_sum / st_sum if st_sum else None          # 累月基础品类完成率（不含当期）
        BW = pa_sum / pt_sum if pt_sum else None          # 累月毛利完成率（不含当期）
        AA = (AY + BW) / 2 if (AY is not None and BW is not None) else None
        # V 第三分量：累月含当期完成率 = (已完成月份完成合计 + 当期I) / 已完成月份目标合计
        az_inner = (sa_sum + I) / st_sum if st_sum else None
        V = None
        if J is not None and R is not None and az_inner is not None:
            V = min(J, 1.3) * 0.4 + R * 0.5 + az_inner * 0.1
        row = {
            "name": name, "C": C, "D": D, "E": E,
            "G": G, "H": H, "I": I, "J": J, "K": K, "L": L, "M": M,
            "O": O, "P": P, "Q": Q, "R": R, "S": S, "V": V,
            "AA": AA, "AY": AY, "BW": BW,
            "cum_sales_target": cum["sales_target"], "cum_sales_actual": cum["sales_actual"],
            "cum_profit_target": cum["profit_target"], "cum_profit_actual": cum["profit_actual"],
            "cum_sales_total_target": st_sum, "cum_sales_total_actual": sa_sum,
            "cum_profit_total_target": pt_sum, "cum_profit_total_actual": pa_sum,
            "completed_months": month_before - 1,
        }
        return row

    def build_tongbao(self):
        """构建两个版本：excl_hebi(5行) 与 incl_hebi(6行)"""
        versions = {}
        for key, order, unranked in (("excl_hebi", COUNTY_ORDER_5, UNRANKED_5),
                                     ("incl_hebi", COUNTY_ORDER_6, UNRANKED_6)):
            included = list(order)
            cum = self.build_cumulative(included)
            # 合计行
            total_sums = {
                "adj_sales": sum(self.county[c]["adj_sales"] for c in included),
                "sales_after": sum(self.county[c]["sales_after"] for c in included),
                "adj_profit": sum(self.county[c]["adj_profit"] for c in included),
                "profit_after": sum(self.county[c]["profit_after"] for c in included),
                "adj_retail": sum(self.county[c]["adj_retail"] for c in included),
                "tongqi": sum(self.county[c]["tongqi"] for c in RANKED_COUNTIES),  # K7=Σ3县区
                "sales_target": 0, "profit_target": 0, "avg_fuel": 0,
            }
            total_row = self._tongbao_row("合计", total_sums, cum["合计"], is_total=True)
            rows = [total_row]
            for c in order:
                rows.append(self._tongbao_row(c, self.county[c], cum[c]))
            # 排名块：3县区按 V 降序 + 未排名县区
            ranked = sorted([r for r in rows if r["name"] in RANKED_COUNTIES],
                            key=lambda r: -(r["V"] or 0))
            ranking = [{"rank": i + 1, "unit": r["name"], "rate": r["V"]}
                      for i, r in enumerate(ranked)]
            ranking += [{"rank": None, "unit": c, "rate": None} for c in unranked]
            versions[key] = {
                "rows": rows,
                "ranking": ranking,
                "rank_block_counties": unranked,
            }
        self.tongbao = versions
        return versions

    # ---------- 入口 ----------

    def run(self, save=True):
        self.load()
        self.build_station_rows()
        self.build_county_data()
        self.build_tongbao()
        result = {
            "report_date": self.report_date,
            "year_month": self.year_month,
            "report_day": self.report_day,
            "month_days": self.month_days,
            "time_progress": round(self.report_day / self.month_days, 4),
            "station_rows": self.station_rows,
            "tongbao": self.tongbao,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if save:
            self._save_result(result)
        logger.info(f"[v0.2管道] 报表 {self.report_date} 计算完成: "
                    f"{len(self.station_rows)}站, "
                    f"excl_hebi合计H={versions_h(result, 'excl_hebi'):.4f}万, "
                    f"incl_hebi合计H={versions_h(result, 'incl_hebi'):.4f}万")
        return result

    def _save_result(self, result):
        conn = db.get_conn()
        try:
            with conn:
                conn.execute(
                    """INSERT INTO result_tongbao (report_date, pipeline, rows_json, summary_json)
                       VALUES (?,?,?,?)
                       ON CONFLICT(report_date) DO UPDATE SET
                           rows_json=excluded.rows_json, summary_json=excluded.summary_json""",
                    (self.report_date, "v02",
                     json.dumps(result, ensure_ascii=False),
                     json.dumps({"stations": len(self.station_rows)}, ensure_ascii=False)))
        finally:
            conn.close()


def versions_h(result, key):
    total = [r for r in result["tongbao"][key]["rows"] if r["name"] == "合计"][0]
    return total["H"] or 0


def run_pipeline(report_date, save=True):
    """对外入口：跑一次完整计算"""
    return Pipeline(report_date).run(save=save)
