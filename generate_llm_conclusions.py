#!/usr/bin/env python3
"""
美股日报 15 条结论 → LLM 生成器
读取 real market data，调用 OpenCode Zen LLM 按提示词一次性生成 15 章结构化结论。

设计：
- 复用 OPENCODE_ZEN_API_KEY（.env）+ longcat-2.0-free
- 输出 /root/stock_daily/llm_data/llm_<date>.json（15 章 → 具体字段）
- 失败时输出 null 字段，由 generate_stock_daily 走本地兜底
"""
from __future__ import annotations

import json
import os
import sys
import time
import datetime
from pathlib import Path

import requests  # 注意：必须用 requests，urllib 会被 Cloudflare 拦（403 error code 1010）

ROOT = Path("/root/stock_daily")
LLM_API_URL = os.environ.get("LLM_API_URL", "https://opencode.ai/zen/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "longcat-2.0-free")
LLM_TIMEOUT = 120


def load_llm_key() -> str:
    env_path = Path("/root/.hermes/.env")
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENCODE_ZEN_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    except Exception as e:
        print(f"[WARN] 读取 .env 失败: {e}", file=sys.stderr)
    return ""


def _pct(ind: dict) -> str:
    try:
        return f"{float(ind.get('change_pct', 0)):+.2f}%"
    except Exception:
        return "—"


def _compact_data(data: dict) -> dict:
    """把采集的原始 JSON 压缩成 LLM 可读的中文要点，控制 token。"""
    out: dict = {}

    indices = data.get("indices") or {}
    idx_compact = {}
    for name, v in indices.items():
        if isinstance(v, dict):
            idx_compact[name] = {
                "price": v.get("price"),
                "prev_close": v.get("prev_close"),
                "change_pct": v.get("change_pct"),
                "high": v.get("high"),
                "low": v.get("low"),
            }
    out["indices"] = idx_compact

    sectors = data.get("sectors_performance") or []
    out["sectors"] = [
        {"name": s.get("name") or s.get("etf", ""), "etf": s.get("etf", ""), "change_pct": s.get("change_pct"),
         "change_5d": s.get("change_5d"), "change_1m": s.get("change_1m")}
        for s in sectors
    ]

    themes = data.get("themes_performance") or []
    out["themes"] = [
        {"name": t.get("name"), "etf": t.get("etf", ""), "change_pct": t.get("change_pct"),
         "change_5d": t.get("change_5d"), "change_1m": t.get("change_1m")}
        for t in themes
    ]

    mag7 = data.get("magnificent_7") or {}
    out["magnificent_7"] = {
        s: {"price": v.get("price"), "change_pct": v.get("change_pct")}
        for s, v in mag7.items() if isinstance(v, dict)
    }

    futures = data.get("futures") or {}
    out["futures"] = {
        s: {"change_pct": v.get("change_pct")} for s, v in futures.items() if isinstance(v, dict)
    }

    macro = data.get("macro") or {}
    out["macro"] = {
        k: (v if isinstance(v, (int, float, str)) else
            (v.get("price") or v.get("value") or v.get("change_pct") if isinstance(v, dict) else v))
        for k, v in macro.items()
    }
    return out


SYSTEM_PROMPT = (
    "你是资深美股投资分析师，基于给定的当日真实市场数据，生成一份专业的收盘分析日度的15条结构化结论。\n"
    "要求：\n"
    "1. 严格基于提供的数据，不回编、不臆造具体数值。所有数字必须来自输入数据。\n"
    "2. 每条结论精炼、专业、有数据支撑，中文，每条 30~60 字。\n"
    "3. 必须覆盖以下 15 个章节，每个章节给出结论性文字。\n"
    "4. 只输出合法 JSON，不要输出任何解释、markdown 代码块或多余文字。\n"
    "5. 若某章节数据缺失，就写'当日暂无相关数据'，不要编造。\n"
)


def _build_user_prompt(data_compact: dict) -> str:
    return (
        "【当日美股真实市场数据】\n"
        + json.dumps(data_compact, ensure_ascii=False, indent=1)
        + "\n\n"
        "请按以下15章节，生成每条结论文字，严格输出 JSON 对象（键名固定如下）：\n"
        "{\n"
        '  "summary": "一句话总结当日大盘",\n'
        '  "market_overview": "大盘表现总览(指数/涨跌/极值)",\n'
        '  "intraday": "盘中走势复盘",\n'
        '  "macro": "宏观环境(利率/Fed/美元/黄金/原油)",\n'
        '  "sectors": "板块表现",\n'
        '  "themes": "主题与风格表现",\n'
        '  "breadth": "市场宽度与参与度",\n'
        '  "technical": "技术面分析",\n'
        '  "stocks": "重点个股异动(七巨头/AI硬件/软件/电力)",\n'
        '  "earnings": "财报日历与解读",\n'
        '  "institutions": "机构观点",\n'
        '  "rotation": "板块轮动",\n'
        '  "watchlist": "重点关注股(明日)",\n'
        '  "risks": "风险提示",\n'
        '  "conclusion": "最终结论(含操作建议)"\n'
        "}"
    )


def generate_conclusions(data: dict, max_retries=3) -> str:
    """调用 LLM 生成 15 条结论文本。失败返回空串（由调用方兜底）。"""
    api_key = load_llm_key()
    if not api_key:
        print("[WARN] 未找到 OPENCODE_ZEN_API_KEY，跳过 LLM", file=sys.stderr)
        return ""

    data_compact = _compact_data(data)
    sys_prompt = SYSTEM_PROMPT
    usr_prompt = _build_user_prompt(data_compact)

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": usr_prompt},
        ],
        "max_tokens": 4096,
        "temperature": 0.3,
    }

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                LLM_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=LLM_TIMEOUT,
            )
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "3"))
                print(f"[WARN] LLM 429 限流，等待 {retry_after}s", file=sys.stderr)
                time.sleep(retry_after + 1)
                continue
            if resp.status_code == 403:
                print(f"[WARN] LLM 403 Forbidden（Cloudflare 拦截或 key 失效）: {resp.text[:200]}", file=sys.stderr)
                time.sleep(3)
                continue
            resp.raise_for_status()
            body = resp.json()
            msg = (body.get("choices") or [{}])[0].get("message", {}) or {}
            content = (msg.get("content") or "").strip()
            if not content:
                content = (msg.get("reasoning_content") or "").strip()
            if content:
                return content
            print("[WARN] LLM 返回空 content", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] LLM 生成失败 (attempt {attempt+1}): {e}", file=sys.stderr)
            if attempt < max_retries - 1:
                time.sleep(3)
    return ""


