# coding: utf-8
"""QMT 终端模型拼接部署共用库。

片段命名:
  - \"foo.py\"           -> 策略目录下的 foo.py
  - \"common:bar.py\"    -> scripts/qmt_common/bar.py
  - \"common:single/x.py\" -> scripts/qmt_common/single/x.py

参数面板 XML 用 deploy_formula_layout 拷到 python/formulaLayout/<入口stem>.xml。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMON_DIR = Path(__file__).resolve().parent

PREAMBLE = """\
#coding:gbk
# 由 _deploy_qmt_gbk.py 自动生成；请勿手改。请编辑策略片段与 scripts/qmt_common/ 后重新部署。
import datetime
import json
import os
import traceback

import numpy as np

"""

_DROP_IMPORT = re.compile(
    r"^import\s+(datetime|json|os|traceback|sys)\s*$|"
    r"^from\s+(datetime|json|os|traceback|sys)\s+import\s+.*$|"
    r"^import\s+numpy(\s+as\s+np)?\s*$|"
    r"^from\s+numpy\s+import\s+.*$",
    re.M,
)


def resolve_fragment(name: str, strategy_dir: Path) -> Path:
    if name.startswith("common:"):
        rel = name[len("common:") :]
        path = COMMON_DIR / rel
    else:
        path = strategy_dir / name
    if not path.is_file():
        raise SystemExit("missing fragment: %s -> %s" % (name, path))
    return path


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
    text = re.sub(
        r"^#\s*coding[:=]\s*[\w\-]+\s*\n",
        "",
        text,
        count=1,
        flags=re.M,
    )
    text = "\n".join(
        ln for ln in text.splitlines() if not _DROP_IMPORT.match(ln.strip())
    )
    if not text.endswith("\n"):
        text += "\n"
    return text


def build_bundle(
    module_order: Sequence[str],
    strategy_dir: Path,
    preamble: str | None = None,
) -> str:
    parts = [preamble if preamble is not None else PREAMBLE]
    for name in module_order:
        parts.append("\n")
        parts.append(read_fragment(resolve_fragment(name, strategy_dir)))
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
        raise SystemExit("source has non-GBK characters: %s" % (bad,))
    data = text.encode("gbk")
    data.decode("gbk")
    return data


def write_preview(text: str, preview: Path) -> None:
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_text(text, encoding="utf-8", newline="\n")
    print("wrote preview", preview, "chars", len(text))


def deploy_formula_layout(
    src: Path,
    qmt_python_dir: Path,
    stems: Iterable[str],
) -> None:
    """Copy panel XML to python/formulaLayout/<stem>.xml for each deployed entry."""
    if not src.is_file():
        raise SystemExit("missing panel xml: %s" % src)
    text = src.read_text(encoding="utf-8")
    if "<TCStageLayout>" not in text:
        raise SystemExit("formula layout missing TCStageLayout: %s" % src)
    dest_dir = qmt_python_dir / "formulaLayout"
    dest_dir.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes()
    wrote = 0
    for stem in stems:
        stem = str(stem).strip()
        if not stem:
            continue
        dest = dest_dir / ("%s.xml" % stem)
        dest.write_bytes(data)
        print("wrote formulaLayout", dest, "bytes", len(data))
        wrote += 1
    if wrote == 0:
        raise SystemExit("deploy_formula_layout: empty stems")


def deploy_gbk(
    text: str,
    targets: Iterable[Path],
    compile_name: str = "qmt_bundle.py",
) -> None:
    compile(text, compile_name, "exec")
    data = to_gbk_source(text)
    compile(data, compile_name, "exec")
    for dest in targets:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            got = dest.read_bytes()
            got.decode("gbk")
            compile(got, str(dest), "exec")
            print("wrote", dest, "bytes", len(data))
        except OSError as e:
            print("SKIP", dest, e)
