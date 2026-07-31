# coding: utf-8
"""将 qmt_terminal_hwr_t1.py 部署为国金 QMT 模型交易用的 GBK 文件。

编辑 scripts/qmt/qmt_terminal_hwr_t1.py 后运行本脚本。
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "qmt_terminal_hwr_t1.py"

QMT_DIR = Path(r"D:\service\GJQMT") / "python"
TARGETS = [
    QMT_DIR / "HwrT1.py",
    QMT_DIR / "高胜率T1.py",
]


def read_source() -> str:
    raw = SRC.read_bytes()
    text = None
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise SystemExit("cannot decode: %s" % SRC)
    return text


def to_gbk_source(text: str) -> bytes:
    text = re.sub(
        r"^#\s*coding[:=]\s*[\w\-]+",
        "#coding:gbk",
        text,
        count=1,
        flags=re.M,
    )
    bad = []
    for i, ch in enumerate(text):
        try:
            ch.encode("gbk")
        except UnicodeEncodeError:
            bad.append((i, repr(ch), hex(ord(ch))))
            if len(bad) >= 20:
                break
    if bad:
        raise SystemExit("source has non-GBK characters: %s" % (bad,))
    data = text.encode("gbk")
    data.decode("gbk")
    return data


def main() -> None:
    if not SRC.is_file():
        raise SystemExit("missing %s" % SRC)
    text = read_source()
    compile(text, str(SRC), "exec")
    data = to_gbk_source(text)
    compile(data, "HwrT1.py", "exec")
    for dest in TARGETS:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            got = dest.read_bytes()
            got.decode("gbk")
            compile(got, str(dest), "exec")
            print("wrote", dest, "bytes", len(data))
        except OSError as e:
            print("SKIP", dest, e)
    print("OK: 打开国金 QMT -> 模型交易 -> 加载 HwrT1 / 高胜率T1")
    print("主图: 目标股票 | 周期=1分钟 | 部署后请重新编译")
    print("默认 DRY_RUN=True；确认日志后再改 False 并重新部署")


if __name__ == "__main__":
    main()
