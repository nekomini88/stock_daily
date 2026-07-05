#!/usr/bin/env python3
"""
结论生成器 — 基于真实市场数据动态生成第15节结论

目标：替换 stock_daily 报告模板中硬编码的 market_conclusion /
market_phase / trading_bias / key_signals，使最终结论可复现、不丢信息。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _pct(val: Optional[float]) -> Optional[float]:
    if isinstance(val, (int, float)):
        return float(val)
    return None


def _fmt(val: Optional[float]) -> str:
    if val is None:
        return "暂无"
    return f"{val:+.2f}%"


def _safe(items: Any, idx: int = 0) -> Any:
    if not items or not isinstance(items, list):
        return None
    try:
        return items[idx]
    except Exception:
        return None


def analyze_session(data: Dict[str, Any]) -> Dict[str, Any]:
    indices = data.get("indices") or {}
    macro = data.get("macro") or {}
    mag7 = data.get("magnificent_7") or {}
    futures = data.get("futures") or {}
    sectors_performance: List[Dict[str, Any]] = data.get("sectors_performance") or []
    themes_performance: List[Dict[str, Any]] = data.get("themes_performance") or []

    # 硬编码别名映射（保持稳定性）
    alias = {
        "^GSPC": "S&P 500",
        "SPY": "S&P 500",
        "^IXIC": "Nasdaq 100",
        "QQQ": "Nasdaq 100",
        "^DJI": "Dow Jones",
        "DIA": "Dow Jones",
        "^RUT": "Russell 2000",
        "IWM": "Russell 2000",
        "SOXX": "半导体",
        "VIX": "VIX",
    }

    sp_name = alias.get("^GSPC", "S&P 500")
    qq_name = alias.get("^IXIC", "Nasdaq 100")

    sp = indices.get(sp_name) or indices.get("SPY") or {}
    qq = indices.get(qq_name) or indices.get("QQQ") or {}
    dw = indices.get(alias.get("^DJI", "Dow Jones")) or indices.get("DIA") or {}
    ru = indices.get(alias.get("^RUT", "Russell 2000")) or indices.get("IWM") or {}
    soxx = indices.get("半导体") or indices.get("SOXX") or {}
    bond = macro.get("10Y收益率") or macro.get("^TNX") or {}
    dxy = macro.get("美元指数DXY") or macro.get("DX-Y.NYB") or {}
    gold = macro.get("黄金") or macro.get("GC=F") or {}

    sp_chg = _pct(sp.get("change_pct"))
    qq_chg = _pct(qq.get("change_pct"))
    dw_chg = _pct(dw.get("change_pct"))
    ru_chg = _pct(ru.get("change_pct"))
    soxx_chg = _pct(soxx.get("change_pct"))

    rising_sectors = [s for s in sectors_performance if _pct(s.get("change")) and _pct(s.get("change")) > 0]
    falling_sectors = [s for s in sectors_performance if _pct(s.get("change")) and _pct(s.get("change")) < 0]
    top_sector = _safe(rising_sectors, 0)
    worst_sector = _safe(falling_sectors, 0)

    mag7_names = []
    for sym, row in mag7.items() if isinstance(mag7, dict) else []:
        p = _pct(row.get("change_pct"))
        if p is not None:
            mag7_names.append((sym, p))
    mag7_positive = [x for x in mag7_names if x[1] >= 0]
    mag7_negative = [x for x in mag7_names if x[1] < 0]
    best_mag7 = _safe(sorted(mag7_positive, key=lambda x: x[1], reverse=True), 0)
    worst_mag7 = _safe(sorted(mag7_negative, key=lambda x: x[1]), 0)

    # 信号池
    signals: List[str] = []

    def add_signal(text: str) -> None:
        if text and text not in signals:
            signals.append(text)

    def sector_info(s):
        name = s.get("name", "板块") if isinstance(s, dict) else "板块"
        chg = _pct(s.get("change"))
        return f"{name}({_fmt(chg)})" if chg is not None else name

    # 判断逻辑：bias 与 phase
    def pct2(val):
        v = _pct(val)
        return 0.0 if v is None else v

    # phase
    if pct2(sp_chg) > 1.5 and pct2(qq_chg) > 1.5:
        market_phase = "强多头"
    elif pct2(sp_chg) > 0.5 and pct2(qq_chg) > 0:
        market_phase = "温和多头"
    elif pct2(sp_chg) < -1.5 and pct2(qq_chg) < -1.5:
        market_phase = "剧烈调整"
    elif pct2(sp_chg) < -0.5 and pct2(qq_chg) < 0:
        market_phase = "偏弱调整"
    elif pct2(ru_chg or 0.0) > 0.5 and pct2(sp_chg or 0.0) < 0:
        market_phase = "高低切/补涨"
    elif abs(pct2(sp_chg)) <= 0.3 and abs(pct2(qq_chg)) <= 0.5:
        market_phase = "窄幅震荡"
    elif pct2(sp_chg or 0) > 0 and pct2(qq_chg or 0) < 0:
        market_phase = "价值占优/成长承压"
    elif pct2(sp_chg or 0) < 0 and pct2(qq_chg or 0) > 0:
        market_phase = "成长修复/价值承压"
    else:
        market_phase = "结构分化"

    # bias
    good = bad = 0
    if pct2(sp_chg) > 0:
        good += 1
    else:
        bad += 1
    if pct2(qq_chg) > 0:
        good += 1
    else:
        bad += 1
    if best_mag7:
        good += 1
    if worst_sector and pct2(worst_sector.get("change")) < -1.0:
        bad += 1
    if pct2(ru_chg or 0) > 0.5:
        good += 1

    if bad >= good:
        trading_bias = "防守为主，优先减仓高风险成长股，关注公用事业、必需消费品等防御板块"
    elif good == 0:
        trading_bias = "维持现有仓位，不宜追涨杀跌，观察量能变化"
    else:
        trading_bias = "偏进取，优先关注主线龙头，仓位可向强势板块倾斜，但避免单票仓位过重"

    # 结论
    parts = []
    if pct2(sp_chg or 0) > 0 and pct2(qq_chg or 0) > 0:
        parts.append(f"主要指数录得涨幅，{sp_name} {_fmt(sp_chg)}，{qq_name} {_fmt(qq_chg)}，市场整体偏多")
    elif pct2(sp_chg or 0) < 0 and pct2(qq_chg or 0) < 0:
        parts.append(f"主要指数承压收跌，{sp_name} {_fmt(sp_chg)}，{qq_name} {_fmt(qq_chg)}，市场情绪偏谨慎")
    else:
        parts.append(f"指数表现分化，{sp_name} {_fmt(sp_chg)}，{qq_name} {_fmt(qq_chg)}，结构性机会占主导")
    if soxx_chg is not None:
        if soxx_chg < -5.0:
            parts.append("半导体大幅回调，警惕芯片链获利了结压力")
        elif soxx_chg < -1.0:
            parts.append("半导体走弱，短期高位承压")
        elif soxx_chg > 3.0:
            parts.append("半导体大涨，AI 硬件链延续强势")
        elif soxx_chg > 1.0:
            parts.append("半导体偏强，AI 硬件链仍受追捧")
    if top_sector:
        parts.append(f"行业领涨方向：{sector_info(top_sector)}")
    if worst_sector:
        parts.append(f"承压板块：{sector_info(worst_sector)}")
    if best_mag7:
        parts.append(f"Magnificent 7 领涨：{best_mag7[0]}({_fmt(best_mag7[1])})")
    if worst_mag7:
        parts.append(f"Magnificent 7 领跌：{worst_mag7[0]}({_fmt(worst_mag7[1])})")
    if pct2(bond.get("change_pct")) > 0.3:
        parts.append("美债收益率上行加快，对成长股估值形成压制")
    elif pct2(bond.get("change_pct")) < -0.3:
        parts.append("美债收益率下修，有利于权益资产估值修复")
    if pct2(dxy.get("change_pct")) > 0.3:
        parts.append("美元走强，新兴市场与大宗商品承压")
    elif pct2(dxy.get("change_pct")) < -0.3:
        parts.append("美元走弱，风险偏好边际改善")
    if pct2(gold.get("change_pct")) > 1.5:
        parts.append("黄金大涨，避险情绪升温")
    if pct2(ru_chg or 0) > 1.0:
        parts.append("小盘股表现占优，市场风险偏好改善")
    elif pct2(ru_chg or 0) < -1.0:
        parts.append("小盘股回调，避险情绪升温")

    if not parts:
        parts.append("市场整体维持中性格局，等待下一明确催化剂")
    market_conclusion = "；".join(parts) + "。"

    # 信号池
    if pct2(sp_chg or 0) > 1.0:
        add_signal(f"标普强势大涨，确认短期多头格局延续")
    elif pct2(sp_chg or 0) < -1.0:
        add_signal(f"标普跌幅超过1%，短期风险升温")
    if soxx_chg is not None:
        if soxx_chg < -5.0:
            add_signal("半导体单日跌幅大于5%，警惕中期调整")
        if soxx_chg > 3.0:
            add_signal("半导体大涨突破，AI 硬件链仍为市场主旋律")
    if top_sector:
        add_signal(f"领涨板块：{sector_info(top_sector)}")
    if best_mag7:
        add_signal(f"龙头最强标的：{best_mag7[0]} {_fmt(best_mag7[1])}")
    if pct2(bond.get("change_pct")) > 0.3:
        add_signal("10Y 美债收益率明显上行")
    elif pct2(bond.get("change_pct")) < -0.3:
        add_signal("10Y 美债收益率明显下行")
    if pct2(gold.get("change_pct")) > 2.0:
        add_signal("黄金大幅波动，反映不确定性与避险情绪")
    if pct2(ru_chg or 0) > 1.0:
        add_signal("小盘股显著跑赢，市场风险偏好转暖")
    elif pct2(ru_chg or 0) < -1.0:
        add_signal("小盘股显著走弱，避险情绪升温")
    if themes_performance:
        top_theme = _safe(sorted(themes_performance, key=lambda x: _pct(x.get("change")) or 0, reverse=True), 0)
        if top_theme:
            add_signal(f"最强主题/风格：{top_theme.get('name', '主题')} {_fmt(_pct(top_theme.get('change')))}")
    while len(signals) < 5:
        signals.append("暂无其他强信号，关注次日宏观催化与财报日程")
    # deduplicate while preserving order
    seen = set()
    signals = [s for s in signals if s not in seen and not seen.add(s)][:5]

    return {
        "market_conclusion": market_conclusion,
        "market_phase": market_phase,
        "trading_bias": trading_bias,
        "key_signals": signals,
        "debug": {
            "sp_chg": sp_chg,
            "qq_chg": qq_chg,
            "ru_chg": ru_chg,
            "soxx_chg": soxx_chg,
            "bond_chg": _pct(bond.get("change_pct")),
            "gold_chg": _pct(gold.get("change_pct")),
            "dxy_chg": _pct(dxy.get("change_pct")),
            "top_sector": top_sector.get("name") if isinstance(top_sector, dict) else None,
            "worst_sector": worst_sector.get("name") if isinstance(worst_sector, dict) else None,
            "best_mag7": best_mag7[0] if best_mag7 else None,
            "worst_mag7": worst_mag7[0] if worst_mag7 else None,
        },
    }
