# -*- coding: utf-8 -*-
"""
v0.2 输出渲染器：计算结果 → xlsx（通报5行版/通报6行版/附表）+ 通报 PNG

格式依据《数据逻辑》文档 + 2026-10-11 日报版式逆向：
- 字体：微软雅黑（文档要求思源黑体，但本机未安装思源黑体 CN，仅有日文变体；
  沿用日报实际使用的微软雅黑，后续安装思源黑体后改 FONT_NAME 一处即可）
- 数据一位小数（'0.0_ '），率百分数一位小数（'0.0%'）
- 数据标签浅蓝色（#DDEBF7），合计行再浅一点的蓝色（#EDF3FA），两处文本加粗
- 除零显示 '#DIV/0!'（与日报一致）
"""
import calendar
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from store import logger, OUTPUT_DIR

# ===== 版式常量 =====
FONT_NAME = "微软雅黑"
FILL_LABEL = "DDEBF7"   # 数据标签浅蓝
FILL_TOTAL = "EDF3FA"   # 合计行再浅一点的蓝
NF_NUM = "0.0_ "        # 数据一位小数
NF_PCT = "0.0%"         # 率百分数一位小数
NF_TARGET = "0.0_ "     # 目标同样一位小数（文档：所有数据保留一位小数）
DIV0 = "#DIV/0!"

RULE_TEXT = ("综合完成率＝毛利完成率×50%＋基础品类销售额完成率×40%"
             "+累月营业额计划完成率10%;基础品类完成率130%封顶")

_THIN = Side(style="thin", color="BFBFBF")
BORDER_ALL = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
AL_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
AL_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)


def _font(size, bold=False):
    return Font(name=FONT_NAME, size=size, bold=bold)


def _num(v):
    """数值或空"""
    return None if v is None else float(v)


def _div0(v):
    """除零场景显示 #DIV/0!（与日报一致）"""
    return DIV0 if v is None else float(v)


# =====================================================================
# 通报工作表渲染
# =====================================================================

