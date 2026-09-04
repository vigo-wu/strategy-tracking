# coding: utf-8
"""组合 BOOK 回放：多票 universe 扫池 + 合并明细 + 按票 KPI 归因。"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze import (  # noqa: E402
    DEFAULT_CSV_ROOT,
    DEFAULT_DIVIDEND_TYPE,
    analyze_detail,
    daily_csv_for_stock,
    load_detail_raw,
    parse_budget_from_log,
    resolve_typed_dir,
    sibling_log_path,
)
from market_csv import walk_days  # noqa: E402
from mock_qmt import BookMockContext, _as_tag  # noqa: E402
from run import (  # noqa: E402
    THEME,
    _exec_bundle,
    _patch_fast_ohlcv,
    _patch_quiet_status,
    apply_config_overrides,
    get_market_store,
    install_config_overrides,
)
from book_pool_patch import install_book_pool_patch  # noqa: E402
from compound_wallet import (  # noqa: E402
    install_compound_patch,
    make_wallet,
    read_wallet_end,
)
from trades_csv import CombinedTradeLedger, trades_csv_path, wrap_fill_hooks  # noqa: E402

MA_TYPES = ("SMA", "EMA")


def _norm_detail_stock(code: str) -> str:
    raw = str(code or "").strip().upper()
    if not raw or raw.lower() == "NAN":
        return ""
    if "." in raw:
        num, mkt = raw.rsplit(".", 1)
        num = num.zfill(6) if num.isdigit() else num
        return "%s.%s" % (num, mkt)
    num = raw.zfill(6) if raw.isdigit() else raw
    mkt = "SH" if num.startswith("6") else "SZ"
    return "%s.%s" % (num, mkt)


def book_stocks_hash(book_stocks: Mapping[str, Any]) -> str:
    items = []
    for code in sorted(book_stocks.keys()):
        cfg = book_stocks[code]
        if isinstance(cfg, dict):
            ma = str(cfg.get("ma_type") or "").upper()
            div = str(cfg.get("dividend_type") or "").lower()
        else:
            ma = str(cfg or "").upper()
            div = ""
        items.append([str(code).upper(), ma, div])
    raw = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]


def normalize_book_stocks(raw: Mapping[str, Any] | None) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not raw:
        return out
    for code, cfg in raw.items():
        stock = str(code or "").strip().upper()
        if not stock:
            continue
        if isinstance(cfg, dict):
            ma = str(cfg.get("ma_type") or "EMA").strip().upper()
            div = str(cfg.get("dividend_type") or DEFAULT_DIVIDEND_TYPE).strip().lower()
        else:
            ma = str(cfg or "EMA").strip().upper()
            div = DEFAULT_DIVIDEND_TYPE
        if ma not in MA_TYPES:
            ma = "EMA"
        out[stock] = {"ma_type": ma, "dividend_type": div}
    return out


def book_log_name(*, kind: str, year: str, tag: str, end: str = "") -> str:
    y = str(year or "").strip()
    t = str(tag or "").strip()
    if kind == "score":
        return "local_bt_book_score_%s_u%s.txt" % (y, t)
    if kind == "fixed":
        e = str(end or y).strip()
        return "local_bt_book_fixed_%s_%s_k%s.txt" % (y, e, t)
    return "local_bt_book_hold_%s_k%s.txt" % (y, t)


def load_stores_for_book(
    book_stocks: Mapping[str, Any],
    csv_root: str | Path,
) -> tuple[dict[str, Any], list[str]]:
    from analyze import (  # noqa: WPS433
        csv_source_dividend_type,
        load_divid_factors_json,
        uses_pit_front,
    )

    stores: dict[str, Any] = {}
    errors: list[str] = []
    factors_by_stock: dict[str, dict] = {}
    root = Path(csv_root)
    norm = normalize_book_stocks(book_stocks)
    for stock, cfg in norm.items():
        div = str(cfg.get("dividend_type") or DEFAULT_DIVIDEND_TYPE)
        data_div = csv_source_dividend_type(div)
        path = daily_csv_for_stock(resolve_typed_dir(root, data_div), stock)
        if path is None or not Path(path).is_file():
            errors.append("%s 缺 CSV (%s→%s)" % (stock, div, data_div))
            continue
        try:
            if uses_pit_front(div):
                factors_by_stock[stock] = load_divid_factors_json(root, stock)
            stores[stock] = get_market_store(path, stock=stock)
        except Exception as e:
            errors.append("%s 加载失败: %s" % (stock, e))
    return stores, errors, factors_by_stock


def attribute_portfolio_kpi(
    detail_path: str | Path,
    budget: float | None = None,
    log_path: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    """组合明细 → {stock: kpi}，字段对齐 kpi_from_detail。"""
    from stock_select import kpi_from_detail  # noqa: WPS433

    path = Path(detail_path)
    if not path.is_file():
        return {}
    log = Path(log_path) if log_path else path.with_name(path.stem.replace("_操作明细", "") + ".txt")
    if not log.is_file():
        log = None
    bud = float(budget) if budget is not None else parse_budget_from_log(log, default=100000.0)
    try:
        df = load_detail_raw(path)
    except Exception:
        return {}
    if df.empty or "代码" not in df.columns:
        return {}
    codes = df["代码"].astype(str).str.strip().unique()
    out: dict[str, dict[str, Any]] = {}
    for code in codes:
        stock = _norm_detail_stock(code)
        if not stock:
            continue
        sub = df[df["代码"].astype(str).str.strip() == str(code).strip()]
        if sub.empty:
            continue
        tmp = path.parent / ("_attr_%s_%s.csv" % (path.stem, stock.replace(".", "_")))
        try:
            sub = sub.copy()
            sub["代码"] = stock.split(".", 1)[0]
            sub.to_csv(tmp, index=False, encoding="gbk")
            out[stock] = kpi_from_detail(tmp, log, stock)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
    return out


def run_book_backtest(
    book_stocks: Mapping[str, Any],
    start: str,
    end: str,
    csv_root: str | Path,
    out_dir: str | Path | None = None,
    *,
    log_name: str = "",
    quiet: bool = True,
    overrides: Mapping[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """组合 universe 回放 → (log_path, meta)。"""
    norm = normalize_book_stocks(book_stocks)
    if not norm:
        raise ValueError("BOOK_STOCKS 为空")
    stores, load_err, factors_by_stock = load_stores_for_book(norm, csv_root)
    if not stores:
        raise ValueError("无可用 CSV: %s" % ("; ".join(load_err) or "空池"))
    chart = sorted(stores.keys())[0]
    primary = stores[chart]
    walk = walk_days(primary.bars, start=start, end=end)
    if not walk:
        raise ValueError("walk 区间无 K 线 start=%s end=%s" % (start, end))
    tags = [_as_tag(b.dt) for b in walk]
    ctx = BookMockContext(stores, tags, chart)
    ctx.start = start or walk[0].day
    ctx.end = end or walk[-1].day
    ctx.barpos = 0
    if factors_by_stock:
        ctx.divid_factors_by_stock = factors_by_stock
        # 任一票 PIT → 指纹；ex_rights 按票 logical div + 取数时置 _pit_front_active
        any_pit = any(
            str((norm.get(s) or {}).get("dividend_type") or "").lower()
            in ("front", "front_ratio")
            for s in stores
        )
    else:
        any_pit = False

    dest = Path(out_dir) if out_dir else THEME / "report"
    dest.mkdir(parents=True, exist_ok=True)
    fname = str(log_name or "").strip()
    if not fname:
        h = book_stocks_hash(norm)
        y = str(start or walk[0].day)[:4]
        fname = book_log_name(kind="hold", year=y, tag=h)
    log_path = dest / fname

    merged_overrides: dict[str, Any] = dict(overrides or {})
    merged_overrides["BOOK_STOCKS"] = dict(norm)
    budget = float(merged_overrides.get("TRADE_BUDGET") or 100000.0)

    ns = _exec_bundle()
    _patch_fast_ohlcv(ns)
    install_config_overrides(ns, merged_overrides)
    if quiet:
        _patch_quiet_status(ns)

    wallet = make_wallet(ns, merged_overrides, budget)
    install_book_pool_patch(ns)
    if wallet is not None:
        install_compound_patch(ns, wallet)
    ledger = CombinedTradeLedger(lambda: str(getattr(ns.get("A"), "stock", "") or ""))
    wrap_fill_hooks(ns, ledger, wallet)
    wallet_start = float(wallet.cash) if wallet is not None else budget

    banner = (
        "local_bt_book n=%s walk=%s %s chart=%s budget=%s pit=%s"
        % (len(norm), walk[0].day, walk[-1].day, chart, budget, "1" if any_pit else "0")
    )
    if wallet is not None:
        banner += " compound=1 wallet_start=%.2f" % wallet_start
    log_f = open(log_path, "w", encoding="utf-8", newline="\n")
    log_f.write(banner + "\n")
    if load_err:
        log_f.write("WARN skip: %s\n" % "; ".join(load_err))

    old_out, old_err = sys.stdout, sys.stderr
    if quiet:
        from run import _QuietFile  # noqa: WPS433

        sink = _QuietFile(log_f)
        sys.stdout = sink
        sys.stderr = sink
    try:
        ns["init"](ctx)
        apply_config_overrides(ns, merged_overrides)
        a = ns["A"]
        a.watch = list(stores.keys())
        a.chart_stock = chart
        a.stock = chart
        handle_uni = ns.get("_handle_universe")
        if not callable(handle_uni):
            raise RuntimeError("_handle_universe 不可用")
        for i, _bar in enumerate(walk):
            ctx.barpos = i
            handle_uni(ctx)
    finally:
        if quiet:
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            except Exception:
                pass
            sys.stdout, sys.stderr = old_out, old_err
        if wallet is not None:
            wallet_end = read_wallet_end(ns, wallet)
            log_f.write("wallet_end=%.2f\n" % float(wallet_end))
        log_f.close()

    trades_path = trades_csv_path(log_path)
    ledger.write(trades_path)
    wallet_end_val = read_wallet_end(ns, wallet) if wallet is not None else None
    meta = {
        "log_path": str(log_path),
        "trades_path": str(trades_path),
        "budget": budget,
        "n_stocks": len(stores),
        "skipped": load_err,
        "walk_start": walk[0].day,
        "walk_end": walk[-1].day,
        "n_bars": len(walk),
        "compound": wallet is not None,
        "wallet_cash_start": wallet_start if wallet is not None else None,
        "wallet_cash_end": wallet_end_val,
    }
    return log_path, meta


def analyze_book_detail(
    detail_path: str | Path,
    budget: float = 100000.0,
    log_path: str | Path | None = None,
    csv_root: str | Path | None = None,
    dividend_type: str = "",
) -> dict[str, Any]:
    """组合明细 → 组合级 analyze + 按票归因。"""
    path = Path(detail_path)
    bud = float(budget)
    log = Path(log_path) if log_path else sibling_log_path(path)
    if log and log.is_file():
        bud = parse_budget_from_log(log, default=bud)
    combo = analyze_detail(
        path,
        budget=bud,
        log_path=log,
        csv_root=csv_root if csv_root is not None else DEFAULT_CSV_ROOT,
        dividend_type=dividend_type,
        hold_metrics=False,
    )
    per_stock = attribute_portfolio_kpi(path, budget=bud, log_path=log)
    combo["per_stock"] = per_stock
    combo["sum_pnl"] = float((combo.get("stats") or {}).get("sum_pnl") or 0.0)
    return combo
