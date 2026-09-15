#!/usr/bin/env python3
"""
美股日报 HTML → Telegram 分段发送脚本
对应原 shell: /root/stock_daily/send_tg_report.sh

支持从同目录 config.ini 读取配置，实现发送频道解耦。
"""

import re
import sys
import json
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

# hermes CLI 定位：cron 环境 PATH 不含 hermes，需用绝对路径。
# 优先 <HOME>/.local/bin/hermes，其次 PATH 里的 hermes
import shutil, os
_HOME = os.path.expanduser("~")
_HERMES_CANDIDATES = [
    str(Path(_HOME) / ".local/bin/hermes"),
    str(Path("/root") / ".local/bin/hermes"),
    "hermes",  # 最后的 PATH 兜底
]
_HERMES_CMD = os.environ.get("HERMES_CMD_PATH")
if not _HERMES_CMD:
    for _c in _HERMES_CANDIDATES:
        if _c == "hermes":
            _found = shutil.which("hermes")
            if _found:
                _HERMES_CMD = _found
                break
        elif Path(_c).is_file():
            _HERMES_CMD = _c
            break
_HERMES_CMD = _HERMES_CMD or "hermes"
HERMES_CMD = [_HERMES_CMD, "send", "--to"]


# ─── HTML → Telegram 等宽纯文本 ─────────────────────────────
_DATE_RE = re.compile(r"美股收盘日报[｜|]\s*(\d{4}-\d{2}-\d{2})")


def _report_title(html: str) -> str:
    """从 HTML 里提取报告日期生成标题（原先写死日期，发出去的标题日期是错的）。"""
    m = _DATE_RE.search(html)
    date = m.group(1) if m else __import__("datetime").date.today().isoformat()
    return f"📈 美股收盘日报｜{date}"


def html_to_tg(html: str) -> str:
    title = _report_title(html)
    # 0) 只取 <body>，避免 <head> 里的 <title> 重复；再从正文里只保留第一个报告标题之后的内容
    m = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL | re.IGNORECASE)
    html = m.group(1) if m else html
    idx = html.find(title)
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
    for variant in (title, f"美股收盘日报｜{title.split('｜')[-1]}"):
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
    header = f"<b>{title}</b>"
    footer = "\n\n⚠️ 本报告基于市场数据自动生成，仅供参考，不构成投资建议。投资有风险，入市需谨慎。"
    full = header + "\n\n" + html.strip() + footer
    full = re.sub(r"\n{3,}", "\n\n", full)
    return full.strip()


# ─── 分段 ─────────────────────────────────────────────────
def split_chunks(text: str, title: str):
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
        prefix = "" if first else f"<b>{title}（续）</b>\n\n"
        chunks.append(prefix + text[pos : pos + split].strip())
        pos += split
        first = False
    return chunks


# ─── 发送 ─────────────────────────────────────────────────
def _extract_message_id(stdout: str) -> str:
    """从 hermes send --json 的输出里取 message_id（兼容多种返回结构）。"""
    text = (stdout or "").strip()
    if not text:
        return "?"
    try:
        data = json.loads(text)
    except Exception:
        m = re.search(r'message_id["\']?\s*[:=]\s*"?(\d+)', text)
        return m.group(1) if m else "?"
    stack = [data]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if isinstance(cur.get("message_id"), (int, str)):
                return str(cur["message_id"])
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return "?"


def _hermes_skipped(stdout: str) -> bool:
    """hermes send 在 cron 里若目标与自动投递目标相同，会返回 skipped=true 而并未发出。"""
    try:
        data = json.loads((stdout or "").strip())
    except Exception:
        return False
    return bool(isinstance(data, dict) and data.get("skipped"))


def _bot_token() -> str:
    """从 ~/.hermes/.env 读取 Telegram bot token。"""
    env = Path(os.path.expanduser("~")) / ".hermes" / ".env"
    try:
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return ""


def _send_via_bot_api(chat_id: str, text: str) -> dict:
    """Telegram Bot API 直发。

    cron 里 hermes send 会因"与自动投递同目标"跳过，若直接当成功会误报投递成功，
    所以被跳过时改用 Bot API 真正把日报送进频道。
    """
    import urllib.request as _urlreq
    token = _bot_token()
    if not token:
        return {"ok": False, "id": "缺少 TELEGRAM_BOT_TOKEN", "raw": ""}
    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                          "disable_web_page_preview": True}).encode()
    req = _urlreq.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=payload,
                          headers={"Content-Type": "application/json"})
    try:
        with _urlreq.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
    except Exception as e:  # 网络/权限错误如实上报
        return {"ok": False, "id": f"Bot API 异常: {e}", "raw": ""}
    if body.get("ok"):
        msg_id = str((body.get("result") or {}).get("message_id", "?"))
        return {"ok": True, "id": msg_id, "raw": json.dumps(body, ensure_ascii=False)[:500]}
    return {"ok": False, "id": f"Bot API 失败: {body.get('description')}",
            "raw": json.dumps(body, ensure_ascii=False)[:500]}


def send_telegram(file_path: Path, chat_id: str) -> dict:
    """发送单个分段，返回 {ok, id, raw, transport}。

    优先 hermes send；若被 cron 去重跳过或失败，退回 Bot API 直发。
    """
    cmd = HERMES_CMD + [f"telegram:{chat_id}", "--file", str(file_path), "--json"]
    raw = ""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        raw = result.stdout.strip()
        if not _hermes_skipped(raw):
            return {"ok": True, "id": _extract_message_id(raw), "raw": raw[:500],
                    "transport": "hermes-send"}
    except subprocess.CalledProcessError as e:
        raw = (e.stderr or "").strip()

    text = Path(file_path).read_text(encoding="utf-8")
    fallback = _send_via_bot_api(chat_id, text)
    fallback["transport"] = "bot-api"
    fallback["raw"] = fallback.get("raw") or raw[:500]
    return fallback


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
    chunks = split_chunks(full_text, _report_title(raw))
    print(f"✅ 分段完成: {len(chunks)} 段")
    for i, c in enumerate(chunks, 1):
        p = base_dir / f"chunk_{i}.txt"
        p.write_text(c, encoding="utf-8")
        print(f"   [{i}] {p.name} ({len(c)} chars)")

    # 4. 发送
    print()
    print("📤 开始发送...")
    chunk_files = sorted(base_dir.glob("chunk_*.txt"))
    send_log = base_dir / "tg_send_log.jsonl"
    for i, chunk_file in enumerate(chunk_files, 1):
        res = send_telegram(chunk_file, chat_id)
        with open(send_log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"chunk": chunk_file.name, "ok": res["ok"], "message_id": res["id"],
                                 "transport": res.get("transport"), "raw": res.get("raw", "")[:500]},
                                ensure_ascii=False) + "\n")
        if res["ok"]:
            print(f"   [{i}] ✅ 已发送 (message_id={res['id']}, via {res.get('transport')}) -> {chunk_file.name}")
        else:
            print(f"   [{i}] ❌ 发送失败: {res['id']}")
            sys.exit(1)

    print()
    print(f"🎉 全部完成！共发送 {len(chunks)} 条消息到 {chat_id}")


if __name__ == "__main__":
    main()
