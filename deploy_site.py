#!/usr/bin/env python3
"""把美股日报发布到绿云（/data/sites/stock）。

与动漫日报同一套：管线只产出 index/，发布由这里做，避免「生成了但没上线」。
不要用 rsync --delete：远端还有 author-badge 这类不归管线管的静态文件。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SITE = BASE / "index"
HOST = "root@109.107.140.95"
DEST = "/data/sites/stock/"


def run(cmd: list[str]) -> int:
    print("+", " ".join(cmd))
    return subprocess.run(cmd).returncode


def main() -> int:
    if not (SITE / "index.html").exists():
        print(f"❌ 缺少 {SITE/'index.html'}，先跑 generate_stock_daily.py")
        return 1
    if run(["rsync", "-az", "--stats", f"{SITE}/", f"{HOST}:{DEST}"]) != 0:
        print("❌ rsync 失败")
        return 1
    run(["ssh", HOST,
         "cd /data/sites/stock && ls -d 20*-*-* 2>/dev/null | sort -r | tail -n +181 | xargs -r rm -rf; "
         "echo 远端期数: $(ls -d /data/sites/stock/20*-*-* 2>/dev/null | wc -l)"])
    print("✅ 已发布到", DEST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
