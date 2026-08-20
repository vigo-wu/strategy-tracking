# -*- coding: utf-8 -*-
"""Replay 4 CSVs as one 200k book: fill-the-gap sizing, 40% vs 50% name cap."""
from __future__ import annotations

import csv
import json
from collections import defaultdict, deque
from datetime import date, datetime
from pathlib import Path

DIR = Path(__file__).resolve().parent
START = 200_000.0
BOOK_N = 4
CASH_RATIO = 0.95
MIN_LOT = 20_000.0


def parse_num(s):
    return float(str(s).replace(",", "").strip() or 0)


def load_events():
    rows = []
    for f in sorted(DIR.glob("*.csv")):
        with open(f, encoding="gbk") as fh:
            for row in csv.DictReader(fh):
                t = datetime.strptime(row["操作时间"], "%Y-%m-%d %H:%M:%S")
                rows.append(
                    {
                        "code": row["代码"],
                        "name": row["名称"],
                        "dt": t,
                        "side": row["操作类型"].strip(),
                        "price": parse_num(row["操作价格"]),
                        "qty": parse_num(row["数量"]),
                        "pnl": parse_num(row["盈利"]),
                    }
                )
    rows.sort(key=lambda r: (r["dt"], 0 if r["side"] == "买入" else 1, r["code"]))
    return rows


class Book:
    def __init__(self, max_name_frac, label):
        self.max_name_frac = max_name_frac
        self.label = label
        self.cash = START
        self.lots = defaultdict(deque)  # code -> {orig, ours, px}
        self.last_px = {}
        self.skipped = 0
        self.fills = 0
        self.realized = 0.0
        self.equity_pts = []  # (dt, equity)
        self.max_name_w = 0.0
        self.max_dd = 0.0
        self.peak = START
        self.skip_notional = 0.0
        self.year_realized = defaultdict(float)

    def book_mv(self):
        mv = 0.0
        for code, q in self.lots.items():
            px = self.last_px.get(code, 0.0)
            for lot in q:
                px_use = px if px > 0 else lot["px"]
                mv += lot["ours"] * px_use
        return mv

    def n_held(self):
        n = 0
        for q in self.lots.values():
            if any(lot["ours"] > 1e-6 for lot in q):
                n += 1
        return n

    def name_mv(self, code):
        px = self.last_px.get(code)
        mv = 0.0
        for lot in self.lots[code]:
            px_use = px if px else lot["px"]
            mv += lot["ours"] * px_use
        return mv

    def equity(self):
        return self.cash + self.book_mv()

    def mark(self, dt):
        eq = self.equity()
        self.equity_pts.append((dt, eq))
        if eq > self.peak:
            self.peak = eq
        dd = (self.peak - eq) / self.peak if self.peak > 0 else 0.0
        if dd > self.max_dd:
            self.max_dd = dd
        e = eq if eq > 0 else 1.0
        for code in list(self.lots.keys()):
            if not self.lots[code]:
                continue
            w = self.name_mv(code) / e
            if w > self.max_name_w:
                self.max_name_w = w

    def buy(self, ev):
        code, px, orig = ev["code"], ev["price"], ev["qty"]
        self.last_px[code] = px
        is_new = self.name_mv(code) < 1e-6
        k_after = self.n_held() + (1 if is_new else 0)
        empty = max(0, BOOK_N - k_after)
        reserve = empty * MIN_LOT
        eq = self.equity()
        cap = CASH_RATIO * eq
        mv = self.book_mv()
        name_limit = min(self.max_name_frac * eq, cap - (BOOK_N - 1) * MIN_LOT)
        name_room = name_limit - self.name_mv(code)
        acct_room = cap - mv - reserve
        budget = min(acct_room, name_room, self.cash)
        shares = int(budget / px / 100.0) * 100 if px > 0 else 0
        notional = shares * px
        if shares < 100 or notional + 1e-6 < MIN_LOT:
            self.skipped += 1
            self.skip_notional += orig * px
            self.lots[code].append({"orig": orig, "ours": 0.0, "px": px})
            self.mark(ev["dt"])
            return
        self.cash -= notional
        self.lots[code].append({"orig": orig, "ours": float(shares), "px": px})
        self.fills += 1
        self.mark(ev["dt"])

    def sell(self, ev):
        code, px, remain = ev["code"], ev["price"], ev["qty"]
        self.last_px[code] = px
        pnl = 0.0
        while remain > 1e-6 and self.lots[code]:
            lot = self.lots[code][0]
            take_orig = min(lot["orig"], remain)
            frac = take_orig / lot["orig"] if lot["orig"] else 0.0
            take_ours = lot["ours"] * frac
            pnl += (px - lot["px"]) * take_ours
            lot["orig"] -= take_orig
            lot["ours"] -= take_ours
            remain -= take_orig
            if lot["orig"] < 1e-6:
                self.lots[code].popleft()
        self.cash += (ev["qty"] - remain)  # placeholder, fixed below
        # cash should increase by shares sold * px; recompute from pnl and cost
        # Redo cash: we added wrong. Use explicit:
        # Actually let's recompute sell cash properly in a second pass.
        self._last_sell_pnl = pnl
        self._last_sell_proceeds = None
        self.realized += pnl
        self.year_realized[ev["dt"].year] += pnl
        self.mark(ev["dt"])


