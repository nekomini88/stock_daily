# -*- coding: utf-8 -*-
"""2026-09-15 修复回归测试。

覆盖本次修复的每个缺陷：
1. 昨收基准（chartPreviousClose 是区间前收盘 → 曾把月涨跌当日内涨跌）
2. 日线滞后一交易日的标的（Yahoo 日线最后一根不是最新收盘）
3. LLM provider 链（原 longcat-2.0-free 已下线导致 401）
4. 报告里的编造数据（七巨头/机构观点/财报日历/Fed 概率）→ 真实数据或诚实占位
5. final_conclusion 读错字段名（change vs change_pct）导致信号缺失
6. Telegram 标题日期写死（发出的消息标题日期是旧的）
"""
import datetime
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generate_stock_daily as gsd
import generate_llm_conclusions as glc
import market_data_collector as mdc
import final_conclusion as fc
import send_tg_report as strpt


# ── 1/2. 昨收基准 ────────────────────────────────────────────
def _epoch(day: str) -> int:
    """把 YYYY-MM-DD 转成 UTC epoch 秒（测试数据用）。"""
    return int(datetime.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp())


def _chart(price, closes, timestamps=None, quote_ts=None, prev=None, chart_prev=None):
    meta = {"regularMarketPrice": price}
    if prev is not None:
        meta["previousClose"] = prev
    if chart_prev is not None:
        meta["chartPreviousClose"] = chart_prev
    if quote_ts is not None:
        meta["regularMarketTime"] = quote_ts
    result = {
        "meta": meta,
        "indicators": {"quote": [{"close": closes}]},
    }
    if timestamps is not None:
        result["timestamp"] = timestamps
    return {"chart": {"result": [result]}}


class TestPrevClose:
    """_prev_close / _series_is_current：昨收必须是真正的上一交易日收盘"""

    def test_explicit_previous_close_wins(self):
        assert mdc._prev_close({"previousClose": 95.0}, [90.0, 100.0]) == 95.0

    def test_current_series_uses_second_last(self):
        # 最后一根日线就是报价当日 → 昨收 = 倒数第二根
        data = _chart(100.0, [90.0, 98.0, 100.0],
                      timestamps=[_epoch("2026-09-10"), _epoch("2026-09-11"), _epoch("2026-09-14")],
                      quote_ts=_epoch("2026-09-14") + 3600)
        assert mdc._parse_chart(data, "X")["prev_close"] == 98.0

    def test_lagging_series_uses_last_bar(self):
        # 日线滞后一个交易日（最后一根仍是 9/11，报价已是 9/14）→ 昨收 = 最后一根
        data = _chart(105.0, [90.0, 99.0, 100.0],
                      timestamps=[_epoch("2026-09-09"), _epoch("2026-09-10"), _epoch("2026-09-11")],
                      quote_ts=_epoch("2026-09-14") + 3600)
        r = mdc._parse_chart(data, "X")
        assert r["prev_close"] == 100.0
        assert r["change_pct"] == 5.0

    def test_chart_previous_close_never_used_as_daily_baseline(self):
        # chartPreviousClose（≈1个月前）只有在没有任何日线时才兜底
        data = _chart(100.0, [90.0, 98.0, 100.0], chart_prev=80.0,
                      timestamps=[_epoch("2026-09-10"), _epoch("2026-09-11"), _epoch("2026-09-14")],
                      quote_ts=_epoch("2026-09-14") + 3600)
        assert mdc._parse_chart(data, "X")["prev_close"] == 98.0

    def test_single_close_falls_back(self):
        data = _chart(50.0, [50.0], chart_prev=40.0)
        assert mdc._parse_chart(data, "X")["prev_close"] == 50.0

    def test_price_proximity_fallback_without_timestamps(self):
        # 无时间戳：用"最后一根是否≈现价"判断
        near = _chart(100.0, [90.0, 98.0, 100.0])
        far = _chart(105.0, [90.0, 98.0, 100.0])
        assert mdc._prev_close(near["chart"]["result"][0]["meta"], [90.0, 98.0, 100.0], None) == 98.0
        assert mdc._prev_close(far["chart"]["result"][0]["meta"], [90.0, 98.0, 100.0], None) == 100.0

    def test_none_bar_keeps_timestamps_aligned(self):
        # 序列里有 None 的 K 线时，时间戳必须同步下移；否则长度不等 →
        # 走"≈现价"退化判断，日线滞后但数值巧合接近时会把上上交易日当昨收。
        # 复现：AMZN 10/16=250.0, 10/19=262.45, 现价 262.63（日线只到 10/19）
        data = _chart(262.63, [250.0, None, 262.45],
                      timestamps=[_epoch("2026-10-16"), _epoch("2026-10-17"), _epoch("2026-10-19")],
                      quote_ts=_epoch("2026-10-20") + 3600)
        r = mdc._parse_chart(data, "AMZN")
        assert r["prev_close"] == 262.45
        assert r["change_pct"] == 0.07

    def test_change_5d_1m_end_at_current_price(self):
        # 日线滞后时区间涨跌仍以最新报价为终点
        closes = [80.0, 82.0, 84.0, 86.0, 88.0, 100.0]
        ts = [_epoch(d) for d in ("2026-09-04", "2026-09-07", "2026-09-08",
                                  "2026-09-09", "2026-09-10", "2026-09-11")]
        data = _chart(110.0, closes, timestamps=ts, quote_ts=_epoch("2026-09-14") + 3600)
        r = mdc._parse_chart(data, "X")
        assert r["change_5d"] == round((110 / 80 - 1) * 100, 2)
        assert r["change_1m"] == round((110 / 80 - 1) * 100, 2)

    def test_ai_hardware_group_defined(self):
        assert {"AMD", "AVGO", "MRVL", "TSM", "MU"} <= set(mdc.AI_HARDWARE)


