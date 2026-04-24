"""台股清單 — 透過 TWSE OpenAPI 取得所有上市股票的當日快照."""
from __future__ import annotations

from functools import lru_cache
from time import time

import pandas as pd
import requests

TWSE_STOCK_DAY_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"

_NUMERIC_COLS = [
    "OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice",
    "Change", "TradeVolume", "TradeValue", "Transaction",
]


def _fetch_twse_raw() -> list[dict]:
    r = requests.get(TWSE_STOCK_DAY_ALL, timeout=20,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json()


def fetch_twse_snapshot() -> pd.DataFrame:
    """取得 TWSE 所有上市股票的最新交易日快照（僅 4 碼一般股票）."""
    rows = _fetch_twse_raw()
    df = pd.DataFrame(rows)
    for c in _NUMERIC_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["Code"].astype(str).str.match(r"^\d{4}$")]
    df = df[df["TradeVolume"].fillna(0) > 0]
    df = df.reset_index(drop=True)
    return df


# Streamlit 端會用 st.cache_data 包裝；這裡再加一層時效快取避免重複呼叫
_cache: dict = {"time": 0, "df": None}


def snapshot(max_age_sec: int = 3600) -> pd.DataFrame:
    now = time()
    if _cache["df"] is not None and now - _cache["time"] < max_age_sec:
        return _cache["df"]
    df = fetch_twse_snapshot()
    _cache["df"] = df
    _cache["time"] = now
    return df
