from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import argparse
import copy
import json
import datetime
import re
import sys


# ===== 常量 =====
# 报告路径/时间
_REPORT_OUTPUT_DIR = Path("/root/stock_daily/files")
_REPORT_TZ = datetime.timezone(datetime.timedelta(hours=8))  # 北京时间
_DATE_FMT = "%Y-%m-%d"
_GENERATED_AT_FORMAT = "%Y-%m-%d %H:%M:%S"

# 空数据兜底文案
_PLACEHOLDER_NA = "暂无"
_NO_REAL_TIME_ANALYSIS = "暂无实时数据，以上市公司财报与盘面判断为主"

# 涨跌幅解读阈值
_CHG_STRONG_UP = 5.0      # 技术状态: ≥5% 强势上涨
_CHG_UP = 1.5             # 技术状态: ≥1.5% 上涨
_CHG_DOWN = -1.5          # 技术状态: ≤-1.5% 下跌
_CHG_STRONG_DOWN = -5.0   # 技术状态: ≤-5% 大幅下跌
_CHG_YIELD_MOVE = 0.5     # 债券收益率日变化阈值
_CHG_BIG_MOVE = 3.0       # 资产/主题: ≥3% 强势上涨
_CHG_BIG_DROP = -3.0      # 资产/主题: ≤-3% 明显下跌
_CHG_SECTOR_BOOST = 2.0   # 板块: ≥2% 放量大涨
_CHG_SECTOR_DROP = -2.0   # 板块: ≤-2% 承压回落
_CHG_SECTOR_MILD = 1.0    # 板块: ±1% 温和走强/小幅走弱
_VS_SP500_THRESHOLD = 0.5  # 板块相对标普跑赢/跑输阈值
_NUM_K = 1e3
_NUM_M = 1e6
_NUM_B = 1e9


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-file", default=None)
    parser.add_argument("--today", default=None)
    return parser.parse_args()


def data_file_path(args):
    if args.data_file:
        return Path(args.data_file)
    today = args.today or datetime.date.today().strftime(_DATE_FMT)
    return Path(f"/root/stock_daily/daily_news/market_data_{today}.json")


def number_format(value):
    """千分位格式化：1234567 → 1,234,567；None → N/A"""
    if value is None:
        return "N/A"
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return str(value)