def _render_tongbao_sheet(ws, result, version_key):
    """渲染一个版本的通报工作表（A-BX 共 76 列）"""
    ym = result["year_month"]           # '2026-10'
    y, m = int(ym[:4]), int(ym[5:7])
    day = result["report_day"]
    mdays = result["month_days"]
    rows = result["tongbao"][version_key]["rows"]
    ranking = result["tongbao"][version_key]["ranking"]
    by_name = {r["name"]: r for r in rows}

    # ---- 标题区 ----
    ws.merge_cells("A1:Y1")
    c = ws["A1"]
    c.value = f"{y}年{m}月非油品基础品类销售进度表"
    c.font = _font(36, bold=True)
    c.alignment = AL_CENTER
    ws.row_dimensions[1].height = 61

    ws["A2"] = f"报表日期：{y}年{m}月1-{day}日"
    ws["A2"].font = _font(14)
    ws["A2"].alignment = AL_LEFT
    ws["U2"] = "月时间进度："
    ws["U2"].font = _font(14)
    ws["U2"].alignment = Alignment(horizontal="left", vertical="center")
    ws["V2"] = day / mdays
    ws["V2"].font = _font(14)
    ws["V2"].number_format = NF_PCT
    ws["V2"].alignment = AL_CENTER
    ws.row_dimensions[2].height = 28

    ws.merge_cells("A3:W3")
    ws["A3"] = RULE_TEXT
    ws["A3"].font = _font(14)
    ws["A3"].alignment = AL_LEFT
    ws.merge_cells("Z3:AY3")
    ws["Z3"] = "年进度："
    ws["Z3"].font = _font(14)
    ws["Z3"].alignment = AL_LEFT
    ws.merge_cells("AZ3:BX3")
    doy = datetime(y, m, day).timetuple().tm_yday
    ws["AZ3"] = doy / (366 if calendar.isleap(y) else 365)
    ws["AZ3"].font = _font(14)
    ws["AZ3"].number_format = NF_PCT
    ws["AZ3"].alignment = AL_CENTER
    ws.row_dimensions[3].height = 44

    # ---- 表头（R4-R6）----
    hdr_font = _font(14, bold=True)
    ws.merge_cells("A4:V4")
    ws["A4"] = "当期完成情况"
    ws.merge_cells("Z4:BX4")
    ws["Z4"] = "累月完成情况"
    for addr in ("A4", "Z4"):
        ws[addr].font = hdr_font
        ws[addr].alignment = AL_CENTER
        ws[addr].fill = PatternFill("solid", fgColor=FILL_LABEL)
    ws.row_dimensions[4].height = 29

    two_row = [
        ("A5", "A6", "序号"), ("B5", "B6", "单位"), ("C5", "C6", "日均吨油销售"),
        ("D5", "D6", "门零吨油销售额\n（剔除烟草、洗车含非非）元"),
        ("E5", "E6", "门零销售\n（剔除烟草、洗车含非非）"), ("F5", "F6", "单位"),
        ("N5", "N6", "单位"),
    ]
    for top, low, text in two_row:
        r5 = int(top[1:])
        ws.merge_cells(f"{top[:-1]}5:{top[:-1]}6")
        ws[top] = text
    ws["G5"] = "基础品类（权重40%）"
    ws.merge_cells("G5:J5")
    for addr, text in [("G6", "目标计划"), ("H6", "完成量（含非非互促赠券）"),
                       ("I6", "完成量（剔除非非互促赠券）"), ("J6", "完成率")]:
        ws[addr] = text
    ws["K5"] = "同比"
    ws.merge_cells("K5:M5")
    for addr, text in [("K6", "同期"), ("L6", "增/减量"), ("M6", "增幅")]:
        ws[addr] = text
    ws["O5"] = "毛利（权重50%）"
    ws.merge_cells("O5:S5")
    for addr, text in [("O6", "目标计划"), ("P6", "完成量（含非非互促赠券）"),
                       ("Q6", "完成量（剔除非非互促赠券）"), ("R6", "完成率"), ("S6", "毛利率")]:
        ws[addr] = text
    ws["T5"] = "综合排名"
    ws.merge_cells("T5:V5")
    for addr, text in [("T6", "名次"), ("U6", "单位"), ("V6", "完成率")]:
        ws[addr] = text
    ws["Z5"] = "综合排名"
    ws.merge_cells("Z5:AA5")
    ws["Z6"] = "单位"
    ws["AA6"] = "完成率"
    # 累月基础品类（通报实际表头为"权重50%"）
    ws["AB5"] = "基础品类（权重50%）"
    ws.merge_cells("AB5:AY5")
    for i, addr in enumerate(["AB6", "AC6", "AD6", "AE6", "AF6", "AG6", "AH6", "AI6", "AJ6"]):
        ws[addr] = f"{i + 1}月目标"
    ws["AK6"] = "合计目标"
    for i in range(12):
        ws.cell(row=6, column=38 + i).value = f"{i + 1}月"
    ws["AX6"] = "合计销售"
    ws["AY6"] = "完成率"
    # 累月毛利
    ws["AZ5"] = "毛利（权重50%）"
    ws.merge_cells("AZ5:BX5")
    for i, addr in enumerate(["AZ6", "BA6", "BB6", "BC6", "BD6", "BE6", "BF6", "BG6", "BH6"]):
        ws[addr] = f"{i + 1}月目标"
    ws["BI6"] = "合计目标"
    for i in range(12):
        ws.cell(row=6, column=62 + i).value = f"{i + 1}月"
    ws["BV6"] = "合计销售"
    ws["BW6"] = "完成率"
    ws["BX6"] = "毛利率"

    for r in (5, 6):
        for c in range(1, 77):
            cell = ws.cell(row=r, column=c)
            cell.font = hdr_font
            cell.alignment = AL_CENTER
            if cell.fill.patternType is None:
                cell.fill = PatternFill("solid", fgColor=FILL_LABEL)
    ws.row_dimensions[5].height = 31
    ws.row_dimensions[6].height = 63

    # ---- 数据行（R7 起）----
    total_font = _font(14, bold=True)
    data_font = _font(16)
    data_rows = rows[1:]                       # 县区行
    total = rows[0]

    def put(r, c, v, numfmt=NF_NUM, font=data_font, fill=None):
        cell = ws.cell(row=r, column=c)
        cell.value = v
        cell.font = font
        cell.alignment = AL_CENTER
        if numfmt:
            cell.number_format = numfmt
        if fill:
            cell.fill = PatternFill("solid", fgColor=fill)
        return cell

    def put_row(r, row, seq=None, total_row=False):
        f = total_font if total_row else data_font
        fill = FILL_TOTAL if total_row else None
        no_target = row["name"] in ("商客", "鹤壁") and not total_row
        if total_row:
            ws.merge_cells(f"A{r}:B{r}")
            put(r, 1, "合计", None, f, fill)
            ws.merge_cells(f"T{r}:U{r}")
            put(r, 20, "合计", None, f, fill)
        else:
            put(r, 1, seq, None, f, fill)
            put(r, 2, row["name"], None, f, fill)
        put(r, 3, _num(row["C"]), NF_NUM, f, fill)
        put(r, 4, _num(row["D"]), NF_NUM, f, fill)
        put(r, 5, _num(row["E"]), NF_NUM, f, fill)
        put(r, 6, row["name"], None, f, fill)                 # F 单位
        put(r, 7, None if (no_target or not row["G"]) else row["G"], NF_TARGET, f, fill)
        put(r, 8, _num(row["H"]), NF_NUM, f, fill)
        put(r, 9, _num(row["I"]), NF_NUM, f, fill)
        put(r, 10, None if row["J"] is None else row["J"], NF_PCT, f, fill)
        put(r, 11, _num(row["K"]), NF_NUM, f, fill)
        put(r, 12, _num(row["L"]), NF_NUM, f, fill)
        put(r, 13, _div0(row["M"]), NF_PCT, f, fill)
        put(r, 14, row["name"], None, f, fill)                # N 单位
        put(r, 15, None if (no_target or not row["O"]) else row["O"], NF_TARGET, f, fill)
        put(r, 16, _num(row["P"]), NF_NUM, f, fill)
        put(r, 17, _num(row["Q"]), NF_NUM, f, fill)
        put(r, 18, None if row["R"] is None else row["R"], NF_PCT, f, fill)
        put(r, 19, None if row["S"] is None else row["S"], NF_PCT, f, fill)
        # V 列：合计行放自身综合完成率（与日报一致）；县区行随后被排名块覆盖
        put(r, 22, None if row["V"] is None else row["V"], NF_PCT, f, fill)
        # 累月综合排名块 Z/AA
        put(r, 26, row["name"], None, f, fill)
        put(r, 27, None if row["AA"] is None else row["AA"], NF_PCT, f, fill)
        # 累月基础品类：目标 1-9 月(28-36) 合计(37) 完成 1-12 月(38-49) 合计(50) 完成率(51)
        for i in range(9):
            v = row["cum_sales_target"][i]
            put(r, 28 + i, None if (no_target or not v) else v, NF_TARGET, f, fill)
        put(r, 37, None if (no_target or not row["cum_sales_total_target"])
            else row["cum_sales_total_target"], NF_TARGET, f, fill)
        for i in range(12):
            put(r, 38 + i, _num(row["cum_sales_actual"][i]), NF_NUM, f, fill)
        put(r, 50, _num(row["cum_sales_total_actual"]), NF_NUM, f, fill)
        put(r, 51, _div0(row["AY"]), NF_PCT, f, fill)
        # 累月毛利：目标 1-9 月(52-60) 合计(61) 完成 1-12 月(62-73) 合计(74) 完成率(75) 毛利率(76)
        for i in range(9):
            v = row["cum_profit_target"][i]
            put(r, 52 + i, None if (no_target or not v) else v, NF_TARGET, f, fill)
        put(r, 61, None if (no_target or not row["cum_profit_total_target"])
            else row["cum_profit_total_target"], NF_TARGET, f, fill)
        for i in range(12):
            put(r, 62 + i, _num(row["cum_profit_actual"][i]), NF_NUM, f, fill)
        put(r, 74, _num(row["cum_profit_total_actual"]), NF_NUM, f, fill)
        put(r, 75, _div0(row["BW"]), NF_PCT, f, fill)
        put(r, 76, _num(_bx(row)), NF_PCT, f, fill)

    def _bx(row):
        """累月毛利率 = 毛利合计销售 / 基础品类合计销售（不含当期，与日报 BX 列一致）"""
        sa, pa = row["cum_sales_total_actual"], row["cum_profit_total_actual"]
        return (pa / sa) if sa else None

    # 合计行
    put_row(7, total, total_row=True)
    # 县区行
    r = 8
    for i, row in enumerate(data_rows, 1):
        put_row(r, row, seq=i)
        ws.row_dimensions[r].height = 45
        r += 1
    ws.row_dimensions[7].height = 45

    # 排名块（T/U/V）：覆盖 R8 起按完成率降序
    rank_rows = [x for x in ranking if x["rank"] is not None]
    rr = 8
    for x in rank_rows:
        put(rr, 20, x["rank"], None, data_font)
        put(rr, 21, x["unit"], None, data_font)
        put(rr, 22, x["rate"], NF_PCT, data_font)
        rr += 1
    for x in [q for q in ranking if q["rank"] is None]:
        put(rr, 20, None, None, data_font)
        put(rr, 21, x["unit"], None, data_font)
        put(rr, 22, None, NF_PCT, data_font)
        rr += 1

    # 边框
    last_row = 7 + len(data_rows)
    for row_cells in ws.iter_rows(min_row=4, max_row=last_row, min_col=1, max_col=76):
        for cell in row_cells:
            cell.border = BORDER_ALL

    # 列宽
    widths = {"A": 6.9, "B": 17.7, "C": 11.3, "D": 14.1, "E": 11.3, "F": 17.3,
              "G": 12.6, "H": 15.0, "I": 15.0, "J": 12.6, "K": 10.6, "L": 10.6,
              "M": 10.6, "N": 21.6, "O": 12.6, "P": 14.3, "Q": 14.3, "R": 12.6,
              "S": 10.6, "T": 10.6, "U": 17.5, "V": 10.6, "W": 1.6, "X": 8.4,
              "Y": 8.4, "Z": 12.6, "AA": 10.6, "AK": 11.3, "AL": 14.0,
              "AX": 13.5, "AY": 12.6, "BI": 11.3, "BV": 13.5, "BW": 12.6, "BX": 12.6}
    for c in list(range(28, 37)) + list(range(62, 71)):
        widths[get_column_letter(c)] = 9.5
    for c in list(range(38, 50)) + list(range(74, 76)):
        widths[get_column_letter(c)] = 8.6
    for letter, w in widths.items():
        ws.column_dimensions[letter].width = w
    ws.sheet_view.zoomScale = 70


