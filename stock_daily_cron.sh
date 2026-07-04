#!/bin/bash
# 美股日报自动生成发送脚本
# 流程:
# 1. 收集数据生成 JSON
# 2. 生成 HTML
# 3. 生成 TG 用 TXT 分段文件并发送到 Telegram频道
# 4. 发送 HTML 邮件到配置邮箱

set -euo pipefail

cd /root/us_stock_daily

today=$(date +%Y-%m-%d)
mkdir -p files/${today}
echo "=== 开始生成 ${today} 美股收盘日报 ==="

# 1. 生成实时数据
python3 market_data_collector.py

# 2. 生成 HTML 报告
python3 generate_report.py

HTML_FILE="files/${today}/美股收盘日报_${today}.html"

if [[ ! -f "$HTML_FILE" ]]; then
    echo "❌ 报告生成失败，文件不存在: $HTML_FILE"
    exit 1
fi

echo "✅ 报告生成成功: $HTML_FILE"

# 3. 生成 TXT 分段文件并发送到 Telegram 频道
echo "=== 发送到 Telegram ==="
python3 send_tg_report.py "$HTML_FILE"

# 4. 发送 HTML 邮件
echo "=== 发送邮件 ==="
python3 send_report_email.py "$HTML_FILE" "美股收盘日报 ${today}" --html

echo "=== ${today} 美股收盘日报发送完成 ==="