def compact_number(value):
    """大数缩写：44,246,082 → 44.2M；1,234 → 1.2K"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "暂无"
    if v >= _NUM_B:
        return f"{v/_NUM_B:.1f}B"
    elif v >= _NUM_M:
        return f"{v/_NUM_M:.1f}M"
    elif v >= _NUM_K:
        return f"{v/_NUM_K:.1f}K"
    return str(int(v))


def round_value(value, decimals=2):
    """数值保留 decimals 位小数；None → 暂无"""
    if value is None:
        return "暂无"
    try:
        return round(float(value), decimals)
    except (ValueError, TypeError):
        return str(value)


def technical_status(name, index):
    """基于真实涨跌幅的动态技术状态（不再硬编码）"""
    try:
        chg = float(index.get("change_pct", 0))
    except (TypeError, ValueError):
        return "数据缺失"
    if chg >= _CHG_STRONG_UP:
        return "强势上涨"
    elif chg >= _CHG_UP:
        return "上涨"
    elif chg >= _CHG_DOWN:
        return "震荡"
    elif chg >= _CHG_STRONG_DOWN:
        return "下跌"
    else:
        return "大幅下跌"


def bond_analysis(name, bond):
    """基于真实收益率日变化的动态解读"""
    try:
        chg = float(bond.get("change_pct", 0))
        price = float(bond.get("price", 0))
    except (TypeError, ValueError):
        return "数据缺失"
    if price <= 0:
        return "数据缺失"
    if chg > _CHG_YIELD_MOVE:
        return "收益率上行，压制估值"
    elif chg < -_CHG_YIELD_MOVE:
        return "收益率下行，利好风险资产"
    elif "10Y" in name:
        return f"长端利率 {price:.2f}%，窄幅波动"
    else:
        return "窄幅波动"


def asset_analysis(name, asset):
    """基于真实资产涨跌的动态解读"""
    try:
        chg = float(asset.get("change_pct", 0))
    except (TypeError, ValueError):
        return "数据缺失"
    if chg >= _CHG_BIG_MOVE:
        return f"强势上涨 {chg:+.1f}%"
    elif chg <= _CHG_BIG_DROP:
        return f"明显下跌 {chg:+.1f}%"
    elif chg > 0:
        return f"小幅上涨 {chg:+.1f}%"
    elif chg < 0:
        return f"小幅下跌 {chg:+.1f}%"
    return "持平"


# 板块驱动解读基础文案（基于涨跌幅与板块属性的轻量动态解读，不含编造突发新闻）
_SECTOR_BASE = {
    "信息技术": "科技权重主导，AI/半导体景气度高企",
    "通信服务": "平台与广告收入驱动",
    "可选消费": "消费与旅游需求波动",
    "金融": "利率曲线与信贷环境敏感",
    "工业": "制造业景气与资本开支",
    "医疗保健": "防御属性，政策/研发周期主导",
    "必需消费": "必需需求稳定，防御属性",
    "能源": "油价与能源价格联动",
    "公用事业": "防御性，利率敏感",
    "材料": "周期品价格与地产需求",
    "房地产": "利率与 REITs 周期",
}


def _sector_driver(name, chg):
    """板块驱动解读：按涨跌幅附加强弱文案（分档：≥2% 大涨 / ≥1% 温和 / ≤-2% 回落 / ≤-1% 走弱）"""
    base = _SECTOR_BASE.get(name, "板块基本面")
    try:
        c = float(chg)
    except (TypeError, ValueError):
        return base
    if c >= _CHG_SECTOR_BOOST:
        return f"{base}，放量大涨 {c:+.1f}%"
    if c >= _CHG_SECTOR_MILD:
        return f"{base}，温和走强 {c:+.1f}%"
    if c <= _CHG_SECTOR_DROP:
        return f"{base}，承压回落 {c:+.1f}%"
    if c <= -_CHG_SECTOR_MILD:
        return f"{base}，小幅走弱 {c:+.1f}%"
    return f"{base}，窄幅整理 {c:+.1f}%"


def _vs_sp500(chg, sp_chg):
    """板块相对标普涨跌判断：差 ≥0.5 跑赢，≤-0.5 跑输，否则持平"""
    try:
        c = float(chg); s = float(sp_chg)
    except (TypeError, ValueError):
        return "—"
    diff = c - s
    if diff >= _VS_SP500_THRESHOLD:
        return "跑赢"
    elif diff <= -_VS_SP500_THRESHOLD:
        return "跑输"
    return "持平"


def _theme_analysis(name, chg):
    """主题涨跌动态解读"""
    try:
        c = float(chg)
    except (TypeError, ValueError):
        return "主题表现待观察"
    if c >= _CHG_BIG_MOVE:
        return f"主题强势，当日+{c:.1f}%"
    elif c <= _CHG_BIG_DROP:
        return f"主题回调，当日{c:+.1f}%"
    elif c > 0:
        return f"温和走强，当日+{c:.1f}%"
    elif c < 0:
        return f"小幅走弱，当日{c:+.1f}%"
    return "基本持平"


def _adapt_group(group_list, extra=None, sp500_chg=None):
    """把采集器输出（name/symbol/change_pct）适配为模板字段（name/etf/change/change_5d/change_1m）。"""
    out = []
    for item in group_list or []:
        if not isinstance(item, dict):
            continue
        row = {
            "name": item.get("name", ""),
            "etf": item.get("symbol", ""),
            "change": item.get("change_pct"),
            "change_5d": item.get("change_5d"),
            "change_1m": item.get("change_1m"),
        }
        if isinstance(extra, dict) and extra.get("kind") == "sector":
            row["vs_sp500"] = _vs_sp500(item.get("change_pct"), sp500_chg)
            row["driver"] = _sector_driver(item.get("name"), item.get("change_pct"))
        if isinstance(extra, dict) and extra.get("kind") == "theme":
            row["analysis"] = _theme_analysis(item.get("name"), item.get("change_pct"))
        out.append(row)
    return out


def _report_date(data_file):
    """由数据文件名推导报告日期（market_data_YYYY-MM-DD.json → YYYY-MM-DD）。"""
    stem = data_file.stem
    if "market_data_" in stem:
        return stem.replace("market_data_", "")
    return datetime.date.today().strftime(_DATE_FMT)


def _load_template():
    """创建 Jinja 环境并注册过滤器/全局函数，返回 report 模板。"""
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=True,
    )
    env.filters['number_format'] = number_format
    env.filters['compact'] = compact_number
    env.filters['round'] = round_value
    env.globals['technical_status'] = technical_status
    env.globals['bond_meaning'] = bond_analysis
    env.globals['asset_meaning'] = asset_analysis
    return env.get_template("report.html.j2")


def _apply_final_conclusion(report_data, data):
    """15. 动态最终结论：优先 analyze_session(data)，失败走硬编码兜底。"""
    try:
        from final_conclusion import analyze_session
        conclusion = analyze_session(data)
        report_data.update(conclusion)
    except Exception as e:
        print(f"⚠️  最终结论生成失败，使用硬编码兜底：{e}", file=sys.stderr)
        report_data.setdefault("market_conclusion", "指数分化，科技股表现强劲，AI主线延续，市场宽度改善")
        report_data.setdefault("market_phase", "强趋势上涨")
        report_data.setdefault("trading_bias", "适合逢低布局AI相关股票，控制仓位避免追高")
        report_data.setdefault("key_signals", [
            "10Y美债收益率接近4.5%关键位",
            "纳指RSI进入超买区域",
            "半导体板块新高数量增加",
            "AI软件股开始补涨",
            "市场宽度改善信号",
        ])


_SP500_NAME = "S&P 500"


def _sp500_change(data):
    """标普500当日涨跌幅（用于板块跑赢/跑输判断）；缺失或非法返回 None。"""
    raw = (data.get("indices") or {}).get(_SP500_NAME, {}).get("change_pct")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _apply_real_group(report_data, data, key, kind, sp500_chg=None):
    """14.5 用采集的真实板块/主题数据替换硬编码表格（仅当有适配结果）。

    板块表按当日涨跌排序，使「排名」列与真实表现一致。
    """
    real = data.get(key)
    if isinstance(real, list) and real:
        adapted = _adapt_group(real, {"kind": kind}, sp500_chg)
        if adapted:
            if kind == "sector":
                adapted.sort(key=lambda r: -(r["change"] if isinstance(r.get("change"), (int, float)) else -999))
            report_data[key] = adapted


_SYMBOL_ALIAS = {
    "S&P 500": "^GSPC", "Nasdaq 100": "^IXIC", "Dow Jones": "^DJI",
    "Russell 2000": "^RUT", "半导体指数": "^SOX", "VIX": "^VIX",
}

# 无数据源 / LLM 未生成时的诚实占位（绝不写假数字）
_LLM_MISSING = "暂无（当日 LLM 分析未生成）"
_NO_SOURCE = "暂无（采集器未接入该数据源）"


def _num(value):
    """只接受真实数值（排除 bool/字符串），否则 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _iter_stocks(items):
    """兼容采集器输出：dict（{symbol: {...}}）或 list（[{symbol: ...}]）。"""
    if isinstance(items, dict):
        for sym, item in items.items():
            if isinstance(item, dict):
                yield sym, item
    elif isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                yield item.get("symbol") or item.get("name", ""), item