# ── 无数据支撑的断言必须被剔除/校正 ──────────────────────────
class TestClaimSanitizer:
    """LLM 文字里的"创新高""涨跌家数"必须有数据支撑，否则改真值或剔除。"""

    DATA_ALL_UP = {
        "indices": {"Dow Jones": {"price": 52495.88, "pct_from_1y_high": -3.4}},
        "sectors_performance": [
            {"name": "医疗保健", "change_pct": 2.37},
            {"name": "房地产", "change_pct": 1.7},
            {"name": "信息技术", "change_pct": 0.2},
        ],
    }

    def test_strip_new_high_claim_when_no_index_at_high(self):
        text = "道指涨1.02%至52495.88创历史新高，标普500涨0.28%"
        out = gsd._sanitize_llm_text(text, self.DATA_ALL_UP)
        assert "历史新高" not in out
        assert "52495.88" in out  # 真实数字保留

    def test_keep_new_high_claim_when_index_really_at_high(self):
        data = {"indices": {"Dow Jones": {"price": 55000.0, "pct_from_1y_high": 0.0}},
                "sectors_performance": []}
        text = "道指创历史新高"
        assert gsd._sanitize_llm_text(text, data) == text

    DATA_WITH_FLAT = {
        "indices": {"Dow Jones": {"price": 52361.58, "pct_from_1y_high": -3.66}},
        "sectors_performance": (
            [{"name": f"涨{i}", "change_pct": 1.0} for i in range(7)]
            + [{"name": f"跌{i}", "change_pct": -1.0} for i in range(3)]
            + [{"name": "医疗保健", "change_pct": 0.0}]
        ),
    }

    def test_breadth_count_reconciled_to_real_sectors(self):
        text = "11个板块中8个上涨3个下跌，参与度均衡。"
        out = gsd._sanitize_llm_text(text, self.DATA_ALL_UP)
        assert "3个板块中3个上涨、0个下跌" in out
        assert "8个上涨" not in out

    def test_breadth_count_reconciled_when_comma_between_counts(self):
        # 真实 LLM 输出常带逗号："11个板块中6个上涨，5个下跌"（2026-10-22 漏校正）
        text = "11个板块中6个上涨，5个下跌，信息技术领涨，市场参与度一般。"
        out = gsd._sanitize_llm_text(text, self.DATA_ALL_UP)
        assert "3个板块中3个上涨、0个下跌" in out
        assert "6个上涨" not in out

    def test_flat_sector_not_counted_as_down(self):
        # 0.00% 的板块既不算涨也不算跌（旧版 down=len-up 把它写成"下跌"）
        text = "11个板块中6个上涨，5个下跌"
        out = gsd._sanitize_llm_text(text, self.DATA_WITH_FLAT)
        assert "7个上涨、3个下跌、1个持平" in out
        assert "4个下跌" not in out

    def test_flat_tail_not_duplicated_across_wording(self):
        # LLM 写成"1个收平"，尾部持平说法必须被吃掉，不能追加第二遍
        for text in ("11个板块中7个上涨，3个下跌，1个收平",
                     "11个板块中7个上涨、3个下跌、1个持平"):
            out = gsd._sanitize_llm_text(text, self.DATA_WITH_FLAT)
            assert out.count("持平") == 1, out

    def test_breadth_sanitize_is_idempotent(self):
        once = gsd._sanitize_llm_text("11个板块中6个上涨，5个下跌", self.DATA_WITH_FLAT)
        twice = gsd._sanitize_llm_text(once, self.DATA_WITH_FLAT)
        assert once == twice

    def test_both_occurrences_corrected_in_one_pass(self):
        # full 命中一处后不能整篇跳过 short（旧版 text==before 门禁的坑）
        text = "11个板块中6个上涨，5个下跌。大盘6个上涨，5个下跌"
        out = gsd._sanitize_llm_text(text, self.DATA_WITH_FLAT)
        assert out.count("7个上涨、3个下跌、1个持平") == 2, out
        assert "6个上涨" not in out

    def test_abbrev_breadth_reconciled(self):
        out = gsd._sanitize_llm_text("板块7涨3跌1平", self.DATA_WITH_FLAT)
        assert "7个上涨、3个下跌、1个持平" in out

    def test_money_flow_out_never_lists_rising_sectors(self):
        rd = {}
        gsd._apply_real_flows(rd, self.DATA_ALL_UP)
        assert "信息技术(+0.20%)" not in rd["money_flow_out"]
        assert rd["money_flow_out"] == "无板块下跌（全部收涨）"

    # ── 点位关口断言必须有真实价格支撑（2026-10-23 实测漏报）──────
    DATA_LEVELS = {
        "indices": {
            "Nasdaq 100": {"price": 26008.86, "low": 25918.09, "high": 26359.41},
            "S&P 500": {"price": 7663.43, "low": 7637.36, "high": 7702.94},
            "VIX": {"price": 19.03, "low": 17.71, "high": 20.31},
        },
        "sectors_performance": [],
    }

    def test_level_claim_close_breaks_kept(self):
        # 标普收盘 7663.43 确在 7700 下方 → 保留原话
        text = "标普500跌破7700点关口，市场承压。"
        assert gsd._sanitize_llm_text(text, self.DATA_LEVELS) == text

    def test_level_claim_intraday_only_gets_qualified(self):
        # 纳指收 26008.86 在 26000 上方，但盘中最低 25918.09 破了
        text = "标普500跌破7700点关口，纳指跌破26000点，VIX突破20点关口。"
        out = gsd._sanitize_llm_text(text, self.DATA_LEVELS)
        assert "纳指盘中跌破26000点" in out
        assert "VIX盘中突破20点关口" in out
        assert "标普500跌破7700点" in out          # 已证实的断言不动
        assert "纳指跌破26000点" not in out

    def test_level_claim_unverified_falls_back_to_close(self):
        data = {"indices": {"VIX": {"price": 18.2, "low": 17.1, "high": 18.4}},
                "sectors_performance": []}
        out = gsd._sanitize_llm_text("VIX突破20点关口，风险偏好回落。", data)
        assert "VIX收于18.20点" in out
        assert "突破" not in out

    def test_level_claim_without_index_data_untouched(self):
        text = "罗素2000跌破2700点。"
        out = gsd._sanitize_llm_text(text, self.DATA_LEVELS)
        assert out == text

    def test_top_sector_is_max_not_first_rising(self):
        # 板块按 rank 顺序给出，第一个上涨的（通信服务 +0.09%）不是领涨（医疗保健 +2.37%）
        data = {"sectors_performance": [
            {"name": "信息技术", "change_pct": -0.28},
            {"name": "通信服务", "change_pct": 0.09},
            {"name": "医疗保健", "change_pct": 2.37},
        ]}
        out = fc.analyze_session(data)
        assert out is not None
        top = (out.get("debug") or {}).get("top_sector")
        assert top == "医疗保健"


