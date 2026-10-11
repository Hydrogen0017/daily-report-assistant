# -*- coding: utf-8 -*-
"""
v0.2 数据源声明式注册表
新增数据源 = 在此追加一个 DataSource 定义，核心代码零改动。

字段说明：
- id:            数据源唯一标识
- file_keywords: 文件名识别关键词（按顺序匹配第一个命中）
- target_table:  入库目标表
- period_tag:    fact_sales_detail 的期间标记（current/same_period/retail），其他表为 None
- station_col:   站名列候选（按序匹配）
- fields:        标准字段 -> 候选列名列表（目标列 -> 源列候选）
- required:      必须命中才算导入成功的字段
"""
from dataclasses import dataclass, field


@dataclass
class DataSource:
    id: str
    name: str                      # 显示名
    file_keywords: list            # 文件名识别关键词
    target_table: str
    period_tag: str = None         # 仅 fact_sales_detail 使用
    station_col: list = field(default_factory=list)
    fields: dict = field(default_factory=dict)   # 标准字段 -> 候选列名
    required: list = field(default_factory=list) # 必须命中的标准字段
    dedup: bool = True             # 导入前按当日+该源快照覆盖


# ===== 现有 6 张导出表的定义 =====

# 当期全 / 同期全 / 当期零：同构 21 列（编码|组织 ... 毛利率%）
_SALES_SHEET_FIELDS = {
    "category": ["名称|品类"],
    "qty": ["销售数量"],
    "amount": ["含税|销售金额", "含税销售金额"],
    "profit": ["含税|毛利金额", "含税毛利金额"],
}
_SALES_SHEET_STATION = ["名称|组织", "组织名称"]

DATA_SOURCES = [
    DataSource(
        id="dangqi_all",
        name="当期全部大类销售明细",
        file_keywords=["当期全", "当期全部"],
        target_table="fact_sales_detail",
        period_tag="current",
        station_col=_SALES_SHEET_STATION,
        fields=_SALES_SHEET_FIELDS,
        required=["category", "amount"],
    ),
    DataSource(
        id="tongqi_all",
        name="同期全部大类销售明细",
        file_keywords=["同期全", "同期全部"],
        target_table="fact_sales_detail",
        period_tag="same_period",
        station_col=_SALES_SHEET_STATION,
        fields=_SALES_SHEET_FIELDS,
        required=["category", "amount"],
    ),
    DataSource(
        id="dangqi_ling",
        name="当期零售明细",
        file_keywords=["当期零", "当期零售"],
        target_table="fact_sales_detail",
        period_tag="retail",
        station_col=_SALES_SHEET_STATION,
        fields=_SALES_SHEET_FIELDS,
        required=["category", "amount"],
    ),
    DataSource(
        id="crm",
        name="CRM用券明细",
        file_keywords=["CRM", "crm"],
        target_table="fact_crm",
        station_col=["组织名称"],
        fields={
            "rule_name": ["券规则名称"],
            "category": ["大类"],
            "qty": ["销售数量"],
            "amount": ["订单销售金额（含券）"],
            "quan_amount": ["拆分后用券金额"],
            "pay_amount": ["拆分后实际支付金额(不含券)"],
        },
        required=["category"],
    ),
    DataSource(
        id="dianzi_quan",
        name="电子券核销明细",
        file_keywords=["电子券", "非油券"],
        target_table="fact_electron_quan",
        station_col=["用券站点名称"],
        fields={
            "rule_name": ["电子券规则名称"],
            "quan_type": ["券类型"],
            "quan_amount": ["拆分后商品用券金额"],
            "sales_amount": ["订单优惠后销售金额"],
            "profit": ["含税毛利额"],
        },
        required=["quan_amount"],
    ),
    DataSource(
        id="yangche_ka",
        name="养车卡销售明细",
        file_keywords=["养车卡", "养车"],
        target_table="fact_yangche_ka",
        station_col=["店铺名称"],
        fields={
            "category": ["一级类目"],
            "product_name": ["商品名称"],
            "qty": ["销售数量"],
            "amount": ["商品销售金额"],
        },
        required=["amount"],
    ),
]

_SOURCE_INDEX = {ds.id: ds for ds in DATA_SOURCES}


def get_source(source_id):
    return _SOURCE_INDEX.get(source_id)


def identify_file(filename):
    """按文件名识别数据源，返回 DataSource 或 None"""
    name = str(filename)
    for ds in DATA_SOURCES:
        for kw in ds.file_keywords:
            if kw in name:
                return ds
    return None


def list_sources():
    """全部数据源（界面展示用）"""
    return [{"id": ds.id, "name": ds.name, "table": ds.target_table,
             "keywords": ds.file_keywords} for ds in DATA_SOURCES]
