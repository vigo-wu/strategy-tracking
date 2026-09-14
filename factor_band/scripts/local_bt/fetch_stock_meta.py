# coding: utf-8
"""拉取全市场 A 股名单，写成 stock_meta.json（code -> [名称, 品种, 行业]）。

依赖: akshare
用法（在本目录或任意 cwd）:
  python fetch_stock_meta.py
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import akshare as ak

OUT = Path(__file__).with_name("stock_meta.json")


def _norm_name(raw: object) -> str:
    s = unicodedata.normalize("NFKC", str(raw or "")).strip()
    s = re.sub(r"\s+", "", s)
    return s


def _norm_industry(raw: object) -> str:
    s = str(raw or "").strip()
    if not s or s.lower() in {"nan", "none"}:
        return "其它"
    # 深交所/北交所常见「J 金融业」→「金融业」
    m = re.match(r"^[A-Z]\s+(.+)$", s)
    if m:
        s = m.group(1).strip()
    return s or "其它"


def _load_existing() -> dict[str, list]:
    if not OUT.is_file():
        return {}
    with OUT.open(encoding="utf-8") as f:
        return json.load(f)


def _industry_from_sz() -> dict[str, str]:
    df = ak.stock_info_sz_name_code(symbol="A股列表")
    code_col = "A股代码" if "A股代码" in df.columns else df.columns[1]
    ind_col = "所属行业" if "所属行业" in df.columns else df.columns[-1]
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        code = str(row[code_col]).strip().zfill(6)
        out[code] = _norm_industry(row[ind_col])
    return out


def _industry_from_bj() -> dict[str, str]:
    if not hasattr(ak, "stock_info_bj_name_code"):
        return {}
    df = ak.stock_info_bj_name_code()
    code_col = "证券代码" if "证券代码" in df.columns else df.columns[0]
    ind_col = "所属行业" if "所属行业" in df.columns else None
    if ind_col is None:
        for c in df.columns:
            if "行业" in str(c):
                ind_col = c
                break
    if ind_col is None:
        return {}
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        code = str(row[code_col]).strip().zfill(6)
        out[code] = _norm_industry(row[ind_col])
    return out


def build() -> dict[str, list]:
    existing = _load_existing()
    print("fetching A-share code/name ...")
    base = ak.stock_info_a_code_name()
    print(f"  {len(base)} rows")

    print("fetching SZ industries ...")
    sz_ind = _industry_from_sz()
    print(f"  {len(sz_ind)} rows")

    print("fetching BJ industries ...")
    bj_ind = _industry_from_bj()
    print(f"  {len(bj_ind)} rows")

    result: dict[str, list] = {}
    for _, row in base.iterrows():
        code = str(row["code"]).strip().zfill(6)
        name = _norm_name(row["name"])
        industry = sz_ind.get(code) or bj_ind.get(code)
        if not industry and code in existing:
            old = existing[code]
            if isinstance(old, list) and len(old) >= 3 and old[1] == "股票":
                industry = str(old[2])
        industry = industry or "其它"
        result[code] = [name, "股票", industry]

    # 保留原 JSON 里的非股票（如 ETF）
    kept = 0
    for code, meta in existing.items():
        if code in result:
            continue
        if isinstance(meta, list) and len(meta) >= 2 and meta[1] != "股票":
            result[code] = list(meta)
            kept += 1
    if kept:
        print(f"kept {kept} non-stock entries from existing file")

    return dict(sorted(result.items()))


def main() -> None:
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    n_stock = sum(1 for v in data.values() if v[1] == "股票")
    n_other = len(data) - n_stock
    print(f"wrote {OUT}  stocks={n_stock} other={n_other} total={len(data)}")


if __name__ == "__main__":
    main()
