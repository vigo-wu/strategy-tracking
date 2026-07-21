"""
红利资产·绝对防御低回撤波段 · 日度选股（复现 model.md 通达信公式）。
预筛：市值≥300亿、成交额≥1.5亿、非ST；
技术面：TREND_OK + NEAR_LINE + LOW_HS + (CROSS_MA5 OR KDJ_OK)。
中证红利成分与股息率≥4.5% 未自动核验，命中后需人工核对。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import akshare as ak
import baostock as bs
import numpy as np
import pandas as pd
import requests

THEME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = THEME_ROOT.parent
OUT_DIR = THEME_ROOT / "output"
DATA_DIR = REPO_ROOT / "data" / "daily"
OUT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

MIN_CAP_YI = 300.0
MIN_AMOUNT = 1.5e8  # 1.5 亿


@dataclass
class Hit:
    code: str
    name: str
    trade_date: str
    close: float
    open: float
    low: float
    pct_chg: float
    market_cap_yi: float | None
    amount_yi: float | None
    turn_ma3: float
    anchor: str
    stop_line: float
    k: float
    note: str = "市值+流动性预筛；成分/股息待核"


def to_bs_code(code6: str) -> str:
    if code6.startswith(("5", "6", "9")):
        return f"sh.{code6}"
    return f"sz.{code6}"


def fetch_market_cap_yi(code6: str, retries: int = 3) -> float | None:
    if code6.startswith(("688", "689", "60", "90")):
        prefix = "sh"
    else:
        prefix = "sz"
    url = f"https://qt.gtimg.cn/q={prefix}{code6}"
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=8)
            r.encoding = "gbk"
            m = re.search(r'="([^"]+)"', r.text)
            if not m:
                time.sleep(0.3 * (attempt + 1))
                continue
            parts = m.group(1).split("~")
            if len(parts) > 45 and parts[45]:
                return round(float(parts[45]), 2)
        except Exception:
            time.sleep(0.3 * (attempt + 1))
    return None


def sma_tdx(series: pd.Series, n: int, m: int) -> pd.Series:
    """通达信 SMA(X,N,M)。"""
    out = []
    y: float | None = None
    for x in series:
        if pd.isna(x):
            out.append(np.nan)
            continue
        xf = float(x)
        if y is None or pd.isna(y):
            y = xf
        else:
            y = (m * xf + (n - m) * y) / n
        out.append(y)
    return pd.Series(out, index=series.index)


def check_bars(df: pd.DataFrame) -> tuple[bool, dict]:
    if len(df) < 260:
        return False, {"reason": "bars<260"}

    d = df.copy()
    d["ma5"] = d["close"].rolling(5).mean()
    d["ma120"] = d["close"].rolling(120).mean()
    d["ma250"] = d["close"].rolling(250).mean()

    # 换手：优先 turn 列；否则无法判定 LOW_HS
    if "turn" in d.columns:
        d["turn_ma3"] = d["turn"].rolling(3).mean()
    else:
        return False, {"reason": "no_turn"}

    llv = d["low"].rolling(9).min()
    hhv = d["high"].rolling(9).max()
    denom = (hhv - llv).replace(0, np.nan)
    rsv = (d["close"] - llv) / denom * 100
    d["k"] = sma_tdx(rsv, 3, 1)
    d["d"] = sma_tdx(d["k"], 3, 1)

    i = len(d) - 1
    row = d.iloc[i]
    prev = d.iloc[i - 1]
    prev2 = d.iloc[i - 2] if i >= 2 else prev

    trend_ok = bool(row["close"] > row["ma250"] and row["ma250"] >= prev["ma250"])
    near_120 = bool(row["close"] >= row["ma120"] and row["close"] <= row["ma120"] * 1.03)
    near_250 = bool(row["close"] >= row["ma250"] and row["close"] <= row["ma250"] * 1.03)
    near_line = near_120 or near_250
    low_hs = bool(pd.notna(row["turn_ma3"]) and row["turn_ma3"] <= 0.6)
    cross_ma5 = bool(row["close"] > row["ma5"] and prev["close"] <= prev["ma5"])
    kdj_ok = bool(
        pd.notna(row["k"])
        and pd.notna(row["d"])
        and row["k"] < 30
        and prev["k"] <= prev["d"]
        and row["k"] > row["d"]
    )
    right_ok = cross_ma5 or kdj_ok

    ok = trend_ok and near_line and low_hs and right_ok

    # 锚均线：优先半年线支撑；否则年线
    if near_120:
        anchor, stop = "MA120", float(row["ma120"] * 0.975)
    else:
        anchor, stop = "MA250", float(row["ma250"] * 0.975)

    meta = {
        "trend_ok": trend_ok,
        "near_line": near_line,
        "low_hs": low_hs,
        "cross_ma5": cross_ma5,
        "kdj_ok": kdj_ok,
        "close": float(row["close"]),
        "open": float(row["open"]),
        "low": float(row["low"]),
        "turn_ma3": float(row["turn_ma3"]) if pd.notna(row["turn_ma3"]) else None,
        "anchor": anchor,
        "stop_line": stop,
        "k": float(row["k"]) if pd.notna(row["k"]) else None,
        "trade_date": str(row["date"])[:10],
        "pct_chg": float(row["close"] / prev["close"] - 1) * 100,
        "_prev2_unused": float(prev2["close"]),
    }
    return ok, meta


def fetch_hist_bs(code6: str, start: str, end: str) -> pd.DataFrame | None:
    cache = DATA_DIR / f"{code6}.csv"
    rs = bs.query_history_k_data_plus(
        to_bs_code(code6),
        "date,open,high,low,close,volume,amount,turn,tradestatus",
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
        rows,
        columns=["date", "open", "high", "low", "close", "vol", "amount", "turn", "tradestatus"],
    )
    for c in ("open", "high", "low", "close", "vol", "amount", "turn"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["tradestatus"] == "1"].dropna(subset=["close"]).reset_index(drop=True)
    df = df[df["vol"] > 0]
    if len(df):
        # 写入时保留 turn；与旧缓存列可并存
        df.to_csv(cache, index=False)
    return df


def append_today_bar(df: pd.DataFrame, spot_row: pd.Series, today: str) -> pd.DataFrame:
    last_date = str(df.iloc[-1]["date"])[:10]
    if last_date >= today:
        return df
    turn = spot_row.get("换手率", np.nan)
    try:
        turn_v = float(turn) if pd.notna(turn) else np.nan
    except (TypeError, ValueError):
        turn_v = np.nan
    bar = {
        "date": today,
        "open": float(spot_row["今开"]),
        "high": float(spot_row["最高"]),
        "low": float(spot_row["最低"]),
        "close": float(spot_row["最新价"]),
        "vol": float(spot_row["成交量"]),
        "amount": float(spot_row["成交额"]),
        "turn": turn_v,
        "tradestatus": "1",
    }
    return pd.concat([df, pd.DataFrame([bar])], ignore_index=True)


def main() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"报告日: {today}")
    print("拉取新浪快照…")
    spot = ak.stock_zh_a_spot()
    spot["raw"] = spot["代码"].astype(str)
    spot["code"] = spot["raw"].str[-6:]
    spot["name"] = spot["名称"].astype(str)
    spot["amount"] = pd.to_numeric(spot["成交额"], errors="coerce")

    mask = (
        ~spot["raw"].str.startswith("bj")
        & (~spot["name"].str.contains("ST", case=False, na=False))
        & (spot["amount"] >= MIN_AMOUNT)
        & (spot["code"].str.match(r"^(60|00|30)\d{4}$"))
    )
    candidates = spot.loc[mask].copy()
    print(f"成交额预筛（≥1.5亿、非ST、主板/创业）：{len(candidates)} 只")

    print("市值过滤中…")
    keep_idx = []
    cap_map: dict[str, float] = {}
    for n, (idx, row) in enumerate(candidates.iterrows(), 1):
        if n % 40 == 0:
            print(f"  市值 {n}/{len(candidates)}")
        mv = fetch_market_cap_yi(row["code"])
        time.sleep(0.08)
        if mv is not None and mv >= MIN_CAP_YI:
            keep_idx.append(idx)
            cap_map[row["code"]] = mv
    candidates = candidates.loc[keep_idx].copy()
    print(f"市值≥{MIN_CAP_YI:.0f}亿：{len(candidates)} 只")

    end = today
    start = (datetime.now() - timedelta(days=500)).strftime("%Y-%m-%d")
    lg = bs.login()
    print("baostock:", lg.error_code, lg.error_msg)

    hits: list[Hit] = []
    fail = {"hist_fail": 0, "tech_fail": 0}
    try:
        for n, (_, row) in enumerate(candidates.iterrows(), 1):
            code, name = row["code"], row["name"]
            if n % 20 == 0 or n == 1:
                print(f"  日线 {n}/{len(candidates)} … {code} {name}")
            df = fetch_hist_bs(code, start, end)
            if df is None or len(df) < 250:
                fail["hist_fail"] += 1
                continue
            df = append_today_bar(df, row, today)
            if len(df) < 260:
                fail["hist_fail"] += 1
                continue
            ok, meta = check_bars(df)
            if not ok:
                fail["tech_fail"] += 1
                continue
            hits.append(
                Hit(
                    code=code,
                    name=name,
                    trade_date=meta["trade_date"],
                    close=round(meta["close"], 2),
                    open=round(meta["open"], 2),
                    low=round(meta["low"], 2),
                    pct_chg=round(meta["pct_chg"], 2),
                    market_cap_yi=cap_map.get(code),
                    amount_yi=round(float(row["amount"]) / 1e8, 2),
                    turn_ma3=round(meta["turn_ma3"], 3) if meta["turn_ma3"] is not None else 0.0,
                    anchor=meta["anchor"],
                    stop_line=round(meta["stop_line"], 2),
                    k=round(meta["k"], 2) if meta["k"] is not None else 0.0,
                )
            )
            print(
                f"  ✓ HIT {code} {name} 换手3日={meta['turn_ma3']:.2f}% "
                f"{meta['anchor']}止损{meta['stop_line']:.2f}"
            )
    finally:
        bs.logout()

    trade_date = hits[0].trade_date if hits else today
    result = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "prefilter_count": int(len(candidates)),
        "hit_count": len(hits),
        "fail_stats": fail,
        "hits": [asdict(h) for h in hits],
        "note": "未自动校验中证红利成分与股息率≥4.5%、PE分位",
    }
    out = OUT_DIR / f"screener_{trade_date}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame([asdict(h) for h in hits]).to_csv(
        OUT_DIR / f"screener_{trade_date}.csv", index=False, encoding="utf-8-sig"
    )
    print("\n======== 选股结果 ========")
    print(f"交易日 {trade_date} | 命中 {len(hits)} | 市值池 {len(candidates)} | {fail}")
    for h in hits:
        print(f"  {h.code} {h.name} 收{h.close} {h.anchor}止损{h.stop_line} 市值{h.market_cap_yi}亿")
    print(f"已写入 {out}")


if __name__ == "__main__":
    main()
