#!/usr/bin/env python3
"""补抓缺失的大盘指数并合并进当日 JSON（Yahoo 瞬时失败时的修复脚本）。

用法: python3 repair_indices.py 2026-10-31
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/root/stock_daily")
import market_data_collector as mdc

ETFS = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq 100",
    "^DJI": "Dow Jones",
    "^RUT": "Russell 2000",
    "^SOX": "半导体指数",
    "^VIX": "VIX",
}


def main():
    date_str = sys.argv[1]
    path = Path(f"/root/stock_daily/daily_news/market_data_{date_str}.json")
    data = json.loads(path.read_text())
    indices = data.get("indices") or {}
    for sym, name in ETFS.items():
        existing = indices.get(name) or {}
        if existing.get("price") and "error" not in existing:
            print(f"skip {name} (已有)")
            continue
        got = None
        for attempt in range(1, 6):
            r = mdc.fetch_yahoo(sym)
            if "error" not in r and r.get("price"):
                got = r
                break
            print(f"  {sym} 第{attempt}次失败，重试…", flush=True)
            time.sleep(3)
        if not got:
            print(f"❌ {name} 全部重试失败")
            continue
        h = mdc.fetch_52w(sym)
        if h:
            got.update(h)
            if got.get("price") and h.get("high_1y"):
                got["pct_from_1y_high"] = round((got["price"] / h["high_1y"] - 1) * 100, 2)
        indices[name] = got
        print(f"✅ {name} {got['price']} ({got['change_pct']}%) src={got['source']}")
        time.sleep(1)
    # 保持固定顺序
    ordered = {n: indices[n] for _, n in ETFS.items() if n in indices}
    data["indices"] = ordered
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"写入 {path}: {len(ordered)}/6 指数")
    for n, v in ordered.items():
        print(f"  {n:12s} {v.get('price'):>12} {v.get('change_pct'):>7}%")


if __name__ == "__main__":
    main()
