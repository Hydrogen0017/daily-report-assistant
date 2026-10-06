# -*- coding: utf-8 -*-
"""
非油日报数据处理核心模块
实现从6张导出表到完整日报的10步自动化处理流程
预留跨月目标更新、轻油销量更新、手动调整等维护接口
"""
import pandas as pd
import numpy as np
from datetime import date
from pathlib import Path
from store import logger, UPLOADS_DIR, OUTPUT_DIR, CACHE_DIR, load_config, save_config, get_today_str
from base_data import (get_station_regions, get_light_oil_sales,
                       get_quan_coefficients, get_monthly_targets)

# 导出表文件名映射
UPLOAD_FILES = {
    "dangqi_all": "当期全.xlsx",       # 当期全部大类销售明细
    "tongqi_all": "同期全.xlsx",       # 同期全部大类销售明细
    "dangqi_ling": "当期零.xlsx",      # 当期零售明细
    "crm": "CRM.xlsx",                 # CRM用券明细
    "dianzi_quan": "电子券.xlsx",      # 电子券核销明细
    "yangche_ka": "养车卡.xlsx",       # 养车卡销售明细
}

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


def replace_na(df, columns=None):
    """将NaN替换为0"""
    if columns is None:
        return df.fillna(0)
    for col in columns:
        if col in df.columns:
            df[col] = df[col].fillna(0)
    return df


