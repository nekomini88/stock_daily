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

# AI 硬件 / 半导体重点个股（8.2 章节真实数据源）
AI_HARDWARE = {
    "AMD": "AMD",
    "AVGO": "博通",
    "MRVL": "Marvell",
    "TSM": "台积电",
    "MU": "美光",
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

def _series_is_current(meta, timestamps, closes):
    """日线序列最后一根是否就是当前报价所在的交易日。

    Yahoo 对不少标的的日线会滞后一个交易日（最后一根是上一交易日收盘，而
    regularMarketPrice 已是最新收盘）。用报价时间戳与最后一根日线时间戳对比
    判断；缺时间戳时退化为"最后一根收盘价是否≈现价"。
    """
    quote_ts = meta.get("regularMarketTime")
    if quote_ts and timestamps:
        try:
            quote_day = datetime.fromtimestamp(quote_ts, timezone.utc).date()
            last_day = datetime.fromtimestamp(timestamps[-1], timezone.utc).date()
            return quote_day == last_day
        except (TypeError, ValueError, OSError):
            pass
    price = meta.get("regularMarketPrice")
    if price and closes[-1]:
        return abs(price / closes[-1] - 1) <= 0.001
    return True


def _prev_close(meta, closes, timestamps=None):
    """上一交易日收盘价。

    Yahoo 已不返回 meta.previousClose，而 meta.chartPreviousClose 是 range 区间
    起始日**之前**的收盘价（range=1mo 时约等于一个月前）。直接拿它当"昨收"会把
    月涨跌当成日涨跌（WTI/BTC 每天"涨 20%+"就是这么来的）。故：
    显式 previousClose > 日线序列中与报价同一交易日的上一根 > 最后一根 > chartPreviousClose。
    """
    explicit = meta.get("previousClose")
    if explicit:
        return explicit
    if len(closes) < 2:
        return closes[-1] if closes else (meta.get("chartPreviousClose", 0) or 0)
    return closes[-2] if _series_is_current(meta, timestamps, closes) else closes[-1]


def _parse_chart(data, symbol):
    result = data["chart"]["result"][0]
    meta = result["meta"]
    price = meta.get("regularMarketPrice", 0)
    raw_closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", []) or []
    raw_ts = result.get("timestamp") or []
    # 过滤 None 时必须让时间戳同步下移，否则长度不等 → timestamps=None →
    # 退化成"最后一根收盘价≈现价"判断，日线滞后但数值巧合接近时会把
    # 上上交易日当成昨收（AMZN/AVGO/XLC/XLI 曾因此把 +0.07% 写成 +5.05%）
    closes, timestamps = [], []
    for i, c in enumerate(raw_closes):
        if c:
            closes.append(c)
            if i < len(raw_ts):
                timestamps.append(raw_ts[i])
    if len(timestamps) != len(closes):
        timestamps = None  # 真的无法对齐，才放弃时间戳判断
    if not closes:
        closes = [price]
    prev_close = _prev_close(meta, closes, timestamps)
    change_pct = round((price / prev_close - 1) * 100, 2) if prev_close else "暂无"
    # 区间涨跌以最新报价为终点（日线滞后时 closes[-1] 不是最新价）
    last = price or closes[-1]
    change_5d = None
    change_1m = None
    if len(closes) >= 6:
        change_5d = round((last / closes[-6] - 1) * 100, 2)
    if len(closes) >= 2:
        change_1m = round((last / closes[0] - 1) * 100, 2)
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

def fetch_52w(symbol):
    """一年内最高收盘价与日期（用于判定"创新高"类断言是否成立）。"""
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        url = f"https://{host}/v8/finance/chart/{symbol}?interval=1d&range=1y"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                result = json.loads(resp.read())["chart"]["result"][0]
            ts = result.get("timestamp") or []
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            bars = [(t, c) for t, c in zip(ts, closes) if c is not None]
            if not bars:
                return None
            t, c = max(bars, key=lambda x: x[1])
            return {"high_1y": round(c, 2),
                    "high_1y_date": datetime.fromtimestamp(t, timezone.utc).date().isoformat()}
        except Exception:
            continue
    return None


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
    for name, item in indices.items():
        h = fetch_52w(item.get("symbol") or "")
        if h:
            item.update(h)
            price = item.get("price")
            if price and h.get("high_1y"):
                item["pct_from_1y_high"] = round((price / h["high_1y"] - 1) * 100, 2)
    output["indices"] = indices

    # 2. 七巨头 + 重点个股
    print("📈 获取重点个股...", file=sys.stderr)
    stocks = {}
    for sym in MAGS:
        r = fetch_yahoo(sym)
        if "error" not in r:
            stocks[sym] = r
    output["magnificent_7"] = stocks

    # 2.4 AI 硬件/半导体重点个股
    hw = []
    for sym, name in AI_HARDWARE.items():
        r = fetch_yahoo(sym)
        if "error" not in r:
            hw.append({**r, "name": name})
    output["ai_hardware"] = hw

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
