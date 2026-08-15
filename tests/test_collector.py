# -*- coding: utf-8 -*-
"""stock_daily 核心逻辑测试：采集器其余纯函数（Stooq CSV 解析、常量表完整性、批量数据整形、降级分支）"""
import sys
import os
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_data_collector as mdc


# 模拟 Stooq 返回的 CSV 内容（含表头 + 5 行日线）
STOOQ_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-08-10,100,101,99,100,1000\n"
    "2026-08-11,100,103,100,102,1200\n"
    "2026-08-12,102,104,101,104,1100\n"
    "2026-08-13,104,105,103,105,1300\n"
    "2026-08-14,105,107,104,107,1400\n"
)


class TestStooqQuote:
    """_stooq_quote 解析逻辑测试（mock urlopen，不联网）"""

    @staticmethod
    def _mock_resp(csv_text):
        resp = mock.MagicMock()
        resp.read.return_value = csv_text.encode()
        return resp

    def test_parse_basic(self):
        # 最新收盘 107，昨收 105，并返回完整 closes 序列
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value.__enter__.return_value = self._mock_resp(STOOQ_CSV)
            r = mdc._stooq_quote("^GSPC")
        assert r[0] == 107.0
        assert r[1] == 105.0
        assert r[2][-1] == 107.0
        assert r[2][0] == 100.0

    def test_symbol_code_sanitized(self):
        # ^GSPC → gspc；ES=F → esf（去掉 ^ 和 = 再小写）
        for raw, code in [("^GSPC", "gspc"), ("ES=F", "esf")]:
            with mock.patch("urllib.request.urlopen") as m:
                m.return_value.__enter__.return_value = self._mock_resp(STOOQ_CSV)
                mdc._stooq_quote(raw)
                url = m.call_args.args[0].full_url
            assert f"s={code}" in url

    def test_too_few_rows_returns_none(self):
        # 不足 3 行（表头 + 1 行数据）视为无效
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value.__enter__.return_value = self._mock_resp("Date,Close\n2026-08-01,100\n")
            assert mdc._stooq_quote("X") is None

    def test_no_close_column_returns_none(self):
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value.__enter__.return_value = self._mock_resp("Date,Open\n2026-08-01,100\n2026-08-02,101\n")
            assert mdc._stooq_quote("X") is None

    def test_unparseable_closes_returns_none(self):
        # 所有 Close 都无法转 float → 视为无数据
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value.__enter__.return_value = self._mock_resp("Date,Close\n2026-08-01,abc\n2026-08-02,def\n")
            assert mdc._stooq_quote("X") is None

    def test_network_error_returns_none(self):
        # 网络异常 → None（不抛出，走降级链）
        with mock.patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            assert mdc._stooq_quote("X") is None


class TestConstants:
    """采集器常量表完整性"""

    def test_etfs_all_indices(self):
        # 大盘指数键全部以 ^ 开头（真实点数源），共 6 个
        assert len(mdc.ETFS) == 6
        assert all(k.startswith("^") for k in mdc.ETFS)

    def test_sector_etfs_11_sectors(self):
        # GICS 11 大板块，代码均以 XL 开头
        assert len(mdc.SECTOR_ETFS) == 11
        assert all(k.startswith("XL") for k in mdc.SECTOR_ETFS)

    def test_mags_7_stocks(self):
        assert len(mdc.MAGS) == 7

    def test_macro_has_special_symbols(self):
        # 宏观指标含特殊代码形态：^ 指数 / = 期货 / -USD 币种
        assert "^TNX" in mdc.MACRO_INDICATORS
        assert "GC=F" in mdc.MACRO_INDICATORS
        assert "BTC-USD" in mdc.MACRO_INDICATORS

    def test_no_symbol_overlap_between_groups(self):
        # 板块与主题不应出现同一 ETF（避免两张表重复展示）
        overlap = set(mdc.SECTOR_ETFS) & set(mdc.THEME_ETFS)
        assert not overlap


class TestFetchGroupShaping:
    """fetch_group 数据整形逻辑测试（monkeypatch fetch_yahoo，不联网）"""

    def test_shapes_items_and_skips_errors(self, monkeypatch):
        def fake_fetch_yahoo(sym):
            if sym == "XLK":
                return {
                    "symbol": "XLK", "price": 100.0, "prev_close": 95.0,
                    "change_pct": 5.26, "change_5d": 8.0, "change_1m": 12.0,
                    "high": 101.0, "low": 94.0, "volume": 1000,
                }
            return {"symbol": sym, "error": "all sources failed"}

        monkeypatch.setattr(mdc, "fetch_yahoo", fake_fetch_yahoo)
        r = mdc.fetch_group({"XLK": "信息技术", "XLF": "金融"})
        assert "信息技术" in r
        assert "金融" not in r  # 出错项被跳过
        item = r["信息技术"]
        assert item["symbol"] == "XLK"
        assert item["name"] == "信息技术"
        assert item["change_pct"] == 5.26
        assert item["high"] == 101.0


class TestFetchYahooFallback:
    """fetch_yahoo 降级分支（mock 主源失败 → Stooq 兜底 / 全部失败）"""

    def test_stooq_fallback(self, monkeypatch):
        # 主源抛错 → 走 Stooq 分支，source=stooq，高/低为 "暂无"
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 107.0]
        monkeypatch.setattr(mdc, "_yahoo_chart", lambda s: (_ for _ in ()).throw(RuntimeError("down")))
        monkeypatch.setattr(mdc, "_stooq_quote", lambda s: (107.0, 104.0, closes))
        r = mdc.fetch_yahoo("X")
        assert r["source"] == "stooq"
        assert r["price"] == 107.0
        assert r["prev_close"] == 104.0
        assert r["change_pct"] == round((107 / 104 - 1) * 100, 2)
        assert r["change_5d"] == round((107 / 100 - 1) * 100, 2)  # 6 根收盘 → 5日
        assert r["change_1m"] == round((107 / 100 - 1) * 100, 2)  # 首末收盘 → 1月
        assert r["high"] == "暂无"
        assert r["volume"] == 0

    def test_all_sources_failed(self, monkeypatch):
        monkeypatch.setattr(mdc, "_yahoo_chart", lambda s: (_ for _ in ()).throw(RuntimeError("down")))
        monkeypatch.setattr(mdc, "_stooq_quote", lambda s: None)
        assert mdc.fetch_yahoo("X") == {"symbol": "X", "error": "all sources failed"}
