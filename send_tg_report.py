#!/usr/bin/env python3
"""
美股日报 HTML → Telegram 分段发送脚本
对应原 shell: /root/us_stock_daily/send_tg_report.sh

支持从同目录 config.ini 读取配置，实现发送频道解耦。
"""

import re
import sys
import configparser
import subprocess
from pathlib import Path


# ─── 配置文件读取 ─────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.ini"

config = configparser.ConfigParser()
config.read(CONFIG_PATH, encoding="utf-8")

# 默认配置（config 未配置时使用）
DEFAULT_CHAT = config.get("telegram", "chat_id", fallback="-1004363733232")
CHUNK_LIMIT = config.getint("telegram", "chunk_limit", fallback=3900)

HERMES_CMD = ["hermes", "send", "--to"]


# ─── HTML → Telegram 等宽纯文本 ─────────────────────────────
def html_to_tg(html: str) -> str:
    # 0) 只取 <body>，避免 <head> 里的 <title> 重复；再从正文里只保留第一个报告标题之后的内容
    m = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL | re.IGNORECASE)
    html = m.group(1) if m else html
    title_mark = "📈 美股收盘日报｜2026-07-04"
    idx = html.find(title_mark)
    html = html[idx:] if idx >= 0 else html

    # 1) 移除 style / script
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # 2) 提取表格 => 替换为 marker
    tables = []

    def extract_table(m):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.DOTALL)
        lines = []
        for row in rows:
            ths = re.findall(r"<th[^>]*>(.*?)</th>", row, re.DOTALL)
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            cells = ths if ths else tds
            parts = []
            for cell in cells:
                s = re.sub(r"<[^>]+>", "", cell)
                s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ").replace("%%", "%")
                parts.append(s.strip())
            if parts:
                lines.append(" | ".join(parts))
        tables.append("\n".join(lines))
        return f"\x00TABLE{len(tables)-1}\x00"

    html = re.sub(r"<table[^>]*>.*?</table>", extract_table, html, flags=re.DOTALL)

    # 3) 移除所有剩余 HTML 标签
    html = re.sub(r"<[^>]+>", " ", html)

    # 4) 先去掉正文里所有标题行，后面再加统一 header，避免重复
    title_variants = ["📈 美股收盘日报｜2026-07-04", "美股收盘日报｜2026-07-04"]
    for variant in title_variants:
        html = re.sub(r"(?m)^" + re.escape(variant) + r"\s*$", "", html)
        html = re.sub(r"(?m)^\s*" + re.escape(variant) + r"\s*$", "", html)
    html = re.sub(r"\n{3,}", "\n\n", html)

    # 5) 实体解码 + 格式化
    html = html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ").replace("%%", "%")
    lines = [line.strip() for line in html.split("\n") if line.strip()]
    html = "\n".join(lines)

    # 6) 放回表格为 <pre> 块
    for i, tbl in enumerate(tables):
        html = html.replace(f"\x00TABLE{i}\x00", "\n<pre>\n" + tbl + "\n</pre>\n")

    # 7) 头尾包裹
    header = "<b>📈 美股收盘日报｜2026-07-04</b>"
    footer = "\n\n⚠️ 本报告基于市场数据自动生成，仅供参考，不构成投资建议。投资有风险，入市需谨慎。"
    full = header + "\n\n" + html.strip() + footer
    full = re.sub(r"\n{3,}", "\n\n", full)
    return full.strip()


# ─── 分段 ─────────────────────────────────────────────────
def split_chunks(text: str):
    chunks = []
    pos = 0
    first = True
    while pos < len(text):
        if len(text) - pos <= CHUNK_LIMIT:
            chunks.append(text[pos:])
            break
        cut = text[pos : pos + CHUNK_LIMIT]
        split = cut.rfind("\n\n<b>")
        if split < 400:
            split = cut.rfind("\n\n")
        if split < 400:
            split = CHUNK_LIMIT
        prefix = "" if first else "<b>📈 美股收盘日报｜2026-07-04（续）</b>\n\n"
        chunks.append(prefix + text[pos : pos + split].strip())
        pos += split
        first = False
    return chunks


# ─── 发送 ─────────────────────────────────────────────────
def send_telegram(file_path: Path, chat_id: str):
    cmd = HERMES_CMD + [f"telegram:{chat_id}", "--file", str(file_path), "--json"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        msg_id = "?"
        if result.stdout.strip():
            try:
                import json
                msg_id = json.loads(result.stdout).get("message_id", "?")
            except Exception:
                pass
        return True, msg_id
    except subprocess.CalledProcessError as e:
        return False, f"{e.returncode}: {e.stderr.strip()}"


# ─── 主流程 ────────────────────────────────────────────────
def main():
    script_dir = Path(__file__).resolve().parent

    # 1. 读取参数，第一个为 html_file，第二个可覆盖 chat_id
    html_file = sys.argv[1] if len(sys.argv) > 1 else ""
    chat_id = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CHAT

    if not html_file:
        # 默认路径: <script_dir>/files/<today>/美股收盘日报_<today>.html
        today = __import__("datetime").date.today().isoformat()
        html_file = str(script_dir / "files" / today / f"美股收盘日报_{today}.html")

    html_path = Path(html_file)
    if not html_path.is_file():
        print(f"❌ 找不到 HTML 文件: {html_path}")
        print(f"   用法: {Path(sys.argv[0]).name} [html_file] [chat_id]")
        sys.exit(1)

    base_dir = html_path.parent
    print(f"📄 HTML 源文件: {html_path}")
    print(f"📺 目标频道:   {chat_id}")
    print(f"📑 分段上限:   {CHUNK_LIMIT} 字符")
    print()

    # 2. 转换
    raw = html_path.read_text(encoding="utf-8")
    full_text = html_to_tg(raw)
    print(f"✅ 转换完成: {len(full_text)} 字符")

    # 3. 分段
    chunks = split_chunks(full_text)
    print(f"✅ 分段完成: {len(chunks)} 段")
    for i, c in enumerate(chunks, 1):
        p = base_dir / f"chunk_{i}.txt"
        p.write_text(c, encoding="utf-8")
        print(f"   [{i}] {p.name} ({len(c)} chars)")

    # 4. 发送
    print()
    print("📤 开始发送...")
    chunk_files = sorted(base_dir.glob("chunk_*.txt"))
    for i, chunk_file in enumerate(chunk_files, 1):
        ok, msg_id = send_telegram(chunk_file, chat_id)
        if ok:
            print(f"   [{i}] ✅ 已发送 (message_id={msg_id}) -> {chunk_file.name}")
        else:
            print(f"   [{i}] ❌ 发送失败: {msg_id}")
            sys.exit(1)

    print()
    print(f"🎉 全部完成！共发送 {len(chunks)} 条消息到 {chat_id}")


if __name__ == "__main__":
    main()