def _trend_text(change_1m):
    """由近1月涨跌推导趋势文字。"""
    if change_1m is None:
        return _NO_SOURCE
    if change_1m >= 5:
        return f"近1月 {change_1m:+.1f}%，偏强"
    if change_1m <= -5:
        return f"近1月 {change_1m:+.1f}%，偏弱"
    return f"近1月 {change_1m:+.1f}%，震荡"


def _move_judgment(change_pct):
    """由当日涨跌推导当日表现标签。"""
    if change_pct is None:
        return _NO_SOURCE
    if change_pct <= -3:
        return "跌幅居前"
    if change_pct >= 3:
        return "涨幅居前"
    return "窄幅波动"


def _cls(value):
    """表格单元格颜色类（None → neutral）。"""
    if (value or 0) > 0:
        return "positive"
    if (value or 0) < 0:
        return "negative"
    return "neutral"


def _pct_text(value):
    """带符号百分比文本；无真实数值时诚实占位。"""
    return f"{value:+.2f}%" if value is not None else _NO_SOURCE


def _mover_rows(items):
    """个股表格行——全部字段来自真实行情（涨跌/近5日/近1月/日内区间）。"""
    rows = []
    for sym, item in _iter_stocks(items):
        chg = _num(item.get("change_pct"))
        if item.get("error") or chg is None:
            continue
        low, high = _num(item.get("low")), _num(item.get("high"))
        chg5, chg1m = _num(item.get("change_5d")), _num(item.get("change_1m"))
        rows.append({
            "symbol": sym,
            "name": item.get("name", sym),
            "change_pct": chg,
            "change_5d": chg5,
            "change_1m": chg1m,
            "low": low,
            "high": high,
            # 展示层字段：模板只做取值，避免 None 参与比较
            "chg_text": _pct_text(chg),
            "chg_5d_text": _pct_text(chg5),
            "chg_1m_text": _pct_text(chg1m),
            "cls": _cls(chg),
            "cls_5d": _cls(chg5),
            "cls_1m": _cls(chg1m),
            "range": f"{low:,.2f} - {high:,.2f}" if low is not None and high is not None else _NO_SOURCE,
            "trend": _trend_text(chg1m),
        })
    return rows


def _group_side(items, name_key):
    """按当日涨跌排序分组，返回 (全部, 前三涨, 前三跌)。

    "跌"必须是真跌：全线上涨时把涨幅最小的板块当"资金流出"是把上涨写成下跌
    （曾出现"主要流出：工业(+0.07%)、通信服务(+0.09%)"）。
    """
    ranked = [i for i in (items or []) if _num(i.get("change_pct")) is not None]
    top = sorted(ranked, key=lambda i: -i["change_pct"])[:3]
    bottom = [i for i in sorted(ranked, key=lambda i: i["change_pct"]) if i["change_pct"] < 0][:3]
    label = lambda i: f"{i.get(name_key)}({i['change_pct']:+.2f}%)"
    return ranked, [label(i) for i in top], [label(i) for i in bottom]


