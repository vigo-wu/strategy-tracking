"""Sweep per-trade budget under TOTAL=200k for Top20 list."""
import importlib

import run_backtest as rb

importlib.reload(rb)

BUDGETS = [20_000, 25_000, 30_000, 33_333, 40_000, 45_000, 50_000, 66_666]


def main() -> None:
    universe = rb.load_list_md(rb.LIST_MD)
    rb.ensure_cache(universe, rb.HIST_START, rb.BT_END)
    market_ok = rb.load_market_ok_dates()
    candidates: list[rb.Candidate] = []
    for _, row in universe.iterrows():
        candidates.extend(rb.collect_candidates(row["code6"], row["name"], row["sector"]))

    print(f"signals={len(candidates)} capital=200000")
    print(
        f"{'budget':>8} {'slots':>5} {'filled':>6} {'full':>4} {'cash':>4} "
        f"{'peak':>4} {'pnl':>10} {'ret%':>7}"
    )
    rows = []
    for budget in BUDGETS:
        rb.TOTAL_CAPITAL = 200_000.0
        rb.PER_TRADE_BUDGET = float(budget)
        rb.MAX_SLOTS = max(1, int(rb.TOTAL_CAPITAL // rb.PER_TRADE_BUDGET))
        trades, meta = rb.allocate_portfolio(candidates, market_ok)
        full = sum(1 for t in trades if t.skipped and t.skip_reason == "满仓位")
        cash = sum(1 for t in trades if t.skipped and t.skip_reason == "现金不足")
        row = {
            "budget": budget,
            "slots": rb.MAX_SLOTS,
            "filled": meta["filled_count"],
            "full": full,
            "cash": cash,
            "peak": meta["peak_concurrent"],
            "pnl": meta["total_pnl"],
            "ret": meta["total_return_pct"],
        }
        rows.append(row)
        print(
            f"{row['budget']:8.0f} {row['slots']:5d} {row['filled']:6d} "
            f"{row['full']:4d} {row['cash']:4d} {row['peak']:4d} "
            f"{row['pnl']:10.2f} {row['ret']:7.2f}"
        )

    # Prefer higher ret%; tie-break fewer full-slot skips, then rounder budget
    best = sorted(rows, key=lambda r: (-r["ret"], r["full"], -r["budget"]))[0]
    print(
        f"BEST: budget={best['budget']:.0f} slots={best['slots']} "
        f"ret={best['ret']:.2f}% pnl={best['pnl']:.2f} "
        f"(full_skip={best['full']}, cash_skip={best['cash']})"
    )


if __name__ == "__main__":
    main()