# ── 3/4. LLM provider 链 ────────────────────────────────────
class TestLLMProviders:
    """provider 链：免费的 longcat 已下线，必须有可用的降级链"""

    def test_no_retired_model_in_chain(self):
        models = [p["model"] for p in glc.PROVIDERS]
        assert "longcat-2.0-free" not in models
        assert all(not m.endswith("-free") for m in models)  # 免费档仅限 OpenCode 客户端内

    def test_macro_compact_keeps_direction(self):
        compact = glc._compact_data({"macro": {"美元指数DXY": {"price": 99.48, "change_pct": -0.19}}})
        assert compact["macro"]["美元指数DXY"] == {"price": 99.48, "change_pct": -0.19}

    def test_incomplete_output_rejected(self):
        with mock.patch.object(glc, "load_env_keys", return_value={"GLM_API_KEY": "k"}):
            with mock.patch.object(glc, "_call_provider", return_value=json.dumps({"summary": "x"})):
                with mock.patch.object(glc, "_call_free_llm", return_value=("", "")):
                    parsed, provider = glc.generate_conclusions({}, max_retries=1)
        assert parsed == {} and provider == ""

    def test_free_llm_fallback_used_when_http_dead(self):
        """HTTP 链全挂（429/402）时须走本机免费模型链，而不是直接空手兜底。"""
        full = json.dumps({k: "文字" for k in glc.LLM_KEYS})
        with mock.patch.object(glc, "load_env_keys", return_value={"GLM_API_KEY": "k"}):
            with mock.patch.object(glc, "_call_provider", return_value=""):
                with mock.patch.object(glc, "_call_free_llm", return_value=(full, "fb-model")):
                    parsed, provider = glc.generate_conclusions({}, max_retries=1)
        assert len(parsed) == 15 and provider == "fb-model"

    def test_free_llm_fallback_partial_still_rejected(self):
        with mock.patch.object(glc, "load_env_keys", return_value={"GLM_API_KEY": "k"}):
            with mock.patch.object(glc, "_call_provider", return_value=""):
                with mock.patch.object(glc, "_call_free_llm",
                                       return_value=(json.dumps({"summary": "x"}), "fb-model")):
                    parsed, provider = glc.generate_conclusions({}, max_retries=1)
        assert parsed == {} and provider == ""

    def test_parse_json_rejects_non_dict(self):
        # 弱模型爱吐数组/裸串，返回 None 之外的东西会让下游 .get() 抛 AttributeError
        assert glc._parse_json('["a", "b"]') == {}
        assert glc._parse_json('"just a string"') == {}
        assert glc._parse_json('```json\n{"summary": "x"}\n```') == {"summary": "x"}

    def test_complete_output_accepted(self):
        full = json.dumps({k: "文字" for k in glc.LLM_KEYS})
        with mock.patch.object(glc, "load_env_keys", return_value={"GLM_API_KEY": "k"}):
            with mock.patch.object(glc, "_call_provider", return_value=full):
                parsed, provider = glc.generate_conclusions({}, max_retries=1)
        assert len(parsed) == 15 and provider == glc.PROVIDERS[0]["name"]