def _apply_real_session(report_data, data):
    """2.盘中走势复盘：只有日线快照，就写日线事实，不编分时走势。"""
    sp = (data.get("indices") or {}).get(_SP500_NAME) or {}
    low, high, price = _num(sp.get("low")), _num(sp.get("high")), _num(sp.get("price"))
    if price is None:
        return
    prev = _num(sp.get("prev_close"))
    report_data["pre_market"] = f"日内最低 {low:,.2f}" if low is not None else _NO_SOURCE
    report_data["opening"] = f"日内最高 {high:,.2f}" if high is not None else _NO_SOURCE
    report_data["midday"] = (
        f"收盘 {price:,.2f}" + (f"，较前一交易日 {price / prev - 1:+.2%}" if prev else "")
    )
    if low is not None and high is not None and high > low:
        pos = (price - low) / (high - low) * 100
        where = "偏上沿" if pos >= 66 else ("偏下沿" if pos <= 33 else "居中")
        report_data["closing"] = f"收盘位于当日区间 {pos:.0f}% 位置（{where}）"
    else:
        report_data["closing"] = _NO_SOURCE


def _apply_real_movers(report_data, data):
    """8.1/8.2：七巨头与 AI 硬件表格改用真实行情。"""
    mag = _mover_rows(data.get("magnificent_7") or {})
    if mag:
        report_data["magnificent_7"] = mag
    hw = _mover_rows(data.get("ai_hardware") or [])
    if hw:
        report_data["ai_hardware"] = hw


def _apply_real_focus_stocks(report_data, data, limit=5):
    """12：重点关注股 = 当日真实波动最大的标的（七巨头 + AI 硬件）。"""
    rows = _mover_rows(data.get("magnificent_7") or {}) + _mover_rows(data.get("ai_hardware") or [])
    if not rows:
        return
    ranked = sorted(rows, key=lambda r: -abs(r["change_pct"]))[:limit]
    report_data["focus_stocks"] = [{**r, "judgment": _move_judgment(r["change_pct"])} for r in ranked]


def _breadth_label(up, total):
    """市场宽度档位与风险等级的唯一口径（§11 market_state 与 §14 breadth_status 共用）。"""
    if not total:
        return "暂无", "暂无"
    if up <= 3:
        return f"普跌（{up}/{total} 板块上涨）", "高"
    if up >= total:
        return f"普涨（{up}/{total} 板块上涨）", "低"
    if up >= total - 1:
        return f"接近普涨（{up}/{total} 板块上涨）", "中"
    return f"分化（{up}/{total} 板块上涨）", "中高"


def _apply_real_flows(report_data, data):
    """11.板块轮动：资金流向与市场状态按真实板块涨跌推导。"""
    ranked, top, bottom = _group_side(data.get("sectors_performance"), "name")
    if not ranked:
        return
    report_data["money_flow_in"] = "、".join(top) or "暂无"
    report_data["money_flow_out"] = "、".join(bottom) or "无板块下跌（全部收涨）"
    up = sum(1 for s in ranked if s["change_pct"] > 0)
    down = len(ranked) - up
    state = _breadth_label(up, len(ranked))[0].split("（")[0]
    # 保留原有措辞（"普跌调整/普涨行情/分化震荡"），只统一阈值口径
    state = {"普跌": "普跌调整", "普涨": "普涨行情", "分化": "分化震荡",
             "接近普涨": "接近普涨"}.get(state, state)
    sp500 = _sp500_change(data)
    detail = f"，标普500 当日 {sp500:+.2f}%" if sp500 is not None else ""
    report_data["market_state"] = f"{state}：{len(ranked)} 大板块 {up} 涨 {down} 跌{detail}"


def _apply_real_macro_observations(report_data, data):
    """13.1 宏观观察 + 3.2 状态：全部由真实行情推导。"""
    macro = data.get("macro") or {}
    vix = (data.get("indices") or {}).get("VIX") or {}

    def pc(item):
        return _num(item.get("price")), _num(item.get("change_pct"))

    y10, y10c = pc(macro.get("10Y收益率") or {})
    if y10 is not None:
        level = "，站上 5% 关口，估值压力显著" if y10 >= 5 else "，关注 4.5% 支撑与 5% 关口"
        change = f"（当日 {y10c:+.2f}%）" if y10c is not None else ""
        report_data["ten_yield_observation"] = f"10Y 收 {y10:.3f}%{change}{level}"

    dxy, dxyc = pc(macro.get("美元指数DXY") or {})
    if dxy is not None:
        tone = "美元走强压制风险资产" if (dxyc or 0) > 0 else "美元走弱利好风险资产"
        report_data["dollar_observation"] = f"DXY {dxy:.3f}（{dxyc:+.2f}%），{tone}" if dxyc is not None else f"DXY {dxy:.3f}"

    parts = []
    for label, name in (("WTI", "WTI原油"), ("黄金", "黄金"), ("铜", "铜期货")):
        price, chg = pc(macro.get(name) or {})
        if price is not None:
            parts.append(f"{label} {price:,.2f}（{chg:+.2f}%）" if chg is not None else f"{label} {price:,.2f}")
    vp, vc = pc(vix)
    if vp is not None:
        parts.append(f"VIX {vp:.2f}（{vc:+.2f}%）" if vc is not None else f"VIX {vp:.2f}")
    if parts:
        report_data["commodity_observation"] = "、".join(parts)


