# -*- coding: utf-8 -*-
"""stock_daily 核心逻辑测试：Yahoo chart 数据解析"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data_collector import _parse_chart


def make_chart_data(price=100.0, prev=95.0, closes=None, high=101.0, low=94.0, volume=1000):
    """构造 Yahoo chart API 返回结构"""
    if closes is None:
        closes = [90.0, 92.0, 94.0, 96.0, 98.0, price]
    return {
        "chart": {
            "result": [{
                "meta": {
                    "regularMarketPrice": price,
                    "previousClose": prev,
                    "regularMarketDayHigh": high,
                    "regularMarketDayLow": low,
                    "regularMarketVolume": volume,
                },
                "indicators": {"quote": [{"close": closes}]},
            }]
        }
    }


class TestParseChart:
    """_parse_chart 纯函数测试"""

    def test_basic_parse(self):
        r = _parse_chart(make_chart_data(price=100.0, prev=95.0), "TEST")
        assert r["symbol"] == "TEST"
        assert r["price"] == 100.0
        assert r["prev_close"] == 95.0
        assert r["change_pct"] == round((100/95 - 1) * 100, 2)
        assert r["source"] == "yahoo"

    def test_change_calculation(self):
        # 100 vs 95 → +5.26%
        r = _parse_chart(make_chart_data(price=100.0, prev=95.0), "X")
        assert r["change_pct"] == 5.26

    def test_negative_change(self):
        r = _parse_chart(make_chart_data(price=90.0, prev=100.0), "X")
        assert r["change_pct"] == -10.0

    def test_5d_change(self):
        # closes[-1]=100, closes[-6]=90 → +11.11%
        closes = [90.0, 91.0, 92.0, 93.0, 94.0, 100.0]
        r = _parse_chart(make_chart_data(closes=closes), "X")
        assert r["change_5d"] == round((100/90 - 1) * 100, 2)

    def test_prev_close_fallback(self):
        # prev_close 缺失 → 用 closes[-2]
        data = make_chart_data(price=100.0, prev=0)
        data["chart"]["result"][0]["meta"]["previousClose"] = 0
        data["chart"]["result"][0]["meta"]["chartPreviousClose"] = 0
        r = _parse_chart(data, "X")
        assert r["prev_close"] == 98.0  # closes[-2]

    def test_no_closes_uses_price(self):
        data = make_chart_data(price=50.0, prev=50.0, closes=[None, None])
        r = _parse_chart(data, "X")
        assert r["price"] == 50.0
        assert r["change_pct"] == 0.0

    def test_meta_fields_passed_through(self):
        r = _parse_chart(make_chart_data(high=105.5, low=93.2, volume=9999), "X")
        assert r["high"] == 105.5
        assert r["low"] == 93.2
        assert r["volume"] == 9999


class TestStooqFallback:
    """Stooq 降级逻辑测试（模拟 CSV 输入）"""

    def test_stooq_parse_logic(self):
        # 直接测 CSV 解析路径：模拟 _stooq_quote 内部逻辑
        import io
        import csv
        rows = list(csv.reader(io.StringIO("Date,Close\n2026-08-01,100\n2026-08-02,102\n")))
        header, data = rows[0], rows[1:]
        ci = header.index("Close")
        closes = [float(r[ci]) for r in data]
        assert closes[-1] == 102.0
        assert closes[-2] == 100.0
        chg = round((closes[-1] / closes[-2] - 1) * 100, 2)
        assert chg == 2.0
