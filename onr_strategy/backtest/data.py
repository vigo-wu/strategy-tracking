# coding: utf-8
"""行情容器：内存 / CSV。分钟线按 bar 时刻截断，禁止用决策后数据。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Protocol, Tuple

import pandas as pd


OHLCV = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class StockMeta:
    symbol: str
    name: str = ""
    list_date: Optional[date] = None
    is_st: bool = False
    sw2: str = ""
    exchange: str = ""


def hhmm_of(ts) -> int:
    t = pd.Timestamp(ts)
    return int(t.hour) * 100 + int(t.minute)


def add_hhmm(df: pd.DataFrame, col: str = "datetime") -> pd.DataFrame:
    out = df.copy()
    out["hhmm"] = out[col].map(hhmm_of)
    return out


def slice_hhmm(
    df: pd.DataFrame,
    start: int,
    end: int,
    *,
    col: str = "datetime",
    end_inclusive: bool = True,
) -> pd.DataFrame:
    if df is None or df.empty:
        return df.iloc[0:0] if df is not None else pd.DataFrame()
    work = df if "hhmm" in df.columns else add_hhmm(df, col)
    if end_inclusive:
        mask = (work["hhmm"] >= start) & (work["hhmm"] <= end)
    else:
        mask = (work["hhmm"] >= start) & (work["hhmm"] < end)
    return work.loc[mask].copy()


def last_at_or_before(df: pd.DataFrame, hhmm: int, col: str = "close") -> Optional[float]:
    if df is None or df.empty:
        return None
    work = df if "hhmm" in df.columns else add_hhmm(df)
    hit = work.loc[work["hhmm"] <= hhmm]
    if hit.empty:
        return None
    val = hit.iloc[-1][col]
    if pd.isna(val):
        return None
    return float(val)


def board_limit_ratio(symbol: str, is_st: bool) -> float:
    if is_st:
        return 0.05
    code = symbol.split(".")[0]
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    return 0.10


def limit_up_price(pre_close: float, symbol: str, is_st: bool) -> float:
    return round(float(pre_close) * (1.0 + board_limit_ratio(symbol, is_st)), 2)


def limit_down_price(pre_close: float, symbol: str, is_st: bool) -> float:
    return round(float(pre_close) * (1.0 - board_limit_ratio(symbol, is_st)), 2)


def is_bj(symbol: str) -> bool:
    return symbol.upper().endswith(".BJ") or symbol.upper().endswith(".BJSE")


class MarketStore(Protocol):
    def trading_days(self) -> List[date]:
        ...

    def symbols(self) -> List[str]:
        ...

    def meta(self, symbol: str) -> StockMeta:
        ...

    def daily(self, symbol: str) -> pd.DataFrame:
        ...

    def minutes(self, symbol: str, day: date) -> pd.DataFrame:
        ...

    def index_minutes(self, symbol: str, day: date) -> pd.DataFrame:
        ...

    def large_buy_ratio(self, symbol: str, day: date) -> Optional[float]:
        ...

    def industry_ret_1445(self, sw2: str, day: date) -> Optional[float]:
        ...

    def industry_keys(self, day: date) -> List[str]:
        ...


@dataclass
class MemoryStore:
    metas: Dict[str, StockMeta]
    daily_map: Dict[str, pd.DataFrame]
    minute_map: Dict[Tuple[str, date], pd.DataFrame]
    index_minute_map: Dict[Tuple[str, date], pd.DataFrame] = field(default_factory=dict)
    large_buy: Dict[Tuple[str, date], float] = field(default_factory=dict)
    industry_ret: Dict[Tuple[str, date], float] = field(default_factory=dict)
    compact_map: Dict[Tuple[str, date], dict] = field(default_factory=dict)
    days: List[date] = field(default_factory=list)

    def trading_days(self) -> List[date]:
        return list(self.days)

    def symbols(self) -> List[str]:
        return sorted(self.metas.keys())

    def meta(self, symbol: str) -> StockMeta:
        return self.metas[symbol]

    def daily(self, symbol: str) -> pd.DataFrame:
        return self.daily_map[symbol]

    def minutes(self, symbol: str, day: date) -> pd.DataFrame:
        return self.minute_map.get((symbol, day), pd.DataFrame())

    def index_minutes(self, symbol: str, day: date) -> pd.DataFrame:
        return self.index_minute_map.get((symbol, day), pd.DataFrame())

    def large_buy_ratio(self, symbol: str, day: date) -> Optional[float]:
        return self.large_buy.get((symbol, day))

    def industry_ret_1445(self, sw2: str, day: date) -> Optional[float]:
        if not sw2:
            return None
        return self.industry_ret.get((sw2, day))

    def industry_keys(self, day: date) -> List[str]:
        return sorted({k[0] for k in self.industry_ret if k[1] == day})

    def compact_intraday(self, symbol: str, day: date) -> Optional[dict]:
        return self.compact_map.get((symbol, day))


def _parse_day(val) -> date:
    return pd.Timestamp(val).date()


def _ensure_daily(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = out["date"].map(_parse_day)
    if "pre_close" not in out.columns:
        out = out.sort_values("date")
        out["pre_close"] = out["close"].shift(1)
    if "suspended" not in out.columns:
        out["suspended"] = 0
    if "float_mkt_cap" not in out.columns:
        out["float_mkt_cap"] = 50e8
    if "amount" not in out.columns:
        out["amount"] = out["close"] * out["volume"]
    return out.sort_values("date").reset_index(drop=True)


def _ensure_minute(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["datetime"] = pd.to_datetime(out["datetime"])
    if "amount" not in out.columns:
        out["amount"] = out["close"] * out["volume"]
    return add_hhmm(out.sort_values("datetime"))


class CsvStore:
    """长表 CSV。schema 见 model.md 回测脚手架节。"""

    def __init__(self, root: str | Path):
        root = Path(root)
        meta_df = pd.read_csv(root / "meta.csv")
        self.metas: Dict[str, StockMeta] = {}
        for _, row in meta_df.iterrows():
            ld = row["list_date"] if "list_date" in row and pd.notna(row["list_date"]) else None
            self.metas[str(row["symbol"])] = StockMeta(
                symbol=str(row["symbol"]),
                name=str(row["name"]) if "name" in row and pd.notna(row.get("name")) else "",
                list_date=_parse_day(ld) if ld is not None else None,
                is_st=bool(row["is_st"]) if "is_st" in row else False,
                sw2=str(row["sw2"]) if "sw2" in row and pd.notna(row.get("sw2")) else "",
                exchange=str(row["exchange"]) if "exchange" in row and pd.notna(row.get("exchange")) else "",
            )
        daily = _ensure_daily(pd.read_csv(root / "daily.csv"))
        self.daily_map = {sym: g.reset_index(drop=True) for sym, g in daily.groupby("symbol")}
        self.minute_map: Dict[Tuple[str, date], pd.DataFrame] = {}
        minute_path = root / "minute.csv"
        if minute_path.exists():
            minute = _ensure_minute(pd.read_csv(minute_path))
            minute["_day"] = minute["datetime"].dt.date
            for (sym, day), g in minute.groupby(["symbol", "_day"]):
                self.minute_map[(str(sym), day)] = g.drop(columns=["_day"]).reset_index(drop=True)
        self.index_minute_map: Dict[Tuple[str, date], pd.DataFrame] = {}
        idx_path = root / "index_minute.csv"
        if idx_path.exists():
            idx = _ensure_minute(pd.read_csv(idx_path))
            idx["_day"] = idx["datetime"].dt.date
            for (sym, day), g in idx.groupby(["symbol", "_day"]):
                self.index_minute_map[(str(sym), day)] = g.drop(columns=["_day"]).reset_index(drop=True)
        self.large_buy: Dict[Tuple[str, date], float] = {}
        lb_path = root / "large_buy.csv"
        if lb_path.exists():
            lb = pd.read_csv(lb_path)
            for _, row in lb.iterrows():
                self.large_buy[(_parse_sym(row["symbol"]), _parse_day(row["date"]))] = float(row["ratio"])
        self.industry_ret: Dict[Tuple[str, date], float] = {}
        ind_path = root / "industry_1445.csv"
        if ind_path.exists():
            ind = pd.read_csv(ind_path)
            for _, row in ind.iterrows():
                self.industry_ret[(str(row["sw2"]), _parse_day(row["date"]))] = float(row["ret"])
        self.compact_map: Dict[Tuple[str, date], dict] = {}
        compact_path = root / "intraday.csv"
        if compact_path.exists():
            compact = pd.read_csv(compact_path)
            for _, row in compact.iterrows():
                self.compact_map[(str(row["symbol"]), _parse_day(row["date"]))] = row.to_dict()
        dayset = set()
        for df in self.daily_map.values():
            dayset.update(df["date"].tolist())
        self.days = sorted(dayset)

    def trading_days(self) -> List[date]:
        return list(self.days)

    def symbols(self) -> List[str]:
        return sorted(self.metas.keys())

    def meta(self, symbol: str) -> StockMeta:
        return self.metas[symbol]

    def daily(self, symbol: str) -> pd.DataFrame:
        return self.daily_map[symbol]

    def minutes(self, symbol: str, day: date) -> pd.DataFrame:
        return self.minute_map.get((symbol, day), pd.DataFrame())

    def index_minutes(self, symbol: str, day: date) -> pd.DataFrame:
        return self.index_minute_map.get((symbol, day), pd.DataFrame())

    def large_buy_ratio(self, symbol: str, day: date) -> Optional[float]:
        return self.large_buy.get((symbol, day))

    def industry_ret_1445(self, sw2: str, day: date) -> Optional[float]:
        if not sw2:
            return None
        return self.industry_ret.get((sw2, day))

    def industry_keys(self, day: date) -> List[str]:
        return sorted({k[0] for k in self.industry_ret if k[1] == day})

    def compact_intraday(self, symbol: str, day: date) -> Optional[dict]:
        return self.compact_map.get((symbol, day))


def _parse_sym(val) -> str:
    return str(val)


def daily_row(store: MarketStore, symbol: str, day: date) -> Optional[pd.Series]:
    df = store.daily(symbol)
    hit = df.loc[df["date"] == day]
    if hit.empty:
        return None
    return hit.iloc[-1]


def daily_history(store: MarketStore, symbol: str, day: date) -> pd.DataFrame:
    df = store.daily(symbol)
    return df.loc[df["date"] < day].copy()


def next_trading_day(days: Iterable[date], day: date) -> Optional[date]:
    seq = list(days)
    try:
        i = seq.index(day)
    except ValueError:
        return None
    if i + 1 >= len(seq):
        return None
    return seq[i + 1]


def trading_age(days: List[date], list_date: Optional[date], day: date) -> Optional[int]:
    """样本窗内的上市交易日数。若 list_date 早于样本首日，视为已过次新期。"""
    if list_date is None or not days:
        return None
    prior = sum(1 for d in days if list_date <= d < day)
    if list_date < days[0]:
        return prior + 252
    return prior


def compact_row(store: MarketStore, symbol: str, day: date) -> Optional[dict]:
    fn = getattr(store, "compact_intraday", None)
    if not callable(fn):
        return None
    return fn(symbol, day)
