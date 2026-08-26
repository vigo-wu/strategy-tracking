# coding: utf-8
"""启动 HlBand 本地回测可视化界面。

  python hongli_band/local_bt_ui.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent / "scripts" / "local_bt" / "app.py"


def main() -> None:
    if not APP.is_file():
        raise SystemExit("missing app: %s" % APP)
    raise SystemExit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(APP), *sys.argv[1:]]))


if __name__ == "__main__":
    main()