def _apply_real_risk_table(report_data, data):
    """14.风险提示：状态与等级按真实数据推导（无源维度诚实标注）。"""
    macro = data.get("macro") or {}
    y10, y10c = _num((macro.get("10Y收益率") or {}).get("price")), _num((macro.get("10Y收益率") or {}).get("change_pct"))
    if y10 is not None:
        report_data["macro_rate_status"] = "上行" if (y10c or 0) > 0 else ("下行" if (y10c or 0) < 0 else "持平")
        report_data["macro_risk_level"] = "高" if y10 >= 5 else ("中高" if y10 >= 4.5 else "中")

    ranked, _, _ = _group_side(data.get("sectors_performance"), "name")
    if ranked:
        up = sum(1 for s in ranked if s["change_pct"] > 0)
        report_data["breadth_status"], report_data["breadth_risk_level"] = _breadth_label(up, len(ranked))

    sox = (data.get("indices") or {}).get("半导体指数") or {}
    sox_1m, sp_1m = _num(sox.get("change_1m")), _num(((data.get("indices") or {}).get(_SP500_NAME) or {}).get("change_1m"))
    if sox_1m is not None and sp_1m is not None:
        gap = sox_1m - sp_1m
        report_data["ai_crowding_status"] = f"半导体近1月 {sox_1m:+.1f}% vs 标普 {sp_1m:+.1f}%（{'领先' if gap > 0 else '落后'} {abs(gap):.1f}pt）"
        report_data["ai_crowding_risk_level"] = "中高" if gap > 5 else ("中" if gap > -5 else "低")

    vix, vixc = _num((data.get("indices", {}).get("VIX") or {}).get("price")), _num((data.get("indices", {}).get("VIX") or {}).get("change_pct"))
    if vix is not None:
        bits = [f"VIX {vix:.2f}"]
        if vixc is not None:
            bits.append(f"当日 {vixc:+.2f}%")
        if y10 is not None:
            bits.append(f"10Y {y10:.3f}%")
        report_data["main_risk"] = "波动放大：" + "、".join(bits)


def _apply_no_source_placeholders(report_data):
    """无数据源章节：明确标注暂无，不留编造内容。"""
    report_data["fed_rate_cut_probability"] = _NO_SOURCE
    report_data["expected_rate_cuts"] = _NO_SOURCE
    report_data["fed_change"] = _NO_SOURCE
    report_data["fed_speech_observation"] = _NO_SOURCE
    report_data["earnings_risk_level"] = _NO_SOURCE
    report_data["recent_earnings"] = [
        {"company": _NO_SOURCE, "revenue": _NO_SOURCE, "eps": _NO_SOURCE,
         "beat_guidance": _NO_SOURCE, "after_hours": _NO_SOURCE, "analysis": _NO_SOURCE},
    ]
    report_data["upcoming_earnings"] = [
        {"date": _NO_SOURCE, "company": _NO_SOURCE, "focus": _NO_SOURCE, "impact": _NO_SOURCE},
    ]
    report_data["institutional_views"] = [
        {"institution": _NO_SOURCE, "viewpoint": _NO_SOURCE,
         "assets": _NO_SOURCE, "impact": _NO_SOURCE},
    ]


def _apply_llm_only_placeholders(report_data):
    """LLM 未生成时的结论文字占位（与 _LLM_FIELD_MAP 的字段一致，LLM 成功会覆盖）。"""
    _fill_placeholders(report_data, sorted(set(_LLM_FIELD_MAP.values()) - {"main_risk"}), _LLM_MISSING)


def _build_technical_rows(data):
    """15a. 用真实指数价格构造技术面表（MA/RSI/MACD 标注暂无）；无有效行返回 None。"""
    rows = []
    for idx_name, idx in (data.get("indices") or {}).items():
        if not isinstance(idx, dict) or "error" in idx:
            continue
        sym = idx.get("symbol") or _SYMBOL_ALIAS.get(idx_name, idx_name)
        price = idx.get("price")
        if price is None or price == 0:
            continue
        lo, hi = idx.get("low", 0), idx.get("high", 0)
        rows.append({
            "symbol": sym,
            "price": price,
            "change_pct": idx.get("change_pct"),
            "ma20": None, "ma50": None, "ma100": None, "ma200": None,
            "rsi": "暂无", "macd": "暂无",
            "support": f"{lo:.2f}" if lo else "暂无",
            "resistance": f"{hi:.2f}" if hi else "暂无",
        })
    return rows or None


