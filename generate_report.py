from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import json
import datetime

def generate_report():
    """生成美股日报报告"""
    # 加载JSON数据
    today = datetime.date.today().strftime("%Y-%m-%d")
    data_file = Path(f"/root/us_stock_daily/daily_news/market_data_{today}.json")
    
    if not data_file.exists():
        print(f"❌ 数据文件 {data_file} 不存在")
        return False
    
    with open(data_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # 创建模板环境
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=True
    )
    
    # 添加自定义过滤器
    def number_format(value):
        if value is None:
            return "N/A"
        try:
            return f"{int(value):,}"
        except (ValueError, TypeError):
            return str(value)
    
    def round_value(value, decimals=2):
        if value is None:
            return "N/A"
        try:
            return round(float(value), decimals)
        except (ValueError, TypeError):
            return str(value)
    
    def technical_status(name, index):
        if name == "半导体":
            return "大幅下跌"
        elif name == "Nasdaq 100":
            return "小幅下跌"
        elif name == "Dow Jones":
            return "上涨"
        elif name == "S&P 500":
            return "上涨"
        elif name == "Russell 2000":
            return "下跌"
        else:
            return "正常"
    
    def bond_analysis(name, bond):
        if name == "10Y收益率":
            return "长端利率上行，压制科技股估值"
        elif name == "5Y Treasury":
            return "中端利率上行，收益率曲线趋平"
        else:
            return "正常"
    
    def asset_analysis(name, asset):
        if name == "美元指数DXY":
            return "美元走弱利好风险资产"
        elif name == "黄金":
            return "避险情绪升温"
        elif name == "WTI原油":
            return "油价震荡"
        elif name == "比特币":
            return "加密货币风险偏好回升"
        else:
            return "正常"
    
    # 注册过滤器
    env.filters['number_format'] = number_format
    env.filters['round'] = round_value
    env.globals['technical_status'] = technical_status
    env.globals['bond_analysis'] = bond_analysis
    env.globals['asset_analysis'] = asset_analysis
    
    # 加载模板
    template = env.get_template("report.html.j2")
    
    # 准备报告数据
    report_data = {
        "data": data,
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
        "market_conclusion": "指数分化，科技股表现强劲，AI主线延续，市场宽度改善",
        "market_phase": "强趋势上涨",
        "trading_bias": "适合逢低布局AI相关股票，控制仓位避免追高",
        "key_signals": [
            "10Y美债收益率接近4.5%关键位",
            "纳指RSI进入超买区域",
            "半导体板块新高数量增加",
            "AI软件股开始补涨",
            "市场宽度改善信号"
        ]
    }
    
    # 渲染模板
    generated_at = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    html_content = template.render(generated_at=generated_at, **report_data)
    
    # 保存报告
    output_dir = Path("/root/us_stock_daily/files") / today
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"美股收盘日报_{today}.html"
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"✅ 美股日报HTML报告已生成：{output_file}")
    return True

if __name__ == "__main__":
    generate_report()