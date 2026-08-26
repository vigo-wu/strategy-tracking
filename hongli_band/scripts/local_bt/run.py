# coding: utf-8
"""无头回放 HlBand：本地日线 CSV + 真实拼接脚本。"""
from __future__ import annotations

import argparse
import importlib.util
import runpy
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
THEME = REPO / "hongli_band"
QMT_DIR = THEME / "scripts" / "qmt"
HLBAND = QMT_DIR / "hlband"
DEPLOY_PY = QMT_DIR / "_deploy_qmt_gbk.py"
REPORT_PY = (
    REPO / ".cursor" / "skills" / "qmt-backtest-report" / "scripts" / "generate_report.py"
)

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from market_csv import (  # noqa: E402
    MarketStore,
    find_weekly_csv,
    load_daily_csv,
    load_weekly_csv,
    walk_days,
)
from mock_qmt import MockContext, _as_tag, inject_qmt_globals  # noqa: E402
from trades_csv import TradeLedger, trades_csv_path, wrap_fill_hooks  # noqa: E402

from qmt_common._deploy_lib import build_bundle  # noqa: E402


class _Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
            try:
                s.flush()
            except Exception:
                pass
        return len(data) if data is not None else 0

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass


def _load_module_order():
    spec = importlib.util.spec_from_file_location("hlband_deploy", DEPLOY_PY)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load %s" % DEPLOY_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.MODULE_ORDER)


def _stock_tag(stock: str) -> str:
    return str(stock).replace(".", "_")


def _exec_bundle() -> dict:
    order = _load_module_order()
    text = build_bundle(order, HLBAND)
    compile(text, "qmt_terminal_hlband.py", "exec")
    ns: dict = {"__name__": "hlband_local"}
    exec(text, ns, ns)
    inject_qmt_globals(ns)
    return ns


def run_backtest(
    csv_path: str | Path,
    start: str = "",
    end: str = "",
    stock: str = "",
    out_dir: str | Path | None = None,
    log_name: str = "",
    weekly_csv: str | Path | None = None,
) -> Path:
    code, bars = load_daily_csv(csv_path, stock=stock)
    walk = walk_days(bars, start=start, end=end)
    if not walk:
        raise SystemExit("no bars in walk range start=%s end=%s" % (start, end))

    weekly_path = Path(weekly_csv) if weekly_csv else find_weekly_csv(csv_path, code)
    weekly_bars = None
    weekly_src = "aggregate drop_forming"
    if weekly_path and Path(weekly_path).is_file():
        _, weekly_bars = load_weekly_csv(weekly_path, stock=code)
        weekly_src = "native %s n=%s" % (weekly_path, len(weekly_bars))

    store = MarketStore(bars, code, weekly=weekly_bars)
    tags = [_as_tag(b.dt) for b in walk]
    ctx = MockContext(store, tags, code)
    ctx.start = start or walk[0].day
    ctx.end = end or walk[-1].day
    ctx.barpos = 0

    dest = Path(out_dir) if out_dir else THEME / "report"
    dest.mkdir(parents=True, exist_ok=True)
    fname = log_name.strip() if log_name else ("local_bt_%s.txt" % _stock_tag(code))
    log_path = dest / fname

    ns = _exec_bundle()
    ledger = TradeLedger(code)
    wrap_fill_hooks(ns, ledger)
    log_f = open(log_path, "w", encoding="utf-8", newline="\n")
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = _Tee(old_out, log_f)
    sys.stderr = _Tee(old_err, log_f)
    try:
        n_w0 = len(store.frame("1w", walk[0].day, count=120, fields=["close"]))
        print(
            "local_bt",
            code,
            "csv=",
            csv_path,
            "walk=",
            walk[0].day,
            walk[-1].day,
            "n=",
            len(walk),
            "hist_n=",
            len(bars),
            "weekly=",
            weekly_src,
            "n_w_start=",
            n_w0,
        )
        if n_w0 < 60:
            print(
                "WARN weekly bars at start < 60 (need ~60 for w1, QMT uses 120); "
                "extend daily CSV or dump native 1w with HIST_START well before walk start"
            )
        ns["init"](ctx)
        for i, bar in enumerate(walk):
            ctx.barpos = i
            ns["handlebar"](ctx)
    finally:
        sys.stdout = old_out
        sys.stderr = old_err
        log_f.close()
    trades_path = trades_csv_path(log_path)
    ledger.write(trades_path)
    print("wrote log", log_path, "bars", len(walk))
    print("wrote trades", trades_path, "n=", len(ledger.rows))
    return log_path


def _run_report(log_path: Path, out_dir: Path) -> None:
    if not REPORT_PY.is_file():
        raise SystemExit("missing report script: %s" % REPORT_PY)
    report_dir = out_dir / "local_bt_report"
    terminal = trades_csv_path(log_path)
    argv = [
        str(REPORT_PY),
        "--theme",
        str(THEME),
        "--log",
        str(log_path),
        "--out-dir",
        str(report_dir),
        "--no-kline",
        "--title",
        "HlBand 本地回测",
    ]
    if terminal.is_file():
        argv.extend(["--terminal-csv", str(terminal)])
    else:
        argv.append("--no-terminal")
    sys.argv = argv
    runpy.run_path(str(REPORT_PY), run_name="__main__")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="HlBand local backtest from KlineDump daily CSV")
    ap.add_argument("--csv", required=True, help="KlineDump 日线 CSV")
    ap.add_argument("--start", default="", help="回测起点 yyyymmdd（CSV 须含更早暖机）")
    ap.add_argument("--end", default="", help="回测终点 yyyymmdd")
    ap.add_argument("--stock", default="", help="覆盖 CSV 中的代码，如 600350.SH")
    ap.add_argument(
        "--out",
        default=str(THEME / "report"),
        help="日志输出目录（默认 hongli_band/report）",
    )
    ap.add_argument("--log-name", default="", help="日志文件名，默认 local_bt_{stock}.txt")
    ap.add_argument(
        "--weekly-csv",
        default="",
        help="QMT 原生 1w CSV；缺省则同目录 {code}_1w_*.csv，再缺省则日线合成并丢掉未收盘周",
    )
    ap.add_argument("--report", action="store_true", help="事后用 gen_report；成交真源为本回测操作明细")
    args = ap.parse_args(argv)

    log_path = run_backtest(
        args.csv,
        start=args.start,
        end=args.end,
        stock=args.stock,
        out_dir=args.out,
        log_name=args.log_name,
        weekly_csv=args.weekly_csv or None,
    )
    if args.report:
        _run_report(log_path, Path(args.out))


if __name__ == "__main__":
    main()
