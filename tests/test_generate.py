# -*- coding: utf-8 -*-
"""stock_daily 报告生成模块纯函数测试：格式化过滤器、涨跌幅解读、表格适配逻辑"""
import sys
import os
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generate_stock_daily as gsd


class TestDataFilePath:
    """data_file_path 数据文件路径解析"""

    def test_explicit_data_file(self):
        # 显式指定 --data-file 时原样返回
        args = SimpleNamespace(data_file="custom.json", today=None)
        assert str(gsd.data_file_path(args)) == "custom.json"

    def test_default_path_with_today(self):
        # 未指定时按 --today 拼默认路径
        args = SimpleNamespace(data_file=None, today="2026-08-14")
        assert str(gsd.data_file_path(args)) == "/root/stock_daily/daily_news/market_data_2026-08-14.json"


class TestParseArgs:
    """parse_args 命令行参数解析（mock sys.argv）"""

    def test_defaults(self):
        with mock.patch("sys.argv", ["generate_stock_daily.py"]):
            args = gsd.parse_args()
            assert args.data_file is None
            assert args.today is None

    def test_with_values(self):
        with mock.patch("sys.argv", ["generate_stock_daily.py", "--data-file", "x.json", "--today", "2026-08-14"]):
            args = gsd.parse_args()
            assert args.data_file == "x.json"
            assert args.today == "2026-08-14"


class TestNumberFormat:
    """number_format 千分位格式化"""

    def test_none(self):
        assert gsd.number_format(None) == "N/A"

    def test_int(self):
        assert gsd.number_format(1234567) == "1,234,567"

    def test_float_truncates(self):
        # 小数部分直接截断为整数再千分位
        assert gsd.number_format(1234.9) == "1,234"

    def test_non_numeric_falls_back(self):
        # 无法转 int 时原样返回
        assert gsd.number_format("暂无") == "暂无"


class TestCompactNumber:
    """compact_number 大数缩写"""

    def test_million(self):
        assert gsd.compact_number(44246082) == "44.2M"

    def test_billion(self):
        assert gsd.compact_number(1500000000) == "1.5B"

    def test_thousand(self):
        assert gsd.compact_number(1234) == "1.2K"

    def test_small(self):
        assert gsd.compact_number(999) == "999"

    def test_none_or_invalid(self):
        assert gsd.compact_number(None) == "暂无"
        assert gsd.compact_number("abc") == "暂无"


class TestRoundValue:
    """round_value 数值保留小数"""

    def test_none(self):
        assert gsd.round_value(None) == "暂无"

    def test_round(self):
        assert gsd.round_value(3.14159) == 3.14
        assert gsd.round_value(3.14159, 3) == 3.142

    def test_invalid(self):
        assert gsd.round_value("abc") == "abc"


class TestTechnicalStatus:
    """technical_status 涨跌幅 → 技术状态映射"""

    def test_strong_up(self):
        assert gsd.technical_status("X", {"change_pct": 5.2}) == "强势上涨"

    def test_up(self):
        assert gsd.technical_status("X", {"change_pct": 2.0}) == "上涨"

    def test_flat(self):
        assert gsd.technical_status("X", {"change_pct": 0.0}) == "震荡"

    def test_down(self):
        assert gsd.technical_status("X", {"change_pct": -2.0}) == "下跌"

    def test_strong_down(self):
        assert gsd.technical_status("X", {"change_pct": -6.0}) == "大幅下跌"

    def test_missing_or_invalid(self):
        # 缺字段按 0 处理（震荡）；不可转 float → 数据缺失
        assert gsd.technical_status("X", {}) == "震荡"
        assert gsd.technical_status("X", {"change_pct": "abc"}) == "数据缺失"


class TestBondAnalysis:
    """bond_analysis 债券收益率动态解读"""

    def test_yield_up(self):
        assert gsd.bond_analysis("10Y收益率", {"change_pct": 1.0, "price": 4.5}) == "收益率上行，压制估值"

    def test_yield_down(self):
        assert gsd.bond_analysis("10Y收益率", {"change_pct": -1.0, "price": 4.5}) == "收益率下行，利好风险资产"

    def test_narrow_10y(self):
        # 10Y 且波动小 → 带具体利率的窄幅波动文案
        assert gsd.bond_analysis("10Y收益率", {"change_pct": 0.1, "price": 4.25}) == "长端利率 4.25%，窄幅波动"

    def test_narrow_other(self):
        assert gsd.bond_analysis("美元指数DXY", {"change_pct": 0.1, "price": 104.5}) == "窄幅波动"

    def test_no_price(self):
        assert gsd.bond_analysis("10Y收益率", {"change_pct": 1.0, "price": 0}) == "数据缺失"

    def test_invalid(self):
        assert gsd.bond_analysis("10Y收益率", {"change_pct": "abc"}) == "数据缺失"