def _parse_json(content: str) -> dict:
    """尝试解析 LLM 输出 JSON，容忍 ```json 包裹。"""
    content = content.strip()
    if content.startswith("```"):
        # 去掉 ```json ... ``` 之类包裹
        import re
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
        if m:
            content = m.group(1).strip()
    try:
        return json.loads(content)
    except Exception:
        # 尝试提取第一个 { ... } 平衡块
        import re
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {}


def main():
    today = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().strftime("%Y-%m-%d")
    data_file = Path(ROOT) / "daily_news" / f"market_data_{today}.json"
    if not data_file.exists():
        # 尝试读最新
        base = ROOT / "daily_news"
        candidates = sorted(base.glob("market_data_*.json"))
        data_file = candidates[-1] if candidates else None
        if data_file:
            today = data_file.stem.replace("market_data_", "")
    if not data_file or not data_file.exists():
        print("❌ 找不到 market data，退出", file=sys.stderr)
        return 1

    data = json.loads(data_file.read_text(encoding="utf-8"))
    content = generate_conclusions(data)
    parsed = _parse_json(content) if content else {}

    out_dir = ROOT / "llm_data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"market_llm_{today}.json"
    out_file.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ LLM 结论已生成: {out_file} ({len(parsed)} 章节)")
    return 0


if __name__ == "__main__":
    sys.exit(main())