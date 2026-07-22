"""
红利中字头 50 池 · 历史回测（origin v3.1）。
入场同 v2.0；出场：R1=入场-2ATR或收破EMA60超2% → R0=+8%保本 → R2=+9%平60% → R3=余仓连2日破EMA60。
大盘：上证收盘≥日EMA130 才开仓（原持仓不受影响）。
板块：同行业持仓≥3 跳过。
资金：总盘50万 / 单笔5万 / 最多10仓。
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import baostock as bs
import numpy as np
import pandas as pd

THEME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = THEME_ROOT.parent
DATA_DIR = REPO_ROOT / "data" / "daily"
OUT_DIR = THEME_ROOT / "output"
LIST_MD = THEME_ROOT / "list.md"
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

BT_START = "2023-01-01"
BT_END = "2026-07-21"
HIST_START = "2021-01-01"
MAX_HOLD = 120

TOTAL_CAPITAL = 200_000.0
PER_TRADE_BUDGET = 50_000.0
MAX_SLOTS = int(TOTAL_CAPITAL // PER_TRADE_BUDGET)  # 4
MAX_PER_SECTOR = 3

# list.md 行业粗分（拥挤风控）
SECTOR_MAP: dict[str, str] = {
    "601939": "银行", "601988": "银行", "601328": "银行", "601398": "银行",
    "601288": "银行", "601998": "银行", "601818": "银行", "600919": "银行",
    "601628": "保险", "601318": "保险", "601601": "保险",
    "601088": "煤炭", "601666": "煤炭", "601898": "煤炭", "000983": "煤炭", "601101": "煤炭",
    "601857": "石油", "600938": "石油", "600028": "石油", "600968": "石油", "600026": "石油",
    "600795": "电力", "600011": "电力", "600505": "电力", "600886": "电力", "000027": "电力",
    "601919": "航运港口", "601872": "航运港口", "001872": "航运港口", "600018": "航运港口",
    "601880": "航运港口",
    "601668": "建筑", "601186": "建筑", "601390": "建筑", "601800": "建筑",
    "600282": "钢铁", "600019": "钢铁",
    "601006": "交运设备", "601766": "交运设备", "600150": "交运设备",
    "601600": "有色", "601958": "有色", "002738": "有色", "600916": "有色",
    "600737": "消费", "600048": "地产", "601104": "医药", "000400": "电力设备",
    "600449": "建材", "600522": "军工电子",
}


def to_bs_code(code6: str) -> str:
    c = code6.zfill(6)
    if c.startswith(("5", "6", "9")):
        return f"sh.{c}"
    return f"sz.{c}"


def load_list_md(path: Path = LIST_MD) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        m = re.match(r"\|\s*\d+\s*\|\s*(\d{6})\s*\|\s*([^|]+?)\s*\|", line.strip())
        if not m:
            continue
        code6, name = m.group(1), m.group(2).strip()
        rows.append(
            {
                "code": to_bs_code(code6),
                "code6": code6,
                "name": name,
                "sector": SECTOR_MAP.get(code6, "其他"),
            }
        )
    if not rows:
        raise ValueError(f"未能从 {path} 解析到股票代码")
    return pd.DataFrame(rows)


@dataclass
class Candidate:
    code: str
    name: str
    sector: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    stop_line: float
    hold_days: int
    ret_pct: float
    exit_reason: str
    r0_triggered: bool
    r2_triggered: bool
    r2_date: str | None


@dataclass
class Trade:
    code: str
    name: str
    sector: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    stop_line: float
    hold_days: int
    ret_pct: float
    exit_reason: str
    shares: int
    cost: float
    proceeds: float
    pnl: float
    r0_triggered: bool = False
    r2_triggered: bool = False
    r2_date: str | None = None
    skipped: bool = False
    skip_reason: str = ""


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def atr_series(d: pd.DataFrame) -> pd.Series:
    prev_c = d["close"].shift(1)
    tr = pd.concat(
        [
            d["high"] - d["low"],
            (d["high"] - prev_c).abs(),
            (d["low"] - prev_c).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(span=14, adjust=False).mean()


def lot_shares(price: float, budget: float | None = None) -> int:
    if budget is None:
        budget = PER_TRADE_BUDGET
    if price <= 0:
        return 0
    return int(budget // (price * 100)) * 100


def download_one(bs_code: str, start: str, end: str) -> pd.DataFrame | None:
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,volume,amount,tradestatus",
        start_date=start,
        end_date=end,
        frequency="d",
        adjustflag="2",
    )
    if rs.error_code != "0":
        return None
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return None
    df = pd.DataFrame(
        rows, columns=["date", "open", "high", "low", "close", "vol", "amount", "tradestatus"]
    )
    for c in ("open", "high", "low", "close", "vol", "amount"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["tradestatus"] == "1"].dropna(subset=["close"])
    return df[df["vol"] > 0].reset_index(drop=True)


def ensure_cache(universe: pd.DataFrame, start: str, end: str) -> None:
    bs.login()
    try:
        # 上证指数
        idx_path = DATA_DIR / "000001_sh.csv"
        need_idx = True
        if idx_path.exists():
            try:
                old = pd.read_csv(idx_path, usecols=["date"])
                if not old.empty and str(old["date"].iloc[-1])[:10] >= end:
                    need_idx = False
            except Exception:
                pass
        if need_idx:
            print("  下载 上证指数 sh.000001")
            df = download_one("sh.000001", start, end)
            if df is not None and len(df):
                df.to_csv(idx_path, index=False)

        for i, row in universe.iterrows():
            path = DATA_DIR / f"{row['code6']}.csv"
            if path.exists():
                try:
                    old = pd.read_csv(path, usecols=["date"])
                    if not old.empty and str(old["date"].iloc[-1])[:10] >= end:
                        continue
                except Exception:
                    pass
            if i % 10 == 0:
                print(f"  下载 {i+1}/{len(universe)} {row['code6']}")
            df = download_one(row["code"], start, end)
            if df is not None and len(df):
                df.to_csv(path, index=False)
    finally:
        bs.logout()


def load_market_ok_dates() -> set[str]:
    """日线近似：上证收盘 >= EMA130（≈周EMA26）的日期允许开仓。"""
    path = DATA_DIR / "000001_sh.csv"
    if not path.exists():
        return set()
    d = pd.read_csv(path)
    d["ema130"] = ema(d["close"], 130)
    ok = d["close"] >= d["ema130"]
    return set(str(x)[:10] for x in d.loc[ok, "date"])


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["ema20"] = ema(d["close"], 20)
    d["ema60"] = ema(d["close"], 60)
    d["w_fast"] = ema(d["close"], 60)
    d["w_slow"] = ema(d["close"], 130)
    d["mavol3"] = d["vol"].rolling(3).mean()
    d["mavol5"] = d["vol"].rolling(5).mean()
    d["mavol20"] = d["vol"].rolling(20).mean()
    d["atr"] = atr_series(d)
    d["swing_high20"] = d["high"].rolling(20).max()
    return d


def signal_mask(d: pd.DataFrame) -> pd.Series:
    week = (d["w_fast"] > d["w_slow"]) & (d["close"] >= d["w_fast"])
    near60 = (d["low"] <= d["ema60"] * 1.02) & (d["close"] <= d["ema60"] * 1.05)
    vol_shrink = d["mavol5"] <= d["mavol20"] * 0.85
    yang = d["close"] > d["open"]
    reclaim = d["close"] > d["ema20"]
    vol_ok = d["vol"] > d["mavol3"] * 1.2
    bars = pd.Series(np.arange(len(d)) >= 159, index=d.index)
    return week & near60 & vol_shrink & yang & reclaim & vol_ok & bars


def simulate(d: pd.DataFrame, entry_i: int) -> dict | None:
    """v3.1：R1=ATR或收破EMA60×0.98；R0=+8%保本；R2=+9%平60%；R3=余仓连2日破EMA60。"""
    if entry_i >= len(d) - 1:
        return None
    entry = d.iloc[entry_i]
    entry_px = float(entry["close"])
    atr0 = float(entry["atr"])
    if pd.isna(atr0) or atr0 <= 0:
        return None
    hard_stop = entry_px - 2 * atr0
    swing_high = float(entry["swing_high20"])
    last_i = min(entry_i + MAX_HOLD, len(d) - 1)

    trail_stop = hard_stop
    r0_done = False
    r2_done = False
    r2_date = None
    r2_exit_px = None
    below_ema60 = 0
    exit_i, exit_px, reason = entry_i, entry_px, "R3"

    for j in range(entry_i + 1, last_i + 1):
        row = d.iloc[j]
        px = float(row["close"])
        lo = float(row["low"])
        hi = float(row["high"])
        ema60 = float(row["ema60"])
        profit = (px / entry_px - 1) * 100

        # R1：ATR/保本止损触达（盘中）
        if lo <= trail_stop:
            exit_i = j
            exit_px = trail_stop
            reason = "R1" if not r0_done else "R0+R1"
            break

        # R1 附加：未 R2 前，收盘有效跌破 EMA60 超 2%
        if (not r2_done) and px < ema60 * 0.98:
            exit_i, exit_px, reason = j, px, "R1"
            break

        # R0：+8% 保本
        if (not r0_done) and profit >= 8.0:
            r0_done = True
            trail_stop = entry_px

        # R2：+9% 或触前高 → 平 60%
        if (not r2_done) and (profit >= 9.0 or hi >= swing_high * 0.995 or px >= swing_high * 0.995):
            r2_done = True
            r2_date = str(row["date"])[:10]
            r2_exit_px = px
            below_ema60 = 0
            trail_stop = -1e18  # 余仓只看 EMA60 的 R3
            continue

        # R3：余仓（或未减仓全仓）连 2 日收盘破 EMA60 无法收回
        if r2_done:
            if px < ema60:
                below_ema60 += 1
            else:
                below_ema60 = 0
            if below_ema60 >= 2:
                exit_i, exit_px, reason = j, px, "R3"
                break

        exit_i, exit_px, reason = j, px, "R3"

    if r2_done and r2_exit_px is not None:
        r2_ret = r2_exit_px / entry_px - 1
        rest_ret = float(exit_px) / entry_px - 1
        blended = 0.6 * r2_ret + 0.4 * rest_ret
        ret_pct = round(blended * 100, 2)
        eff_exit = round(entry_px * (1 + blended), 3)
        if "R1" in reason:
            reason = "R2+" + reason
        else:
            reason = "R2+R3"
    else:
        ret_pct = round((float(exit_px) / entry_px - 1) * 100, 2)
        eff_exit = round(float(exit_px), 3)

    return {
        "entry_date": str(entry["date"])[:10],
        "exit_date": str(d.iloc[exit_i]["date"])[:10],
        "entry_price": round(entry_px, 3),
        "exit_price": eff_exit,
        "stop_line": round(hard_stop, 3),
        "hold_days": int(exit_i - entry_i),
        "ret_pct": ret_pct,
        "exit_reason": reason,
        "r0_triggered": r0_done,
        "r2_triggered": r2_done,
        "r2_date": r2_date,
    }


def collect_candidates(code6: str, name: str, sector: str) -> list[Candidate]:
    path = DATA_DIR / f"{code6}.csv"
    if not path.exists():
        return []
    raw = pd.read_csv(path)
    if len(raw) < 180:
        return []
    d = add_indicators(raw)
    sig = signal_mask(d)
    out: list[Candidate] = []
    i, n = 0, len(d)
    while i < n:
        if not bool(sig.iloc[i]):
            i += 1
            continue
        dt = str(d.iloc[i]["date"])[:10]
        if dt < BT_START or dt > BT_END:
            i += 1
            continue
        r = simulate(d, i)
        if not r:
            i += 1
            continue
        out.append(Candidate(code=code6, name=name, sector=sector, **r))
        exit_date = r["exit_date"]
        j = i + 1
        while j < n and str(d.iloc[j]["date"])[:10] <= exit_date:
            j += 1
        i = j
    return out


def allocate_portfolio(
    candidates: list[Candidate], market_ok: set[str]
) -> tuple[list[Trade], dict]:
    ordered = sorted(candidates, key=lambda t: (t.entry_date, t.code))
    cash = TOTAL_CAPITAL
    open_pos: list[Trade] = []
    filled: list[Trade] = []
    skipped: list[Trade] = []
    peak_slots = 0
    skip_mkt = 0
    skip_sector = 0

    def settle_exits(as_of: str) -> None:
        nonlocal cash, open_pos
        still: list[Trade] = []
        for t in open_pos:
            if t.exit_date <= as_of:
                cash += t.proceeds
                filled.append(t)
            else:
                still.append(t)
        open_pos = still

    def sector_count(sector: str) -> int:
        return sum(1 for t in open_pos if t.sector == sector)

    for c in ordered:
        settle_exits(c.entry_date)
        shares = lot_shares(c.entry_price)
        cost = round(shares * c.entry_price, 2)
        skip_reason = ""
        if market_ok and c.entry_date not in market_ok:
            skip_reason = "大盘过滤(上证弱)"
            skip_mkt += 1
        elif shares < 100:
            skip_reason = "不足1手"
        elif len(open_pos) >= MAX_SLOTS:
            skip_reason = "满仓位"
        elif cost > cash + 1e-6:
            skip_reason = "现金不足"
        elif sector_count(c.sector) >= MAX_PER_SECTOR:
            skip_reason = f"板块拥挤({c.sector}≥{MAX_PER_SECTOR})"
            skip_sector += 1

        if skip_reason:
            skipped.append(
                Trade(
                    code=c.code,
                    name=c.name,
                    sector=c.sector,
                    entry_date=c.entry_date,
                    exit_date=c.exit_date,
                    entry_price=c.entry_price,
                    exit_price=c.exit_price,
                    stop_line=c.stop_line,
                    hold_days=c.hold_days,
                    ret_pct=c.ret_pct,
                    exit_reason=c.exit_reason,
                    shares=0,
                    cost=0.0,
                    proceeds=0.0,
                    pnl=0.0,
                    r0_triggered=c.r0_triggered,
                    r2_triggered=c.r2_triggered,
                    r2_date=c.r2_date,
                    skipped=True,
                    skip_reason=skip_reason,
                )
            )
            continue

        proceeds = round(cost * (1 + c.ret_pct / 100), 2)
        pnl = round(proceeds - cost, 2)
        t = Trade(
            code=c.code,
            name=c.name,
            sector=c.sector,
            entry_date=c.entry_date,
            exit_date=c.exit_date,
            entry_price=c.entry_price,
            exit_price=c.exit_price,
            stop_line=c.stop_line,
            hold_days=c.hold_days,
            ret_pct=c.ret_pct,
            exit_reason=c.exit_reason,
            shares=shares,
            cost=cost,
            proceeds=proceeds,
            pnl=pnl,
            r0_triggered=c.r0_triggered,
            r2_triggered=c.r2_triggered,
            r2_date=c.r2_date,
        )
        cash -= cost
        open_pos.append(t)
        peak_slots = max(peak_slots, len(open_pos))

    settle_exits("9999-12-31")
    final_equity = round(cash, 2)
    total_pnl = round(final_equity - TOTAL_CAPITAL, 2)
    meta = {
        "total_capital": TOTAL_CAPITAL,
        "per_trade_budget": PER_TRADE_BUDGET,
        "max_slots": MAX_SLOTS,
        "max_per_sector": MAX_PER_SECTOR,
        "signal_count": len(candidates),
        "filled_count": len(filled),
        "skipped_count": len(skipped),
        "skipped_market": skip_mkt,
        "skipped_sector": skip_sector,
        "peak_concurrent": peak_slots,
        "final_equity": final_equity,
        "total_pnl": total_pnl,
        "total_return_pct": round(total_pnl / TOTAL_CAPITAL * 100, 2),
        "strategy_version": "v3.1",
    }
    return filled + skipped, meta


def per_symbol_stats(trades: list[Trade], universe: pd.DataFrame) -> tuple[list[str], pd.DataFrame]:
    filled = [t for t in trades if not t.skipped]
    by_code: dict[str, list[Trade]] = {}
    for t in filled:
        by_code.setdefault(t.code, []).append(t)
    zero = [c for c in universe["code6"].tolist() if c not in by_code]
    rows = []
    for code6, name in zip(universe["code6"], universe["name"]):
        ts = by_code.get(code6, [])
        if not ts:
            continue
        rets = np.array([t.ret_pct for t in ts])
        pnls = np.array([t.pnl for t in ts])
        rows.append(
            {
                "code": code6,
                "name": name,
                "n": len(ts),
                "win_rate": round(float((rets > 0).mean() * 100), 1),
                "avg_ret": round(float(rets.mean()), 2),
                "sum_pnl": round(float(pnls.sum()), 2),
            }
        )
    stats = (
        pd.DataFrame(rows).sort_values("sum_pnl", ascending=False) if rows else pd.DataFrame()
    )
    return zero, stats


def summarize(trades: list[Trade], cap_meta: dict) -> dict:
    filled = [t for t in trades if not t.skipped]
    if not filled:
        return {"trade_count": 0, **cap_meta}
    rets = np.array([t.ret_pct for t in filled])
    pnls = np.array([t.pnl for t in filled])
    by_r: dict[str, int] = {}
    for t in filled:
        by_r[t.exit_reason] = by_r.get(t.exit_reason, 0) + 1
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    return {
        "trade_count": len(filled),
        "win_rate_pct": round(float((rets > 0).mean() * 100), 2),
        "avg_ret_pct": round(float(rets.mean()), 2),
        "median_ret_pct": round(float(np.median(rets)), 2),
        "avg_win_pct": round(float(wins.mean()), 2) if len(wins) else None,
        "avg_loss_pct": round(float(losses.mean()), 2) if len(losses) else None,
        "avg_hold_days": round(float(np.mean([t.hold_days for t in filled])), 1),
        "exit_reason_counts": by_r,
        "max_ret_pct": round(float(rets.max()), 2),
        "min_ret_pct": round(float(rets.min()), 2),
        "sum_pnl": round(float(pnls.sum()), 2),
        "avg_pnl": round(float(pnls.mean()), 2),
        "max_pnl": round(float(pnls.max()), 2),
        "min_pnl": round(float(pnls.min()), 2),
        "r0_count": sum(1 for t in filled if t.r0_triggered),
        "r2_count": sum(1 for t in filled if t.r2_triggered),
        "notes": [
            "策略版本：origin v3.1（R0=+8%保本 / R2=+9%平60% / R3=余仓连2日破EMA60）",
            f"总资金 {TOTAL_CAPITAL:.0f}；单笔约 {PER_TRADE_BUDGET:.0f}；最多 {MAX_SLOTS} 仓；同板块最多 {MAX_PER_SECTOR}",
            "大盘：上证收盘≥日EMA130 才开仓（原持仓不受影响）；R1含收破EMA60超2%",
            "未计税费；板块行业为手工粗分",
        ],
        **cap_meta,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="v3.1 list 回测")
    parser.add_argument("--universe", choices=["list"], default="list")
    parser.add_argument("--list", type=Path, default=LIST_MD)
    args = parser.parse_args()

    universe = load_list_md(args.list)
    print(f"=== list {len(universe)} 只 | v3.1 | 资金 {TOTAL_CAPITAL:.0f} ===")
    ensure_cache(universe, HIST_START, BT_END)
    market_ok = load_market_ok_dates()
    print(f"大盘允许开仓日约 {len(market_ok)} 天")

    candidates: list[Candidate] = []
    for i, row in universe.iterrows():
        print(f"  {i+1}/{len(universe)} {row['code6']} {row['name']}")
        candidates.extend(collect_candidates(row["code6"], row["name"], row["sector"]))
    print(f"信号 {len(candidates)} → 配资")
    all_trades, cap_meta = allocate_portfolio(candidates, market_ok)
    summary = summarize(all_trades, cap_meta)
    zero, per_stats = per_symbol_stats(all_trades, universe)
    notes = list(summary.get("notes") or [])
    notes.append(f"股票池：list.md，共 {len(universe)} 只")
    summary["notes"] = notes
    summary.update(
        {
            "bt_start": BT_START,
            "bt_end": BT_END,
            "universe": "list",
            "universe_size": len(universe),
            "zero_signal_codes": zero,
            "run_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    stamp = f"list_{BT_START}_{BT_END}".replace("-", "")
    filled = [t for t in all_trades if not t.skipped]
    skipped = [t for t in all_trades if t.skipped]
    trades_df = pd.DataFrame([asdict(t) for t in filled])
    if not trades_df.empty:
        trades_df["code"] = trades_df["code"].astype(str).str.zfill(6)
    trades_df.to_csv(OUT_DIR / f"backtest_trades_{stamp}.csv", index=False, encoding="utf-8-sig")
    if skipped:
        skip_df = pd.DataFrame([asdict(t) for t in skipped])
        skip_df["code"] = skip_df["code"].astype(str).str.zfill(6)
        skip_df.to_csv(OUT_DIR / f"backtest_skipped_{stamp}.csv", index=False, encoding="utf-8-sig")
    (OUT_DIR / f"backtest_summary_{stamp}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    md = [
        "# 周日双周期 · 历史回测报告（origin v3.1 · list.md）",
        "",
        f"- 区间：{BT_START} ~ {BT_END}",
        f"- 策略版本：**v3.1**（R0=+8%保本｜R2=+9%平60%｜R3=连2日破EMA60）",
        f"- 资金：总盘 **{TOTAL_CAPITAL:.0f}**；单笔约 **{PER_TRADE_BUDGET:.0f}**；最多 **{MAX_SLOTS}** 仓；同板块≤**{MAX_PER_SECTOR}**",
        f"- 信号 / 成交 / 跳过：{summary.get('signal_count')} / {summary.get('filled_count')} / {summary.get('skipped_count')}（大盘{summary.get('skipped_market')}｜板块{summary.get('skipped_sector')}）",
        f"- 期末权益 / 总盈亏 / 收益率：{summary.get('final_equity')} / {summary.get('total_pnl')} / {summary.get('total_return_pct')}%",
        f"- 胜率：{summary.get('win_rate_pct')}%",
        f"- 平均 / 中位数%：{summary.get('avg_ret_pct')}% / {summary.get('median_ret_pct')}%",
        f"- 触发 R0 / R2：{summary.get('r0_count')} / {summary.get('r2_count')}",
        f"- 单笔盈亏合计 / 均盈亏：{summary.get('sum_pnl')} / {summary.get('avg_pnl')}",
        f"- 极值（元）：{summary.get('max_pnl')} / {summary.get('min_pnl')}",
        f"- 平均持仓：{summary.get('avg_hold_days')} 日｜峰值同时持仓：{summary.get('peak_concurrent')}",
        f"- 出场分布：{summary.get('exit_reason_counts')}",
        "",
        "## 假设",
        "",
    ]
    for n in summary.get("notes", []):
        md.append(f"- {n}")
    if zero:
        md.extend(["", f"## 零信号标的（{len(zero)} 只）", "", ", ".join(zero)])
    if not per_stats.empty:
        top, bot = per_stats.head(5), per_stats.tail(5).iloc[::-1]
        md.extend(
            [
                "",
                "## 分票盈亏 Top5 / Bottom5",
                "",
                "| 代码 | 名称 | 笔数 | 胜率% | 均收益% | 盈亏合计(元) |",
                "| :--- | :--- | ---: | ---: | ---: | ---: |",
            ]
        )
        for _, r in top.iterrows():
            md.append(
                f"| {r['code']} | {r['name']} | {r['n']} | {r['win_rate']} | {r['avg_ret']} | {r['sum_pnl']} |"
            )
        md.append("| ... | ... | ... | ... | ... | ... |")
        for _, r in bot.iterrows():
            md.append(
                f"| {r['code']} | {r['name']} | {r['n']} | {r['win_rate']} | {r['avg_ret']} | {r['sum_pnl']} |"
            )
    if filled:
        ordered = sorted(filled, key=lambda t: (t.entry_date, t.code))
        md.extend(
            [
                "",
                "## 信号交易明细（按入场日 · 已成交）",
                "",
                f"共 {len(ordered)} 笔。见 `backtest_trades_{stamp}.csv`。",
                "",
                "| # | 代码 | 名称 | 板块 | 入场日 | 出场日 | 买入 | 有效卖出 | 股数 | 成本 | 盈亏 | 收益% | R0 | R2 | 出场 |",
                "| ---: | :--- | :--- | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :--- |",
            ]
        )
        for i, t in enumerate(ordered, 1):
            ret_s = f"+{t.ret_pct:.2f}" if t.ret_pct > 0 else f"{t.ret_pct:.2f}"
            pnl_s = f"+{t.pnl:.2f}" if t.pnl > 0 else f"{t.pnl:.2f}"
            md.append(
                f"| {i} | {t.code} | {t.name} | {t.sector} | {t.entry_date} | {t.exit_date} | "
                f"{t.entry_price} | {t.exit_price} | {t.shares} | {t.cost:.2f} | "
                f"{pnl_s} | {ret_s} | {'Y' if t.r0_triggered else ''} | {'Y' if t.r2_triggered else ''} | {t.exit_reason} |"
            )
    if skipped:
        md.extend(
            [
                "",
                f"## 跳过信号（{len(skipped)} 笔）",
                "",
                "| 代码 | 名称 | 信号日 | 原因 |",
                "| :--- | :--- | :--- | :--- |",
            ]
        )
        for t in sorted(skipped, key=lambda x: (x.entry_date, x.code)):
            md.append(f"| {t.code} | {t.name} | {t.entry_date} | {t.skip_reason} |")
    (OUT_DIR / f"backtest_report_{stamp}.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"报告已写 {OUT_DIR}")


if __name__ == "__main__":
    main()
