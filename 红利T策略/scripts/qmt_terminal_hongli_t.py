#coding:gbk
"""
HongliT v2.5 for Guojin QMT terminal (model trade).

Main chart: 561580.SH, period=1d
UI: select stock + account, run in LIVE (not simulate) to send orders.

Rules:
  R-A   zero float + lower band + J<=0     -> buy Float A (50000)
  R-B   has A + lower + J<=0 + drop>=2.5%  -> buy Float B (25000) else skip
  R-Sell upper + J>=100                    -> sell ALL float only (keep base)
  No R1

IMPORTANT:
  - Keep this file encoding=GBK, first line #coding:gbk
  - Base position is MANUAL; this script only trades float A/B
  - DRY_RUN=True prints only; set False to passorder
"""
import datetime
import json
import os

import numpy as np

# ===================== user config =====================
DRY_RUN = True
AUTO_BUY_BASE = False

# Fallback when not started from "模型交易" (no account/accountType inject)
ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

FLOAT_A_BUDGET = 50000.0
FLOAT_B_BUDGET = 25000.0
BASE_BUDGET = 200000.0
SPACE_STEP = 0.025

BOLL_N = 20
BOLL_K = 2.0
KDJ_N = 9
LOWER_TOL = 1.002
UPPER_TOL = 0.998

DECISION_START = "143000"
DECISION_END = "145700"

# QMT model runtime has no __file__; use fixed path under terminal python/
STATE_FILE = r"D:\office\国金证券QMT交易端\python\hongli_t_qmt_state.json"
# =======================================================


class _S(object):
    pass


A = _S()