# =====================================================================
# 附表工作表渲染
# =====================================================================

FUBEI_HEADERS = ["序号", "名称|组织", "标准编码", "销售金额", "调整增加", "调整减少",
                 "调整后总销售", "crm", "剔除", "洗车", "新零售电子卷", "扣卷合计",
                 "销售卷后", "毛利金额", "调整增加", "调整减少", "调整后毛利", "卷",
                 "毛利卷后", "剔除烟草后零售销售", "调整增加", "调整减少", "调整后零售",
                 "所属县区", "轻油销量", "日均轻油", "门零吨油销售额（剔除烟草含非非）元"]
FUBEI_WIDTHS = [5.9, 32, 15.3, 11.5, 11, 11, 12.5, 10, 8, 10, 14, 11,
               12, 11.5, 11, 11, 12.5, 10, 12.5, 14.5, 11, 11, 12.3,
               13.4, 9.4, 10.0, 12.5]
FUBEI_KEYS = ["seq", "station", "standard_code", "sales", "adj_add", "adj_sub",
              "adj_sales", "crm", "tic", "wash", "ecoupon", "quan_total",
              "sales_after", "profit", "p_adj_add", "p_adj_sub", "adj_profit",
              "quan_total", "profit_after", "tobacco_retail", "r_adj_add",
              "r_adj_sub", "adj_retail", "county", "light_oil", "avg_oil",
              "per_ton_oil"]


