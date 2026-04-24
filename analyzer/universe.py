"""台股清單 — 透過 TWSE OpenAPI 取得所有上市股票的當日快照."""
from __future__ import annotations

from functools import lru_cache
from time import time

import pandas as pd

from . import http

TWSE_STOCK_DAY_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_DAILY_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

_NUMERIC_COLS = [
    "OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice",
    "Change", "TradeVolume", "TradeValue", "Transaction",
]


def _fetch_twse_raw() -> list[dict]:
    r = http.get(TWSE_STOCK_DAY_ALL, timeout=20)
    r.raise_for_status()
    return r.json()


def _fetch_tpex_raw() -> list[dict]:
    r = http.get(TPEX_DAILY_URL, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_twse_snapshot() -> pd.DataFrame:
    """TWSE 上市 + TPEX 上櫃合併快照."""
    rows = _fetch_twse_raw()
    df_twse = pd.DataFrame(rows)
    df_twse["Market"] = "TSE"

    # TPEX 上櫃：欄位名不同，映射成 TWSE 相容格式
    try:
        tpex_rows = _fetch_tpex_raw()
        df_tpex = pd.DataFrame(tpex_rows).rename(columns={
            "SecuritiesCompanyCode": "Code",
            "CompanyName": "Name",
            "Open": "OpeningPrice",
            "High": "HighestPrice",
            "Low": "LowestPrice",
            "Close": "ClosingPrice",
            "TradingShares": "TradeVolume",
            "TransactionAmount": "TradeValue",
            "TransactionNumber": "Transaction",
        })
        df_tpex["Market"] = "OTC"
        # TPEX Change 可能帶 +/- 符號字串
        df = pd.concat([df_twse, df_tpex], ignore_index=True, sort=False)
    except Exception:
        df = df_twse

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