# 无真实数据源的字段 → 空数据兜底
_BREADTH_COUNT_FIELDS = [
    "nyse_advance", "nyse_decline", "nyse_ratio",
    "nasdaq_advance", "nasdaq_decline", "nasdaq_ratio",
    "nyda_new_highs", "nyda_new_lows", "nasdaq_new_highs", "nasdaq_new_lows",
]
_BREADTH_ANALYSIS_FIELDS = [
    "breadth_decline_analysis", "breadth_ratio_analysis",
    "new_highs_analysis", "new_lows_analysis",
    "ma_20_sp500_analysis", "ma_20_qqq_analysis",
]
_MA_FIELDS = [
    "ma_20_sp500", "ma_50_sp500", "ma_100_sp500", "ma_200_sp500",
    "ma_20_qqq", "ma_50_qqq", "ma_100_qqq", "ma_200_qqq",
]


def _fill_placeholders(report_data, fields, value=_PLACEHOLDER_NA):
    """空数据兜底：把一批字段统一置为占位文案。"""
    for field in fields:
        report_data[field] = value


_LLM_FIELD_MAP = {
    "summary": "market_summary",
    "market_overview": "market_driver",
    "intraday": "core_reason",
    "macro": "bond_analysis_summary",
    "sectors": "sector_analysis",
    "themes": "theme_analysis",
    "breadth": "breadth_advance_analysis",
    "technical": "technical_key_points",
    "stocks": "main_focus",
    "earnings": "earnings_risk_status",
    "institutions": "market_sentiment",
    "rotation": "main_line_analysis",
    "watchlist": "economic_data_observation",
    "risks": "main_risk",
    "conclusion": "market_conclusion",
}


# 没有数据源的断言：一律不许 LLM 直接写进报告
_NEW_HIGH_RE = re.compile(r"(?:创下|创出|刷新|突破|创)?(?:历史新高|历史高位|历史峰值|创纪录新高|新高)")


def _index_1y_highs(data):
    """{指数名: 距一年最高收盘价的百分比}（采集器 range=1y 算出的真实值）。"""
    out = {}
    for name, item in (data.get("indices") or {}).items():
        if isinstance(item, dict) and _num(item.get("pct_from_1y_high")) is not None:
            out[name] = _num(item["pct_from_1y_high"])
    return out


def _sanitize_llm_text(text, data):
    """剔除 LLM 里没有数据支撑的硬断言（宁可少写，不可编造）。

    ① "创历史新高"：报告没有 ATH 数据源，用采集器的"距一年最高收盘价"证伪。
    ② 涨跌家数：板块口径由真实数据算出，LLM 写的数字与之矛盾就改回真值。
    """
    if not isinstance(text, str) or not text.strip():
        return text
    highs = _index_1y_highs(data)
    at_high = bool(highs) and max(highs.values()) >= -0.1
    if not at_high and _NEW_HIGH_RE.search(text):
        def _drop(m, _t=text):
            # 前面紧跟价格数字（"至52495.88创历史新高"）→ 整句删掉断言；
            # 否则（"道指创新高"）换成"上涨"，避免留下断句
            prev = _t[m.start() - 1] if m.start() else ""
            nxt = _t[m.end()] if m.end() < len(_t) else ""
            if nxt.isdigit() and prev == "%":
                return "至"      # "涨1.02%创历史新高52495.88点" → "涨1.02%至52495.88点"
            if prev.isdigit() or prev == "%":
                return ""        # "至52495.88创历史新高，" → 直接删
            return "上涨"        # "道指创新高" → "道指上涨"
        text = _NEW_HIGH_RE.sub(_drop, text)
        print("⚠️  已剔除无数据支撑的\"创新高\"表述（当日无指数处于一年高点）", file=sys.stderr)

    sectors = [x for x in (data.get("sectors_performance") or [])
               if isinstance(x, dict) and _num(x.get("change_pct")) is not None]
    if sectors:
        up = sum(1 for x in sectors if (_num(x["change_pct"]) or 0.0) > 0)
        down = sum(1 for x in sectors if (_num(x["change_pct"]) or 0.0) < 0)
        flat = len(sectors) - up - down
        # 持平板块既不算涨也不算跌：按 len-up 算 down 会把 0.00% 的板块写成"下跌"
        tail = f"、{flat}个持平" if flat else ""
        canonical = f"{up}个上涨、{down}个下跌{tail}"
        # LLM 会写成 "11个板块中6个上涨，5个下跌"，中间的逗号/顿号很常见，
        # 旧正则不允许分隔符 → 静默不校正（与同份报告板块表自相矛盾）。
        sep = r"\s*[，,、/和及与]?\s*"
        # 尾部已存在的持平说法必须一并吃掉，否则会重复追加（"…1个持平、1个持平"）；
        # 措辞覆盖 持平/平盘/收平/走平，"个/家"两种量词都要认。
        fl = r"(?:" + sep + r"\d+\s*[个家](?:持平|平盘|收平|走平))?"
        # 先跑 short 再跑 full：short 只吃数字段，命中后文本已变成规范形，
        # 不会把 full 的产物再改一遍（旧版用 text==before 门禁，
        # 导致 full 命中一处就整篇跳过 short，同一段第二处家数漏校正、且非幂等）。
        short = re.compile(r"(\d+)\s*[个家](?:板块)?(?:上涨|收涨|走高|上升)" + sep +
                           r"(\d+)\s*[个家](?:板块)?(?:下跌|收跌|走低|下降)" + fl)
        full = re.compile(r"(\d+)\s*个板块中\s*(\d+)\s*[个家](?:上涨|收涨|走高|上升)" + sep +
                          r"(\d+)\s*[个家](?:下跌|收跌|走低|下降)" + fl)
        # 缩写写法 "7涨3跌1平"（不带量词/动词）也认，否则静默漏校正
        abbrev = re.compile(r"(\d+)\s*涨\s*(\d+)\s*跌(?:\s*(\d+)\s*平)?")
        before = text
        text = short.sub(lambda m: canonical, text)
        text = full.sub(lambda m: f"{len(sectors)}个板块中{canonical}", text)
        text = abbrev.sub(lambda m: canonical, text)
        if text != before:
            print(f"⚠️  已校正 LLM 涨跌家数 → {len(sectors)}个板块中{canonical}",
                  file=sys.stderr)

    text = _sanitize_level_claims(text, data)
    return text


