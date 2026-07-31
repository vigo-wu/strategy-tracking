# coding: utf-8
"""One-shot splitter: monolith -> hongli/*.py fragments. Re-run only if re-splitting."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "qmt_terminal_hongli_t.py"
OUT = ROOT / "hongli"

# inclusive 1-based line ranges from current monolith (utf-8)
# Each fragment assumes prior symbols exist after bundle (no cross-imports).
SPECS = [
    ("_header.py", 2, 50),  # docstring body without triple-quotes wrapper handled below
    ("config.py", 58, 181),
    ("ctx.py", 184, 194),
    ("period.py", 197, 264),
    ("state_io.py", 266, 320),
    ("backtest.py", 322, 392),
    ("state.py", 395, 578),
    ("indicators.py", 580, 616),
    ("market_util.py", 619, 727),
    ("market.py", 730, 972),
    ("mode.py", 974, 1056),
    ("broker.py", 1059, 1220),
    ("orders.py", 1223, 1620),
    ("runtime.py", 1623, 1819),
    ("strategy.py", 1822, 2057),
    ("_main_guard.py", 2060, 2072),
]

DOC_BANNER = '''# === hongli/{name} ===
# Fragment for Guojin QMT bundle. Do not import across modules at runtime;
# _deploy_qmt_gbk.py concatenates in MODULE_ORDER into one GBK file.
'''


def slice_lines(lines: list[str], start: int, end: int) -> str:
    return "".join(lines[start - 1 : end])


def main() -> None:
    raw = SRC.read_bytes()
    text = None
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise SystemExit("cannot decode %s" % SRC)
    lines = text.splitlines(True)
    OUT.mkdir(parents=True, exist_ok=True)

    for name, start, end in SPECS:
        body = slice_lines(lines, start, end)
        if name == "_header.py":
            # wrap as module docstring
            # body already starts with HongliT... inside original """
            # Original lines 2-50 are inside the opening """ on line 2
            # Line 2 is `"""\n` and line 50 is `"""\n` — SPECS used 2-50 which includes both
            content = DOC_BANNER.format(name=name) + body
            # If body still has triple quotes, keep as-is for docstring after bundle header
            if not body.lstrip().startswith('"""'):
                content = DOC_BANNER.format(name=name) + '"""\n' + body.rstrip() + '\n"""\n'
            else:
                content = DOC_BANNER.format(name=name) + body
        else:
            content = DOC_BANNER.format(name=name) + body
            if not content.endswith("\n"):
                content += "\n"
        dest = OUT / name
        dest.write_text(content, encoding="utf-8", newline="\n")
        print("wrote", dest, "lines", start, "-", end)

    print("OK:", OUT)


if __name__ == "__main__":
    main()