def replay(events, max_name_frac, label):
    b = Book(max_name_frac, label)
    for ev in events:
        if ev["side"] == "买入":
            b.buy(ev)
        else:
            code, px, remain = ev["code"], ev["price"], ev["qty"]
            b.last_px[code] = px
            proceeds = 0.0
            pnl = 0.0
            while remain > 1e-6 and b.lots[code]:
                lot = b.lots[code][0]
                take_orig = min(lot["orig"], remain)
                frac = take_orig / lot["orig"] if lot["orig"] else 0.0
                take_ours = lot["ours"] * frac
                proceeds += take_ours * px
                pnl += (px - lot["px"]) * take_ours
                lot["orig"] -= take_orig
                lot["ours"] -= take_ours
                remain -= take_orig
                if lot["orig"] < 1e-6:
                    b.lots[code].popleft()
            b.cash += proceeds
            b.realized += pnl
            b.year_realized[ev["dt"].year] += pnl
            b.mark(ev["dt"])
    b.mark(events[-1]["dt"])
    return b


def month_end_curve(pts, start_dt, end_dt):
    """Last equity in each calendar month, plus start."""
    by_m = {}
    for dt, eq in pts:
        key = date(dt.year, dt.month, 1)
        by_m[key] = eq
    keys = sorted(by_m)
    labels = [k.strftime("%y-%m") for k in keys]
    vals = [round(by_m[k], 0) for k in keys]
    return labels, vals


def cagr(start, end, days):
    if start <= 0 or end <= 0 or days <= 0:
        return float("nan")
    return (end / start) ** (365.0 / days) - 1


def summarize(book, first, last):
    days = (last - first).days + 1
    eq = book.equity()
    return {
        "label": book.label,
        "final_equity": round(eq, 2),
        "total_pnl": round(eq - START, 2),
        "total_ret": (eq / START) - 1,
        "cagr": cagr(START, eq, days),
        "max_dd": book.max_dd,
        "max_name_w": book.max_name_w,
        "skipped_buys": book.skipped,
        "fills": book.fills,
        "realized": round(book.realized, 2),
        "open_mv": round(book.book_mv(), 2),
        "cash": round(book.cash, 2),
        "year_realized": {str(y): round(v, 2) for y, v in sorted(book.year_realized.items())},
    }


def original_combined(events):
    """Independent 50k lots, sum realized PnL onto 200k (no shared cap, no resize)."""
    cash_pnl = 0.0
    pts = []
    year_realized = defaultdict(float)
    for ev in events:
        if ev["side"] == "卖出":
            cash_pnl += ev["pnl"]
            year_realized[ev["dt"].year] += ev["pnl"]
        pts.append((ev["dt"], START + cash_pnl))
    return pts, year_realized


def main():
    events = load_events()
    first, last = events[0]["dt"], events[-1]["dt"]
    out = {"first": str(first.date()), "last": str(last.date()), "days": (last - first).days + 1}
    curves = {}
    stats = []
    for frac, lab in ((0.40, "cap40"), (0.50, "cap50"), (0.99, "no_name_cap")):
        b = replay(events, frac, lab)
        labels, vals = month_end_curve(b.equity_pts, first, last)
        curves[lab] = {"labels": labels, "equity": vals}
        stats.append(summarize(b, first, last))
    orig_pts, orig_year = original_combined(events)
    labels, vals = month_end_curve(orig_pts, first, last)
    curves["orig_fixed50k"] = {"labels": labels, "equity": vals}
    orig_final = orig_pts[-1][1]
    days = (last - first).days + 1
    stats.append(
        {
            "label": "orig_fixed50k",
            "final_equity": round(orig_final, 2),
            "total_pnl": round(orig_final - START, 2),
            "total_ret": (orig_final / START) - 1,
            "cagr": cagr(START, orig_final, days),
            "max_dd": None,
            "max_name_w": None,
            "skipped_buys": 0,
            "fills": sum(1 for e in events if e["side"] == "买入"),
            "realized": round(orig_final - START, 2),
            "year_realized": {str(y): round(v, 2) for y, v in sorted(orig_year.items())},
        }
    )
    out["stats"] = stats
    out["curves"] = curves
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