def _render_fubei_sheet(ws, result):
    hdr_font = Font(name=FONT_NAME, size=11, bold=True)
    for c, h in enumerate(FUBEI_HEADERS, 1):
        cell = ws.cell(row=1, column=c)
        cell.value = h
        cell.font = hdr_font
        cell.alignment = AL_CENTER
        cell.border = BORDER_ALL
    ws.row_dimensions[1].height = 28

    body_font = Font(name=FONT_NAME, size=11)
    total_font = Font(name=FONT_NAME, size=11, bold=True)
    r = 2
    for row in result["station_rows"]:
        for c, key in enumerate(FUBEI_KEYS, 1):
            v = row.get(key)
            cell = ws.cell(row=r, column=c)
            cell.value = v if not isinstance(v, float) else round(v, 4)
            cell.font = body_font
            cell.alignment = AL_CENTER if c != 2 else Alignment(horizontal="left", vertical="center")
            cell.border = BORDER_ALL
            if key in ("sales", "adj_add", "adj_sub", "adj_sales", "crm", "tic", "wash",
                       "ecoupon", "quan_total", "sales_after", "profit", "p_adj_add",
                       "p_adj_sub", "adj_profit", "profit_after", "tobacco_retail",
                       "r_adj_add", "r_adj_sub", "adj_retail", "light_oil", "avg_oil"):
                cell.number_format = "0.00_ "
            if key == "per_ton_oil":
                cell.number_format = "0.00"
        r += 1

    # 合计行
    for c, key in enumerate(FUBEI_KEYS, 1):
        cell = ws.cell(row=r, column=c)
        cell.font = total_font
        cell.border = BORDER_ALL
        cell.alignment = AL_CENTER
        if key in ("seq", "station", "standard_code", "county", "per_ton_oil"):
            cell.value = "合计" if c == 1 else None
            continue
        total = sum((srow.get(key) or 0) for srow in result["station_rows"])
        cell.value = round(total, 4)
        cell.number_format = "0.00_ "
    ws.merge_cells(f"A{r}:B{r}")

    for c, w in enumerate(FUBEI_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "C2"


# =====================================================================
# PNG 渲染（通报可见区：19 列结构）
# =====================================================================

def render_png(result, out_path, version_key="excl_hebi"):
    from PIL import Image, ImageDraw, ImageFont

    ym = result["year_month"]
    y, m = int(ym[:4]), int(ym[5:7])
    day, mdays = result["report_day"], result["month_days"]
    rows = result["tongbao"][version_key]["rows"]
    ranking = [x for x in result["tongbao"][version_key]["ranking"] if x["rank"]]

    margin, title_h, date_h, header_h, row_h = 60, 64, 36, 96, 44
    cols = [
        ("序号", 52), ("单位", 118), ("日均吨油\n销售(吨)", 108),
        ("门零吨油\n销售额(元)", 118), ("门零销售\n(万元)", 100),
        ("目标\n计划", 88), ("完成量\n(含非非)", 102), ("完成量\n(剔除非非)", 102), ("完成率", 78),
        ("同期", 88), ("增/减量", 92), ("增幅", 78),
        ("目标\n计划", 88), ("完成量\n(含非非)", 102), ("完成量\n(剔除非非)", 102), ("完成率", 78),
        ("毛利率", 78),
        ("名次", 58), ("单位", 100), ("综合\n完成率", 92),
    ]
    total_w = sum(w for _, w in cols) + margin * 2
    total_h = margin + title_h + date_h + header_h + row_h * len(rows) + margin

    img = Image.new("RGB", (total_w, total_h), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    try:
        f_title = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 30)
        f_date = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 15)
        f_hdr = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 13)
        f_data = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 15)
        f_bold = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 15)
    except Exception:
        f_title = f_date = f_hdr = f_data = f_bold = ImageFont.load_default()

    c_header_bg, c_sub_bg, c_total_bg = "#4472C4", "#8EAADB", "#D6DCE4"
    c_white, c_text, c_border = "#FFFFFF", "#1F1F1F", "#BFBFBF"

    def fmt_num(v):
        return f"{v:.1f}" if v is not None else "-"

    def fmt_pct(v):
        return f"{v * 100:.1f}%" if v is not None else "-"

    yy = margin
    title = f"{y}年{m}月非油品基础品类销售进度表"
    tw = draw.textbbox((0, 0), title, font=f_title)[2]
    draw.text(((total_w - tw) / 2, yy), title, fill=c_text, font=f_title)
    yy += title_h

    draw.text((margin, yy), f"报表日期：{y}年{m}月1-{day}日", fill="#5F6368", font=f_date)
    prog = f"月时间进度：{day / mdays * 100:.1f}%    单位：万元"
    pw = draw.textlength(prog, font=f_date)
    draw.text((total_w - margin - pw, yy), prog, fill="#5F6368", font=f_date)
    yy += date_h

    group_spans = [(0, 2, ""), (2, 5, "门零情况"), (5, 9, "基础品类（权重40%）"),
                   (9, 12, "同比"), (12, 17, "毛利（权重50%）"), (17, 20, "综合排名")]
    x = margin
    for s, e, label in group_spans:
        w = sum(cols[j][1] for j in range(s, e))
        draw.rectangle([x, yy, x + w, yy + header_h // 2], fill=c_header_bg, outline=c_white)
        if label:
            lw = draw.textlength(label, font=f_hdr)
            draw.text((x + (w - lw) / 2, yy + 14), label, fill=c_white, font=f_hdr)
        x += w
    x = margin
    for name, w in cols:
        draw.rectangle([x, yy + header_h // 2, x + w, yy + header_h], fill=c_sub_bg, outline=c_white)
        lines = name.split("\n")
        line_h = 18
        y0 = yy + header_h // 2 + (12 if len(lines) == 1 else 4)
        for i, ln in enumerate(lines):
            lw = draw.textlength(ln, font=f_hdr)
            draw.text((x + (w - lw) / 2, y0 + i * line_h), ln, fill=c_white, font=f_hdr)
        x += w
    yy += header_h

    rank_map = {}
    for i, rk in enumerate(ranking):
        rank_map[rk["unit"]] = (rk["rank"], rk["rate"])

    for idx, row in enumerate(rows):
        is_total = row["name"] == "合计"
        bg = c_total_bg if is_total else ("#F5F8FC" if idx % 2 == 0 else "#FFFFFF")
        x = margin
        if is_total:
            vals = ["", "合计", fmt_num(row["C"]), fmt_num(row["D"]), fmt_num(row["E"]),
                    fmt_num(row["G"]), fmt_num(row["H"]), fmt_num(row["I"]), fmt_pct(row["J"]),
                    fmt_num(row["K"]), fmt_num(row["L"]), fmt_pct(row["M"]),
                    fmt_num(row["O"]), fmt_num(row["P"]), fmt_num(row["Q"]), fmt_pct(row["R"]),
                    fmt_pct(row["S"]), "合计", "", fmt_pct(row["V"])]
        else:
            rk = rank_map.get(row["name"], (None, None))
            vals = [str(idx), row["name"], fmt_num(row["C"]), fmt_num(row["D"]), fmt_num(row["E"]),
                    fmt_num(row["G"]) if row["G"] else "-", fmt_num(row["H"]), fmt_num(row["I"]),
                    fmt_pct(row["J"]), fmt_num(row["K"]), fmt_num(row["L"]),
                    fmt_pct(row["M"]) if row["K"] else "-",
                    fmt_num(row["O"]) if row["O"] else "-", fmt_num(row["P"]), fmt_num(row["Q"]),
                    fmt_pct(row["R"]) if row["R"] else "-", fmt_pct(row["S"]),
                    str(rk[0]) if rk[0] else "-", rk[0] and row["name"] or "",
                    fmt_pct(rk[1]) if rk[1] else "-"]
        for (name, w), v in zip(cols, vals):
            draw.rectangle([x, yy, x + w, yy + row_h], fill=bg, outline=c_border)
            font = f_bold if is_total else f_data
            color = c_text
            if v.endswith("%") and v not in ("-",):
                try:
                    color = "#386A20" if float(v.rstrip("%")) >= 0 else "#B3261E"
                except ValueError:
                    color = c_text
            lw = draw.textlength(str(v), font=font)
            draw.text((x + (w - lw) / 2, yy + 11), str(v), fill=color, font=font)
            x += w
        yy += row_h

    img.save(out_path, "PNG")
    logger.info(f"[v0.2渲染] PNG已保存: {out_path}")
    return str(out_path)


# =====================================================================
# 总入口
# =====================================================================

def render_xlsx(result, out_path):
    """渲染 xlsx：通报（5行版）+ 通报（含鹤壁6行版）+ 附表"""
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "通报"
    _render_tongbao_sheet(ws1, result, "excl_hebi")
    ws2 = wb.create_sheet("通报（含鹤壁）")
    _render_tongbao_sheet(ws2, result, "incl_hebi")
    ws3 = wb.create_sheet("附表")
    _render_fubei_sheet(ws3, result)
    wb.save(out_path)
    logger.info(f"[v0.2渲染] xlsx已保存: {out_path}")
    return str(out_path)


def render_all(result, output_dir=None):
    """渲染全部输出物，返回 {xlsx, png, png_hebi}"""
    output_dir = output_dir or OUTPUT_DIR
    rd = result["report_date"]
    xlsx_path = output_dir / f"每日通报{rd}.xlsx"
    png_path = output_dir / f"每日通报{rd}.png"
    png_hebi = output_dir / f"每日通报{rd}（含鹤壁）.png"
    out = {
        "xlsx": render_xlsx(result, xlsx_path),
        "png": render_png(result, png_path, "excl_hebi"),
        "png_hebi": render_png(result, png_hebi, "incl_hebi"),
    }
    return out
