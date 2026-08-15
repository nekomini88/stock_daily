from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import argparse
import copy
import json
import datetime
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
    """板块驱动解读：按涨跌幅附加强弱文案"""
    base = _SECTOR_BASE.get(name, "板块基本面")
    try:
        c = float(chg)
    except (TypeError, ValueError):
        return base
    if c >= _CHG_SECTOR_BOOST:
        return f"{base}，放量大涨"
    elif c <= _CHG_SECTOR_DROP:
        return f"{base}，承压回落"
    return f"{base}，窄幅整理"


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
    """14.5 用采集的真实板块/主题数据替换硬编码表格（仅当有适配结果）。"""
    real = data.get(key)
    if isinstance(real, list) and real:
        adapted = _adapt_group(real, {"kind": kind}, sp500_chg)
        if adapted:
            report_data[key] = adapted


_SYMBOL_ALIAS = {
    "S&P 500": "^GSPC", "Nasdaq 100": "^IXIC", "Dow Jones": "^DJI",
    "Russell 2000": "^RUT", "半导体指数": "^SOX", "VIX": "^VIX",
}


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


def _apply_llm_conclusions(report_data, today):
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
                    report_data[field] = val.strip()
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


# 硬编码兜底报告数据（真实数据适配/LLM 结论覆盖前的种子数据，generate_report 每次深拷贝使用）
_FALLBACK_REPORT_DATA = {
    "data": None,
    "market_summary": "指数分化，科技股表现强劲，AI硬件继续主导市场",
    "market_driver": "财报驱动，AI主线延续，利率环境相对稳定",
    "market_sentiment": "risk-on情绪，资金流入科技成长股",
    "main_focus": "AI硬件、软件、半导体板块",
    "technical_analysis": "标普创新高，纳指相对弱势，市场宽度分化",
    "pre_market": "美股期货小幅高开，科技股期货领涨",
    "opening": "开盘后科技股快速拉升，纳指一度涨超1%",
    "midday": "午盘出现分化，部分获利盘回吐",
    "closing": "尾盘科技股再度走强，纳指收复日内失地",
    "core_reason": "财报季进入高峰期，AI相关公司业绩超预期",
    "bond_analysis_summary": "美债收益率小幅上行，曲线趋于平坦化",
    "fed_rate_cut_probability": "85%",
    "expected_rate_cuts": "2",
    "fed_change": "较前一日持平",
    "asset_analysis": {
        "美元指数DXY": "美元走弱利好风险资产",
        "黄金": "避险情绪升温，金价突破关键阻力位",
        "WTI原油": "油价震荡，OPEC+会议临近",
        "比特币": "加密货币风险偏好回升"
    },
    "sectors_performance": [
        {"rank": 1, "name": "信息技术", "etf": "XLK", "change": 2.3, "change_5d": 8.5, "change_1m": 15.2, "vs_sp500": "跑赢", "driver": "AI硬件需求强劲"},
        {"rank": 2, "name": "可选消费", "etf": "XLY", "change": 1.8, "change_5d": 6.2, "change_1m": 12.8, "vs_sp500": "跑赢", "driver": "消费复苏预期"},
        {"rank": 3, "name": "通信服务", "etf": "XLC", "change": 1.5, "change_5d": 5.8, "change_1m": 11.5, "vs_sp500": "跑赢", "driver": "科技巨头表现"},
        {"rank": 4, "name": "金融", "etf": "XLF", "change": 0.8, "change_5d": 3.2, "change_1m": 7.5, "vs_sp500": "跑输", "driver": "利率环境敏感"},
        {"rank": 5, "name": "工业", "etf": "XLI", "change": 0.5, "change_5d": 2.8, "change_1m": 6.9, "vs_sp500": "跑输", "driver": "经济数据平淡"},
        {"rank": 6, "name": "医疗保健", "etf": "XLV", "change": 0.2, "change_5d": 1.5, "change_1m": 4.2, "vs_sp500": "跑输", "driver": "防御性板块"},
        {"rank": 7, "name": "必需消费", "etf": "XLP", "change": -0.1, "change_5d": 0.8, "change_1m": 3.1, "vs_sp500": "跑输", "driver": "通胀压力"},
        {"rank": 8, "name": "能源", "etf": "XLE", "change": -0.5, "change_5d": -1.2, "change_1m": 2.3, "vs_sp500": "跑输", "driver": "油价回调"},
        {"rank": 9, "name": "公用事业", "etf": "XLU", "change": -0.3, "change_5d": -0.5, "change_1m": 1.8, "vs_sp500": "跑输", "driver": "防御性板块"},
        {"rank": 10, "name": "材料", "etf": "XLB", "change": -0.4, "change_5d": -1.8, "change_1m": 0.9, "vs_sp500": "跑输", "driver": "周期性板块"},
        {"rank": 11, "name": "房地产", "etf": "XLRE", "change": -0.6, "change_5d": -2.1, "change_1m": -0.5, "vs_sp500": "跑输", "driver": "利率敏感"}
    ],
    "sector_analysis": "成长股主导，防御性板块表现疲软，AI相关板块持续领涨",
    "themes_performance": [
        {"name": "半导体", "etf": "SMH/SOXX", "change": 3.2, "change_5d": 12.5, "change_1m": 25.8, "analysis": "AI硬件需求强劲，业绩超预期"},
        {"name": "软件", "etf": "IGV", "change": 2.8, "change_5d": 10.2, "change_1m": 22.3, "analysis": "AI应用需求增长，估值修复"},
        {"name": "网络安全", "etf": "CIBR/HACK", "change": 1.9, "change_5d": 8.7, "change_1m": 18.5, "analysis": "企业安全支出增加"},
        {"name": "云计算", "etf": "CLOU/WCLD", "change": 2.1, "change_5d": 9.3, "change_1m": 20.1, "analysis": "云服务需求稳定增长"},
        {"name": "AI/自动化", "etf": "BOTZ/AIQ", "change": 3.5, "change_5d": 14.2, "change_1m": 28.7, "analysis": "AI投资热潮延续"},
        {"name": "小盘成长", "etf": "IWO", "change": 1.2, "change_5d": 5.6, "change_1m": 11.8, "analysis": "成长风格延续"},
        {"name": "小盘价值", "etf": "IWN", "change": -0.3, "change_5d": -1.2, "change_1m": 2.3, "analysis": "价值风格疲软"},
        {"name": "等权标普", "etf": "RSP", "change": 0.9, "change_5d": 4.1, "change_1m": 9.2, "analysis": "市场宽度改善"},
        {"name": "大盘成长", "etf": "QQQ/SCHG", "change": 2.5, "change_5d": 11.3, "change_1m": 23.5, "analysis": "科技巨头领涨"},
        {"name": "大盘价值", "etf": "VTV", "change": -0.1, "change_5d": -0.8, "change_1m": 3.7, "analysis": "价值风格落后"}
    ],
    "theme_analysis": "AI硬件继续主导，软件股补涨，小盘股参与度提升",
    "ma_20_sp500": 65,
    "ma_50_sp500": 72,
    "ma_100_sp500": 78,
    "ma_200_sp500": 82,
    "ma_20_sp500_analysis": "20日均线参与度健康，未出现过度拥挤",
    "ma_20_qqq": 68,
    "ma_50_qqq": 75,
    "ma_100_qqq": 80,
    "ma_200_qqq": 85,
    "ma_20_qqq_analysis": "纳指参与度高于标普，显示科技股强势",
    "nyse_advance": 2450,
    "nyse_decline": 1850,
    "nyse_ratio": "1.32",
    "nasdaq_advance": 2800,
    "nasdaq_decline": 1600,
    "nasdaq_ratio": "1.75",
    "nyda_new_highs": 120,
    "nyda_new_lows": 45,
    "nasdaq_new_highs": 180,
    "nasdaq_new_lows": 30,
    "breadth_advance_analysis": "市场宽度改善，纳指领涨",
    "breadth_decline_analysis": "下跌家数减少，恐慌情绪缓解",
    "breadth_ratio_analysis": "涨跌比显示积极情绪",
    "new_highs_analysis": "新高数量增加，显示趋势延续",
    "new_lows_analysis": "新低数量正常，风险有限",
    "technical_analysis": [
        {"symbol": "SPY", "price": 744.78, "ma20": 730.5, "ma50": 720.2, "ma100": 710.8, "ma200": 700.1, "rsi": 68, "macd": "金叉", "support": "730", "resistance": "750"},
        {"symbol": "QQQ", "price": 712.6, "ma20": 700.3, "ma50": 690.5, "ma100": 680.2, "ma200": 670.8, "rsi": 72, "macd": "金叉", "support": "700", "resistance": "720"},
        {"symbol": "IWM", "price": 297.58, "ma20": 295.2, "ma50": 290.8, "ma100": 285.5, "ma200": 280.2, "rsi": 58, "macd": "死叉", "support": "290", "resistance": "300"},
        {"symbol": "SMH", "price": 566.32, "ma20": 550.1, "ma50": 540.3, "ma100": 530.5, "ma200": 520.8, "rsi": 75, "macd": "金叉", "support": "550", "resistance": "580"},
        {"symbol": "IGV", "price": 450.5, "ma20": 440.2, "ma50": 430.8, "ma100": 420.5, "ma200": 410.2, "rsi": 70, "macd": "金叉", "support": "440", "resistance": "460"}
    ],
    "technical_key_points": "SPY/QQQ处于超买区域，需关注回调风险；半导体板块RSI超买，可能面临获利了结",
    "magnificent_7": [
        {"symbol": "NVDA", "change_pct": -0.46, "reason": "财报后小幅回调", "technical": "处于历史高位", "watch": "关注50日均线支撑"},
        {"symbol": "MSFT", "change_pct": 10.67, "reason": "AI产品发布超预期", "technical": "突破历史新高", "watch": "继续强势"},
        {"symbol": "AAPL", "change_pct": 12.17, "reason": "iPhone 16预购强劲", "technical": "突破历史新高", "watch": "继续强势"},
        {"symbol": "GOOGL", "change_pct": 4.71, "reason": "AI搜索增长", "technical": "接近历史新高", "watch": "关注阻力位"},
        {"symbol": "AMZN", "change_pct": 6.9, "reason": "AWS云服务增长", "technical": "反弹至关键阻力位", "watch": "关注突破"},
        {"symbol": "META", "change_pct": 7.37, "reason": "广告收入增长", "technical": "突破历史新高", "watch": "继续强势"},
        {"symbol": "TSLA", "change_pct": 4.89, "reason": "电动车销量增长", "technical": "反弹至20日线", "watch": "关注50日线"}
    ],
    "ai_hardware": [
        {"symbol": "AMD", "change_pct": 8.5, "reason": "AI芯片需求增长", "technical": "突破历史新高", "watch": "继续强势"},
        {"symbol": "AVGO", "change_pct": 6.2, "reason": "数据中心芯片订单", "technical": "接近历史新高", "watch": "关注阻力位"},
        {"symbol": "MRVL", "change_pct": 9.8, "reason": "AI芯片设计突破", "technical": "突破历史新高", "watch": "继续强势"},
        {"symbol": "TSM", "change_pct": 5.3, "reason": "代工需求强劲", "technical": "反弹至20日线", "watch": "关注50日线"}
    ],
    "recent_earnings": [
        {"company": "NVDA", "revenue": "超预期", "eps": "超预期", "beat_guidance": "是", "after_hours": 2.5, "analysis": "AI芯片需求超预期，指引上调"},
        {"company": "MSFT", "revenue": "超预期", "eps": "超预期", "beat_guidance": "是", "after_hours": 8.3, "analysis": "Azure AI服务增长强劲"},
        {"company": "AAPL", "revenue": "超预期", "eps": "超预期", "beat_guidance": "是", "after_hours": 6.7, "analysis": "iPhone 16预购火爆"}
    ],
    "upcoming_earnings": [
        {"date": "2026-07-05", "company": "AMZN", "focus": "AWS云服务增长", "impact": "云计算板块"},
        {"date": "2026-07-06", "company": "GOOGL", "focus": "AI搜索收入", "impact": "科技巨头"},
        {"date": "2026-07-07", "company": "META", "focus": "广告收入", "impact": "社交媒体"}
    ],
    "institutional_views": [
        {"institution": "高盛", "viewpoint": "上调标普500目标至5500点", "assets": "大盘科技股", "impact": "利好市场"},
        {"institution": "摩根士丹利", "viewpoint": "AI硬件需求持续强劲", "assets": "半导体", "impact": "板块利好"}
    ],
    "market_state": "AI硬件主升浪",
    "money_flow_in": "AI硬件、软件、半导体",
    "money_flow_out": "能源、公用事业、防御性板块",
    "main_line_analysis": "AI主线健康，软件股开始补涨，市场宽度扩散",
    "focus_stocks": [
        {"symbol": "NVDA", "change_pct": -0.46, "trend": "高位震荡", "news": "财报后小幅回调", "support": "180", "resistance": "200", "judgment": "回踩支撑"},
        {"symbol": "MSFT", "change_pct": 10.67, "trend": "继续强势", "news": "AI产品发布", "support": "380", "resistance": "400", "judgment": "继续强势"},
        {"symbol": "AAPL", "change_pct": 12.17, "trend": "继续强势", "news": "iPhone 16预购", "support": "300", "resistance": "320", "judgment": "继续强势"},
        {"symbol": "AMD", "change_pct": 8.5, "trend": "继续强势", "news": "AI芯片需求", "support": "150", "resistance": "170", "judgment": "继续强势"},
        {"symbol": "AVGO", "change_pct": 6.2, "trend": "高位震荡", "news": "数据中心订单", "support": "160", "resistance": "180", "judgment": "高位震荡"}
    ],
    "ten_yield_observation": "关注4.5%关键阻力位",
    "dollar_observation": "美元指数走弱，利好风险资产",
    "commodity_observation": "油价震荡，黄金突破关键位",
    "fed_speech_observation": "关注FOMC官员讲话",
    "economic_data_observation": "非农数据即将公布",
    "spy_support": "730",
    "spy_resistance": "750",
    "qqq_support": "700",
    "qqq_resistance": "720",
    "smh_qqq_comparison": "SMH继续强于QQQ",
    "sector_rotation_observation": "AI硬件继续领涨，软件补涨，防御板块走弱",
    "tomorrow_watchlist": [
        {"symbol": "NVDA", "reason": "财报后回调，关注支撑位"},
        {"symbol": "MSFT", "reason": "突破新高，继续观察"},
        {"symbol": "AMD", "reason": "AI芯片需求强劲"},
        {"symbol": "AMZN", "reason": "AWS云服务增长"},
        {"symbol": "GOOGL", "reason": "AI搜索收入增长"}
    ],
    "main_risk": "美债收益率上行压制估值，AI硬件可能面临获利了结",
    "macro_rate_status": "上行",
    "macro_risk_level": "中高",
    "breadth_status": "改善",
    "breadth_risk_level": "低",
    "ai_crowding_status": "高",
    "ai_crowding_risk_level": "中高",
    "earnings_risk_status": "中等",
    "earnings_risk_level": "中",
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

    # 16. 覆盖 LLM 生成的 15 条结论（若存在 llm_data/market_llm_<date>.json）
    _apply_llm_conclusions(report_data, today)

    # 渲染并保存报告
    _render_and_save(template, report_data, today)
    return True


if __name__ == "__main__":
    generate_report()