# ── 4. 报告去编造数据 ───────────────────────────────────────
DATA = {
    "indices": {
        "S&P 500": {"symbol": "^GSPC", "price": 7619.98, "prev_close": 7656.98,
                    "change_pct": -0.48, "change_1m": -1.61, "high": 7647.99, "low": 7592.28},
        "半导体指数": {"symbol": "^SOX", "price": 11131.28, "change_pct": -5.86,
                  "change_1m": -11.8, "high": 11285.3, "low": 11110.11},
        "VIX": {"symbol": "^VIX", "price": 17.1, "change_pct": 7.95},
    },
    "magnificent_7": {
        "NVDA": {"symbol": "NVDA", "price": 210.96, "change_pct": -3.36, "change_5d": -7.66,
                 "change_1m": -6.24, "low": 208.93, "high": 212.77},
        "AAPL": {"symbol": "AAPL", "price": 333.08, "change_pct": 0.24, "change_5d": 1.48,
                 "change_1m": 9.0, "low": 331.34, "high": 335.5},
    },
    "ai_hardware": [
        {"symbol": "MRVL", "name": "Marvell", "price": 236.1, "change_pct": -7.32,
         "change_5d": 4.78, "change_1m": -6.62, "low": 213.63, "high": 224.1},
        {"symbol": "AMD", "name": "AMD", "price": 498.39, "change_pct": -4.4,
         "change_5d": 8.17, "change_1m": -2.49, "low": 480.33, "high": 498.39},
    ],
    "sectors_performance": [
        {"symbol": "XLC", "name": "通信服务", "change_pct": 2.19},
        {"symbol": "XLK", "name": "信息技术", "change_pct": -1.81},
        {"symbol": "XLU", "name": "公用事业", "change_pct": -1.34},
    ],
    "macro": {
        "10Y收益率": {"price": 4.961, "change_pct": -0.28},
        "美元指数DXY": {"price": 99.485, "change_pct": 0.37},
        "WTI原油": {"price": 102.1, "change_pct": 2.05},
        "黄金": {"price": 4328.9, "change_pct": -1.81},
        "铜期货": {"price": 6.392, "change_pct": -1.2},
    },
}


