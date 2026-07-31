# coding: utf-8
"""Deploy qmt_terminal_hongli_t.py into Guojin QMT as GBK."""
from __future__ import annotations

import re
from pathlib import Path

REPO = (
    Path(r"D:\vigo\strategy-tracking")
    / "红利T策略"
    / "scripts"
    / "qmt_terminal_hongli_t.py"
)
QMT_DIR = Path(r"D:\service\GJQMT") / "python"
CFG = Path(r"D:\service\GJQMT") / "config" / "indexUserConfig.xml"
# Cover every entry the user may load in model trade
TARGETS = [
    QMT_DIR / "HLCL.py",
    QMT_DIR / "红利T_v25.py",
    QMT_DIR / "HLT策略.py",
]
_SIMPLE = re.compile(
    r'name="HLCL" type="2" simpleRun="([01])"',
    re.M,
)


def to_gbk_source(text: str) -> bytes:
    # ensure coding cookie
    text = re.sub(
        r"^#\s*coding[:=]\s*[\w\-]+",
        "#coding:gbk",
        text,
        count=1,
        flags=re.M,
    )
    # drop UTF-8 replacement chars / non-GBK (strict fail is clearer than silent ?)
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
            "source has non-GBK characters; fix repo before deploy: %s" % (bad,)
        )
    data = text.encode("gbk")
    # Guojin reads by coding cookie; must be valid GBK bytes
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
        "  2) python 红利T策略/scripts/_fix_hlcl_simplerun.py\n"
        "  3) Restart QMT; do NOT enable independent/simple run on HLCL"
    )


def main() -> None:
    # Repo may be UTF-8 (editor) or already GBK; prefer UTF-8 then GBK
    raw = REPO.read_bytes()
    text = None
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise SystemExit("cannot decode repo source as utf-8/gbk: %s" % REPO)

    data = to_gbk_source(text)
    compile(data, "qmt_terminal_hongli_t.py", "exec")
    for dest in TARGETS:
        dest.write_bytes(data)
        # verify round-trip
        got = dest.read_bytes()
        got.decode("gbk")
        compile(got, str(dest), "exec")
        print("wrote", dest, "bytes", len(data))
    _warn_simplerun()
    print("OK: open Guojin QMT -> model trade -> load HLCL / 红利T_v25 / HLT策略")
    print("Main chart: 561580.SH | PERIOD=follow | recompile after deploy")
    print("Do NOT save HLCL.py from UTF-8 editor; always re-run this deploy script")


if __name__ == "__main__":
    main()
