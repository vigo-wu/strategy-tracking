# coding: utf-8
"""Force HLCL catalog simpleRun=0 so model-trade Start uses PythonFormula.

Run ONLY after fully exiting Guojin QMT (XtItClient / XtMiniQmt),
otherwise the UI will rewrite simpleRun=1 on save.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

CFG = Path(r"D:\service\GJQMT\config\indexUserConfig.xml")
PAT = re.compile(
    r'(name="HLCL" type="2" simpleRun=")([01])("/>)',
    re.M,
)


def main() -> int:
    if not CFG.is_file():
        print("missing", CFG)
        return 1
    raw = CFG.read_text(encoding="utf-8", errors="surrogateescape")
    m = PAT.search(raw)
    if not m:
        print("HLCL catalog entry not found")
        return 1
    cur = m.group(2)
    print("before simpleRun=", cur)
    if cur == "0":
        print("already 0; nothing to do")
        return 0
    bak = CFG.with_suffix(CFG.suffix + ".bak_simplerun")
    bak.write_bytes(CFG.read_bytes())
    new = PAT.sub(r"\g<1>0\g<3>", raw, count=1)
    CFG.write_text(new, encoding="utf-8", errors="surrogateescape")
    got = PAT.search(CFG.read_text(encoding="utf-8", errors="surrogateescape"))
    print("after simpleRun=", got.group(2) if got else "?")
    print("backup", bak)
    print("OK: start QMT -> open HLCL in formula editor -> compile/save -> model trade Start")
    print("Accept: log shows PythonFormula construct + HongliT init (NOT refuse standalone)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
