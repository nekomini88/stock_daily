"""确定性捕获 generate_report 输出用于重构前后字节级对比。

用法: python3 refactor_verify/capture.py <data_file_stem> <out_html_path>
固定 datetime.now() 使 generated_at 确定, 输出 HTML 字节 + sha256 + stdout。
"""
import sys
import io
import hashlib
from pathlib import Path
from types import SimpleNamespace
import datetime as _real_dt

sys.path.insert(0, "/root/stock_daily")
import generate_stock_daily as gsd


class FixedDateTime(_real_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return _real_dt.datetime(2026, 8, 11, 9, 30, 0, tzinfo=tz)


def main():
    data_stem = sys.argv[1]          # e.g. market_data_2026-08-11
    out_html = sys.argv[2]           # 捕获的 HTML 字节保存路径
    today = data_stem.replace("market_data_", "")
    data_file = Path("/root/stock_daily/daily_news") / f"{data_stem}.json"
    assert data_file.exists(), data_file

    gsd.datetime.datetime = FixedDateTime  # 仅替换 datetime 类, date/timezone/timedelta 不受影响

    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        args = SimpleNamespace(data_file=str(data_file), today=None)
        result = gsd.generate_report(args)
    finally:
        sys.stdout = old

    out_file = Path("/root/stock_daily/files") / today / f"美股收盘日报_{today}.html"
    html = out_file.read_bytes()
    Path(out_html).write_bytes(html)
    print(f"RESULT={result}")
    print(f"SHA256={hashlib.sha256(html).hexdigest()}")
    print(f"BYTES={len(html)}")
    print(f"STDOUT={buf.getvalue()!r}")


if __name__ == "__main__":
    main()
