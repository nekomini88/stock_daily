# stock_daily — 美股收盘日报生成与投递系统

专业的美股市场日报工具：每日自动采集 **Yahoo Finance 真实行情**，由 **LLM 基于当日真实数据生成 15 章专业分析结论**，渲染为 HTML 报告，并同时投递到 **Telegram 频道** 与 **Email**。

## 🏗 架构

```text
Yahoo Finance 行情采集
      │  market_data_collector.py
      ▼
daily_news/market_data_YYYY-MM-DD.json   ← 真实行情快照（指数/七巨头/板块/主题/期货/宏观）
      │
      ├─► generate_llm_conclusions.py ──► llm_data/market_llm_YYYY-MM-DD.json（15 章结论）
      │        OpenCode Zen (longcat-2.0-free)
      │
      ▼
generate_stock_daily.py  (Jinja2 模板渲染，LLM 结论覆盖文字、真实数据填表格)
      │
      ▼
files/YYYY-MM-DD/美股收盘日报_YYYY-MM-DD.html
      │
      ├─► send_tg_report.py      ──► Telegram 频道（等宽文本自动分段）
      └─► send_report_email.py   ──► Email（HTML 邮件）
```

## 📁 目录结构

```
stock_daily/
├── stock_daily.sh                  # 主入口：采集 → LLM 结论 → 生成 HTML → 发 TG → 发邮件 → 红线审查
├── market_data_collector.py        # Yahoo Finance 行情采集（指数/七巨头/11板块/主题/期货/宏观）
├── generate_llm_conclusions.py     # LLM 生成 15 章结论（OpenCode Zen，基于真实数据）
├── generate_stock_daily.py         # 读取 JSON + LLM 结论，渲染 HTML 报告
├── final_conclusion.py             # 第15章规则兜底（LLM 失败时使用）
├── templates/
│   └── report.html.j2              # Jinja2 报告模板（15 章节）
├── send_tg_report.py               # HTML → Telegram 等宽文本，自动分段发送
├── send_report_email.py            # 发送 HTML 邮件
├── docker-compose.yml              # Caddy 静态部署（index/ 快照站点）
├── Caddyfile                       # Caddy 配置
└── config.ini                      # 私密配置（SMTP/TG 频道，不提交）
```

## 🔧 报告 15 章节结构

LLM 按固定 JSON schema 输出，映射到模板：

| # | 章节 | LLM 键 |
|---|------|--------|
| 0 | 今日一句话总结 | `summary` |
| 1 | 大盘表现总览 | `market_overview` |
| 2 | 盘中走势复盘 | `intraday` |
| 3 | 宏观环境（利率/Fed/美元/黄金/原油） | `macro` |
| 4 | 板块表现 | `sectors` |
| 5 | 主题与风格表现 | `themes` |
| 6 | 市场宽度与参与度 | `breadth` |
| 7 | 技术面分析 | `technical` |
| 8 | 重点个股异动 | `stocks` |
| 9 | 财报日历与解读 | `earnings` |
| 10 | 机构观点 | `institutions` |
| 11 | 板块轮动 | `rotation` |
| 12 | 重点关注股 | `watchlist` |
| 13 | 明日观察清单 | `risks`* |
| 14 | 风险提示 | — |
| 15 | 最终结论 | `conclusion` |

> *`risks` 映射至模板第 14 章风险提示；第 13 章观察清单由 LLM `watchlist` 与真实行情共同填充。

**原则**：表格数值一律使用当日真实采集数据；LLM 只生成分析性结论文本，缺失数据章节输出"当日暂无相关数据"，禁止编造。

## 🚀 本地运行

```bash
bash stock_daily.sh
```

或分步执行：

```bash
# 1. 采集行情
python3 market_data_collector.py

# 2. 生成 LLM 15 章结论（失败不阻断，自动用规则兜底）
python3 generate_llm_conclusions.py 2026-08-06

# 3. 生成 HTML 报告
python3 generate_stock_daily.py --today 2026-08-06

# 4. 发送（可选）
python3 send_tg_report.py files/2026-08-06/美股收盘日报_2026-08-06.html
python3 send_report_email.py files/2026-08-06/美股收盘日报_2026-08-06.html "美股收盘日报 2026-08-06" --html
```

## ⏰ 调度

Hermes cron job（`fd5ef5bf3bff`，工作日 08:00）：

```text
0 8 * * 2-6  →  bash /root/stock_daily/stock_daily.sh
```

投递目标：
- Telegram 频道：`-1004363733232`（cron deliver）
- Email：（config.ini `recipient`，发件人 `Nekomini daily bot`）

## 🤖 LLM 接入

- **Endpoint**：`https://opencode.ai/zen/v1/chat/completions`
- **Model**：`longcat-2.0-free`
- **Key**：`OPENCODE_ZEN_API_KEY`（`/root/.hermes/.env`）
- ⚠️ **必须用 `requests`**：`urllib` 会被 Cloudflare 拦截（HTTP 403 error code 1010）

## 🔒 隐私

`config.ini`（SMTP 密码等）已写入 `.gitignore`，绝不提交。生成产物（`daily_news/`、`files/`、`llm_data/`、`index/`、`cron.log`）均不纳入版本控制。

## 🐳 Docker 静态部署

Caddy 容器提供 `index/index.html` 最新日报快照：

```bash
docker compose up -d
```

- 访问：`http://localhost:9005` 或 `http://<IP>:9005`
- 容器名：`stock_daily`，端口 `9005:80`

## 📌 关键实现细节

- **TG 发送**：`send_tg_report.py` 使用 hermes CLI 绝对路径（`$HOME/.local/bin/hermes`），适配 cron 最小环境
- **缓存**：静态资源带版本参数（如 `?v=1.1.2`）避免浏览器/CF 缓存旧版
- **兜底链**：LLM 失败 → `final_conclusion.py` 规则结论 → 模板硬编码默认值，保证报告永不中断
