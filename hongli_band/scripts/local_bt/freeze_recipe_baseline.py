# coding: utf-8
"""冻结第 2 步前的 local_bt 基线：成交 / reason / 期末仓 + 现网评槽抽样。"""
from __future__ import annotations

import csv
import json
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from market_csv import DailyBar, MarketStore
from run import run_backtest
from trades_csv import trades_csv_path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "recipe_baseline.json"
STOCK = "600350.SH"


def _bars(n: int = 220, start: str = "20180102") -> list[DailyBar]:
    d = datetime.strptime(start, "%Y%m%d")
    bars: list[DailyBar] = []
    while len(bars) < n:
        if d.weekday() < 5:
            i = len(bars)
            cycle = i % 40
            px = 10.0 + 0.04 * i - 0.35 * max(0, cycle - 28)
            if cycle >= 32:
                vol = 4.0e5
            else:
                vol = 1.2e6 + 2.0e5 * (cycle % 5)
            hi = px + 0.08
            lo = px - 0.08
            bars.append(
                DailyBar(
                    day=d.strftime("%Y%m%d"),
                    dt=d.replace(hour=0, minute=0, second=0, microsecond=0),
                    open=px,
                    high=hi,
                    low=lo,
                    close=px,
                    volume=vol,
                    stock=STOCK,
                )
            )
        d += timedelta(days=1)
    return bars


def _write_csv(path: Path, bars: list[DailyBar]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stock", "datetime", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow(
                [
                    b.stock,
                    b.dt.strftime("%Y-%m-%d"),
                    b.open,
                    b.high,
                    b.low,
                    b.close,
                    b.volume,
                ]
            )


