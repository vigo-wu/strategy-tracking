# coding: utf-8
"""python -m onr_strategy.backtest --demo"""
from __future__ import annotations

import argparse
from pathlib import Path

from onr_strategy.backtest.config import EXIT_MODES, OnrConfig, parse_disable
from onr_strategy.backtest.data import CsvStore
from onr_strategy.backtest.engine import format_summary, run_backtest, split_tables, summarize
from onr_strategy.backtest.synthetic import build_demo_store


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="ONR v0.1 无前视回测脚手架（非 QMT）")
    p.add_argument("--demo", action="store_true", help="跑内置合成样本")
    p.add_argument("--csv-dir", type=str, default="", help="长表 CSV 目录")
    p.add_argument("--exit", dest="exit_mode", default="rules", choices=EXIT_MODES)
    p.add_argument("--disable", default="", help="关闭因子，逗号分隔：momentum,industry,large_order,...")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--start", default="", help="YYYY-MM-DD，截断交易日")
    p.add_argument("--end", default="", help="YYYY-MM-DD")
    p.add_argument("--out", type=str, default="")
    p.add_argument("--no-baseline", action="store_true")
    args = p.parse_args(argv)

    cfg = OnrConfig(exit_mode=args.exit_mode, baseline_seed=args.seed)
    disabled = parse_disable(args.disable)
    if disabled:
        cfg = cfg.disable(*disabled)

    if args.demo:
        store = build_demo_store()
    elif args.csv_dir:
        store = CsvStore(args.csv_dir)
    else:
        p.error("指定 --demo 或 --csv-dir")
        return 2

    if args.start or args.end:
        import pandas as pd

        s = pd.Timestamp(args.start).date() if args.start else None
        e = pd.Timestamp(args.end).date() if args.end else None
        store.days = [
            d
            for d in store.trading_days()
            if (s is None or d >= s) and (e is None or d <= e)
        ]

    results = run_backtest(store, cfg, with_baseline=not args.no_baseline)
    for name, res in results.items():
        print(format_summary(name, summarize(res)))
        if res.warnings:
            print("  warnings:", ", ".join(res.warnings))
        splits = split_tables(res)
        if not splits["weekday"].empty:
            print("  weekday mean net:")
            print(splits["weekday"].to_string(index=False))

    out = Path(args.out) if args.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
        for name, res in results.items():
            tf = res.trades_frame()
            df = res.days_frame()
            if not tf.empty:
                tf.to_csv(out / ("%s_trades.csv" % name), index=False)
            if not df.empty:
                df.to_csv(out / ("%s_days.csv" % name), index=False)
        print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
