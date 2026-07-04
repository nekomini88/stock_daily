#!/usr/bin/env python3
"""
美股收盘数据收集脚本 - 通过 Yahoo Finance 获取最新收盘数据
为 LLM 分析提供结构化数据输入
"""
import json, sys, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

ETFS = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "DIA": "Dow Jones",
    "IWM": "Russell 2000",
    "SOXX": "半导体",
    "VIX": "VIX",
}

SECTOR_ETFS = {
    "XLK": "信息技术",
    "XLC": "通信服务",
    "XLY": "可选消费",
    "XLF": "金融",
    "XLI": "工业",
    "XLV": "医疗保健",
    "XLP": "必需消费",
    "XLE": "能源",
    "XLU": "公用事业",
    "XLB": "材料",
    "XLRE": "房地产",
}

THEME_ETFS = {
    "SMH": "半导体ETF",
    "SOXX": "半导体指数ETF",
    "IGV": "软件ETF",
    "CIBR": "网络安全ETF",
    "HACK": "网络安全ETF",
    "CLOU": "云计算ETF",
    "WCLD": "云计算ETF",
    "BOTZ": "机器人和人工智能ETF",
    "AIQ": "人工智能和大数据ETF",
    "IWO": " Russell 2000 Growth",
    "IWN": " Russell 2000 Value",
    "RSP": "S&P 500 Equal Weight",
    "VTV": "Vanguard Value",
}

MACRO_INDICATORS = {
    "TNX": "10Y收益率",
    "TYX": "30Y收益率",
    "^TNX": "10Y收益率", # alternative
    "^IRX": "13T国债", # 13-week, maybe not needed
    "^FVX": "5Y Treasury",
    # We'll just use TNX, ^TNX, and maybe ^IRX for 13-week, but we can keep simple
    "DX-Y.NYB": "美元指数DXY",
    "GC=F": "黄金",
    "CL=F": "WTI原油",
    "BTC-USD": "比特币",
    "ETH-USD": "以太坊",
}

MAGS = {
    "NVDA": "NVIDIA",
    "MSFT": "Microsoft",
    "AAPL": "Apple",
    "GOOGL": "Alphabet",
    "AMZN": "Amazon",
    "META": "Meta",
    "TSLA": "Tesla",
}
def fetch_yahoo(symbol):
    """Fetch Yahoo Finance quote data"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        result = data["chart"]["result"][0]
        meta = result["meta"]
        # Get current price and previous close from meta
        price = meta.get("regularMarketPrice", 0)
        prev_close = meta.get("previousClose", 0) or meta.get("chartPreviousClose", 0)
        # Fallback: use last close from timestamps/indicators if prev_close is 0
        if prev_close == 0:
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            closes = [c for c in closes if c]
            if len(closes) >= 2:
                prev_close = closes[-2]
        change_pct = round((price / prev_close - 1) * 100, 2) if prev_close else "暂无"
        return {
            "symbol": symbol,
            "price": price,
            "prev_close": prev_close,
            "change_pct": change_pct,
            "high": meta.get("regularMarketDayHigh", 0),
            "low": meta.get("regularMarketDayLow", 0),
            "volume": meta.get("regularMarketVolume", 0),
        }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

def fetch_futures():
    """Get ES and NQ futures"""
    results = {}
    for sym, name in [("ES=F", "S&P期货"), ("NQ=F", "Nasdaq期货")]:
        r = fetch_yahoo(sym)
        if "error" not in r:
            results[name] = r
    return results

def fetch_macro():
    """Get key macro data points"""
    results = {}
    for sym, name in MACRO_INDICATORS.items():
        r = fetch_yahoo(sym)
        if "error" not in r:
            results[name] = r
    return results

def main():
    date_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    output = {"date": date_str, "timestamp": datetime.now().isoformat()}

    # 1. 大盘指数
    print("📊 获取大盘指数...", file=sys.stderr)
    indices = {}
    for sym, name in ETFS.items():
        r = fetch_yahoo(sym)
        if "error" not in r:
            indices[name] = r
    output["indices"] = indices

    # 2. 七巨头 + 重点个股
    print("📈 获取重点个股...", file=sys.stderr)
    stocks = {}
    for sym in MAGS:
        r = fetch_yahoo(sym)
        if "error" not in r:
            stocks[sym] = r
    output["magnificent_7"] = stocks

    # 3. 期货
    print("🔮 获取期货数据...", file=sys.stderr)
    output["futures"] = fetch_futures()

    # 4. 宏观
    print("🌍 获取宏观数据...", file=sys.stderr)
    output["macro"] = fetch_macro()

    # Save
    output_dir = Path("/root/us_stock_daily/daily_news")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"market_data_{date_str}.json"
    output_file.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"✅ 数据已保存到 {output_file}", file=sys.stderr)
    
    # Output JSON for LLM
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    main()
