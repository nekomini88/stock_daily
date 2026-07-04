# us_stock_daily - 美股收盘日报生成与发送系统

专业的美股市场日报工具，每日自动生成《美股收盘日报》并发送到邮箱与 Telegram 频道。
报告采用多章节结构，输出 HTML 邮件版与等宽文本 Telegram 版。

## 当前流程

JSON 数据 → HTML 报告 → TG 纯文本 → 邮件发送
       ↓           ↓
 market_data_   generate_report.py
  collector.py        ├─ templates/report.html.j2
                      └─ files/<YYYY-MM-DD>/美股收盘日报_<YYYY-MM-DD>.html
                                    ↓
                            send_tg_report.py
                                    ├─ 生成 <pre> 分段文本
                                    ├─ 自动拆分多条消息
                                    └─ hermes send --file → Telegram
                                    ↓
                            send_report_email.py
                                    └─ SMTP_SSL → 收件人

## 功能特性

- **多章节报告**：大盘、宏观、板块、主题、市场宽度、技术面、重点个股、财报日历、机构观点、板块轮动、重点关注股、明日计划、风险提示、最终结论
- **双格式输出**：
  - HTML：邮件富文本
  - 纯文本：Telegram 等宽排版，自动分段
- **自动发送**：
  - Telegram：读取 `config.ini` 的频道 ID
  - 邮件：读取 `config.ini` 的 SMTP 配置
- **配置集中**：`config.ini` 集中管理 Telegram 频道与邮箱配置，敏感配置避免硬编码

## 项目文件

us_stock_daily/
├── stock_daily_cron.sh                 # 主入口：收集数据 → 生成 HTML → 发送 TG → 发送邮件
├── market_data_collector.py            # 收集 Yahoo Finance 行情并写入 daily_news/*.json
├── generate_report.py                  # 读取 JSON 并渲染模板
├── templates/
│   └── report.html.j2                  # Jinja2 报告模板
├── send_tg_report.py                   # HTML → Telegram 等宽文本，自动分段并发送
├── send_report_email.py                # 读取 TXT/HTML 文件并通过 SMTP 发送邮件
├── config.ini                          # Telegram / 邮件配置
├── .gitignore                          # 排除产物、配置、发送脚本、缓存
├── daily_news/                         # 当天市场数据缓存 JSON
├── files/<YYYY-MM-DD>/                 # 输出目录
│   └── 美股收盘日报_<YYYY-MM-DD>.html
│   └─ chunk_*.txt                      # TG 分段文件
├── index/                              # 静态展示目录
└── README.md

## 快速开始

### 环境要求
- Python 3.8+
- 已安装 `smtplib` / `email` / `jinja2`
- 已安装 Hermes CLI 用于 Telegram 发送

### 本地运行

```bash
cd /root/us_stock_daily

# 一键生成并发送
bash stock_daily_cron.sh

# 或分步运行
python3 market_data_collector.py
python3 generate_report.py
python3 send_tg_report.py files/2026-07-04/美股收盘日报_2026-07-04.html
python3 send_report_email.py files/2026-07-04/美股收盘日报_2026-07-04.html "美股收盘日报 2026-07-04" --html
```

### 单独发送（不生成报告）

```bash
# TG
python3 send_tg_report.py files/2026-07-04/美股收盘日报_2026-07-04.html

# 邮件
python3 send_report_email.py files/2026-07-04/美股收盘日报_2026-07-04.html "美股收盘日报" --html
```

## 定时任务

```bash
0 8 * * * cd /root/us_stock_daily && bash stock_daily_cron.sh >> /root/us_stock_daily/cron.log 2>&1
```

## 数据源

- **行情数据**：Yahoo Finance 免费 API
- **模板渲染**：Jinja2
- **邮件发送**：SMTP SSL
- **Telegram 发送**：Hermes CLI + Telegram Bot API

## 配置说明

示例 `config.ini`：

```ini
[telegram]
chat_id = -100XXXXXXX

[email]
smtp_server = smtp.qq.com
smtp_port = 465
sender_email = your@email.com
sender_pass = <邮箱授权码>
recipient = recipient@example.com
sender_name = Nekomini daily bot
```

`config.ini` 已写入 `.gitignore`，不提交到版本库。

## 版本历史

- **v1.0.3** (2026-07-04): 重构发送链路，新增 `send_tg_report.py`，配置集中到 `config.ini`
- **v1.0.2** (2026-07-04): 修复 Telegram 发送异常，统一 HTML→文本转换逻辑
- **v1.0.1** (2026-07-03): 按日期分目录存储、定时任务脚本、文档完善
- **v1.0.0** (2026-07-03): 初始版本，完整15章节报告、HTML+文本双格式、邮件/Telegram自动发送

## 免责声明

本工具生成的报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。

## 许可证

MIT License
