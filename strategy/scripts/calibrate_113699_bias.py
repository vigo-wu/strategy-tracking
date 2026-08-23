# -*- coding: utf-8 -*-
"""金25转债 113699.SH 分时 VWAP 乖离分位校准。数据源：新浪分钟 K（无 1 分钟，用 5/15/30/60 分钟 + 日线）。"""
from __future__ import annotations

import json
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

SYMBOL = "sh113699"
LISTING = "2025-10-27"
OUT_JSON = Path(__file__).resolve().parents[1] / "report" / "113699_bias_calib.json"

UA = {"User-Agent": "Mozilla/5.0"}


def sina_kline(scale: int, datalen: int = 1023) -> pd.DataFrame:
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={SYMBOL}&scale={scale}&ma=no&datalen={datalen}"
    )
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8")
    if not raw or raw == "null":
        return pd.DataFrame()
    rows = json.loads(raw)
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["day"])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["close", "volume"]).sort_values("dt").reset_index(drop=True)
    df["date"] = df["dt"].dt.strftime("%Y-%m-%d")
    df["hm"] = df["dt"].dt.strftime("%H:%M")
    df["typ"] = (df["high"] + df["low"] + df["close"]) / 3.0
    df["amt"] = df["typ"] * df["volume"]
    return df


def add_vwap_bias(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for _, g in df.groupby("date", sort=True):
        g = g.copy()
        cum_amt = g["amt"].cumsum()
        cum_vol = g["volume"].cumsum()
        g["vwap"] = np.where(cum_vol > 0, cum_amt / cum_vol, np.nan)
        g["bias"] = (g["close"] - g["vwap"]) / g["vwap"]
        g["bias_low"] = (g["low"] - g["vwap"]) / g["vwap"]
        g["bias_high"] = (g["high"] - g["vwap"]) / g["vwap"]
        g["bar_i"] = np.arange(len(g))
        out.append(g)
    return pd.concat(out, ignore_index=True)


def skip_open(df: pd.DataFrame, scale: int) -> pd.DataFrame:
    """对齐 model：09:30-09:35、13:00-13:05 不决策。"""
    if scale >= 60:
        return df[df["hm"] != "10:30"].copy()
    drop_hm = {"09:35"}
    if scale <= 5:
        drop_hm.add("13:05")
    return df[~df["hm"].isin(drop_hm)].copy()


def pct_map(x: np.ndarray, qs=None) -> dict:
    qs = qs or (1, 5, 10, 25, 50, 75, 90, 95, 99)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return {}
    p = np.percentile(x, qs)
    return {f"p{q}": float(v) for q, v in zip(qs, p)}


def hit_bar(x: np.ndarray, thr: float, side: str) -> float:
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return float("nan")
    if side == "le":
        return float(np.mean(x <= thr))
    return float(np.mean(x >= thr))


def daily_hits(df: pd.DataFrame) -> dict:
    rows = []
    for day, g in df.groupby("date"):
        rows.append(
            {
                "date": day,
                "n": int(len(g)),
                "min_bias": float(g["bias"].min()),
                "max_bias": float(g["bias"].max()),
                "min_low": float(g["bias_low"].min()),
                "max_high": float(g["bias_high"].max()),
                "eod_bias": float(g["bias"].iloc[-1]),
                "ret": float(g["close"].iloc[-1] / g["open"].iloc[0] - 1.0),
            }
        )
    d = pd.DataFrame(rows)
    eod_abs = d["eod_bias"].abs()
    med = float(eod_abs.median()) if len(d) else float("nan")
    trend = (eod_abs > max(0.02, 2 * med)) if len(d) else pd.Series(dtype=bool)
    thr_buy = [-0.012, -0.018, -0.025, -0.035, -0.045]
    thr_sell = [0.012, 0.025, 0.035, 0.045]
    out = {
        "n_days": int(len(d)),
        "median_abs_eod_bias": med,
        "trend_day_frac": float(trend.mean()) if len(d) else float("nan"),
        "day_min_bias": pct_map(d["min_bias"].to_numpy()),
        "day_max_bias": pct_map(d["max_bias"].to_numpy()),
        "day_hit_buy_close": {str(t): float(np.mean(d["min_bias"] <= t)) for t in thr_buy},
        "day_hit_sell_close": {str(t): float(np.mean(d["max_bias"] >= t)) for t in thr_sell},
        "day_hit_buy_low": {str(t): float(np.mean(d["min_low"] <= t)) for t in thr_buy},
        "day_hit_sell_high": {str(t): float(np.mean(d["max_high"] >= t)) for t in thr_sell},
    }
    return out


def summarize(df: pd.DataFrame, scale: int, skipped: bool) -> dict:
    x = df["bias"].to_numpy()
    xl = df["bias_low"].to_numpy()
    xh = df["bias_high"].to_numpy()
    thr_buy = [-0.012, -0.018, -0.025, -0.035, -0.045]
    thr_sell = [0.012, 0.025, 0.035, 0.045]
    return {
        "scale_min": scale,
        "skip_open": skipped,
        "n_bars": int(len(df)),
        "start": str(df["dt"].min()),
        "end": str(df["dt"].max()),
        "close_bias": pct_map(x),
        "low_bias": pct_map(xl),
        "high_bias": pct_map(xh),
        "bar_hit_buy_close": {str(t): hit_bar(x, t, "le") for t in thr_buy},
        "bar_hit_sell_close": {str(t): hit_bar(x, t, "ge") for t in thr_sell},
        "bar_hit_buy_low": {str(t): hit_bar(xl, t, "le") for t in thr_buy},
        "bar_hit_sell_high": {str(t): hit_bar(xh, t, "ge") for t in thr_sell},
        "daily": daily_hits(df),
    }


def pick_levels(s5: dict, s60: dict) -> dict:
    """
    不以 5m p5 直接当 L1（近月日触发率偏高）。
    L1 对齐上市以来 60m「约 10% 交易日触及」的 -1.8%；
    原 -2.5% 降为 L2；+3.5% 几乎不出现，高抛改 60m p95 ≈ +1.5%。
    """
    p5 = s5["close_bias"]
    p60 = s60["close_bias"]
    return {
        "BIAS_L1": -0.018,
        "BIAS_L2": -0.025,
        "BIAS_FADE": 0.015,
        "STOP_LOSS": 0.03,
        "legacy_L1": -0.025,
        "legacy_fade": 0.035,
        "p5_5m": p5.get("p5"),
        "p10_5m": p5.get("p10"),
        "p90_5m": p5.get("p90"),
        "p95_5m": p5.get("p95"),
        "p5_60m": p60.get("p5"),
        "p95_60m": p60.get("p95"),
        "day_hit_m18_60m": s60["daily"]["day_hit_buy_close"].get("-0.018"),
        "day_hit_m25_5m": s5["daily"]["day_hit_buy_close"].get("-0.025"),
        "day_hit_m25_60m": s60["daily"]["day_hit_buy_close"].get("-0.025"),
        "day_hit_p35_60m": s60["daily"]["day_hit_sell_close"].get("0.035"),
        "notes": [
            "公开源没有该债 1 分钟历史；5 分钟仅近 22 个交易日，60 分钟覆盖上市以来",
            "VWAP 用 typical price * volume 近似成交额",
            "-2.5%/+3.5% 作为 L1/高抛过深，+3.5% 收盘乖离几乎从未出现",
        ],
    }


def main():
    payload = {
        "symbol": "113699.SH",
        "name": "金25转债",
        "listing": LISTING,
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "sina CN_MarketData.getKLineData；无逐笔、无 1 分钟；VWAP=累计 typical*volume",
        "windows": {},
        "recommend": {},
    }
    scales = {5: 1023, 15: 1023, 30: 1023, 60: 1023, 240: 400}
    frames = {}
    for sc, n in scales.items():
        df = sina_kline(sc, n)
        if df.empty:
            continue
        df = df[df["date"] >= LISTING]
        df = add_vwap_bias(df)
        frames[sc] = df
        payload["windows"][f"m{sc}_all"] = summarize(df, sc, False)
        sk = skip_open(df, sc)
        payload["windows"][f"m{sc}_skip_open"] = summarize(sk, sc, True)

    rec = pick_levels(
        payload["windows"]["m5_skip_open"],
        payload["windows"]["m60_skip_open"],
    )
    # 若 5m 窗口太短，用 60m p5/p95 折中，并注明
    rec["rule"] = (
        "L1=-1.8%（上市以来 60m 约 10% 交易日触及）；"
        "L2=-2.5%（原 L1，约 3% 交易日）；"
        "高抛=+1.5%（60m p95）；停用 +3.5%。"
    )
    payload["recommend"] = rec
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT_JSON)
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    for k in ("m5_skip_open", "m15_skip_open", "m60_skip_open", "m240_all"):
        w = payload["windows"].get(k) or {}
        print("---", k, "n", w.get("n_bars"), w.get("start"), "->", w.get("end"))
        print(" close", {a: round(b, 4) for a, b in (w.get("close_bias") or {}).items() if a in ("p5", "p10", "p50", "p90", "p95")})
        print(" day_buy", (w.get("daily") or {}).get("day_hit_buy_close"))
        print(" day_sell", (w.get("daily") or {}).get("day_hit_sell_close"))


if __name__ == "__main__":
    main()
