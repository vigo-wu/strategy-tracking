# coding: utf-8
"""
561580.SH HongliT v2.5 - MiniQMT / xtquant live script.

Rules (see model.md):
  R-A   zero float + lower band + J<=0     -> buy Float A
  R-B   has A + lower + J<=0 + drop>=2.5%  -> buy Float B (else skip)
  R-Sell upper band + J>=100               -> clear all float
  No R1 hard stop.

Docs: https://dict.thinktrader.net/nativeApi/code_examples.html

Setup:
  1. Start MiniQMT and login
  2. Set QMT_USERDATA / ACCOUNT_ID below
  3. Keep DRY_RUN=True until signals look correct
  4. Decision window 14:30-14:57

Encoding:
  - Repo / external python: UTF-8 (# coding: utf-8)
  - Guojin QMT terminal python/: GBK (# coding: gbk) — use scripts/_deploy_qmt_gbk.py
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from xtquant import xtdata, xtconstant
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount

# ============================================================
# 用户配置（部署前必改）
# ============================================================
# 券商端 → ...\userdata_mini ；投研端 → ...\userdata
QMT_USERDATA = r"D:\office\国金证券QMT交易端\userdata"
ACCOUNT_ID = "39953913"  # 例: "2000128"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

STOCK_CODE = "561580.SH"  # 国证央企红利 ETF
STRATEGY_NAME = "HongliT_v25"

# 定额（单位：元；仅浮仓 A/B，无底仓）
FLOAT_A_BUDGET = 50_000.0
FLOAT_B_BUDGET = 25_000.0
SPACE_STEP = 0.025  # Float B 相对 A 最低跌幅

# 指标
BOLL_N, BOLL_K = 20, 2.0
KDJ_N = 9
# 贴近下/上轨容差（与 run_screener 一致）
LOWER_TOL, UPPER_TOL = 1.002, 0.998

# 决策窗口（本地时间）
DECISION_START = (14, 30)
DECISION_END = (14, 57)

# True=只打印信号；False=真实下单
DRY_RUN = True

# 状态落盘（与脚本同目录，兼容放到 QMT\python\ 下运行）
STATE_PATH = Path(__file__).resolve().parent / "hongli_t_qmt_state.json"

# ============================================================
# 运行态
# ============================================================


class _State:
    pass


A = _State()
A.trader = None
A.acc = None
A.last_signal_date = ""  # YYYYMMDD，当日已决策则不再下单
A.acted_today = set()  # {"RA","RB","SELL"}
A.float_a = None  # {"shares":int,"price":float,"cost":float} | None
A.float_b = None
A.busy = False


def log(*args):
    print(dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *args, flush=True)


# ---------- 状态持久化 ----------


def load_state():
    if not STATE_PATH.exists():
        return
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log("读取状态失败", e)
        return
    A.float_a = raw.get("float_a")
    A.float_b = raw.get("float_b")
    A.last_signal_date = raw.get("last_signal_date", "")
    log("已加载状态", STATE_PATH, "A=", A.float_a, "B=", A.float_b)


def save_state():
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stock": STOCK_CODE,
        "version": "v2.5",
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "float_a": A.float_a,
        "float_b": A.float_b,
        "last_signal_date": A.last_signal_date,
    }
    STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 指标 ----------


def calc_boll_kdj(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    mid = out["close"].rolling(BOLL_N).mean()
    std = out["close"].rolling(BOLL_N).std(ddof=0)
    out["boll_mid"] = mid
    out["boll_upper"] = mid + BOLL_K * std
    out["boll_lower"] = mid - BOLL_K * std
    low_n = out["low"].rolling(KDJ_N).min()
    high_n = out["high"].rolling(KDJ_N).max()
    rsv = (out["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    out["k"] = rsv.ewm(com=2, adjust=False).mean()
    out["d"] = out["k"].ewm(com=2, adjust=False).mean()
    out["j"] = 3 * out["k"] - 2 * out["d"]
    return out


def fetch_daily_df(code: str, count: int = 120) -> pd.DataFrame | None:
    """拉取日线；盘中用最新价覆盖当日 close/high/low，便于收盘前决策。"""
    xtdata.download_history_data(code, period="1d", incrementally=True)
    raw = xtdata.get_market_data_ex(
        [], [code], period="1d", count=count, dividend_type="front_ratio"
    )
    if not raw or code not in raw or raw[code] is None or len(raw[code]) < BOLL_N + KDJ_N:
        log("日线不足", code)
        return None
    df = raw[code].copy()
    # 列名兼容
    cols = {c.lower(): c for c in df.columns}
    for need in ("open", "high", "low", "close"):
        if need not in cols and need not in df.columns:
            log("缺列", need, list(df.columns))
            return None
    rename = {}
    for need in ("open", "high", "low", "close", "volume"):
        if need in cols and cols[need] != need:
            rename[cols[need]] = need
    if rename:
        df = df.rename(columns=rename)
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # 用 tick 最新价修正当日 bar（近似收盘决策）
    try:
        tick = xtdata.get_full_tick([code])
        if tick and code in tick:
            last = float(tick[code].get("lastPrice") or 0)
            if last > 0:
                df.iloc[-1, df.columns.get_loc("close")] = last
                hi = float(df.iloc[-1]["high"])
                lo = float(df.iloc[-1]["low"])
                df.iloc[-1, df.columns.get_loc("high")] = max(hi, last)
                df.iloc[-1, df.columns.get_loc("low")] = min(lo, last) if lo > 0 else last
    except Exception as e:
        log("tick 修正跳过", e)

    return calc_boll_kdj(df)


def lot_shares(price: float, budget: float) -> int:
    if price <= 0 or budget <= 0:
        return 0
    return int(budget // (price * 100)) * 100


def in_decision_window(now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now()
    if now.weekday() >= 5:
        return False
    t = (now.hour, now.minute)
    return DECISION_START <= t <= DECISION_END


def reset_day_if_needed(today: str):
    if A.last_signal_date != today:
        A.acted_today = set()
        A.last_signal_date = today
        save_state()


# ---------- 交易 ----------


class MyXtQuantTraderCallback(XtQuantTraderCallback):
    def on_disconnected(self):
        log("连接断开回调")

    def on_stock_order(self, order):
        log("委托回调 备注=", getattr(order, "order_remark", ""), "状态=", getattr(order, "order_status", ""))

    def on_stock_trade(self, trade):
        log(
            "成交回调",
            getattr(trade, "order_remark", ""),
            "方向=",
            getattr(trade, "offset_flag", ""),
            "价=",
            getattr(trade, "traded_price", ""),
            "量=",
            getattr(trade, "traded_volume", ""),
        )

    def on_order_error(self, order_error):
        log("委托报错", getattr(order_error, "order_remark", ""), getattr(order_error, "error_msg", ""))

    def on_cancel_error(self, cancel_error):
        log("撤单失败", cancel_error)

    def on_order_stock_async_response(self, response):
        log("异步委托回调 备注=", getattr(response, "order_remark", ""), "seq=", getattr(response, "seq", ""))

    def on_cancel_order_stock_async_response(self, response):
        log("异步撤单回调", response)

    def on_account_status(self, status):
        log("账号状态", status)


def query_cash() -> float:
    info = A.trader.query_stock_asset(A.acc)
    if info is None:
        return 0.0
    return float(getattr(info, "m_dCash", 0) or 0)


def query_position(code: str) -> tuple[int, int]:
    """返回 (总量, 可用量)。"""
    positions = A.trader.query_stock_positions(A.acc) or []
    for p in positions:
        if getattr(p, "stock_code", "") == code:
            return int(p.m_nVolume or 0), int(p.m_nCanUseVolume or 0)
    return 0, 0


def last_price(code: str) -> float:
    tick = xtdata.get_full_tick([code])
    if not tick or code not in tick:
        return 0.0
    return float(tick[code].get("lastPrice") or 0)


def place_buy(code: str, shares: int, remark: str) -> bool:
    if shares < 100:
        log("买入量不足1手", shares)
        return False
    price = last_price(code)
    if price <= 0:
        log("无最新价，取消买入")
        return False
    log(f"{'[DRY] ' if DRY_RUN else ''}买入 {code} {shares}股 @约{price} 备注={remark}")
    if DRY_RUN:
        return True
    A.trader.order_stock_async(
        A.acc,
        code,
        xtconstant.STOCK_BUY,
        shares,
        xtconstant.FIX_PRICE,
        price,
        STRATEGY_NAME,
        remark,
    )
    return True


def place_sell(code: str, shares: int, remark: str) -> bool:
    if shares < 100:
        log("卖出量不足1手", shares)
        return False
    _, can_use = query_position(code)
    vol = min(shares, can_use)
    if vol < 100:
        log("可用仓不足", can_use, "目标", shares)
        return False
    log(f"{'[DRY] ' if DRY_RUN else ''}卖出 {code} {vol}股 备注={remark}")
    if DRY_RUN:
        return True
    A.trader.order_stock_async(
        A.acc,
        code,
        xtconstant.STOCK_SELL,
        vol,
        xtconstant.LATEST_PRICE,
        -1,
        STRATEGY_NAME,
        remark,
    )
    return True


# ---------- 信号判定与执行 ----------


def evaluate_and_trade():
    if A.busy:
        return
    now = dt.datetime.now()
    if not in_decision_window(now):
        return
    today = now.strftime("%Y%m%d")
    reset_day_if_needed(today)

    A.busy = True
    try:
        df = fetch_daily_df(STOCK_CODE)
        if df is None:
            return
        last = df.iloc[-1]
        if pd.isna(last.get("boll_lower")) or pd.isna(last.get("j")):
            log("指标未就绪")
            return
        close = float(last["close"])
        lower = float(last["boll_lower"])
        upper = float(last["boll_upper"])
        j = float(last["j"])
        buy_cond = close <= lower * LOWER_TOL and j <= 0
        sell_cond = close >= upper * UPPER_TOL and j >= 100

        has_a = A.float_a is not None and int(A.float_a.get("shares", 0)) >= 100
        has_b = A.float_b is not None and int(A.float_b.get("shares", 0)) >= 100
        zero_float = not has_a and not has_b

        drop_vs_a = None
        if has_a:
            ap = float(A.float_a["price"])
            drop_vs_a = (ap - close) / ap if ap > 0 else None

        log(
            f"决策 close={close:.4f} 下={lower:.4f} 上={upper:.4f} J={j:.2f} "
            f"buy={buy_cond} sell={sell_cond} A={has_a} B={has_b} "
            f"相对A跌幅={None if drop_vs_a is None else round(drop_vs_a * 100, 2)}%"
        )

        # --- R高抛：优先 ---
        if sell_cond and (has_a or has_b) and "SELL" not in A.acted_today:
            sell_sh = 0
            if has_a:
                sell_sh += int(A.float_a["shares"])
            if has_b:
                sell_sh += int(A.float_b["shares"])
            if place_sell(STOCK_CODE, sell_sh, "R高抛"):
                A.float_a = None
                A.float_b = None
                A.acted_today.add("SELL")
                save_state()
                log("R高抛完成，浮仓清空")
            return

        # --- R-A ---
        if buy_cond and zero_float and "RA" not in A.acted_today:
            price = close
            cash = query_cash()
            budget = min(FLOAT_A_BUDGET, cash)
            sh = lot_shares(price, budget)
            if sh <= 0:
                log("R-A 跳过：现金不足/不足1手")
                A.acted_today.add("RA")
                save_state()
                return
            if place_buy(STOCK_CODE, sh, "RA"):
                A.float_a = {"shares": sh, "price": price, "cost": round(sh * price, 2)}
                A.acted_today.add("RA")
                save_state()
                log("R-A 开仓", A.float_a)
            return

        # --- R-B ---
        if buy_cond and has_a and not has_b and "RB" not in A.acted_today:
            ap = float(A.float_a["price"])
            need = ap * (1.0 - SPACE_STEP)
            if close > need + 1e-9:
                log(f"R-B 空间不足：close={close:.4f} 需<={need:.4f}（A价{ap:.4f}×0.975），跳过等跌透")
                # 不记 acted，同日若继续下跌跌透仍可开 B
                return
            price = close
            cash = query_cash()
            budget = min(FLOAT_B_BUDGET, cash)
            sh = lot_shares(price, budget)
            if sh <= 0:
                log("R-B 跳过：现金不足/不足1手")
                A.acted_today.add("RB")
                save_state()
                return
            if place_buy(STOCK_CODE, sh, "RB"):
                A.float_b = {"shares": sh, "price": price, "cost": round(sh * price, 2)}
                A.acted_today.add("RB")
                save_state()
                log("R-B 开仓", A.float_b)
            return

        if not buy_cond and not sell_cond:
            log("观望（无 R-A/R-B/R高抛）")
    except Exception:
        log("evaluate 异常\n", traceback.format_exc())
    finally:
        A.busy = False


def on_quote(data):
    """日线/分钟订阅回调：进入决策窗才评估。"""
    try:
        evaluate_and_trade()
    except Exception:
        log("回调异常\n", traceback.format_exc())


def connect_trader() -> XtQuantTrader:
    if not os.path.isdir(QMT_USERDATA):
        raise FileNotFoundError(
            f"QMT userdata 路径不存在: {QMT_USERDATA}\n"
            "请改为券商端 userdata_mini 或投研端 userdata 目录"
        )
    if ACCOUNT_ID.startswith("填入"):
        raise ValueError("请先在脚本顶部设置 ACCOUNT_ID")

    session_id = int(time.time())
    trader = XtQuantTrader(QMT_USERDATA, session_id)
    trader.register_callback(MyXtQuantTraderCallback())
    trader.start()
    rc = trader.connect()
    log("交易连接结果(0=成功)", rc)
    if rc != 0:
        raise RuntimeError(f"XtQuantTrader.connect 失败: {rc}")
    acc = StockAccount(ACCOUNT_ID, ACCOUNT_TYPE)
    sub = trader.subscribe(acc)
    log("账号订阅结果(0=成功)", sub)
    A.trader = trader
    A.acc = acc
    return trader


def print_account_snapshot():
    cash = query_cash()
    total, can = query_position(STOCK_CODE)
    log(f"账号 {ACCOUNT_ID} 可用资金={cash:.2f} {STOCK_CODE} 总量={total} 可用={can}")
    log(f"DRY_RUN={DRY_RUN} 决策窗={DECISION_START}-{DECISION_END}")


def main():
    log("HongliT v2.5 QMT 脚本启动", STOCK_CODE)
    load_state()
    trader = connect_trader()
    print_account_snapshot()

    # 先补日线，再订阅（参考官方：download → subscribe → run）
    xtdata.download_history_data(STOCK_CODE, period="1d", incrementally=True)
    xtdata.subscribe_quote(STOCK_CODE, period="1m", count=-1, callback=on_quote)
    log("已订阅 1m，等待决策窗口内回调…（Ctrl+C 结束）")

    # 启动时若已在窗口内，立即评估一次
    if in_decision_window():
        evaluate_and_trade()

    trader.run_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("用户中断，退出")
        sys.exit(0)
    except Exception:
        log("启动失败\n", traceback.format_exc())
        sys.exit(1)
