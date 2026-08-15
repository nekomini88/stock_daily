#!/usr/bin/env python3
"""
美股收盘数据收集脚本 - 通过 Yahoo Finance 获取最新收盘数据
为 LLM 分析提供结构化数据输入
"""
import json, sys, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 大盘指数——直接用真实点数（而非 ETF 价格）
ETFS = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq 100",
    "^DJI": "Dow Jones",
    "^RUT": "Russell 2000",
    "^SOX": "半导体指数",
    "^VIX": "VIX",
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
    "HACK": "网络安全ETF",
    "WCLD": "云计算ETF",
    "BOTZ": "机器人和人工智能ETF",
    "AIQ": "人工智能和大数据ETF",
    "IWO": " Russell 2000 Growth",
    "IWN": " Russell 2000 Value",
    "RSP": "S&P 500 Equal Weight",
    "VTV": "Vanguard Value",
}

MACRO_INDICATORS = {
    "^TNX": "10Y收益率",
    "^TYX": "30Y收益率",
    "^IRX": "13T国债",
    "^FVX": "5Y Treasury",
    "DX-Y.NYB": "美元指数DXY",
    "GC=F": "黄金",
    "HG=F": "铜期货",
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
def _yahoo_chart(symbol, timeout=15):
    """尝试主备 Yahoo 子域，返回原始 chart JSON（子域轮询容错）"""
    hosts = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
    last_err = None
    for host in hosts:
        url = f"https://{host}/v8/finance/chart/{symbol}?interval=1d&range=1mo"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception as e:
            last_err = e
    raise last_err if last_err else RuntimeError("yahoo unreachable")

# 备用源：Stooq（无 key，CSV 格式）
import csv, io as _io
def _stooq_quote(symbol):
    """Stooq 备用行情，返回 (price, prev_close, closes) 或 None"""
    code = symbol.replace("=", "").replace("^", "").lower()
    url = f"https://stooq.com/q/d/l/?s={code}&i=d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            rows = list(csv.reader(_io.StringIO(resp.read().decode())))
        if len(rows) < 3:
            return None
        header, data = rows[0], rows[1:]
        if "Close" not in header:
            return None
        ci = header.index("Close")
        closes = []
        for r in data[-40:]:
            try:
                closes.append(float(r[ci]))
            except (ValueError, IndexError):
                continue
        if not closes:
            return None
        return closes[-1], closes[-2] if len(closes) > 1 else closes[-1], closes
    except Exception:
        return None

def _parse_chart(data, symbol):
    result = data["chart"]["result"][0]
    meta = result["meta"]
    price = meta.get("regularMarketPrice", 0)
    prev_close = meta.get("previousClose", 0) or meta.get("chartPreviousClose", 0)
    closes = [c for c in result.get("indicators", {}).get("quote", [{}])[0].get("close", []) if c]
    if not closes:
        closes = [price]
    if prev_close == 0:
        if len(closes) >= 2:
            prev_close = closes[-2]
    change_pct = round((price / prev_close - 1) * 100, 2) if prev_close else "暂无"
    change_5d = None
    change_1m = None
    if len(closes) >= 6:
        change_5d = round((closes[-1] / closes[-6] - 1) * 100, 2)
    if len(closes) >= 2:
        change_1m = round((closes[-1] / closes[0] - 1) * 100, 2)
    return {
        "symbol": symbol,
        "price": price,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "change_5d": change_5d,
        "change_1m": change_1m,
        "high": meta.get("regularMarketDayHigh", 0),
        "low": meta.get("regularMarketDayLow", 0),
        "volume": meta.get("regularMarketVolume", 0),
        "source": "yahoo",
    }

def fetch_yahoo(symbol):
    """Fetch quote with multi-period returns. 主源 Yahoo(多子域轮询)，失败降级 Stooq。"""
    try:
        return _parse_chart(_yahoo_chart(symbol), symbol)
    except Exception as e:
        # 降级: Yahoo 失败 → Stooq (记录原因, 不吞掉)
        import sys
        print(f"⚠️ {symbol} Yahoo 源失败, 降级 Stooq: {e}", file=sys.stderr)
    try:
        st = _stooq_quote(symbol)
        if st:
            price, prev, closes = st
            chg = round((price / prev - 1) * 100, 2) if prev else "暂无"
            c5 = round((closes[-1] / closes[-6] - 1) * 100, 2) if len(closes) >= 6 else None
            c1m = round((closes[-1] / closes[0] - 1) * 100, 2) if len(closes) >= 2 else None
            return {
                "symbol": symbol, "price": price, "prev_close": prev,
                "change_pct": chg, "change_5d": c5, "change_1m": c1m,
                "high": "暂无", "low": "暂无", "volume": 0, "source": "stooq",
            }
    except Exception as e:
        # 降级失败: Stooq 也挂了 → 返回 error (记录原因)
        import sys
        print(f"⚠️ {symbol} Stooq 源也失败: {e}", file=sys.stderr)
    return {"symbol": symbol, "error": "all sources failed"}

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

def fetch_group(symbol_map, category="板块"):
    """批量抓取一组证券，按名称输出 {name: {symbol, change_pct, change_5d, change_1m, ...}}"""
    results = {}
    for sym, name in symbol_map.items():
        r = fetch_yahoo(sym)
        if "error" not in r:
            item = {"symbol": sym, "name": name,
                    "price": r.get("price"), "prev_close": r.get("prev_close"),
                    "change_pct": r.get("change_pct"),
                    "change_5d": r.get("change_5d"), "change_1m": r.get("change_1m"),
                    "high": r.get("high"), "low": r.get("low"), "volume": r.get("volume")}
            results[name] = item
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

    # 2.5 板块表现（11 大板块 ETF）
    print("🏢 获取板块表现...", file=sys.stderr)
    output["sectors_performance"] = [
        {**v, "rank": i+1}
        for i, (name, v) in enumerate(fetch_group(SECTOR_ETFS).items())
    ]

    # 2.6 主题与风格表现（AI/半导体/风格 ETF）
    print("🎯 获取主题表现...", file=sys.stderr)
    output["themes_performance"] = [
        {**v, "rank": i+1}
        for i, (name, v) in enumerate(fetch_group(THEME_ETFS).items())
    ]

    # 3. 期货
    print("🔮 获取期货数据...", file=sys.stderr)
    output["futures"] = fetch_futures()

    # 4. 宏观
    print("🌍 获取宏观数据...", file=sys.stderr)
    output["macro"] = fetch_macro()

    # Save
    output_dir = Path("/root/stock_daily/daily_news")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"market_data_{date_str}.json"
    output_file.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"✅ 数据已保存到 {output_file}", file=sys.stderr)
    
    # Output JSON for LLM
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    main()
