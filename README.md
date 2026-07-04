# stock_daily - 美股收盘日报生成与发送系统

专业的美股市场日报工具，每日自动生成《美股收盘日报》并发送到邮箱与 Telegram 频道。

## 目录

```
stock_daily/
├── stock_daily.sh                  # 主入口：收集数据 → 生成 HTML → 发送 TG → 发送邮件
├── market_data_collector.py         # 收集 Yahoo Finance 行情并写入 daily_news/*.json
├── generate_stock_daily.py          # 读取 JSON 并渲染模板
├── templates/
│   └── report.html.j2               # Jinja2 报告模板
├── send_tg_report.py                # HTML → Telegram 等宽文本，自动分段并发送
├── send_report_email.py             # 发送 HTML 邮件
└── config.ini                       # 私密配置，不提交
```

## 本地运行

```bash
bash stock_daily.sh
```

## 调度

使用系统 crontab，每天 8:00 执行：

```bash
0 8 * * * cd /root/stock_daily && bash stock_daily.sh >> /root/stock_daily/cron.log 2>&1
```

## 隐私

不把敏感内容提交到 GitHub，`config.ini` 已写入 `.gitignore`。
