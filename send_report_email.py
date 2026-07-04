#!/usr/bin/env python3
"""
发送美股日报邮件 - 从纯文本/HTML 文件读取内容
配置信息从同目录 config.ini 的 [email] 段读取
"""
import sys
import configparser
import smtplib
import email.utils
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path


def load_email_config():
    cfg_path = Path(__file__).resolve().parent / "config.ini"
    config = configparser.ConfigParser()
    config.read(cfg_path, encoding="utf-8")

    section = "email"
    return {
        "smtp_server": config.get(section, "smtp_server"),
        "smtp_port": config.getint(section, "smtp_port"),
        "sender_email": config.get(section, "sender_email"),
        "sender_pass": config.get(section, "sender_pass"),
        "recipient": config.get(section, "recipient"),
        "sender_name": config.get(section, "sender_name", fallback=""),
    }


def send_email(content, subject=None, is_html=False, config=None):
    if config is None:
        config = load_email_config()

    if not subject:
        first_line = content.split("\n")[0].strip()
        subject = first_line if first_line else "📊 美股收盘日报"

    msg = MIMEMultipart("alternative")
    sender = config["sender_email"]
    if config.get("sender_name"):
        msg["From"] = email.utils.formataddr((config["sender_name"], sender))
    else:
        msg["From"] = sender
    msg["To"] = config["recipient"]
    msg["Subject"] = subject

    msg.attach(MIMEText(content, "html" if is_html else "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL(config["smtp_server"], config["smtp_port"]) as server:
            server.login(sender, config["sender_pass"])
            server.sendmail(sender, config["recipient"], msg.as_string())
        print("✅ 邮件发送成功！")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 send_report_email.py <file> [subject] [--html]")
        print("  file      - 要发送的文件路径（支持 .txt 和 .html）")
        print("  subject   - 邮件主题（可选）")
        print("  --html    - 强制以HTML格式发送（可选）")
        sys.exit(1)

    file_path = sys.argv[1]
    subject = None
    is_html = False

    for i in range(2, len(sys.argv)):
        arg = sys.argv[i]
        if arg == "--html":
            is_html = True
        elif not arg.startswith("--"):
            subject = arg

    if not is_html and file_path.endswith((".html", ".htm")):
        is_html = True

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    send_email(content, subject, is_html)