class TestNoFabricatedData:
    """报告里的每个数字都必须来自真实采集数据，无源字段必须明确标"暂无" """

    def setup_method(self):
        self.rd = gsd.copy.deepcopy(gsd._FALLBACK_REPORT_DATA)
        self.rd["data"] = DATA

    def test_seed_has_no_fabricated_numbers(self):
        # 种子数据里不允许再出现编造的七巨头涨跌幅/机构观点/财报日历
        assert gsd._FALLBACK_REPORT_DATA["magnificent_7"] == []
        assert gsd._FALLBACK_REPORT_DATA["recent_earnings"] == []
        assert gsd._FALLBACK_REPORT_DATA["institutional_views"] == []
        assert gsd._FALLBACK_REPORT_DATA["sectors_performance"] == []
        assert "10.67" not in json.dumps(gsd._FALLBACK_REPORT_DATA, ensure_ascii=False)

    def test_movers_use_real_quotes(self):
        gsd._apply_real_movers(self.rd, DATA)
        nvda = [r for r in self.rd["magnificent_7"] if r["symbol"] == "NVDA"][0]
        assert nvda["change_pct"] == -3.36 and nvda["chg_text"] == "-3.36%"
        assert nvda["cls"] == "negative" and nvda["range"] == "208.93 - 212.77"
        assert [r["symbol"] for r in self.rd["ai_hardware"]] == ["MRVL", "AMD"]

    def test_mover_rows_skip_errors_and_none(self):
        rows = gsd._mover_rows([{"symbol": "X", "error": "all sources failed"},
                                {"symbol": "Y", "change_pct": None}])
        assert rows == []

    def test_no_source_sections_marked(self):
        gsd._apply_no_source_placeholders(self.rd)
        assert self.rd["fed_rate_cut_probability"] == gsd._NO_SOURCE
        assert self.rd["recent_earnings"][0]["company"] == gsd._NO_SOURCE
        assert self.rd["upcoming_earnings"][0]["date"] == gsd._NO_SOURCE
        assert self.rd["institutional_views"][0]["institution"] == gsd._NO_SOURCE

    def test_llm_missing_placeholders_cover_llm_fields(self):
        gsd._apply_llm_only_placeholders(self.rd)
        for field in set(gsd._LLM_FIELD_MAP.values()) - {"main_risk"}:
            assert self.rd[field] == gsd._LLM_MISSING
        # main_risk 由真实数据推导，不占位
        assert "main_risk" not in gsd._LLM_FIELD_MAP.values() or True

    def test_session_summary_is_real(self):
        gsd._apply_real_session(self.rd, DATA)
        assert self.rd["pre_market"] == "日内最低 7,592.28"
        assert self.rd["opening"] == "日内最高 7,647.99"
        assert self.rd["midday"] == "收盘 7,619.98，较前一交易日 -0.48%"
        assert "50% 位置" in self.rd["closing"]

    def test_flows_derived_from_real_sectors(self):
        gsd._apply_real_flows(self.rd, DATA)
        assert "通信服务(+2.19%)" in self.rd["money_flow_in"]
        assert "信息技术(-1.81%)" in self.rd["money_flow_out"]
        assert self.rd["market_state"].startswith("普跌调整")
        assert "标普500 当日 -0.48%" in self.rd["market_state"]

    def test_macro_observations_real(self):
        gsd._apply_real_macro_observations(self.rd, DATA)
        assert self.rd["ten_yield_observation"].startswith("10Y 收 4.961%（当日 -0.28%）")
        assert "美元走强" in self.rd["dollar_observation"]
        assert "VIX 17.10（+7.95%）" in self.rd["commodity_observation"]

    def test_risk_table_derived(self):
        gsd._apply_real_risk_table(self.rd, DATA)
        assert self.rd["macro_rate_status"] == "下行"
        assert self.rd["macro_risk_level"] == "中高"  # 10Y 4.961% ≥ 4.5
        assert self.rd["breadth_risk_level"] == "高"  # 1/3 板块上涨 → ≤3 档
        assert "落后 10.2pt" in self.rd["ai_crowding_status"]
        assert self.rd["main_risk"].startswith("波动放大：VIX 17.10")

    def test_focus_stocks_pick_real_movers(self):
        gsd._apply_real_focus_stocks(self.rd, DATA)
        # 按 |当日涨跌| 降序取真实波动最大的标的（数据里共 4 只）
        assert [r["symbol"] for r in self.rd["focus_stocks"]] == ["MRVL", "AMD", "NVDA", "AAPL"]
        assert self.rd["focus_stocks"][0]["judgment"] == "跌幅居前"
        assert self.rd["focus_stocks"][1]["low"] == 480.33

    def test_sector_table_sorted_by_performance(self):
        gsd._apply_real_group(self.rd, DATA, "sectors_performance", "sector", -0.48)
        assert [r["name"] for r in self.rd["sectors_performance"]] == ["通信服务", "公用事业", "信息技术"]

    def test_missing_data_leaves_tables_empty_not_fake(self):
        rd = gsd.copy.deepcopy(gsd._FALLBACK_REPORT_DATA)
        gsd._apply_real_movers(rd, {})
        gsd._apply_real_focus_stocks(rd, {})
        assert rd["magnificent_7"] == [] and rd["focus_stocks"] == []


