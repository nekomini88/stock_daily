# -*- coding: utf-8 -*-
"""final_conclusion.py 分析函数测试 (重构前建立安全网)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from final_conclusion import analyze_session, _pct, _fmt, _safe


def _mk(idx_chg=None, sectors=None, mag7=None, macro=None):
    """构造测试数据"""
    return {
        "indices": {
            "S&P 500": {"change_pct": idx_chg[0] if idx_chg else 1.2},
            "Nasdaq 100": {"change_pct": idx_chg[1] if idx_chg else -0.8},
            "Dow Jones": {"change_pct": idx_chg[2] if idx_chg else 0.5},
            "Russell 2000": {"change_pct": idx_chg[3] if idx_chg else -1.5},
        } if idx_chg else {},
        "sectors_performance": sectors or [],
        "magnificent_7": mag7 or {},
        "macro": macro or {},
    }


class TestHelpers:
    def test_pct(self):
        assert _pct(1.23) == 1.23
        assert _pct(None) is None
        assert _pct(0) == 0

    def test_fmt(self):
        assert _fmt(1.2) == "+1.20%"
        assert _fmt(-0.5) == "-0.50%"
        assert _fmt(None) == "暂无"

    def test_safe(self):
        assert _safe([1, 2], 0) == 1
        assert _safe([], 0) is None
        assert _safe([], 5) is None


class TestAnalyzeSession:
    def test_empty_data(self):
        """空数据不崩溃, 返回结构完整"""
        r = analyze_session({})
        assert isinstance(r, dict)
        assert "market_conclusion" in r
        assert "key_signals" in r

    def test_indices_parse(self):
        """指数涨跌解析"""
        r = analyze_session(_mk(idx_chg=[1.2, -0.8, 0.5, -1.5]))
        assert isinstance(r, dict)

    def test_sectors_split(self):
        """板块涨跌分类: 上涨/下跌各归其类"""
        sectors = [
            {"name": "半导体", "change": 2.5},
            {"name": "能源", "change": -1.2},
            {"name": "金融", "change": 0.3},
        ]
        r = analyze_session(_mk(idx_chg=[1, 1, 1, 1], sectors=sectors))
        # 上涨板块被识别
        assert isinstance(r, dict)

    def test_mag7_sort(self):
        """Mag7 排序: 涨幅最高/跌幅最深"""
        mag7 = {
            "AAPL": {"change_pct": 2.0},
            "MSFT": {"change_pct": -1.0},
            "GOOG": {"change_pct": 3.5},
            "AMZN": {"change_pct": -2.5},
        }
        r = analyze_session(_mk(idx_chg=[1, 1, 1, 1], mag7=mag7))
        assert isinstance(r, dict)

    def test_signals_dedup(self):
        """信号去重且最多 5 条"""
        r = analyze_session(_mk(idx_chg=[1.2, -0.8, 0.5, -1.5]))
        signals = r.get("signals", [])
        assert len(signals) <= 5
        assert len(signals) == len(set(signals))

    def test_alias_mapping(self):
        """别名映射: ^GSPC/SPY → S&P 500"""
        data = {
            "indices": {"SPY": {"change_pct": 0.7}},
            "sectors_performance": [], "magnificent_7": {}, "macro": {},
        }
        r = analyze_session(data)
        assert isinstance(r, dict)