def _parse_reasons(log_text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    pat = re.compile(
        r"pending_(entry|exit) set(?: add)? signal=(\S+) .*all=(\S+) day=(\S+)"
    )
    for line in log_text.splitlines():
        m = pat.search(line)
        if m:
            out.append(
                {
                    "kind": m.group(1),
                    "signal": m.group(2),
                    "all": m.group(3),
                    "day": m.group(4),
                }
            )
    return out


def _eval_cases(ns: dict) -> list[dict]:
    cases: list[dict] = []
    closes = [10.0 + 0.02 * i for i in range(80)]
    vols = [1.0e6] * 80
    highs = [c + 0.1 for c in closes]
    lows = [c - 0.1 for c in closes]
    closes_w = [10.0 + 0.05 * i for i in range(50)]
    bull, bear, detail = ns["_eval_weekly"](closes_w)
    buy_ok, buy_rs, _ = ns["_eval_daily_buy"](closes, vols)
    cases.append(
        {
            "id": "trend_up",
            "weekly_bull": bool(bull),
            "weekly_bear": bool(bear),
            "buy_ok": bool(buy_ok),
            "buy_reasons": list(buy_rs),
            "w_bias": bool(ns["_weekly_bias_guard"](detail)[0]),
            "w_slope": bool(ns["_weekly_low_slope_guard"](detail)[0]),
        }
    )

    chase_c = list(closes)
    chase_c[-1] = chase_c[-2] * 1.08
    buy_ok, buy_rs, _ = ns["_eval_daily_buy"](chase_c, vols)
    cases.append({"id": "chase", "buy_ok": bool(buy_ok), "buy_reasons": list(buy_rs)})

    dry_c = list(closes)
    dry_v = list(vols)
    dry_c[-1] = 8.0
    dry_v[-1] = 1.0e4
    buy_ok, buy_rs, _ = ns["_eval_daily_buy"](dry_c, dry_v)
    cases.append({"id": "vol_dry", "buy_ok": bool(buy_ok), "buy_reasons": list(buy_rs)})

    lot = {
        "id": 1,
        "shares": 1000,
        "price": 10.0,
        "hold_peak": 10.2,
        "hold_max_ret": 0.02,
        "hold_bars": 5,
        "time_force_trend_skip": False,
    }
    ok, rs = ns["_eval_lot_sell"](9.0, closes, lot)
    cases.append({"id": "stop_loss", "sell_ok": bool(ok), "sell_reasons": list(rs)})

    lot_t = dict(lot)
    lot_t["hold_peak"] = 11.2
    lot_t["price"] = 10.0
    ok, rs = ns["_eval_lot_sell"](10.6, closes, lot_t)
    cases.append({"id": "trailish", "sell_ok": bool(ok), "sell_reasons": list(rs)})

    pb_c = [10.0 + 0.01 * i for i in range(80)]
    ma20 = ns["_price_ma"](pb_c, 20)
    m20 = ns["_last_valid"](ma20, -1)
    pb_c[-1] = float(m20)
    pb_c[-2] = float(m20) * 1.001
    pb_v = [1.0e6] * 80
    pb_v[-1] = 2.0e5
    pb_v[-2] = 2.0e5
    buy_ok, buy_rs, _ = ns["_eval_daily_buy"](pb_c, pb_v)
    cases.append({"id": "pullback", "buy_ok": bool(buy_ok), "buy_reasons": list(buy_rs)})

    bear_w = [12.0] * 40 + [8.0] * 10
    bull, bear, detail = ns["_eval_weekly"](bear_w)
    cases.append(
        {
            "id": "weekly_bear_day",
            "weekly_bull": bool(bull),
            "weekly_bear": bool(bear),
            "w_bias": bool(ns["_weekly_bias_guard"](detail)[0]),
            "w_slope": bool(ns["_weekly_low_slope_guard"](detail)[0]),
        }
    )

    plat_c = [10.0] * 30 + [10.3]
    plat_h = [10.05] * 30 + [10.35]
    plat_l = [9.95] * 30 + [10.2]
    plat = bool(ns["_daily_plat_break"](plat_c, plat_h, plat_l))
    push_ok, push_rs = ns["_eval_scale_push"](plat_c, plat_h, plat_l, detail, pullback=False)
    cases.append(
        {
            "id": "plat_break",
            "plat": plat,
            "scale_ok": bool(push_ok),
            "scale_reasons": list(push_rs),
        }
    )
    return cases


def snapshot() -> dict:
    from run import _exec_bundle

    ns = _exec_bundle()
    cases = _eval_cases(ns)
    bars = _bars()
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        csv_path = td_p / "600350_SH_1d_20180102_20181130.csv"
        _write_csv(csv_path, bars)
        store = MarketStore(bars, STOCK)
        log_path = run_backtest(
            csv_path,
            start="20180601",
            end="20181130",
            stock=STOCK,
            out_dir=td_p / "out",
            log_name="baseline.txt",
            store=store,
            quiet=True,
            overrides={
                "BOOK_STOCKS": {STOCK},
                "DIVIDEND_TYPE": "none",
                "DRY_RUN": False,
            },
            dividend_type="none",
        )
        trades_path = trades_csv_path(log_path)
        trades: list[list[str]] = []
        if trades_path.is_file():
            raw = trades_path.read_text(encoding="gbk")
            rows = list(csv.reader(raw.splitlines()))
            trades = rows[1:] if rows else []
        log_text = log_path.read_text(encoding="utf-8")
        reasons = _parse_reasons(log_text)
        end_pos = 0
        for row in trades:
            if len(row) < 13:
                continue
            side = row[6]
            qty = int(float(row[12] or 0))
            if side == "买入":
                end_pos += qty
            elif side == "卖出":
                end_pos -= qty
        return {
            "n_trades": len(trades),
            "trades": trades,
            "reasons": reasons,
            "end_pos": end_pos,
            "eval_cases": cases,
            "walk": {"start": "20180601", "end": "20181130", "n_bars": len(bars)},
        }


def main() -> None:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    data = snapshot()
    FIXTURE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "wrote",
        FIXTURE,
        "n_trades=",
        data["n_trades"],
        "end_pos=",
        data["end_pos"],
        "n_reasons=",
        len(data["reasons"]),
    )


if __name__ == "__main__":
    main()