def _lot(price, budget):
    if price is None or price <= 0 or budget <= 0:
        return 0
    return int(budget // (price * 100)) * 100


def _load_state():
    A.float_a = None
    A.float_b = None
    A.base_done = False
    A.acted_day = ""
    A.acted = set()
    if not os.path.isfile(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r") as f:
            raw = json.load(f)
        A.float_a = raw.get("float_a")
        A.float_b = raw.get("float_b")
        A.base_done = bool(raw.get("base_done", False))
        A.acted_day = raw.get("acted_day", "") or ""
        print("HongliT load state", STATE_FILE, A.float_a, A.float_b)
    except Exception as e:
        print("HongliT load state fail", e)


def _save_state():
    payload = {
        "float_a": A.float_a,
        "float_b": A.float_b,
        "base_done": A.base_done,
        "acted_day": A.acted_day,
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2)
    except Exception as e:
        print("HongliT save state fail", e)


def _reset_day(day):
    if A.acted_day != day:
        A.acted_day = day
        A.acted = set()
        _save_state()


def _has_leg(leg):
    return leg is not None and int(leg.get("shares", 0)) >= 100


def _calc_indicators(high, low, close):
    """Return (lower, upper, j, last_close) or None."""
    n = len(close)
    need = max(BOLL_N, KDJ_N) + 2
    if n < need:
        return None
    c = np.asarray(close, dtype=float)
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    # reject padded / flat window (history not ready)
    if np.std(c[-BOLL_N:]) < 1e-8:
        return None
    mid = np.mean(c[-BOLL_N:])
    std = np.std(c[-BOLL_N:])
    lower = mid - BOLL_K * std
    upper = mid + BOLL_K * std

    # KDJ same as run_screener: RSV ewm(com=2)
    rsv = np.zeros(n, dtype=float)
    for i in range(n):
        i0 = max(0, i - KDJ_N + 1)
        hn = np.max(h[i0 : i + 1])
        ln = np.min(l[i0 : i + 1])
        if hn <= ln:
            rsv[i] = 0.0
        else:
            rsv[i] = (c[i] - ln) / (hn - ln) * 100.0
    k = np.zeros(n, dtype=float)
    d = np.zeros(n, dtype=float)
    alpha = 1.0 / 3.0  # ewm com=2 -> alpha=1/(com+1)
    k[0] = rsv[0]
    d[0] = k[0]
    for i in range(1, n):
        k[i] = (1 - alpha) * k[i - 1] + alpha * rsv[i]
        d[i] = (1 - alpha) * d[i - 1] + alpha * k[i]
    j = 3.0 * k[-1] - 2.0 * d[-1]
    return lower, upper, float(j), float(c[-1])


def _bar_end_yyyymmdd(C):
    dt = _bar_datetime(C)
    return dt.strftime("%Y%m%d")


def _diag_once(key, *msg):
    if not hasattr(A, "_diag"):
        A._diag = set()
    if key in A._diag:
        return
    A._diag.add(key)
    print("HongliT diag:", key, " ".join([str(x) for x in msg]))


def _series_from_ex(md, stock, field):
    """Parse get_market_data_ex / get_market_data result into float list."""
    if md is None:
        return None
    obj = None
    # shape1: {code: DataFrame(columns=fields)}
    if isinstance(md, dict) and stock in md:
        df = md[stock]
        if hasattr(df, "columns") and field in getattr(df, "columns", []):
            obj = df[field]
        elif isinstance(df, dict) and field in df:
            obj = df[field]
        elif hasattr(df, "__getitem__"):
            try:
                obj = df[field]
            except Exception:
                pass
    # shape2: {field: DataFrame(columns=codes)} / Series
    if obj is None and isinstance(md, dict) and field in md:
        df = md[field]
        if hasattr(df, "columns"):
            cols = list(df.columns)
            if stock in cols:
                obj = df[stock]
            elif len(cols) == 1:
                obj = df[cols[0]]
            else:
                obj = df
        elif isinstance(df, dict) and stock in df:
            obj = df[stock]
        else:
            obj = df
    if obj is None:
        return None
    try:
        vals = list(np.asarray(obj, dtype=float).reshape(-1))
    except Exception:
        try:
            vals = [float(x) for x in list(obj)]
        except Exception:
            return None
    out = []
    for fv in vals:
        try:
            if fv != fv:  # nan
                continue
            out.append(float(fv))
        except Exception:
            continue
    return out


def _download_hist(stock):
    """Supplement local daily history (QMT builtin name varies)."""
    for fn_name in ("download_history_data", "down_history_data"):
        fn = globals().get(fn_name)
        if callable(fn):
            try:
                fn(stock, "1d", "20220101", "")
                print("HongliT downloaded history via", fn_name)
                return
            except Exception as e:
                print(fn_name, "fail", e)


def _get_ohlc(C, stock, count=120):
    """Fetch daily OHLC; try get_market_data_ex then fallbacks."""
    end = _bar_end_yyyymmdd(C)
    need = max(BOLL_N, KDJ_N) + 2
    md = None
    source = None

    # 1) get_market_data_ex
    try:
        md = C.get_market_data_ex(
            fields=["high", "low", "close"],
            stock_code=[stock],
            period="1d",
            end_time=end,
            count=count,
            dividend_type="front_ratio",
            fill_data=True,
            subscribe=False,
        )
        source = "get_market_data_ex"
    except TypeError:
        try:
            md = C.get_market_data_ex(
                ["high", "low", "close"],
                [stock],
                period="1d",
                start_time="",
                end_time=end,
                count=count,
                dividend_type="front_ratio",
            )
            source = "get_market_data_ex/pos"
        except Exception as e:
            _diag_once("ex_fail", e)
            md = None
    except Exception as e:
        _diag_once("ex_fail", e)
        md = None

    close = _series_from_ex(md, stock, "close") if md is not None else None

    # 2) get_market_data
    if not close or len(close) < need:
        try:
            md2 = C.get_market_data(
                ["high", "low", "close"],
                stock_code=[stock],
                period="1d",
                end_time=end,
                count=count,
                dividend_type="front_ratio",
            )
            source = "get_market_data"
            close = _series_from_ex(md2, stock, "close")
            high = _series_from_ex(md2, stock, "high")
            low = _series_from_ex(md2, stock, "low")
            md = md2
        except Exception as e:
            _diag_once("gmd_fail", e)

    # 3) get_history_data (legacy, still works on some builds)
    if not close or len(close) < need:
        try:
            c_map = C.get_history_data(count, "1d", "close", dividend_type="front_ratio")
            h_map = C.get_history_data(count, "1d", "high", dividend_type="front_ratio")
            l_map = C.get_history_data(count, "1d", "low", dividend_type="front_ratio")
            if c_map and stock in c_map:
                close = [float(x) for x in c_map[stock] if x == x]
                high = [float(x) for x in h_map[stock]] if h_map and stock in h_map else list(close)
                low = [float(x) for x in l_map[stock]] if l_map and stock in l_map else list(close)
                source = "get_history_data"
                md = {"close": close}
        except Exception as e:
            _diag_once("hist_fail", e)

    if not close:
        _diag_once(
            "empty",
            "end=",
            end,
            "barpos=",
            getattr(C, "barpos", None),
            "md_type=",
            type(md),
            "md_keys=",
            list(md.keys())[:8] if isinstance(md, dict) else None,
        )
        return None

    if md is not None and source != "get_history_data":
        high = _series_from_ex(md, stock, "high")
        low = _series_from_ex(md, stock, "low")
    if not high or len(high) != len(close):
        high = list(close)
    if not low or len(low) != len(close):
        low = list(close)

    if len(close) < need:
        _diag_once("short", "n=", len(close), "need=", need, "source=", source, "end=", end)
        return None

    _diag_once(
        "ok",
        "source=",
        source,
        "n=",
        len(close),
        "end=",
        end,
        "last=",
        close[-1],
        "std20=",
        round(float(np.std(close[-BOLL_N:])), 6),
    )
    return high, low, close


def _is_backtest(C):
    return bool(getattr(C, "do_back_test", False))


def _bar_datetime(C):
    """Bar time in backtest; wall clock in live."""
    try:
        tag = C.get_bar_timetag(C.barpos)
        # timetag_to_datetime is QMT builtin when available
        if "timetag_to_datetime" in globals():
            s = timetag_to_datetime(tag, "%Y%m%d%H%M%S")
            return datetime.datetime.strptime(str(s), "%Y%m%d%H%M%S")
        # fallback: ms timestamp
        if tag > 10**12:
            return datetime.datetime.fromtimestamp(tag / 1000.0)
        return datetime.datetime.fromtimestamp(tag)
    except Exception:
        return datetime.datetime.now()


def _available_cash():
    if getattr(A, "is_backtest", False):
        return 10**9
    accs = get_trade_detail_data(A.acct, A.acct_type, "account")
    if not accs:
        print("account not login", A.acct)
        return None
    return float(accs[0].m_dAvailable)


def _can_use_vol(stock):
    if getattr(A, "is_backtest", False) or DRY_RUN:
        # backtest/dry: trust strategy state shares
        return 10**9
    positions = get_trade_detail_data(A.acct, A.acct_type, "position")
    for p in positions:
        code = p.m_strInstrumentID + "." + p.m_strExchangeID
        if code == stock:
            return int(p.m_nCanUseVolume or 0)
    return 0


def _order_buy(C, vol, remark):
    msg = "HongliT BUY %s %s x%d" % (remark, A.stock, vol)
    print(("[DRY] " if DRY_RUN else "") + msg)
    if DRY_RUN:
        return True
    passorder(A.buy_code, 1101, A.acct, A.stock, 14, -1, vol, "HongliT_v25", 1, msg, C)
    A.waiting_list.append(msg)
    return True


def _order_sell(C, vol, remark):
    can = _can_use_vol(A.stock)
    vol = min(int(vol), can)
    if vol < 100:
        print("sell skip, can_use=", can, "want=", vol)
        return False
    msg = "HongliT SELL %s %s x%d" % (remark, A.stock, vol)
    print(("[DRY] " if DRY_RUN else "") + msg)
    if DRY_RUN:
        return True
    passorder(A.sell_code, 1101, A.acct, A.stock, 14, -1, vol, "HongliT_v25", 1, msg, C)
    A.waiting_list.append(msg)
    return True


def init(C):
    # stock from chart; account from 模型交易 UI if present, else config
    A.stock = C.stockcode + "." + C.market
    if "account" in globals() and account:
        A.acct = str(account)
    elif hasattr(C, "accountid") and C.accountid:
        A.acct = str(C.accountid)
    else:
        A.acct = ACCOUNT_ID

    if "accountType" in globals() and accountType:
        A.acct_type = str(accountType)
    else:
        A.acct_type = ACCOUNT_TYPE

    try:
        C.set_account(A.acct)
    except Exception:
        pass

    A.buy_code = 23 if A.acct_type == "STOCK" else 33
    A.sell_code = 24 if A.acct_type == "STOCK" else 34
    A.waiting_list = []
    A.busy = False
    A.is_backtest = _is_backtest(C)
    _download_hist(A.stock)
    _load_state()
    # backtest: start with clean float state so replay is consistent
    if A.is_backtest:
        A.float_a = None
        A.float_b = None
        A.acted_day = ""
        A.acted = set()
        A.ready_logged = False
    else:
        A.ready_logged = True
    C.set_universe([A.stock])
    print(
        "HongliT v2.5 init",
        A.stock,
        A.acct,
        A.acct_type,
        "DRY_RUN=",
        DRY_RUN,
        "BACKTEST=",
        A.is_backtest,
        "STATE=",
        STATE_FILE,
    )


def handlebar(C):
    # live: only latest bar; backtest: every bar (skip inside if OHLC not ready)
    if (not getattr(A, "is_backtest", False)) and (not C.is_last_bar()):
        return
    if A.busy:
        return
    A.busy = True
    try:
        if getattr(A, "is_backtest", False) and (C.barpos % 100 == 0):
            print("HongliT progress barpos=", C.barpos, "time=", _bar_end_yyyymmdd(C))
        _handle(C)
    except Exception as e:
        print("HongliT handlebar error", e)
    finally:
        A.busy = False


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    now = _bar_datetime(C) if bt else datetime.datetime.now()
    now_s = now.strftime("%H%M%S")
    day = now.strftime("%Y%m%d")

    if not bt:
        # live: only near close window
        if now_s < "093000" or now_s > "150000":
            return
        if now_s < DECISION_START or now_s > DECISION_END:
            return
    # backtest daily bar ~= close decision, no wall-clock window

    _reset_day(day)

    if (not bt) and A.waiting_list:
        found = []
        orders = get_trade_detail_data(A.acct, A.acct_type, "order")
        for od in orders:
            if od.m_strRemark in A.waiting_list:
                found.append(od.m_strRemark)
        A.waiting_list = [x for x in A.waiting_list if x not in found]
        if A.waiting_list:
            print("waiting orders", A.waiting_list)
            return

    cash = _available_cash()
    if cash is None:
        return

    ohlc = _get_ohlc(C, A.stock)
    if ohlc is None:
        return
    high, low, close = ohlc
    ind = _calc_indicators(high, low, close)
    if ind is None:
        return
    lower, upper, j, last = ind
    buy_cond = (last <= lower * LOWER_TOL) and (j <= 0)
    sell_cond = (last >= upper * UPPER_TOL) and (j >= 100)
    has_a = _has_leg(A.float_a)
    has_b = _has_leg(A.float_b)
    zero_float = (not has_a) and (not has_b)
    drop_vs_a = None
    if has_a:
        ap = float(A.float_a["price"])
        if ap > 0:
            drop_vs_a = (ap - last) / ap

    interesting = buy_cond or sell_cond or has_a or has_b
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 20 == 0):
        A.ready_logged = True
        print(
            "HongliT",
            day,
            now_s,
            "n=%d close=%.4f lower=%.4f upper=%.4f J=%.2f buy=%s sell=%s A=%s B=%s dropA=%s"
            % (
                len(close),
                last,
                lower,
                upper,
                j,
                buy_cond,
                sell_cond,
                has_a,
                has_b,
                None if drop_vs_a is None else round(drop_vs_a * 100, 2),
            ),
        )

    # optional base once
    if AUTO_BUY_BASE and (not A.base_done) and ("BASE" not in A.acted):
        vol = _lot(last, min(BASE_BUDGET, cash))
        if vol >= 100:
            if _order_buy(C, vol, "BASE"):
                A.base_done = True
                A.acted.add("BASE")
                _save_state()
                return

    # R-Sell first: clear float only
    if sell_cond and (has_a or has_b) and ("SELL" not in A.acted):
        sell_vol = 0
        if has_a:
            sell_vol += int(A.float_a["shares"])
        if has_b:
            sell_vol += int(A.float_b["shares"])
        if _order_sell(C, sell_vol, "RSell"):
            A.float_a = None
            A.float_b = None
            A.acted.add("SELL")
            _save_state()
            print("HongliT R-Sell done, float cleared")
        return

    # R-A
    if buy_cond and zero_float and ("RA" not in A.acted):
        budget = min(FLOAT_A_BUDGET, cash)
        vol = _lot(last, budget)
        if vol < 100:
            print("R-A skip cash/lot")
            A.acted.add("RA")
            _save_state()
            return
        if _order_buy(C, vol, "RA"):
            A.float_a = {"shares": vol, "price": float(last), "cost": round(vol * last, 2)}
            A.acted.add("RA")
            _save_state()
            print("HongliT R-A opened", A.float_a)
        return

    # R-B
    if buy_cond and has_a and (not has_b) and ("RB" not in A.acted):
        ap = float(A.float_a["price"])
        need = ap * (1.0 - SPACE_STEP)
        if last > need + 1e-9:
            print("R-B skip space close=%.4f need<=%.4f" % (last, need))
            return
        budget = min(FLOAT_B_BUDGET, cash)
        vol = _lot(last, budget)
        if vol < 100:
            print("R-B skip cash/lot")
            A.acted.add("RB")
            _save_state()
            return
        if _order_buy(C, vol, "RB"):
            A.float_b = {"shares": vol, "price": float(last), "cost": round(vol * last, 2)}
            A.acted.add("RB")
            _save_state()
            print("HongliT R-B opened", A.float_b)
        return

    if (not buy_cond) and (not sell_cond) and interesting:
        print("HongliT hold float")
