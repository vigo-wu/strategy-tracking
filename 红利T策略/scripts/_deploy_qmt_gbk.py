# coding: utf-8
"""Deploy qmt_terminal_hongli_t.py into Guojin QMT as GBK."""
from __future__ import annotations

import re
from pathlib import Path

REPO = (
    Path(r"D:\persion\strategy-tracking")
    / "红利T策略"
    / "scripts"
    / "qmt_terminal_hongli_t.py"
)
QMT_DIR = Path(r"D:\office\国金证券QMT交易端") / "python"
TARGETS = [
    QMT_DIR / "红利T_v25.py",
    QMT_DIR / "新建策略文件1.py",
    QMT_DIR / "HLT策略.py",
]


def to_gbk_source(text: str) -> bytes:
    # ensure coding cookie
    text = re.sub(
        r"^#\s*coding[:=]\s*[\w\-]+",
        "#coding:gbk",
        text,
        count=1,
        flags=re.M,
    )
    # drop chars not in gbk
    return text.encode("gbk", errors="replace")


def main() -> None:
    text = REPO.read_text(encoding="utf-8")
    data = to_gbk_source(text)
    compile(data, "qmt_terminal_hongli_t.py", "exec")
    for dest in TARGETS:
        dest.write_bytes(data)
        print("wrote", dest, "bytes", len(data))
    print("OK: open Guojin QMT -> model trade -> load 红利T_v25 / 新建策略文件1")
    print("Main chart: 561580.SH | PERIOD=follow (or 1m/5m/1h/1d/...) | DRY_RUN default in source")


if __name__ == "__main__":
    main()