class DailyReportProcessor:
    """非油日报处理器"""

    def __init__(self, config=None):
        self.config = config or load_config()
        self.report_date = get_today_str()
        self.today_day = date.today().day
        self.current_month = date.today().month
        self.current_year = date.today().year
        self.days_in_month = self._days_in_month()
        self.progress_callback = None

        # 数据容器
        self.dfs = {}           # 原始导出表
        self.fuhe = None        # 附表（每站一行）
        self.fuhe_pivot = None  # 附表透视（按县区）
        self.dalei_fuhe = None  # 大类附表
        self.dalei_tongqi_fuhe = None
        self.dalei_pivot = None
        self.dalei_tongqi_pivot = None
        self.zhengti_huanyuan = None  # 整体还原表
        self.tongbao_data = None      # 通报数据
        self.daozhan_data = {}         # 到站数据
        self.adjustments = []          # 手动调整数据

    def set_progress_callback(self, callback):
        """设置进度回调函数"""
        self.progress_callback = callback

    def _notify_progress(self, step, total, message, status="processing"):
        if self.progress_callback:
            self.progress_callback({
                "step": step,
                "total": total,
                "message": message,
                "status": status,
                "progress": round(step / total * 100, 1)
            })

    def _days_in_month(self):
        """当月天数"""
        import calendar
        return calendar.monthrange(self.current_year, self.current_month)[1]

    def load_uploads(self, file_paths):
        """加载上传的6张导出表
        file_paths: {key: filepath} 或 {key: file_object}
        """
        logger.info("开始加载导出数据文件", step=0)
        self._notify_progress(0, 10, "正在加载导出数据文件...")

        results = {"loaded": [], "errors": []}
        for key, expected_name in UPLOAD_FILES.items():
            if key in file_paths and file_paths[key]:
                try:
                    fp = file_paths[key]
                    # pandas读取时保留原始列名，不做自动清洗
                    df = pd.read_excel(fp, dtype=str)
                    self.dfs[key] = df
                    results["loaded"].append({"key": key, "name": expected_name, "rows": len(df), "cols": len(df.columns)})
                    logger.info(f"已加载 {expected_name}: {len(df)}行 {len(df.columns)}列", step=0)
                except Exception as e:
                    err = f"加载 {expected_name} 失败: {str(e)}"
                    results["errors"].append({"key": key, "name": expected_name, "error": str(e)})
                    logger.error(err, step=0)
            else:
                results["errors"].append({"key": key, "name": expected_name, "error": "文件未上传"})

        self._notify_progress(1, 10, f"数据加载完成: {len(results['loaded'])}个成功, {len(results['errors'])}个失败")
        return results

    def get_columns(self, df, candidates):
        """模糊匹配列名"""
        if df is None:
            return None
        cols = list(df.columns)
        for cand in candidates:
            for c in cols:
                if cand in str(c) or str(c) in cand:
                    return c
        return None

    def step1_prepare_date(self):
        """步骤1 - 准备报表日期（按当日自动计算）"""
        logger.info(f"报表日期: {self.report_date}, 当月第{self.today_day}天/共{self.days_in_month}天", step=1)
        self._notify_progress(1, 10, f"报表日期: {self.report_date} (当月第{self.today_day}天)")
        return {
            "report_date": self.report_date,
            "day_of_month": self.today_day,
            "days_in_month": self.days_in_month,
            "month_str": f"{self.current_year}年{self.current_month}月1-{self.today_day}日"
        }

    def step2_load_dalei_data(self):
        """步骤2 - 大类原始数据入库（当期全+同期全 → 大类附表/大类附表同期）"""
        logger.info("步骤2: 大类原始数据入库", step=2)
        self._notify_progress(2, 10, "正在处理大类原始数据...")

        # 当期全
        df_dq = self.dfs.get("dangqi_all")
        if df_dq is not None:
            self.dalei_fuhe = df_dq.copy()
            # 追加片区列 - 通过站名匹配附表的片区映射
            station_region_map = self._get_station_region_map()
            name_col = self.get_columns(df_dq, ["名称|组织", "名称\\|组织", "组织名称"])
            if name_col and station_region_map:
                self.dalei_fuhe["片区"] = self.dalei_fuhe[name_col].map(
                    lambda x: station_region_map.get(str(x).strip(), station_region_map.get(clean_station_name(str(x).strip()), np.nan))
                )
            logger.info(f"当期大类附表: {len(self.dalei_fuhe)}行", step=2)

        # 同期全
        df_tq = self.dfs.get("tongqi_all")
        if df_tq is not None:
            self.dalei_tongqi_fuhe = df_tq.copy()
            if name_col and station_region_map:
                self.dalei_tongqi_fuhe["片区"] = self.dalei_tongqi_fuhe[name_col].map(
                    lambda x: station_region_map.get(str(x).strip(), station_region_map.get(clean_station_name(str(x).strip()), np.nan))
                )
            logger.info(f"同期大类附表: {len(self.dalei_tongqi_fuhe)}行", step=2)

            # 同期站级销售聚合（用于通报表同比列）
            tq_org_col = self.get_columns(df_tq, ["名称|组织", "名称\\|组织", "组织名称"])
            tq_amt_col = self.get_columns(df_tq, ["含税|销售金额", "含税销售金额"])
            if tq_org_col and tq_amt_col:
                tmp = df_tq[[tq_org_col, tq_amt_col]].copy()
                tmp[tq_amt_col] = pd.to_numeric(tmp[tq_amt_col], errors="coerce").fillna(0)
                g = tmp.groupby(tq_org_col)[tq_amt_col].sum()
                self._tongqi_sales_map = dict(g)
                logger.info(f"同期站级销售: {len(g)}个站点", step=2)

        # 生成大类透视
        self._build_dalei_pivot()
        self._notify_progress(2, 10, "大类原始数据入库完成")
        return {"dalei_rows": len(self.dalei_fuhe) if self.dalei_fuhe is not None else 0,
                "tongqi_rows": len(self.dalei_tongqi_fuhe) if self.dalei_tongqi_fuhe is not None else 0}

    def _get_station_region_map(self):
        """获取站点→片区映射：配置优先，否则使用内置基础数据"""
        return get_station_regions(self.config)

    def _build_dalei_pivot(self):
        """构建大类透视表（品类×片区 → 含税销售额）"""
        logger.info("构建大类透视表", step=2)

        # 当期大类透视
        if self.dalei_fuhe is not None:
            cat_col = self.get_columns(self.dalei_fuhe, ["名称|品类", "名称\\|品类"])
            amt_col = self.get_columns(self.dalei_fuhe, ["含税|销售金额", "含税销售金额"])
            region_col = "片区" if "片区" in self.dalei_fuhe.columns else None

            if cat_col and amt_col:
                df = self.dalei_fuhe[[cat_col, amt_col] + ([region_col] if region_col else [])].copy()
                df[amt_col] = pd.to_numeric(df[amt_col], errors="coerce").fillna(0)
                if region_col:
                    df[region_col] = df[region_col].fillna("#N/A")
                    self.dalei_pivot = df.pivot_table(
                        index=cat_col, columns=region_col,
                        values=amt_col, aggfunc="sum", fill_value=0, margins=True, margins_name="总计"
                    )
                else:
                    self.dalei_pivot = df.groupby(cat_col)[amt_col].sum()

        # 同期大类透视
        if self.dalei_tongqi_fuhe is not None:
            cat_col = self.get_columns(self.dalei_tongqi_fuhe, ["名称|品类", "名称\\|品类"])
            amt_col = self.get_columns(self.dalei_tongqi_fuhe, ["含税|销售金额", "含税销售金额"])
            region_col = "片区" if "片区" in self.dalei_tongqi_fuhe.columns else None

            if cat_col and amt_col:
                df = self.dalei_tongqi_fuhe[[cat_col, amt_col] + ([region_col] if region_col else [])].copy()
                df[amt_col] = pd.to_numeric(df[amt_col], errors="coerce").fillna(0)
                if region_col:
                    df[region_col] = df[region_col].fillna("#N/A")
                    self.dalei_tongqi_pivot = df.pivot_table(
                        index=cat_col, columns=region_col,
                        values=amt_col, aggfunc="sum", fill_value=0, margins=True, margins_name="总计"
                    )
                else:
                    self.dalei_tongqi_pivot = df.groupby(cat_col)[amt_col].sum()

    def step3_tobacco_retail(self):
        """步骤3 - 剔除烟草的零售销售（当期零 → 附表T列）"""
        logger.info("步骤3: 剔除烟草的零售销售", step=3)
        self._notify_progress(3, 10, "正在计算剔除烟草后的零售销售...")

        df = self.dfs.get("dangqi_ling")
        if df is None:
            logger.warn("当期零表未加载，跳过", step=3)
            return {}

        # 找到品类编码列和站名列、销售额列
        code_col = self.get_columns(df, ["编码|品类", "编码\\|品类", "编码"])
        name_col = self.get_columns(df, ["名称|组织", "名称\\|组织", "组织名称"])
        amt_col = self.get_columns(df, ["含税|销售金额", "含税销售金额"])

        if code_col and name_col and amt_col:
            df_filtered = df.copy()
            # 剔除编码为20（烟草）
            df_filtered[code_col] = df_filtered[code_col].astype(str)
            df_filtered = df_filtered[~df_filtered[code_col].str.strip().eq("20")]
            df_filtered[amt_col] = pd.to_numeric(df_filtered[amt_col], errors="coerce").fillna(0)
            # 按站名汇总
            result = df_filtered.groupby(name_col)[amt_col].sum().reset_index()
            result.columns = ["站名", "剔除烟草后零售销售"]
            self._tobacco_retail_map = dict(zip(result["站名"], result["剔除烟草后零售销售"]))
            logger.info(f"剔除烟草零售: {len(result)}个站点", step=3)
            return {"stations": len(result)}
        return {}

    def step4_car_wash(self):
        """步骤4 - 洗车券（当期全筛选洗车券×0.4 → 附表J列）"""
        logger.info("步骤4: 洗车券处理", step=4)
        self._notify_progress(4, 10, "正在计算洗车券...")

        df = self.dfs.get("dangqi_all")
        if df is None:
            return {}

        name_col = self.get_columns(df, ["名称|商品", "名称\\|商品"])
        org_col = self.get_columns(df, ["名称|组织", "名称\\|组织"])
        amt_col = self.get_columns(df, ["含税|销售金额", "含税销售金额"])

        if name_col and amt_col:
            df_wash = df[df[name_col].astype(str).str.contains("河南油非互动洗车券15元1张", na=False)].copy()
            df_wash[amt_col] = pd.to_numeric(df_wash[amt_col], errors="coerce").fillna(0)
            df_wash["洗车金额"] = df_wash[amt_col] * 0.4
            if org_col:
                result = df_wash.groupby(org_col)["洗车金额"].sum().reset_index()
                result.columns = ["站名", "洗车"]
                self._wash_map = dict(zip(result["站名"], result["洗车"]))
                logger.info(f"洗车券: {len(df_wash)}条记录, {len(result)}个站点", step=4)
                return {"records": len(df_wash), "stations": len(result)}
        return {}

    def step5_sales_profit(self):
        """步骤5 - 销售额与毛利（当期全透视 → 附表D、N列）"""
        logger.info("步骤5: 销售额与毛利汇总", step=5)
        self._notify_progress(5, 10, "正在汇总销售额与毛利...")

        df = self.dfs.get("dangqi_all")
        if df is None:
            return {}

        org_col = self.get_columns(df, ["名称|组织", "名称\\|组织"])
        amt_col = self.get_columns(df, ["含税|销售金额", "含税销售金额"])
        profit_col = self.get_columns(df, ["含税|毛利金额", "含税毛利金额"])

        results = {}
        if org_col and amt_col:
            df_tmp = df[[org_col, amt_col] + ([profit_col] if profit_col else [])].copy()
            df_tmp[amt_col] = pd.to_numeric(df_tmp[amt_col], errors="coerce").fillna(0)
            if profit_col:
                df_tmp[profit_col] = pd.to_numeric(df_tmp[profit_col], errors="coerce").fillna(0)
            grouped = df_tmp.groupby(org_col).agg(
                销售金额=(amt_col, "sum"),
                **({"毛利金额": (profit_col, "sum")} if profit_col else {})
            ).reset_index()
            self._sales_map = dict(zip(grouped[org_col], grouped["销售金额"]))
            if profit_col:
                self._profit_map = dict(zip(grouped[org_col], grouped["毛利金额"]))
            else:
                self._profit_map = {}
            results["stations"] = len(grouped)
            logger.info(f"销售毛利汇总: {len(grouped)}个站点", step=5)
        return results

    def step6_crm(self):
        """步骤6 - CRM券（CRM表 → 附表H列）"""
        logger.info("步骤6: CRM券处理", step=6)
        self._notify_progress(6, 10, "正在计算CRM券...")

        df = self.dfs.get("crm")
        if df is None:
            return {}

        # 找到关键列
        org_col = self.get_columns(df, ["组织名称", "名称|组织", "名称\\|组织", "所属部门"])
        quan_amt_col = self.get_columns(df, ["拆分后用券金额", "拆分后商品用券金额"])
        ratio_col = self.get_columns(df, ["非油分摊比例", "非油比例"])

        if org_col and quan_amt_col and ratio_col:
            df_tmp = df.iloc[1:].copy() if len(df) > 1 else df.copy()  # 删除第二行（如需要）
            df_tmp[quan_amt_col] = pd.to_numeric(df_tmp[quan_amt_col], errors="coerce").fillna(0)
            df_tmp[ratio_col] = pd.to_numeric(df_tmp[ratio_col], errors="coerce").fillna(0)
            df_tmp["CRM"] = df_tmp[quan_amt_col] * df_tmp[ratio_col]
            result = df_tmp.groupby(org_col)["CRM"].sum().reset_index()
            self._crm_map = dict(zip(result[org_col], result["CRM"]))
            logger.info(f"CRM券: {len(result)}个站点", step=6)
            return {"stations": len(result)}
        return {}

    def step7_e_coupon(self):
        """步骤7 - 新零售电子券（电子券表+券系数 → 附表K列）"""
        logger.info("步骤7: 新零售电子券处理", step=7)
        self._notify_progress(7, 10, "正在计算新零售电子券...")

        df = self.dfs.get("dianzi_quan")
        if df is None:
            return {}

        # 电子券关键列
        org_col = self.get_columns(df, ["站点名称", "组织名称", "名称|组织"])
        rule_code_col = self.get_columns(df, ["券规则编码", "规则编码", "规则名称"])
        quan_amt_col = self.get_columns(df, ["拆分后商品用券金额", "拆分后用券金额"])

        # 券系数表：配置优先，否则使用内置基础数据（从原日报"券"工作表提取）
        quan_coefficients = get_quan_coefficients(self.config)
        logger.info(f"券系数表: {len(quan_coefficients)}条规则", step=7)

        if org_col and rule_code_col and quan_amt_col:
            df_tmp = df.iloc[1:].copy() if len(df) > 1 else df.copy()
            df_tmp[quan_amt_col] = pd.to_numeric(df_tmp[quan_amt_col], errors="coerce").fillna(0)

            # 查找系数
            def get_coefficients(rule_code):
                return quan_coefficients.get(str(rule_code).strip(), {"non_oil": 0, "weiqi": 0})

            coeffs = df_tmp[rule_code_col].apply(get_coefficients)
            df_tmp["非油系数"] = coeffs.apply(lambda x: x.get("non_oil", 0))
            df_tmp["尾气系数"] = coeffs.apply(lambda x: x.get("weiqi", 0))
            df_tmp["金额1"] = df_tmp["非油系数"] * df_tmp[quan_amt_col]
            df_tmp["金额2"] = df_tmp["尾气系数"] * df_tmp[quan_amt_col]
            df_tmp["合计"] = df_tmp["金额1"] + df_tmp["金额2"]

            result = df_tmp.groupby(org_col)["合计"].sum().reset_index()
            self._ecoupon_map = dict(zip(result[org_col], result["合计"]))
            logger.info(f"电子券: {len(result)}个站点", step=7)
            return {"stations": len(result)}
        return {}

    def step8_yangche_ka(self):
        """步骤8 - 养车卡调整（养车卡 → 附表E、O列）"""
        logger.info("步骤8: 养车卡调整", step=8)
        self._notify_progress(8, 10, "正在计算养车卡调整...")

        df = self.dfs.get("yangche_ka")
        if df is None:
            return {}

        status_col = self.get_columns(df, ["售后状态"])
        dept_col = self.get_columns(df, ["所属部门", "组织名称", "名称|组织"])
        amt_col = self.get_columns(df, ["商品销售金额", "销售金额"])

        if status_col and dept_col and amt_col:
            df_filtered = df[df[status_col].astype(str).str.contains("未售后", na=False)].copy()
            df_filtered[amt_col] = pd.to_numeric(df_filtered[amt_col], errors="coerce").fillna(0)
            result = df_filtered.groupby(dept_col)[amt_col].sum().reset_index()
            result.columns = ["站名", "养车卡调整"]
            self._yangche_map = dict(zip(result["站名"], result["养车卡调整"]))
            logger.info(f"养车卡调整: {len(result)}个站点", step=8)
            return {"stations": len(result)}
        return {}

    def build_fuhe_table(self, station_list=None):
        """构建完整附表（整合所有步骤结果）"""
        logger.info("构建附表", step=9)
        self._notify_progress(9, 10, "正在构建附表...")

        # 获取站点清单（从配置或当期全）
        if station_list is None:
            station_list = self.config.get("stations", [])
            if not station_list and self.dalei_fuhe is not None:
                org_col = self.get_columns(self.dalei_fuhe, ["名称|组织", "名称\\|组织"])
                if org_col:
                    station_list = self.dalei_fuhe[org_col].unique().tolist()

        if not station_list:
            logger.warn("无法获取站点清单", step=9)
            return None

        rows = []
        for idx, station in enumerate(station_list, 1):
            station_clean = clean_station_name(station)
            # 从各map中取数（兼容原名和清洗名）
            def get_val(m, key):
                return m.get(key, m.get(clean_station_name(key), 0)) if m else 0

            sales = get_val(getattr(self, "_sales_map", {}), station)
            profit = get_val(getattr(self, "_profit_map", {}), station)
            crm = get_val(getattr(self, "_crm_map", {}), station)
            wash = get_val(getattr(self, "_wash_map", {}), station)
            ecoupon = get_val(getattr(self, "_ecoupon_map", {}), station)
            tobacco_retail = get_val(getattr(self, "_tobacco_retail_map", {}), station)
            yangche = get_val(getattr(self, "_yangche_map", {}), station)

            # 手动调整
            adj_add = 0
            adj_sub = 0
            adj_profit_add = 0
            adj_profit_sub = 0
            for adj in self.adjustments:
                if adj.get("station") == station:
                    if adj.get("type") == "sales_add": adj_add += adj.get("value", 0)
                    elif adj.get("type") == "sales_sub": adj_sub += adj.get("value", 0)
                    elif adj.get("type") == "profit_add": adj_profit_add += adj.get("value", 0)
                    elif adj.get("type") == "profit_sub": adj_profit_sub += adj.get("value", 0)

            # 轻油销量：配置优先，否则使用内置基础数据；兼容带/不带后缀的站名
            oil_map = get_light_oil_sales(self.config)
            light_oil = oil_map.get(station, oil_map.get(station_clean, oil_map.get(str(station).strip(), 0)))

            # 片区：配置优先，否则使用内置基础数据；兼容带/不带后缀的站名
            region_map = get_station_regions(self.config)
            region = region_map.get(station, region_map.get(station_clean, region_map.get(str(station).strip(), "")))

            # 计算公式（与附表一致）
            adj_total_sales = sales + adj_add - adj_sub
            quan_total = crm + 0 + wash + ecoupon  # H+I+J+K
            sales_after_quan = adj_total_sales - quan_total
            adj_total_profit = profit + adj_profit_add - adj_profit_sub
            profit_after_quan = adj_total_profit - quan_total
            adj_retail = tobacco_retail
            avg_light_oil = safe_float(light_oil) / self.days_in_month if light_oil else 0
            ton_oil_sales = adj_retail / (avg_light_oil * 30) if avg_light_oil else 0

            rows.append({
                "序号": idx,
                "名称|组织": station,
                "标准编码": "",
                "销售金额": sales,
                "调整增加": adj_add,
                "调整减少": adj_sub,
                "调整后总销售": adj_total_sales,
                "crm": crm,
                "剔除": 0,
                "洗车": wash,
                "新零售电子券": ecoupon,
                "扣券合计": quan_total,
                "销售券后": sales_after_quan,
                "毛利金额": profit,
                "调整增加_毛利": adj_profit_add,
                "调整减少_毛利": adj_profit_sub,
                "调整后毛利": adj_total_profit,
                "卷": quan_total,
                "毛利卷后": profit_after_quan,
                "剔除烟草后零售销售": tobacco_retail,
                "调整增加_零售": 0,
                "调整减少_零售": 0,
                "调整后零售": adj_retail,
                "所属县区": region,
                "轻油销量": safe_float(light_oil),
                "日均轻油": avg_light_oil,
                "门零吨油销售额": ton_oil_sales
            })

        self.fuhe = pd.DataFrame(rows)
        logger.info(f"附表构建完成: {len(self.fuhe)}个站点", step=9)

        # 构建附表透视（按县区）
        if "所属县区" in self.fuhe.columns:
            pivot_cols = ["调整后总销售", "销售券后", "调整后毛利", "毛利卷后", "调整后零售"]
            available = [c for c in pivot_cols if c in self.fuhe.columns]
            self.fuhe_pivot = self.fuhe.groupby("所属县区")[available].sum()
            logger.info(f"附表透视: {len(self.fuhe_pivot)}个县区", step=9)

        return self.fuhe

    def add_adjustment(self, station, adj_type, value, reason=""):
        """添加手动调整"""
        self.adjustments.append({
            "station": station,
            "type": adj_type,
            "value": value,
            "reason": reason,
            "time": get_today_str()
        })
        logger.info(f"添加调整: {station} {adj_type}={value} ({reason})", step=8)

    def step10_refresh_pivots(self):
        """步骤10 - 刷新所有透视表"""
        logger.info("步骤10: 刷新透视表与通报数据", step=10)
        self._notify_progress(10, 10, "正在刷新透视表与通报数据...")

        # 已在 build_fuhe_table 中构建附表透视
        # 这里构建通报/到站数据
        self.tongbao_data = self._build_tongbao()
        self._notify_progress(10, 10, "处理完成！", status="done")
        return {"status": "done"}

    def _build_tongbao(self):
        """构建通报数据（县区级汇总，含同比/吨油/排名，与原日报列结构对齐）"""
        if self.fuhe_pivot is None:
            return None

        # 读取当月目标：配置优先，否则使用内置默认目标
        targets = get_monthly_targets(self.config, self.current_year, self.current_month)
        logger.info(f"当月目标: {targets}", step=10)

        # 县区轻油合计（用于日均吨油）
        oil_by_region = {}
        if self.fuhe is not None and "所属县区" in self.fuhe.columns and "轻油销量" in self.fuhe.columns:
            oil_by_region = self.fuhe.groupby("所属县区")["轻油销量"].sum().to_dict()

        # 县区同期销售合计（站级同期销售按片区映射累加到县区）
        region_map = get_station_regions(self.config)
        tongqi_by_region = {}
        for st, amt in (getattr(self, "_tongqi_sales_map", None) or {}).items():
            reg = region_map.get(str(st).strip(), region_map.get(clean_station_name(str(st)), ""))
            if reg:
                tongqi_by_region[reg] = tongqi_by_region.get(reg, 0) + safe_float(amt)

        # 与原日报一致：淇县/浚县/市区经营部/鹤壁(新源站)/商客 五行（鹤壁、商客不参与排名）
        regions = ["淇县", "浚县", "市区经营部", "鹤壁", "商客"]
        results = []
        for region in regions:
            row_data = self.fuhe_pivot.loc[region] if region in self.fuhe_pivot.index else pd.Series(0, index=self.fuhe_pivot.columns)
            target_sales = targets.get(region, {}).get("sales", 0)
            target_profit = targets.get(region, {}).get("profit", 0)
            # 完成量(含非非) = 调整后总销售（扣券前），完成量(剔除非非) = 销售券后（扣券后）
            actual_sales_with = safe_float(row_data.get("调整后总销售", 0)) / 10000  # 转万元
            actual_sales_without = safe_float(row_data.get("销售券后", 0)) / 10000
            actual_profit_with = safe_float(row_data.get("调整后毛利", 0)) / 10000
            actual_profit_without = safe_float(row_data.get("毛利卷后", 0)) / 10000
            # 门零销售（万元）= 调整后零售 / 10000
            retail = safe_float(row_data.get("调整后零售", 0)) / 10000
            # 日均吨油 = 县区轻油合计 / 当月天数
            avg_oil = safe_float(oil_by_region.get(region, 0)) / self.days_in_month
            # 门零吨油销售额（元）= 门零销售万元 × 10000 / (日均吨油 × 30)
            per_ton = retail * 10000 / (avg_oil * 30) if avg_oil else 0
            sales_rate = actual_sales_without / target_sales if target_sales else 0
            profit_rate = actual_profit_without / target_profit if target_profit else 0
            # 同比
            tongqi = safe_float(tongqi_by_region.get(region, 0)) / 10000
            delta = actual_sales_without - tongqi
            growth = delta / tongqi if tongqi else None
            # 毛利率 = 毛利完成量 / 基础品类完成量
            gross_margin = actual_profit_with / actual_sales_with if actual_sales_with else 0
            # 综合完成率 = 毛利×50% + 基础品类销售×40%(封顶130%) + 累月营业额×10%
            composite_rate = profit_rate * 0.5 + min(sales_rate, 1.3) * 0.4 + 0 * 0.1

            results.append({
                "单位": region,
                "日均吨油": avg_oil,
                "门零吨油销售额": per_ton,
                "门零销售": retail,
                "基础品类目标": target_sales,
                "基础品类完成量含非非": actual_sales_with,
                "基础品类完成量剔除非非": actual_sales_without,
                "基础品类完成率": sales_rate,
                "同期": tongqi,
                "增减量": delta,
                "增幅": growth,
                "毛利目标": target_profit,
                "毛利完成量含非非": actual_profit_with,
                "毛利完成量剔除非非": actual_profit_without,
                "毛利完成率": profit_rate,
                "毛利率": gross_margin,
                "综合完成率": composite_rate
            })

        df = pd.DataFrame(results)
        # 名次：考核县区按综合完成率降序
        ranked = ["淇县", "浚县", "市区经营部"]
        if len(df) > 0:
            rank_map = {}
            ranked_df = df[df["单位"].isin(ranked)].sort_values("综合完成率", ascending=False)
            for rank_idx, (_, row) in enumerate(ranked_df.iterrows(), 1):
                rank_map[row["单位"]] = rank_idx
            df["名次"] = df["单位"].map(lambda r: rank_map.get(r, None))
        return df

    def run_all(self, file_paths, adjustments=None):
        """执行完整处理流程"""
        logger.start_session("daily_report")
        logger.info(f"=== 非油日报处理开始 {self.report_date} ===")

        # 加载数据
        load_result = self.load_uploads(file_paths)
        if len(load_result["loaded"]) < 6:
            logger.error("数据文件不完整，请确认6张表全部上传")
            return {"status": "error", "message": "数据文件不完整", "details": load_result}

        # 应用手动调整
        if adjustments:
            for adj in adjustments:
                self.add_adjustment(adj["station"], adj["type"], adj["value"], adj.get("reason", ""))

        # 执行10步
        s1 = self.step1_prepare_date()
        s2 = self.step2_load_dalei_data()
        s3 = self.step3_tobacco_retail()
        s4 = self.step4_car_wash()
        s5 = self.step5_sales_profit()
        s6 = self.step6_crm()
        s7 = self.step7_e_coupon()
        s8 = self.step8_yangche_ka()
        self.build_fuhe_table()
        s10 = self.step10_refresh_pivots()

        logger.info("=== 非油日报处理完成 ===")
        return {
            "status": "success",
            "report_date": self.report_date,
            "steps": {"step1": s1, "step2": s2, "step3": s3, "step4": s4, "step5": s5, "step6": s6, "step7": s7, "step8": s8, "step10": s10},
            "fuhe_rows": len(self.fuhe) if self.fuhe is not None else 0,
            "tongbao_rows": len(self.tongbao_data) if self.tongbao_data is not None else 0
        }



    def output_xlsx(self, template_path=None):
        """输出xlsx文件，'通报'表完全按原日报78列结构排版（A-V可见，W-BZ累月区隐藏保留）"""
        logger.info("输出xlsx文件", step=10)
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "通报"

        # ===== 样式 =====
        f_title = Font(name="微软雅黑", size=14, bold=True)
        f_note = Font(name="微软雅黑", size=9)
        f_header = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
        f_data = Font(name="微软雅黑", size=10)
        f_bold = Font(name="微软雅黑", size=10, bold=True)
        fill_header = PatternFill("solid", fgColor="4472C4")
        fill_subheader = PatternFill("solid", fgColor="8EAADB")
        fill_total = PatternFill("solid", fgColor="D6DCE4")
        thin = Side(style="thin", color="BFBFBF")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        align_left = Alignment(horizontal="left", vertical="center")

        # ===== 列宽（可见区 A-V） =====
        widths = {1:5, 2:10, 3:11, 4:13, 5:11, 6:10, 7:9, 8:9, 9:9, 10:9,
                 11:9, 12:9, 13:9, 14:10, 15:9, 16:9, 17:9, 18:9, 19:9, 20:6, 21:10, 22:9}
        for c, w in widths.items():
            ws.column_dimensions[get_column_letter(c)].width = w
        # 隐藏列 W-BZ（23-78），保留数据结构不删除
        for c in range(23, 79):
            ws.column_dimensions[get_column_letter(c)].hidden = True
            ws.column_dimensions[get_column_letter(c)].width = 8

        # ===== 第1行：标题 =====
        ws["A1"] = f"{self.current_year}年{self.current_month}月非油品基础品类销售进度表"
        ws["A1"].font = f_title
        ws["A1"].alignment = align_center
        ws.row_dimensions[1].height = 32

        # ===== 第2行：日期 =====
        ws["A2"] = f"报表日期：{self.current_year}年{self.current_month}月1-{self.today_day}日"
        ws["A2"].font = f_data
        ws["A2"].alignment = align_left
        ws["Q2"] = "月时间进度："
        ws["Q2"].font = f_data
        ws["Q2"].alignment = Alignment(horizontal="right", vertical="center")
        ws["R2"] = round(self.today_day / self.days_in_month, 4)
        ws["R2"].number_format = "0.00%"
        ws["R2"].font = f_data
        ws["R2"].alignment = align_center
        ws["BA2"] = "单位/万元"
        ws["BA2"].font = f_data

        # ===== 第3行：公式说明 + 年进度 =====
        ws["A3"] = ("综合完成率＝毛利完成率×50%＋基础品类销售额完成率×40%+累月营业额计划完成率10%;"
                    "基础品类完成率130%封顶")
        ws["A3"].font = f_note
        ws["A3"].alignment = align_left
        ws["Z3"] = "年进度："
        ws["Z3"].font = f_note
        ws["Z3"].alignment = Alignment(horizontal="right", vertical="center")

        # ===== 第4行：分区标题 =====
        ws["A4"] = "当期完成情况"
        ws["A4"].font = f_bold
        ws["Z4"] = "累月完成情况"
        ws["Z4"].font = f_bold

        # ===== 第5行：主表头 =====
        main_headers = {
            1: "序号", 2: "单位", 3: "日均吨油销售",
            4: "门零吨油销售额\\n(剔除烟草、洗车含非非)元",
            5: "门零销售\\n(剔除烟草、洗车含非非)",
            6: "单位", 7: "基础品类（权重40%）", 11: "同比",
            14: "单位", 15: "毛利（权重50%）", 20: "综合排名",
            26: "综合排名", 28: "基础品类（权重50%）", 53: "毛利（权重50%）"
        }
        for c, v in main_headers.items():
            cell = ws.cell(row=5, column=c, value=v)
            cell.font = f_header
            cell.fill = fill_header
            cell.alignment = align_center
        # 合并
        for rng in ["A5:A6", "B5:B6", "C5:C6", "D5:D6", "E5:E6", "F5:F6",
                    "G5:J5", "K5:M5", "N5:N6", "O5:S5", "T5:V5", "Z5:AA5",
                    "AB5:AZ5", "BA5:BZ5"]:
            ws.merge_cells(rng)
        ws.row_dimensions[5].height = 28

        # ===== 第6行：子表头 =====
        month_names = [f"{m}月目标" for m in range(1, 11)] + ["合计目标"]
        sales_months = [f"{m}月" for m in range(1, 13)]
        sub_headers = {
            7: "目标计划", 8: "完成量\\n(含非非互促赠券)", 9: "完成量\\n(剔除非非互促赠券)", 10: "完成率",
            11: "同期", 12: "增/减量", 13: "增幅",
            15: "目标计划", 16: "完成量\\n(含非非互促赠券)", 17: "完成量\\n(剔除非非互促赠券)",
            18: "完成率", 19: "毛利率",
            20: "名次", 21: "单位", 22: "完成率",
            26: "单位", 27: "完成率",
            51: "合计销售", 52: "完成率",
            76: "合计销售", 77: "完成率", 78: "毛利率"
        }
        # 基础品类月度目标 AB(28)~AL(38)
        for i, name in enumerate(month_names):
            sub_headers[28 + i] = name
        # 基础品类月度销售 AM(39)~AX(50)
        for i, name in enumerate(sales_months):
            sub_headers[39 + i] = name
        # 毛利月度目标 BA(53)~BK(63)
        for i, name in enumerate(month_names):
            sub_headers[53 + i] = name
        # 毛利月度销售 BL(64)~BW(75)
        for i, name in enumerate(sales_months):
            sub_headers[64 + i] = name
        for c, v in sub_headers.items():
            cell = ws.cell(row=6, column=c, value=v)
            cell.font = f_header
            cell.fill = fill_subheader
            cell.alignment = align_center
        ws.row_dimensions[6].height = 34
        # 表头边框
        for r in [5, 6]:
            for c in range(1, 79):
                ws.cell(row=r, column=c).border = border

        # ===== 数据行（R7合计 + R8-12五个县区） =====
        regions = ["合计", "淇县", "浚县", "市区经营部", "鹤壁", "商客"]
        # 当月对应的累月列
        m = self.current_month
        tgt_col = 28 + (m - 1)        # 基础品类目标月列
        sales_col = 39 + (m - 1)      # 基础品类销售月列
        ptgt_col = 53 + (m - 1)       # 毛利目标月列
        psales_col = 64 + (m - 1)     # 毛利销售月列

        for i, region in enumerate(regions):
            r = 7 + i
            is_total = (i == 0)
            # A/B列
            ws.cell(row=r, column=1, value=("合计" if is_total else i))
            ws.cell(row=r, column=2, value=region)
            ws.cell(row=r, column=6, value=region)   # F 单位
            ws.cell(row=r, column=14, value=region)  # N 单位
            ws.cell(row=r, column=21, value=region)  # U 单位
            ws.cell(row=r, column=26, value=region)  # Z 单位(累月)

            if is_total:
                # 合计行公式
                for c in [3, 4, 5, 7, 8, 9, 11, 12, 15, 16, 17, tgt_col, 38, sales_col, 51,
                          ptgt_col, 63, psales_col, 76]:
                    ws.cell(row=r, column=c, value=f"=SUM({get_column_letter(c)}8:{get_column_letter(c)}12)")
                ws.cell(row=r, column=10, value="=IF(G7=0,0,I7/G7)")            # J 完成率
                ws.cell(row=r, column=13, value="=IF(K7=0,0,L7/K7)")            # M 增幅
                ws.cell(row=r, column=18, value="=IF(O7=0,0,Q7/O7)")            # R 毛利完成率
                ws.cell(row=r, column=19, value="=IF(H7=0,0,P7/H7)")            # S 毛利率
                ws.cell(row=r, column=52, value="=IF(AL7=0,0,AY7/AL7)")         # AZ 累月完成率
                ws.cell(row=r, column=77, value="=IF(BK7=0,0,BX7/BK7)")         # BY 毛利完成率
                ws.cell(row=r, column=78, value="=IF(AY7=0,0,BX7/AY7)")         # BZ 毛利率
                ws.cell(row=r, column=22, value=f"=IF(OR(G7=0,O7=0),0,Q7/O7*0.5+MIN(I7/G7,1.3)*0.4)")  # V 综合
                ws.cell(row=r, column=27, value="=IF(OR(AL7=0,BK7=0),0,BX7/BK7*0.5+MIN(AY7/AL7,1.3)*0.4)")  # AA
            else:
                row_data = self.tongbao_data[self.tongbao_data["单位"] == region]
                if len(row_data) > 0:
                    d = row_data.iloc[0]
                    g = safe_float(d.get("基础品类目标", 0))
                    h = safe_float(d.get("基础品类完成量含非非", 0))
                    ii = safe_float(d.get("基础品类完成量剔除非非", 0))
                    jj = safe_float(d.get("基础品类完成率", 0))
                    kk = safe_float(d.get("同期", 0))
                    ll = safe_float(d.get("增减量", 0))
                    mm = d.get("增幅")
                    o = safe_float(d.get("毛利目标", 0))
                    p = safe_float(d.get("毛利完成量含非非", 0))
                    q = safe_float(d.get("毛利完成量剔除非非", 0))
                    rr = safe_float(d.get("毛利完成率", 0))
                    ss = safe_float(d.get("毛利率", 0))
                    rank = d.get("名次")
                    vv = safe_float(d.get("综合完成率", 0))
                    cc = safe_float(d.get("日均吨油", 0))
                    dd = safe_float(d.get("门零吨油销售额", 0))
                    ee = safe_float(d.get("门零销售", 0))

                    ws.cell(row=r, column=3, value=round(cc, 2))
                    ws.cell(row=r, column=4, value=round(dd, 2))
                    ws.cell(row=r, column=5, value=round(ee, 4))
                    ws.cell(row=r, column=7, value=round(g, 2))
                    ws.cell(row=r, column=8, value=round(h, 4))
                    ws.cell(row=r, column=9, value=round(ii, 4))
                    ws.cell(row=r, column=10, value=round(jj, 4))
                    ws.cell(row=r, column=11, value=round(kk, 4))
                    ws.cell(row=r, column=12, value=round(ll, 4))
                    ws.cell(row=r, column=13, value=round(mm, 4) if mm is not None else None)
                    ws.cell(row=r, column=15, value=round(o, 2))
                    ws.cell(row=r, column=16, value=round(p, 4))
                    ws.cell(row=r, column=17, value=round(q, 4))
                    ws.cell(row=r, column=18, value=round(rr, 4))
                    ws.cell(row=r, column=19, value=round(ss, 4))
                    ws.cell(row=r, column=20, value=rank if rank is not None else "")
                    ws.cell(row=r, column=22, value=round(vv, 4))
                    # 累月区：当月目标/当月销售/合计
                    ws.cell(row=r, column=tgt_col, value=round(g, 2))
                    ws.cell(row=r, column=38, value=round(g, 2))       # AL 合计目标
                    ws.cell(row=r, column=sales_col, value=round(ii, 4))
                    ws.cell(row=r, column=51, value=round(ii, 4))      # AY 合计销售
                    ws.cell(row=r, column=52, value=round(jj, 4))      # AZ 完成率
                    ws.cell(row=r, column=ptgt_col, value=round(o, 2))
                    ws.cell(row=r, column=63, value=round(o, 2))       # BK 合计目标
                    ws.cell(row=r, column=psales_col, value=round(q, 4))
                    ws.cell(row=r, column=76, value=round(q, 4))       # BX 合计销售
                    ws.cell(row=r, column=77, value=round(rr, 4))      # BY 完成率
                    ws.cell(row=r, column=78, value=round(ss, 4))      # BZ 毛利率

            # 格式化
            pct_cols = {10, 13, 18, 19, 22, 27, 52, 77}
            for c in range(1, 79):
                cell = ws.cell(row=r, column=c)
                cell.border = border
                if c <= 22:
                    cell.alignment = align_center
                if is_total:
                    cell.font = f_bold
                    cell.fill = fill_total
                elif i % 2 == 0:
                    cell.fill = PatternFill("solid", fgColor="F2F2F2")
                if c in pct_cols:
                    cell.number_format = "0.00%"
            ws.row_dimensions[r].height = 22

        # ===== 附表 =====
        if self.fuhe is not None:
            ws2 = wb.create_sheet("附表")
            from openpyxl.utils.dataframe import dataframe_to_rows
            for r_idx, row in enumerate(dataframe_to_rows(self.fuhe, index=False, header=True), 1):
                for c_idx, val in enumerate(row, 1):
                    ws2.cell(row=r_idx, column=c_idx, value=val)

        output_path = OUTPUT_DIR / f"每日通报{self.report_date}.xlsx"
        wb.save(output_path)
        logger.info(f"xlsx已保存: {output_path}")
        return str(output_path)

    def output_image(self):
        """输出美化后的通报图片（按原日报'通报'工作表格式）"""
        logger.info("生成通报图片", step=10)
        from PIL import Image, ImageDraw, ImageFont

        if self.tongbao_data is None:
            return None

        # ===== 布局参数 =====
        margin = 60
        title_h = 70
        date_h = 40
        header_h = 90           # 两行表头
        row_h = 48
        regions = ["合计", "淇县", "浚县", "市区经营部", "鹤壁", "商客"]
        data_rows = len(regions)
        table_h = header_h + data_rows * row_h

        # 列定义: (标题, 宽度)  -- 与通报表对齐
        cols = [
            ("序号", 50), ("单位", 110), ("门零吨油\n销售额(元)", 130),
            ("目标\n计划", 90), ("完成量\n(含非非)", 100), ("完成量\n(剔除非非)", 100), ("完成率", 80),
            ("目标\n计划", 90), ("完成量\n(含非非)", 100), ("完成量\n(剔除非非)", 100), ("完成率", 80), ("毛利率", 80),
            ("排名", 60), ("综合\n排名", 90)
        ]
        total_w = sum(w for _, w in cols) + margin * 2
        total_h = margin + title_h + date_h + header_h + data_rows * row_h + margin

        img = Image.new("RGB", (total_w, total_h), "#FFFFFF")
        draw = ImageDraw.Draw(img)

        # 字体
        try:
            font_title = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 28)
            font_date = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 16)
            font_header = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 14)
            font_data = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 15)
            font_bold = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 15)
        except Exception:
            font_title = ImageFont.load_default()
            font_date = font_header = font_data = font_bold = ImageFont.load_default()

        # 颜色
        c_title = "#1F1F1F"
        c_header_bg = "#4472C4"
        c_sub_bg = "#8EAADB"
        c_total_bg = "#D6DCE4"
        c_alt_bg = "#F2F2F2"
        c_white = "#FFFFFF"
        c_text = "#1F1F1F"
        c_border = "#BFBFBF"
        c_rate_good = "#386A20"
        c_rate_bad = "#B3261E"

        y = margin

        # 标题
        title = f"{self.current_year}年{self.current_month}月非油品基础品类销售进度表"
        bbox = draw.textbbox((0, 0), title, font=font_title)
        tw = bbox[2] - bbox[0]
        draw.text(((total_w - tw) / 2, y), title, fill=c_title, font=font_title)
        y += title_h

        # 日期行
        date_str = f"报表日期：{self.current_year}年{self.current_month}月1-{self.today_day}日"
        draw.text((margin, y), date_str, fill="#5F6368", font=font_date)
        progress = f"月时间进度：{self.today_day / self.days_in_month * 100:.1f}%    单位：万元"
        pw = draw.textlength(progress, font=font_date)
        draw.text((total_w - margin - pw, y), progress, fill="#5F6368", font=font_date)
        y += date_h

        # 表头第1行（分组）
        x = margin
        group_spans = [
            (0, 2, ""),          # 序号+单位（无分组标题）
            (2, 3, "门零吨油销售额\n(剔除烟草、洗车含非非)元"),
            (3, 7, "基础品类（权重40%）"),
            (7, 12, "毛利（权重50%）"),
            (12, 13, "排名"),
            (13, 14, "综合排名"),
        ]
        for start, end, label in group_spans:
            w = sum(cols[j][1] for j in range(start, end))
            draw.rectangle([x, y, x + w, y + header_h // 2], fill=c_header_bg, outline=c_white)
            if label:
                lines = label.split("\n")
                for li, ln in enumerate(lines):
                    lw = draw.textlength(ln, font=font_header)
                    draw.text((x + (w - lw) / 2, y + 10 + li * 18), ln, fill=c_white, font=font_header)
            x += w

        # 表头第2行（子列名）
        x = margin
        sub_names = ["序号", "单位", "门零吨油", "目标计划", "完成量(含非非)", "完成量(剔除非非)", "完成率",
                     "目标计划", "完成量(含非非)", "完成量(剔除非非)", "完成率", "毛利率", "排名", "综合排名"]
        for i, (name, w) in enumerate(cols):
            draw.rectangle([x, y + header_h // 2, x + w, y + header_h], fill=c_sub_bg, outline=c_white)
            label = sub_names[i] if i < len(sub_names) else name
            lines = label.split("\n") if "\n" in label else [label]
            for li, ln in enumerate(lines):
                lw = draw.textlength(ln, font=font_header)
                draw.text((x + (w - lw) / 2, y + header_h // 2 + 6 + li * 16), ln, fill=c_white, font=font_header)
            x += w
        y += header_h

        # 数据行
        for i, region in enumerate(regions):
            x = margin
            bg = c_total_bg if i == 0 else (c_alt_bg if i % 2 == 0 else "#FFFFFF")
            font_use = font_bold if i == 0 else font_data

            # 取数据
            if i == 0:
                vals = ["-", "合计", "", "", "", "", "", "", "", "", "", "", "", ""]
            else:
                row_data = self.tongbao_data[self.tongbao_data["单位"] == region]
                d = row_data.iloc[0] if len(row_data) > 0 else {}
                sales_rate = safe_float(d.get("基础品类完成率", 0))
                profit_rate = safe_float(d.get("毛利完成率", 0))
                comp_rate = safe_float(d.get("综合完成率", 0))
                ml = safe_float(d.get("毛利完成量含非非", 0))
                xs = safe_float(d.get("基础品类完成量含非非", 0))
                maoli = ml / xs if xs else 0
                # 排名：仅考核县区（淇县/浚县/市区经营部），其余留空
                ranked_regions = ["淇县", "浚县", "市区经营部"]
                if self.tongbao_data is not None and len(self.tongbao_data) > 0:
                    ranked = self.tongbao_data[self.tongbao_data["单位"].isin(ranked_regions)].sort_values("综合完成率", ascending=False)
                    rank_map = {row["单位"]: rk for rk, (_, row) in enumerate(ranked.iterrows(), 1)}
                else:
                    rank_map = {}
                rank_val = str(rank_map.get(region, "")) if region in ranked_regions else ""
                vals = [
                    str(i), region, "",
                    f"{safe_float(d.get('基础品类目标', 0)):.2f}",
                    f"{safe_float(d.get('基础品类完成量含非非', 0)):.4f}",
                    f"{safe_float(d.get('基础品类完成量剔除非非', 0)):.4f}",
                    f"{sales_rate * 100:.2f}%",
                    f"{safe_float(d.get('毛利目标', 0)):.2f}",
                    f"{safe_float(d.get('毛利完成量含非非', 0)):.4f}",
                    f"{safe_float(d.get('毛利完成量剔除非非', 0)):.4f}",
                    f"{profit_rate * 100:.2f}%",
                    f"{maoli * 100:.2f}%",
                    rank_val, f"{comp_rate * 100:.2f}%"
                ]

            for j, (name, w) in enumerate(cols):
                draw.rectangle([x, y, x + w, y + row_h], fill=bg, outline=c_border)
                v = vals[j] if j < len(vals) else ""
                # 完成率/毛利率/综合排名用颜色标注
                color = c_text
                if j in (6, 10, 11, 13) and i > 0:
                    try:
                        pct = float(v.replace("%", ""))
                        color = c_rate_good if pct >= 50 else c_rate_bad
                    except Exception:
                        pass
                vw = draw.textlength(str(v), font=font_use)
                draw.text((x + (w - vw) / 2, y + 14), str(v), fill=color, font=font_use)
                x += w
            y += row_h

        output_path = OUTPUT_DIR / f"每日通报{self.report_date}.png"
        img.save(output_path, "PNG")
        logger.info(f"图片已保存: {output_path}")
        return str(output_path)


# ===== 维护接口函数 =====

def update_light_oil_sales(config, station_sales_map):
    """更新轻油销量（预留接口，后续根据上传文件编写规则）
    station_sales_map: {站名: 销量}
    """
    if "light_oil_sales" not in config:
        config["light_oil_sales"] = {}
    config["light_oil_sales"].update(station_sales_map)
    save_config(config)
    logger.info(f"更新轻油销量: {len(station_sales_map)}个站点")
    return config


def update_monthly_targets(config, year, month, targets):
    """更新月度目标（跨月时使用）
    targets: {县区: {sales: 目标, profit: 毛利目标}}
    """
    month_key = f"{year}-{month:02d}"
    if "monthly_targets" not in config:
        config["monthly_targets"] = {}
    config["monthly_targets"][month_key] = targets
    save_config(config)
    logger.info(f"更新{month_key}月度目标: {len(targets)}个县区")
    return config


def update_station_regions(config, region_map):
    """更新站点片区映射"""
    if "station_regions" not in config:
        config["station_regions"] = {}
    config["station_regions"].update(region_map)
    save_config(config)
    return config


def update_quan_coefficients(config, coefficients):
    """更新券系数表（券规则编码→系数）"""
    if "quan_coefficients" not in config:
        config["quan_coefficients"] = {}
    config["quan_coefficients"].update(coefficients)
    save_config(config)
    return config