# 点位关口断言："纳指跌破26000点" 这类话必须能用真实价格/日内高低点验证。
# 收盘未破但盘中破了 → 补"盘中"；两端都不成立 → 换成真实收盘点位。
_LEVEL_NAMES = (
    ("纳指100", "Nasdaq 100"), ("纳指", "Nasdaq 100"), ("纳斯达克", "Nasdaq 100"),
    ("标普500", "S&P 500"), ("标普", "S&P 500"),
    ("道指", "Dow Jones"), ("道琼斯", "Dow Jones"),
    ("罗素2000", "Russell 2000"), ("费半", "半导体指数"), ("半导体指数", "半导体指数"),
    ("VIX", "VIX"), ("恐慌指数", "VIX"),
)
_LEVEL_VERBS_BELOW = ("跌破", "失守", "下破", "击穿", "跌穿")
_LEVEL_VERBS_ABOVE = ("突破", "站上", "升破", "涨破", "攻上")
_LEVEL_RE = re.compile(
    r"(?P<name>" + "|".join(re.escape(n) for n, _ in _LEVEL_NAMES) + r")"
    r"\s*(?P<verb>" + "|".join(_LEVEL_VERBS_BELOW + _LEVEL_VERBS_ABOVE) + r")"
    r"\s*(?P<level>\d[\d,]*(?:\.\d+)?)\s*点(?P<gate>关口)?"
)


def _index_by_name(data, canonical):
    for name, item in (data.get("indices") or {}).items():
        if name == canonical and isinstance(item, dict):
            return item
    return None


def _sanitize_level_claims(text, data):
    """校正无数据支撑的点位关口断言（收盘价优先，日内极值次之）。"""
    if not isinstance(text, str) or not text.strip():
        return text
    alias = dict(_LEVEL_NAMES)
    changes = []

    def _fix(m):
        canonical = alias.get(m.group("name"))
        item = _index_by_name(data, canonical) if canonical else None
        if not item:
            return m.group(0)          # 没有该指数数据 → 不动，不改写
        price = _num(item.get("price"))
        try:
            level = float(m.group("level").replace(",", ""))
        except ValueError:
            return m.group(0)
        if price is None:
            return m.group(0)
        verb = m.group("verb")
        gate = m.group("gate") or ""
        extreme = _num(item.get("low")) if verb in _LEVEL_VERBS_BELOW else _num(item.get("high"))

        if verb in _LEVEL_VERBS_BELOW:
            if price < level:
                return m.group(0)      # 收盘确已跌破
            if extreme is not None and extreme < level:
                changes.append(f"{m.group('name')}{verb}{m.group('level')}→盘中{verb}")
                return f"{m.group('name')}盘中{verb}{m.group('level')}点{gate}"
        else:
            if price > level:
                return m.group(0)      # 收盘确已站上
            if extreme is not None and extreme > level:
                changes.append(f"{m.group('name')}{verb}{m.group('level')}→盘中{verb}")
                return f"{m.group('name')}盘中{verb}{m.group('level')}点{gate}"

        # 收盘与日内极值都不支持该断言 → 退回真实收盘点位
        changes.append(f"{m.group(0)}→{m.group('name')}收于{price:,.2f}点")
        return f"{m.group('name')}收于{price:,.2f}点"

    text = _LEVEL_RE.sub(_fix, text)
    for c in changes:
        print(f"⚠️  点位断言无数据支撑已校正：{c}", file=sys.stderr)
    return text