class TestAssetAnalysis:
    """asset_analysis 资产涨跌解读"""

    def test_strong_up(self):
        assert gsd.asset_analysis("黄金", {"change_pct": 3.5}) == "强势上涨 +3.5%"

    def test_strong_down(self):
        assert gsd.asset_analysis("黄金", {"change_pct": -4.2}) == "明显下跌 -4.2%"

    def test_small_up(self):
        assert gsd.asset_analysis("黄金", {"change_pct": 1.0}) == "小幅上涨 +1.0%"

    def test_small_down(self):
        assert gsd.asset_analysis("黄金", {"change_pct": -1.0}) == "小幅下跌 -1.0%"

    def test_flat(self):
        assert gsd.asset_analysis("黄金", {"change_pct": 0}) == "持平"

    def test_missing(self):
        # 缺字段按 0 处理（持平）；不可转 float → 数据缺失
        assert gsd.asset_analysis("黄金", {}) == "持平"
        assert gsd.asset_analysis("黄金", {"change_pct": "abc"}) == "数据缺失"


class TestVsSp500:
    """_vs_sp500 板块相对标普涨跌判断"""

    def test_outperform(self):
        # 差 1.0 ≥ 0.5 → 跑赢
        assert gsd._vs_sp500(2.0, 1.0) == "跑赢"

    def test_underperform(self):
        # 差 -1.0 ≤ -0.5 → 跑输
        assert gsd._vs_sp500(1.0, 2.0) == "跑输"

    def test_even(self):
        # 差 0.2 在 ±0.5 内 → 持平
        assert gsd._vs_sp500(1.2, 1.0) == "持平"

    def test_invalid(self):
        assert gsd._vs_sp500("abc", 1.0) == "—"
        assert gsd._vs_sp500(None, None) == "—"


class TestSectorDriver:
    """_sector_driver 板块驱动解读"""

    def test_strong_up(self):
        assert "放量大涨" in gsd._sector_driver("信息技术", 3.0)

    def test_strong_down(self):
        assert "承压回落" in gsd._sector_driver("能源", -3.0)

    def test_flat(self):
        assert "窄幅整理" in gsd._sector_driver("金融", 0.5)

    def test_unknown_sector(self):
        # 未知板块用通用兜底文案
        assert gsd._sector_driver("未知板块", 1.0) == "板块基本面，窄幅整理"

    def test_missing(self):
        # 涨跌幅缺失 → 只返回基础文案
        assert gsd._sector_driver("信息技术", None) == "科技权重主导，AI/半导体景气度高企"


class TestThemeAnalysis:
    """_theme_analysis 主题涨跌解读"""

    def test_strong(self):
        assert gsd._theme_analysis("半导体", 5.0) == "主题强势，当日+5.0%"

    def test_drop(self):
        assert gsd._theme_analysis("半导体", -5.0) == "主题回调，当日-5.0%"

    def test_mild_up(self):
        assert gsd._theme_analysis("半导体", 1.0) == "温和走强，当日+1.0%"

    def test_mild_down(self):
        assert gsd._theme_analysis("半导体", -1.0) == "小幅走弱，当日-1.0%"

    def test_flat(self):
        assert gsd._theme_analysis("半导体", 0) == "基本持平"

    def test_missing(self):
        assert gsd._theme_analysis("半导体", "abc") == "主题表现待观察"


class TestAdaptGroup:
    """_adapt_group 采集器输出 → 模板字段适配"""

    def test_sector_kind(self):
        # 板块模式：补充 vs_sp500（相对标普 1.0）与 driver
        items = [
            {"name": "信息技术", "symbol": "XLK", "change_pct": 2.0, "change_5d": 8.0, "change_1m": 15.0},
            {"name": "能源", "symbol": "XLE", "change_pct": -1.0, "change_5d": -2.0, "change_1m": 1.0},
        ]
        rows = gsd._adapt_group(items, {"kind": "sector"}, sp500_chg=1.0)
        assert rows[0]["name"] == "信息技术"
        assert rows[0]["etf"] == "XLK"
        assert rows[0]["change"] == 2.0
        assert rows[0]["vs_sp500"] == "跑赢"   # 2.0 - 1.0 = 1.0 ≥ 0.5
        assert rows[0]["driver"].endswith("放量大涨")
        assert rows[1]["vs_sp500"] == "跑输"   # -1.0 - 1.0 = -2.0 ≤ -0.5

    def test_theme_kind(self):
        # 主题模式：补充 analysis 解读
        items = [{"name": "半导体", "symbol": "SMH", "change_pct": 3.2}]
        rows = gsd._adapt_group(items, {"kind": "theme"})
        assert rows[0]["analysis"] == "主题强势，当日+3.2%"

    def test_plain_kind(self):
        # 无 extra → 只做字段改名映射
        items = [{"name": "X", "symbol": "XX", "change_pct": 1.0}]
        rows = gsd._adapt_group(items)
        assert "vs_sp500" not in rows[0]
        assert "analysis" not in rows[0]
        assert rows[0]["change"] == 1.0

    def test_skips_non_dict(self):
        rows = gsd._adapt_group([None, "str", {"name": "A", "symbol": "AA", "change_pct": 1.0}])
        assert len(rows) == 1

    def test_empty(self):
        assert gsd._adapt_group(None) == []
        assert gsd._adapt_group([]) == []


class TestGenerateReportSmoke:
    """generate_report 数据文件缺失时的安全路径（不联网、不调 LLM）"""

    def test_missing_file_returns_false(self, capsys):
        args = SimpleNamespace(data_file="/nonexistent/market_data_x.json", today=None)
        assert gsd.generate_report(args) is False
        out = capsys.readouterr().out
        assert "不存在" in out
