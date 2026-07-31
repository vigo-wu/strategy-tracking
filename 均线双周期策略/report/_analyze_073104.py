# coding: utf-8
import csv
from datetime import datetime
from collections import Counter

path = r"C:\Users\admin\Desktop\日志\回测记录073104.csv"
rows = []
raw = None
for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
    try:
        with open(path, encoding=enc) as f:
            rows = list(csv.DictReader(f))
        print("encoding", enc)
        break
    except UnicodeDecodeError:
        rows = []
if not rows:
    raise SystemExit("cannot decode csv")

buys, sells = [], []
for r in rows:
    t = datetime.strptime(r["操作时间"], "%Y-%m-%d %H:%M:%S")
    px = float(r["操作价格"])
    qty = int(float(r["数量"]))
    pnl = float(r["盈利"])
    fee = float(r["交易费用"])
    mv = float(r["市值"])
    item = dict(t=t, px=px, qty=qty, pnl=pnl, fee=fee, mv=mv, name=r["名称"], code=r["代码"])
    if r["操作类型"] == "买入":
        buys.append(item)
    else:
        sells.append(item)

print("buys", len(buys), "sells", len(sells))
print("range", buys[0]["t"], "->", (sells or buys)[-1]["t"])
print("code", buys[0]["code"], buys[0]["name"])

rounds = []
bi = 0
for s in sells:
    b = buys[bi]
    bi += 1
    hold_days = (s["t"].date() - b["t"].date()).days
    ret = (s["px"] - b["px"]) / b["px"] if b["px"] else 0
    bh = b["t"].strftime("%H:%M")
    sh = s["t"].strftime("%H:%M")
    if ret <= -0.028:
        reason = "stop~3%"
    elif hold_days >= 10:
        reason = "long_hold"
    elif hold_days <= 2 and ret < -0.015:
        reason = "quick_loss"
    elif ret > 0.02:
        reason = "big_win"
    elif ret > 0:
        reason = "small_win"
    elif abs(ret) < 1e-9:
        reason = "flat"
    else:
        reason = "small_loss"
    rounds.append(
        dict(b=b, s=s, hold_days=hold_days, ret=ret, pnl=s["pnl"], bh=bh, sh=sh, reason=reason)
    )

open_buys = buys[bi:]
print("paired", len(rounds), "open", len(open_buys))

pnls = [r["pnl"] for r in rounds]
rets = [r["ret"] for r in rounds]
wins = [r for r in rounds if r["pnl"] > 0.01]
losses = [r for r in rounds if r["pnl"] < -0.01]
flats = [r for r in rounds if abs(r["pnl"]) <= 0.01]
total = sum(pnls)
avg_win = sum(x["pnl"] for x in wins) / len(wins) if wins else 0
avg_loss = sum(x["pnl"] for x in losses) / len(losses) if losses else 0
gross_win = sum(x["pnl"] for x in wins)
gross_loss = abs(sum(x["pnl"] for x in losses))
pf = gross_win / gross_loss if gross_loss else float("inf")

eq = 0
peak = 0
maxdd = 0
for r in rounds:
    eq += r["pnl"]
    peak = max(peak, eq)
    maxdd = min(maxdd, eq - peak)

mw = ml = cw = cl = 0
for r in rounds:
    if r["pnl"] > 0.01:
        cw += 1
        cl = 0
        mw = max(mw, cw)
    elif r["pnl"] < -0.01:
        cl += 1
        cw = 0
        ml = max(ml, cl)
    else:
        cw = cl = 0

buy_h = Counter(r["bh"] for r in rounds)
sell_h = Counter(r["sh"] for r in rounds)
hold_c = Counter(r["hold_days"] for r in rounds)
reason_c = Counter(r["reason"] for r in rounds)

print("=== SUMMARY ===")
print("total_pnl", round(total, 2))
print("budget_ref", round(buys[0]["mv"], 1))
print("ret_vs_budget", round(total / buys[0]["mv"] * 100, 2), "%")
print("winrate", round(len(wins) / len(rounds) * 100, 1), "W/L/F", len(wins), len(losses), len(flats))
print("avg_ret%", round(sum(rets) / len(rets) * 100, 3))
print("med_ret%", round(sorted(rets)[len(rets) // 2] * 100, 3))
print("avg_win", round(avg_win, 2), "avg_loss", round(avg_loss, 2))
print("profit_factor", round(pf, 3))
print("max_win", round(max(pnls), 2), "max_loss", round(min(pnls), 2))
print("maxdd", round(maxdd, 2), "final_eq", round(eq, 2))
print("streak W/L", mw, ml)
print("avg_hold", round(sum(r["hold_days"] for r in rounds) / len(rounds), 2))
print("buy_hours", dict(buy_h))
print("sell_hours", dict(sell_h))
print("hold_days", dict(sorted(hold_c.items())))
print("reasons", dict(reason_c))
print(
    "qty_mismatch",
    [(i, r["b"]["qty"], r["s"]["qty"]) for i, r in enumerate(rounds) if r["b"]["qty"] != r["s"]["qty"]],
)

# year split
by_year = Counter()
pnl_year = {}
for r in rounds:
    y = r["b"]["t"].year
    by_year[y] += 1
    pnl_year[y] = pnl_year.get(y, 0) + r["pnl"]
print("by_year_count", dict(by_year))
print("by_year_pnl", {k: round(v, 2) for k, v in sorted(pnl_year.items())})

# sell hour vs avg ret
from collections import defaultdict

sh_stats = defaultdict(list)
for r in rounds:
    sh_stats[r["sh"]].append(r["pnl"])
print("sell_hour_pnl")
for h, xs in sorted(sh_stats.items()):
    print(" ", h, "n=", len(xs), "sum=", round(sum(xs), 1), "avg=", round(sum(xs) / len(xs), 1))

print("=== ROUNDS ===")
cum = 0
for i, r in enumerate(rounds, 1):
    cum += r["pnl"]
    line = (
        "%02d %s @%.3f -> %s @%.3f hold=%dd ret=%+.2f%% pnl=%+.1f cum=%+.1f %s"
        % (
            i,
            r["b"]["t"].strftime("%Y-%m-%d %H:%M"),
            r["b"]["px"],
            r["s"]["t"].strftime("%Y-%m-%d %H:%M"),
            r["s"]["px"],
            r["hold_days"],
            r["ret"] * 100,
            r["pnl"],
            cum,
            r["reason"],
        )
    )
    print(line)

# check buy after sell same day / double buy
print("=== STRUCTURE CHECK ===")
for i in range(len(rounds) - 1):
    gap = (rounds[i + 1]["b"]["t"] - rounds[i]["s"]["t"]).total_seconds() / 3600
    if gap < 0:
        print("OVERLAP", i + 1, i + 2)
    if gap < 1:
        print("quick_reentry_h", round(gap, 2), "after round", i + 1)

# fee total
print("fee_total", sum(float(r["交易费用"]) for r in rows))
print("avg_notional", round(sum(b["mv"] for b in buys) / len(buys), 1))
