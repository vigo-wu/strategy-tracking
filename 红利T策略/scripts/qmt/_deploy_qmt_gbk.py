# coding: utf-8
"""将 hongli/*.py 片段拼成国金 QMT 模型交易用的单个 GBK 文件。

编辑 scripts/qmt/hongli/ 下片段后运行本脚本。
写入国金 python 目标文件，并重生 qmt_terminal_hongli_t.py（UTF-8 预览）。
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
HONGLI = HERE / "hongli"
PREVIEW = HERE / "qmt_terminal_hongli_t.py"

QMT_DIR = Path(r"D:\service\GJQMT") / "python"
CFG = Path(r"D:\service\GJQMT") / "config" / "indexUserConfig.xml"
TARGETS = [
    QMT_DIR / "HLCL.py",
    QMT_DIR / "红利T_v25.py",
    QMT_DIR / "HLT策略.py",
]

# 依赖顺序：后片段可调用前面已定义的符号。
MODULE_ORDER = [
    "_header.py",
    "config.py",
    "ctx.py",
    "period.py",
    "state_io.py",
    "backtest.py",
    "state.py",
    "indicators.py",
    "market_util.py",
    "market.py",
    "mode.py",
    "broker.py",
    "orders.py",
    "runtime.py",
    "strategy.py",
    "_main_guard.py",
]

_SIMPLE = re.compile(
    r'name="HLCL" type="2" simpleRun="([01])"',
    re.M,
)

PREAMBLE = """\
#coding:gbk
# 由 scripts/qmt/_deploy_qmt_gbk.py 从 hongli/*.py 自动生成
# 请勿手改本文件。请编辑 hongli 片段后重新部署。
import datetime
import json
import os
import traceback

import numpy as np

"""


def read_fragment(path: Path) -> str:
    raw = path.read_bytes()
    text = None
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise SystemExit("cannot decode fragment: %s" % path)
    # 去掉片段内可能残留的 coding 声明
    text = re.sub(
        r"^#\s*coding[:=]\s*[\w\-]+\s*\n",
        "",
        text,
        count=1,
        flags=re.M,
    )
    # 去掉 PREAMBLE 已有的标准库 import（片段不应再 import）
    drop_import = re.compile(
        r"^import\s+(datetime|json|os|traceback|sys)\s*$|"
        r"^from\s+(datetime|json|os|traceback|sys)\s+import\s+.*$|"
        r"^import\s+numpy(\s+as\s+np)?\s*$|"
        r"^from\s+numpy\s+import\s+.*$",
        re.M,
    )
    text = "\n".join(
        ln for ln in text.splitlines() if not drop_import.match(ln.strip())
    )
    if not text.endswith("\n"):
        text += "\n"
    return text


def build_bundle() -> str:
    missing = [n for n in MODULE_ORDER if not (HONGLI / n).is_file()]
    if missing:
        raise SystemExit("missing hongli modules: %s" % missing)
    parts = [PREAMBLE]
    for name in MODULE_ORDER:
        parts.append("\n")
        parts.append(read_fragment(HONGLI / name))
    return "".join(parts)


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
        raise SystemExit(
            "source has non-GBK characters; fix hongli fragments: %s" % (bad,)
        )
    data = text.encode("gbk")
    data.decode("gbk")
    return data


def _warn_simplerun() -> None:
    if not CFG.is_file():
        return
    raw = CFG.read_text(encoding="utf-8", errors="surrogateescape")
    m = _SIMPLE.search(raw)
    if not m:
        print("WARN: HLCL catalog not found in", CFG)
        return
    if m.group(1) == "0":
        print("OK: HLCL simpleRun=0 (model trade uses PythonFormula)")
        return
    print(
        "WARN: HLCL simpleRun=1 -> table Start uses doRun and exits instantly.\n"
        "  1) Fully EXIT QMT\n"
        "  2) python 红利T策略/scripts/qmt/_fix_hlcl_simplerun.py\n"
        "  3) Restart QMT; do NOT enable independent/simple run on HLCL"
    )


def main() -> None:
    text = build_bundle()
    compile(text, "qmt_terminal_hongli_t.py", "exec")
    # 仓库内 UTF-8 预览（内容与部署相同，coding 仍为 gbk）
    PREVIEW.write_text(text, encoding="utf-8", newline="\n")
    print("wrote preview", PREVIEW, "chars", len(text))

    data = to_gbk_source(text)
    compile(data, "qmt_terminal_hongli_t.py", "exec")
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
    _warn_simplerun()
    print("OK: 打开国金 QMT -> 模型交易 -> 加载 HLCL / 红利T_v25 / HLT策略")
    print("主图: 561580.SH | PERIOD=follow | 部署后请重新编译")
    print("只编辑 hongli/*.py；改完务必重新运行本部署脚本")


if __name__ == "__main__":
    main()
