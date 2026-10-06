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

        # 生成大类透视
        self._build_dalei_pivot()
        self._notify_progress(2, 10, "大类原始数据入库完成")
        return {"dalei_rows": len(self.dalei_fuhe) if self.dalei_fuhe is not None else 0,
                "tongqi_rows": len(self.dalei_tongqi_fuhe) if self.dalei_tongqi_fuhe is not None else 0}

    def _get_station_region_map(self):
        """从配置获取站点→片区映射（预留维护接口）"""
        regions = self.config.get("station_regions", {})
        return regions

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

        # 券系数表（从配置或日报表"券"工作表获取）
        quan_coefficients = self.config.get("quan_coefficients", {})

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

            # 轻油销量（从配置获取）
            light_oil = self.config.get("light_oil_sales", {}).get(station, 0)

            # 片区
            region = self.config.get("station_regions", {}).get(station, "")

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
        """构建通报数据（县区级汇总）"""
        if self.fuhe_pivot is None:
            return None

        # 读取当月目标
        month_key = f"{self.current_year}-{self.current_month:02d}"
        targets = self.config.get("monthly_targets", {}).get(month_key, {})

        regions = ["淇县", "浚县", "市区经营部", "商客"]
        results = []
        for region in regions:
            row_data = self.fuhe_pivot.loc[region] if region in self.fuhe_pivot.index else pd.Series(0, index=self.fuhe_pivot.columns)
            target_sales = targets.get(region, {}).get("sales", 0)
            target_profit = targets.get(region, {}).get("profit", 0)
            actual_sales = safe_float(row_data.get("销售券后", 0)) / 10000  # 转万元
            actual_profit = safe_float(row_data.get("毛利卷后", 0)) / 10000
            sales_rate = actual_sales / target_sales if target_sales else 0
            profit_rate = actual_profit / target_profit if target_profit else 0
            # 综合完成率 = 毛利×50% + 基础品类销售×40% + 累月营业额×10%
            composite_rate = profit_rate * 0.5 + min(sales_rate, 1.3) * 0.4 + 0 * 0.1

            results.append({
                "单位": region,
                "基础品类目标": target_sales,
                "基础品类完成量含非非": actual_sales,
                "基础品类完成量剔除非非": actual_sales,
                "基础品类完成率": sales_rate,
                "毛利目标": target_profit,
                "毛利完成量含非非": actual_profit,
                "毛利完成量剔除非非": actual_profit,
                "毛利完成率": profit_rate,
                "综合完成率": composite_rate
            })
        return pd.DataFrame(results)

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
        """输出xlsx文件，'通报'表按原日报格式排版"""
        logger.info("输出xlsx文件", step=10)
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side, numbers
        from openpyxl.utils import get_column_letter

        wb = openpyxl.Workbook()

        # ===== 通报表（按原日报格式） =====
        ws = wb.active
        ws.title = "通报"

        # 样式定义
        f_title = Font(name="微软雅黑", size=14, bold=True)
        f_header = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
        f_data = Font(name="微软雅黑", size=10)
        f_bold = Font(name="微软雅黑", size=10, bold=True)
        fill_header = PatternFill("solid", fgColor="4472C4")
        fill_subheader = PatternFill("solid", fgColor="8EAADB")
        fill_total = PatternFill("solid", fgColor="D6DCE4")
        fill_alt = PatternFill("solid", fgColor="F2F2F2")
        thin = Side(style="thin", color="BFBFBF")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        align_left = Alignment(horizontal="left", vertical="center")

        # 列宽
        col_widths = {1: 6, 2: 12, 3: 12, 4: 14, 5: 12, 6: 14, 7: 14, 8: 10,
                      9: 12, 10: 14, 11: 14, 12: 10, 13: 10, 14: 10, 15: 12}
        for c, w in col_widths.items():
            ws.column_dimensions[get_column_letter(c)].width = w

        # 第1行：标题
        ws.merge_cells("A1:O1")
        ws["A1"] = f"{self.current_year}年{self.current_month}月非油品基础品类销售进度表"
        ws["A1"].font = f_title
        ws["A1"].alignment = align_center
        ws.row_dimensions[1].height = 36

        # 第2行：日期
        ws.merge_cells("A2:E2")
        ws["A2"] = f"报表日期：{self.current_year}年{self.current_month}月1-{self.today_day}日"
        ws["A2"].font = f_data
        ws["A2"].alignment = align_left
        ws.merge_cells("F2:G2")
        ws["F2"] = "月时间进度："
        ws["F2"].font = f_data
        ws["F2"].alignment = Alignment(horizontal="right", vertical="center")
        ws["H2"] = round(self.today_day / self.days_in_month, 4)
        ws["H2"].font = f_data
        ws["H2"].number_format = "0.00%"
        ws["H2"].alignment = align_center
        ws.merge_cells("N2:O2")
        ws["N2"] = "单位：万元"
        ws["N2"].font = f_data
        ws["N2"].alignment = Alignment(horizontal="right", vertical="center")

        # 第3行：主表头
        headers3 = {
            1: "序号", 2: "单位", 4: "门零吨油销售额\n(剔除烟草、洗车含非非)元",
            5: "基础品类（权重40%）", 9: "毛利（权重50%）", 13: "排名", 14: "综合排名"
        }
        for c, v in headers3.items():
            cell = ws.cell(row=3, column=c, value=v)
            cell.font = f_header
            cell.fill = fill_header
            cell.alignment = align_center
            cell.border = border
        # 合并第3行单元格
        ws.merge_cells("B3:C3")    # 单位
        ws.merge_cells("E3:H3")    # 基础品类
        ws.merge_cells("I3:M3")    # 毛利
        ws.merge_cells("N3:N4")    # 排名
        ws.merge_cells("O3:O4")    # 综合排名
        ws.merge_cells("A3:A4")    # 序号
        ws.merge_cells("D3:D4")    # 门零吨油
        ws.row_dimensions[3].height = 30

        # 第4行：子表头
        subheaders = {5: "目标计划", 6: "完成量\n(含非非)", 7: "完成量\n(剔除非非)", 8: "完成率",
                      9: "目标计划", 10: "完成量\n(含非非)", 11: "完成量\n(剔除非非)", 12: "完成率", 13: "毛利率"}
        for c, v in subheaders.items():
            cell = ws.cell(row=4, column=c, value=v)
            cell.font = f_header
            cell.fill = fill_subheader
            cell.alignment = align_center
            cell.border = border
        # 补充B4/C4（单位的子行）
        ws.cell(row=4, column=2, value="县区").font = f_header
        ws.cell(row=4, column=2).fill = fill_subheader
        ws.cell(row=4, column=2).alignment = align_center
        ws.cell(row=4, column=2).border = border
        ws.cell(row=4, column=3, value="站点").font = f_header
        ws.cell(row=4, column=3).fill = fill_subheader
        ws.cell(row=4, column=3).alignment = align_center
        ws.cell(row=4, column=3).border = border
        ws.row_dimensions[4].height = 30

        # 给所有表头加边框
        for r in [3, 4]:
            for c in range(1, 16):
                ws.cell(row=r, column=c).border = border

        # 第5行：合计
        regions = ["合计", "淇县", "浚县", "市区经营部", "商客"]
        for i, region in enumerate(regions):
            r = 5 + i
            ws.cell(row=r, column=1, value=("-" if i == 0 else i)).font = f_bold
            ws.cell(row=r, column=2, value=region).font = f_bold if i == 0 else f_data
            ws.cell(row=r, column=3, value="合计" if i == 0 else "").font = f_bold if i == 0 else f_data

            # 填充数据
            if i == 0:
                # 合计行 = 各县区之和
                for c in range(4, 16):
                    col_letter = get_column_letter(c)
                    ws.cell(row=r, column=c, value=f"=SUM({col_letter}6:{col_letter}9)")
                ws.cell(row=r, column=1).value = "-"
            else:
                # 各县区数据
                row_data = self.tongbao_data[self.tongbao_data["单位"] == region]
                if len(row_data) > 0:
                    d = row_data.iloc[0]
                    ws.cell(row=r, column=5, value=round(safe_float(d.get("基础品类目标", 0)), 2))
                    ws.cell(row=r, column=6, value=round(safe_float(d.get("基础品类完成量含非非", 0)), 4))
                    ws.cell(row=r, column=7, value=round(safe_float(d.get("基础品类完成量剔除非非", 0)), 4))
                    rate = safe_float(d.get("基础品类完成率", 0))
                    ws.cell(row=r, column=8, value=round(rate, 4))
                    ws.cell(row=r, column=8).number_format = "0.00%"
                    ws.cell(row=r, column=9, value=round(safe_float(d.get("毛利目标", 0)), 2))
                    ws.cell(row=r, column=10, value=round(safe_float(d.get("毛利完成量含非非", 0)), 4))
                    ws.cell(row=r, column=11, value=round(safe_float(d.get("毛利完成量剔除非非", 0)), 4))
                    prate = safe_float(d.get("毛利完成率", 0))
                    ws.cell(row=r, column=12, value=round(prate, 4))
                    ws.cell(row=r, column=12).number_format = "0.00%"
                    # 毛利率 = 毛利完成量 / 基础品类完成量
                    ml = safe_float(d.get("毛利完成量含非非", 0))
                    xs = safe_float(d.get("基础品类完成量含非非", 0))
                    ws.cell(row=r, column=13, value=round(ml / xs, 4) if xs else 0)
                    ws.cell(row=r, column=13).number_format = "0.00%"
                    # 综合完成率
                    comp = safe_float(d.get("综合完成率", 0))
                    ws.cell(row=r, column=15, value=round(comp, 4))
                    ws.cell(row=r, column=15).number_format = "0.00%"
                    # 排名
                    ws.cell(row=r, column=14, value=i)

            # 格式化
            for c in range(1, 16):
                cell = ws.cell(row=r, column=c)
                cell.border = border
                cell.alignment = align_center
                if i == 0:
                    cell.font = f_bold
                    cell.fill = fill_total
                elif i % 2 == 0:
                    cell.fill = fill_alt
                if c in (8, 12, 13, 15) and i > 0:
                    cell.number_format = "0.00%"
            ws.row_dimensions[r].height = 24

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
        regions = ["合计", "淇县", "浚县", "市区经营部", "商客"]
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
                    str(i), f"{comp_rate * 100:.2f}%"
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
