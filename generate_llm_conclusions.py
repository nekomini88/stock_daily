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
import sys
import time
import datetime
from pathlib import Path

import requests  # 注意：必须用 requests，urllib 会被 Cloudflare 拦（403 error code 1010）

ROOT = Path("/root/stock_daily")
ENV_PATH = Path("/root/.hermes/.env")
LLM_TIMEOUT = 180
MAX_TOKENS = 8192
MIN_SECTIONS = 12  # 至少覆盖 12/15 章才接受该 provider 的输出

# Provider 链：免费额度优先，失败依次降级。
# 注意：OpenCode Zen 免费档（*-free）现在只允许在 OpenCode 客户端内使用
# （返回 MissingSessionID），longcat-2.0-free 也已下线，故不再作为默认。
PROVIDERS = [
    {"name": "z.ai/glm-4.5-air", "url": "https://api.z.ai/api/paas/v4/chat/completions",
     "key_env": "GLM_API_KEY", "model": "glm-4.5-air"},
    {"name": "z.ai/glm-4.5-flash", "url": "https://api.z.ai/api/paas/v4/chat/completions",
     "key_env": "GLM_API_KEY", "model": "glm-4.5-flash"},
    {"name": "openrouter/gemini-2.5-flash", "url": "https://openrouter.ai/api/v1/chat/completions",
     "key_env": "OPENROUTER_API_KEY", "model": "google/gemini-2.5-flash"},
    {"name": "openrouter/deepseek-chat-v3.1", "url": "https://openrouter.ai/api/v1/chat/completions",
     "key_env": "OPENROUTER_API_KEY", "model": "deepseek/deepseek-chat-v3.1"},
]

LLM_KEYS = [
    "summary", "market_overview", "intraday", "macro", "sectors", "themes",
    "breadth", "technical", "stocks", "earnings", "institutions", "rotation",
    "watchlist", "risks", "conclusion",
]


def load_env_keys() -> dict:
    """读取 /root/.hermes/.env 里的 KEY=VALUE（跳过注释）。"""
    keys = {}
    try:
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, val = line.split("=", 1)
            keys[name.strip()] = val.strip().strip("\"'")
    except Exception as e:
        print(f"[WARN] 读取 .env 失败: {e}", file=sys.stderr)
    return keys


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
    # 只传价格会让 LLM 看不出方向（曾把 -0.19% 的美元写成"上涨"），价格与涨跌一起给
    out["macro"] = {
        k: {"price": v.get("price"), "change_pct": v.get("change_pct")}
        for k, v in macro.items() if isinstance(v, dict)
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


def _call_provider(provider: dict, api_key: str, sys_prompt: str, usr_prompt: str) -> str:
    """调用单个 provider，返回正文（失败返回空串）。"""
    payload = {
        "model": provider["model"],
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": usr_prompt},
        ],
        # 推理型模型（glm-4.5-air）的思考与正文共享额度，给足避免正文为空
        "max_tokens": MAX_TOKENS,
        "temperature": 0.3,
    }
    try:
        resp = requests.post(
            provider["url"],
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=LLM_TIMEOUT,
        )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "5") or 5)
            print(f"[WARN] {provider['name']} 429 限流，等待 {retry_after}s", file=sys.stderr)
            time.sleep(retry_after + 1)
            return ""
        if resp.status_code in (401, 403):
            print(f"[WARN] {provider['name']} {resp.status_code} 无法访问: {resp.text[:200]}", file=sys.stderr)
            return ""
        resp.raise_for_status()
        body = resp.json()
        msg = (body.get("choices") or [{}])[0].get("message", {}) or {}
        content = (msg.get("content") or "").strip()
        if not content:
            content = (msg.get("reasoning_content") or "").strip()
        if not content:
            print(f"[WARN] {provider['name']} 返回空 content", file=sys.stderr)
        return content
    except Exception as e:
        print(f"[WARN] {provider['name']} 调用失败: {e}", file=sys.stderr)
        return ""


def generate_conclusions(data: dict, max_retries=2):
    """按 provider 链生成 15 条结论。

    返回 (parsed: dict, provider_name: str)。全部 provider 失败或覆盖不足时
    parsed 为空 dict，由调用方走诚实占位兜底（绝不写假数据）。
    """
    env_keys = load_env_keys()
    data_compact = _compact_data(data)
    usr_prompt = _build_user_prompt(data_compact)

    for provider in PROVIDERS:
        api_key = env_keys.get(provider["key_env"], "")
        if not api_key:
            print(f"[WARN] {provider['name']} 缺少 {provider['key_env']}，跳过", file=sys.stderr)
            continue
        for attempt in range(max_retries):
            content = _call_provider(provider, api_key, SYSTEM_PROMPT, usr_prompt)
            if not content:
                if attempt < max_retries - 1:
                    time.sleep(3)
                continue
            parsed = _parse_json(content)
            covered = sum(
                1 for k in LLM_KEYS
                if isinstance(parsed.get(k), str) and str(parsed.get(k)).strip()
            )
            if covered >= MIN_SECTIONS:
                return parsed, provider["name"]
            print(f"[WARN] {provider['name']} 仅覆盖 {covered}/15 章，尝试下一个源", file=sys.stderr)
            break
    return {}, ""


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
    # LLM 输出无法解析为 JSON → 空结论 (记录原文便于排障)
    print(f"⚠️ LLM 结论输出无法解析为 JSON, 返回空: {content[:120]}", file=sys.stderr)
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
    parsed, provider_name = generate_conclusions(data)

    out_dir = ROOT / "llm_data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"market_llm_{today}.json"
    out_file.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")

    if len(parsed) < MIN_SECTIONS:
        # 明确失败信号：报告改走真实数据/诚实占位兜底，绝不写假数据
        print(f"❌ LLM 结论生成失败: {out_file} ({len(parsed)}/15 章)", file=sys.stderr)
        return 1
    print(f"✅ LLM 结论已生成: {out_file} ({len(parsed)}/15 章, 来源 {provider_name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())