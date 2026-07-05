#!/bin/bash
# 美股日报自动生成发送脚本
# 流程:
# 1. 收集数据生成 JSON
# 2. 生成 HTML
# 3. 生成 TG 用 TXT 分段文件并发送到 Telegram频道
# 4. 发送 HTML 邮件到配置邮箱
# 5. 提交前红线审查

set -uo pipefail

cd /root/stock_daily

today=$(date +%Y-%m-%d)
mkdir -p files/${today}
echo "=== 开始生成 ${today} 美股收盘日报 ==="

# 1. 生成实时数据
python3 market_data_collector.py

# 2. 生成 HTML 报告（支持动态 data_file / today）
python3 generate_stock_daily.py --today "${today}"

HTML_FILE="files/${today}/美股收盘日报_${today}.html"

if [[ ! -f "$HTML_FILE" ]]; then
    echo "❌ 报告生成失败，文件不存在: $HTML_FILE"
    exit 1
fi

echo "✅ 报告生成成功: $HTML_FILE"

# 3. 生成 TXT 分段文件并发送到 Telegram 频道
echo "=== 发送到 Telegram ==="
for attempt in 1 2 3; do
    if python3 send_tg_report.py "$HTML_FILE"; then
        echo "✅ Telegram 发送成功"
        break
    fi
    echo "⚠️ Telegram 发送失败，第 ${attempt} 次重试..."
    sleep 3
    if [[ $attempt -eq 3 ]]; then
        echo "❌ Telegram 发送失败，已跳过，继续后续流程"
    fi
done

# 4. 发送 HTML 邮件
echo "=== 发送邮件 ==="
python3 send_report_email.py "$HTML_FILE" "美股收盘日报 ${today}" --html

# Step 5: 提交前红线审查（仅审查，不阻断主流程）
echo "🛡️  红线审查..."
RED_REPORT="files/${today}/red_line_review.txt"
if python3 /root/tools/git_red_line_review.py scan "$(pwd)" > "$RED_REPORT"; then
    echo "✅ 红线审查通过"
else
    echo "⚠️  红线审查发现潜在问题，已将报告写入：$RED_REPORT"
    echo "⚠️  日报已发送，但请人工审核上述报告后再提交至 GitHub"
fi

echo "=== ${today} 美股日报发送完成 ==="