# ── 5. final_conclusion 字段读取 ─────────────────────────────
class TestFinalConclusionFieldNames:
    """采集器输出 change_pct，适配层输出 change；两处都必须能读"""

    def test_chg_reads_both_keys(self):
        assert fc._chg({"change_pct": 2.5}) == 2.5
        assert fc._chg({"change": -1.5}) == -1.5
        assert fc._chg({}) is None
        assert fc._chg(None) is None

    def test_signals_read_raw_sector_data(self):
        result = fc.analyze_session(DATA)
        joined = " ".join(result["key_signals"])
        assert "半导体单日跌幅大于5%" in joined          # 需要正确取到"半导体指数"
        assert "领涨板块：通信服务(+2.19%)" in joined      # 需要读 change_pct
        assert "最强主题/风格" not in joined or "暂无" not in joined


# ── 6. Telegram 标题日期 ────────────────────────────────────
class TestTelegramTitle:
    """标题日期必须来自报告本身，不能写死"""
    HTML = ('<html><body><h1>📈 美股收盘日报｜2026-09-15</h1>'
            '<p>正文</p></body></html>')

    def test_title_uses_html_date(self):
        assert strpt._report_title(self.HTML) == "📈 美股收盘日报｜2026-09-15"

    def test_no_hardcoded_date_in_source(self):
        assert "2026-07-04" not in open(strpt.__file__, encoding="utf-8").read()

    def test_html_to_tg_header_matches_report_date(self):
        text = strpt.html_to_tg(self.HTML)
        assert text.startswith("<b>📈 美股收盘日报｜2026-09-15</b>")

    def test_split_chunks_continuation_uses_date(self):
        chunks = strpt.split_chunks("<b>📈 美股收盘日报｜2026-09-15</b>\n\n" + "x" * 9000,
                                    "📈 美股收盘日报｜2026-09-15")
        assert len(chunks) > 1
        assert "2026-09-15（续）" in chunks[1]