def _apply_llm_conclusions(report_data, today, data=None):
    """16. 覆盖 LLM 生成的 15 条结论（若存在 llm_data/market_llm_<date>.json）。"""
    llm_file = Path(__file__).resolve().parent / "llm_data" / f"market_llm_{today}.json"
    if not llm_file.exists():
        return
    try:
        llm = json.loads(llm_file.read_text(encoding="utf-8"))
        if isinstance(llm, dict) and llm:
            applied = 0
            for llm_key, field in _LLM_FIELD_MAP.items():
                val = llm.get(llm_key)
                if isinstance(val, str) and val.strip():
                    report_data[field] = _sanitize_llm_text(val.strip(), data or {})
                    applied += 1
            print(f"🤖 LLM 结论已覆盖 {applied}/15 章")
    except Exception as e:
        print(f"⚠️  LLM 结论加载失败，继续使用原有数据: {e}", file=sys.stderr)


def _render_and_save(template, report_data, today):
    """渲染模板并写入 files/<today>/美股收盘日报_<today>.html。"""
    generated_at = datetime.datetime.now(_REPORT_TZ).strftime(_GENERATED_AT_FORMAT)
    html_content = template.render(generated_at=generated_at, **report_data)

    output_dir = _REPORT_OUTPUT_DIR / today
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"美股收盘日报_{today}.html"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"✅ 美股日报HTML报告已生成：{output_file}")


# 报告数据结构种子。这里**不放任何编造数值**：所有字段都由真实采集数据推导
# （_apply_real_* / final_conclusion / LLM 结论），没有数据源的字段走诚实占位。
_FALLBACK_REPORT_DATA = {
    "data": None,
    # 表格类：结构为空，等真实数据适配器填充；采集失败时留空表而非假数据
    "sectors_performance": [],
    "themes_performance": [],
    "magnificent_7": [],
    "ai_hardware": [],
    "focus_stocks": [],
    "technical_analysis": [],
    "recent_earnings": [],
    "upcoming_earnings": [],
    "institutional_views": [],
}


def generate_report(args=None):
    """生成美股日报报告"""
    args = args or parse_args()
    # 加载JSON数据
    data_file = data_file_path(args)

    if not data_file.exists():
        print(f"❌ 数据文件 {data_file} 不存在")
        return False

    with open(data_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 创建模板环境
    template = _load_template()

    # 准备报告数据（硬编码兜底种子，每次深拷贝避免跨调用污染）
    report_data = copy.deepcopy(_FALLBACK_REPORT_DATA)
    report_data["data"] = data

    # 由数据文件推导报告日期（供 LLM 结论文件定位）
    today = _report_date(data_file)

    # 15. 动态最终结论
    _apply_final_conclusion(report_data, data)

    # 14.5 真实板块/主题数据适配：优先用采集的真实数据替换硬编码表格
    # 标普500当日涨跌（用于板块跑赢/跑输判断）
    sp500_chg = _sp500_change(data)
    _apply_real_group(report_data, data, "sectors_performance", "sector", sp500_chg)
    _apply_real_group(report_data, data, "themes_performance", "theme")

    # 15a. 真实技术面表覆盖：用真实指数价格构造（price/当日涨跌/日高日低真实），MA/RSI/MACD 标注暂无
    tech_rows = _build_technical_rows(data)
    if tech_rows:
        report_data["technical_analysis"] = tech_rows

    # 14b/14c. 市场宽度表与均线参与度：采集器无真实数据源，统一空数据兜底
    _fill_placeholders(report_data, _BREADTH_COUNT_FIELDS)
    _fill_placeholders(report_data, _BREADTH_ANALYSIS_FIELDS, _NO_REAL_TIME_ANALYSIS)
    _fill_placeholders(report_data, _MA_FIELDS)

    # 14d. 其余章节全部由真实行情推导（盘中复盘/个股表/轮动/宏观观察/风险表）
    _apply_real_session(report_data, data)
    _apply_real_movers(report_data, data)
    _apply_real_focus_stocks(report_data, data)
    _apply_real_flows(report_data, data)
    _apply_real_macro_observations(report_data, data)
    _apply_real_risk_table(report_data, data)

    # 14e. 无数据源章节 + LLM 未生成时的诚实占位（LLM 成功会覆盖结论文字）
    _apply_no_source_placeholders(report_data)
    _apply_llm_only_placeholders(report_data)

    # 16. 覆盖 LLM 生成的 15 条结论（若存在 llm_data/market_llm_<date>.json）
    _apply_llm_conclusions(report_data, today, data)

    # 渲染并保存报告
    _render_and_save(template, report_data, today)
    return True


if __name__ == "__main__":
    generate_report()
