# coding: utf-8
"""本地回测用的 QMT Context / passorder / 时间戳替身。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from market_csv import MarketStore, compact_day


def split_stock(stock: str) -> tuple[str, str]:
    s = str(stock or "").strip().upper()
    if "." in s:
        code, market = s.rsplit(".", 1)
        return code, market
    return s, "SH"


def timetag_to_datetime(tag: Any, fmt: str) -> str:
    raw = str(int(tag)) if str(tag).strip().lstrip("-").isdigit() else compact_day(str(tag))
    d = compact_day(raw)
    if len(str(raw)) >= 14 and str(raw).isdigit():
        dt = datetime.strptime(str(raw)[:14], "%Y%m%d%H%M%S")
    elif d:
        dt = datetime.strptime(d, "%Y%m%d").replace(hour=15, minute=0, second=0)
    else:
        dt = datetime.now()
    return dt.strftime(fmt)


def _as_tag(dt: datetime) -> int:
    return int(dt.strftime("%Y%m%d%H%M%S"))


def passorder(*_args: Any, **_kwargs: Any) -> None:
    return None


def download_history_data(*_args: Any, **_kwargs: Any) -> None:
    return None


def _parse_md_call(args: tuple, kwargs: dict) -> dict[str, Any]:
    fields = kwargs.get("fields")
    stock_code = kwargs.get("stock_code")
    period = kwargs.get("period")
    start_time = kwargs.get("start_time", "")
    end_time = kwargs.get("end_time")
    count = kwargs.get("count")
    if args:
        if fields is None and len(args) >= 1:
            fields = args[0]
        if stock_code is None and len(args) >= 2:
            stock_code = args[1]
        if period is None and len(args) >= 3:
            period = args[2]
        if "start_time" not in kwargs and len(args) >= 4:
            start_time = args[3]
        if end_time is None and len(args) >= 5:
            end_time = args[4]
        if count is None and len(args) >= 6:
            count = args[5]
    if isinstance(stock_code, (list, tuple)):
        stocks = [str(x) for x in stock_code]
    elif stock_code:
        stocks = [str(stock_code)]
    else:
        stocks = []
    if fields is None:
        fields = ["open", "high", "low", "close", "volume"]
    try:
        count_i = None if count is None else int(count)
    except (TypeError, ValueError):
        count_i = None
    return {
        "fields": list(fields),
        "stocks": stocks,
        "period": str(period or "1d"),
        "start_time": str(start_time or ""),
        "end_time": str(end_time or ""),
        "count": count_i,
    }


class MockContext:
    def __init__(self, store: MarketStore, walk_tags: list[int], stock: str):
        code, market = split_stock(stock)
        self.stockcode = code
        self.market = market
        self.period = "1d"
        self.do_back_test = True
        self.barpos = 0
        self.accountid = ""
        self.start = ""
        self.end = ""
        self._store = store
        self._walk_tags = list(walk_tags)

    def set_account(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_universe(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def is_last_bar(self) -> bool:
        return False

    def get_bar_timetag(self, barpos: int | None = None) -> int:
        i = self.barpos if barpos is None else int(barpos)
        if i < 0 or i >= len(self._walk_tags):
            return 0
        return int(self._walk_tags[i])

    def get_market_data_ex(self, *args: Any, **kwargs: Any):
        return self._md(*args, **kwargs)

    def get_market_data(self, *args: Any, **kwargs: Any):
        return self._md(*args, **kwargs)

    def _md(self, *args: Any, **kwargs: Any):
        spec = _parse_md_call(args, kwargs)
        stocks = spec["stocks"] or [self.stockcode + "." + self.market]
        out = {}
        for raw in stocks:
            frame = self._store.frame(
                period=spec["period"],
                end_time=spec["end_time"],
                count=spec["count"],
                fields=spec["fields"],
                start_time=spec["start_time"],
                stock=raw,
            )
            out[str(raw)] = frame
        return out


def inject_qmt_globals(ns: dict) -> None:
    ns["passorder"] = passorder
    ns["download_history_data"] = download_history_data
    ns["down_history_data"] = download_history_data
    ns["timetag_to_datetime"] = timetag_to_datetime