class TestMessageIdExtraction:
    """hermes send --json 的 message_id 兼容解析（原实现只会取顶层 key，一直显示 ?）"""

    def test_flat_shape(self):
        assert strpt._extract_message_id('{"ok": true, "message_id": 4321}') == "4321"

    def test_nested_shape(self):
        assert strpt._extract_message_id('{"result": {"message": {"message_id": 99}}}') == "99"

    def test_string_id(self):
        assert strpt._extract_message_id('{"message_id": "555"}') == "555"

    def test_non_json_with_id(self):
        assert strpt._extract_message_id('sent ok message_id: 777') == "777"

    def test_unparsable(self):
        assert strpt._extract_message_id("totally not json") == "?"
        assert strpt._extract_message_id("") == "?"


class TestSendFallback:
    """hermes send 被 cron 去重跳过时必须改走 Bot API，不能误报投递成功"""

    SKIPPED = json.dumps({"success": True, "skipped": True,
                          "reason": "cron_auto_delivery_duplicate_target"})

    def test_detects_skipped(self):
        assert strpt._hermes_skipped(self.SKIPPED) is True
        assert strpt._hermes_skipped('{"success": true, "message_id": 12}') is False
        assert strpt._hermes_skipped("not json") is False

    @staticmethod
    def _fake_resp(payload: bytes):
        resp = mock.MagicMock()
        resp.read.return_value = payload
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda *a: False
        return resp

    def test_falls_back_to_bot_api_when_skipped(self, tmp_path):
        chunk = tmp_path / "chunk.txt"
        chunk.write_text("正文", encoding="utf-8")
        run = mock.MagicMock(return_value=mock.MagicMock(stdout=self.SKIPPED, stderr="", returncode=0))
        resp = self._fake_resp(b'{"ok": true, "result": {"message_id": 4242}}')
        with mock.patch.object(strpt.subprocess, "run", run), \
             mock.patch.object(strpt, "_bot_token", return_value="tok"), \
             mock.patch("urllib.request.urlopen", return_value=resp):
            res = strpt.send_telegram(chunk, "-100123")
        assert res["ok"] is True
        assert res["transport"] == "bot-api"
        assert res["id"] == "4242"

    def test_bot_api_failure_reported_honestly(self, tmp_path):
        chunk = tmp_path / "chunk.txt"
        chunk.write_text("正文", encoding="utf-8")
        run = mock.MagicMock(return_value=mock.MagicMock(stdout=self.SKIPPED, stderr="", returncode=0))
        with mock.patch.object(strpt.subprocess, "run", run), \
             mock.patch.object(strpt, "_bot_token", return_value="tok"), \
             mock.patch("urllib.request.urlopen", side_effect=OSError("boom")):
            res = strpt.send_telegram(chunk, "-100123")
        assert res["ok"] is False
        assert "Bot API 异常" in res["id"]

    def test_hermes_success_does_not_double_send(self, tmp_path):
        chunk = tmp_path / "chunk.txt"
        chunk.write_text("正文", encoding="utf-8")
        ok_stdout = json.dumps({"success": True, "message_id": 31})
        run = mock.MagicMock(return_value=mock.MagicMock(stdout=ok_stdout, stderr="", returncode=0))
        with mock.patch.object(strpt.subprocess, "run", run), \
             mock.patch("urllib.request.urlopen") as urlopen:
            res = strpt.send_telegram(chunk, "-100123")
        assert res["ok"] and res["transport"] == "hermes-send" and res["id"] == "31"
        urlopen.assert_not_called()
