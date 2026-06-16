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
    return http.get_json(TWSE_STOCK_DAY_ALL, timeout=20, retries=2)


def _fetch_tpex_raw() -> list[dict]:
    return http.get_json(TPEX_DAILY_URL, timeout=20, retries=2)


def fetch_twse_snapshot() -> pd.DataFrame:
    """TWSE 上市 + TPEX 上櫃合併快照."""
    rows = _fetch_twse_raw()
    if not rows:
        # 雲端 IP 偶爾被 TWSE 回空，回退至上次成功結果
        if _cache.get("df") is not None and not _cache["df"].empty:
            return _cache["df"]
        raise http.JSONFetchError(TWSE_STOCK_DAY_ALL, 200, "empty array")
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


def _fallback_from_price_cache() -> pd.DataFrame:
    """TWSE OpenAPI 不通時 fallback：從 price_cache 取所有 code + 最新 volume.

    GitHub Actions IP 被 TWSE geo-block 時用這個。
    用 K 線 cache 的最後一日資料模擬 TradeVolume 排序。
    """
    try:
        from . import price_cache
        with price_cache._lock, price_cache._conn() as c:
            rows = c.execute("""
                SELECT o.code, o.close, o.volume
                FROM ohlcv o
                JOIN (
                    SELECT code, MAX(date) AS last_dt
                    FROM ohlcv GROUP BY code
                ) m ON o.code = m.code AND o.date = m.last_dt
            """).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["Code", "ClosingPrice",
                                          "TradeVolume"])
        df["Code"] = df["Code"].astype(str)
        # 嘗試從 industry.snapshot() 抓中文名（不同 OpenAPI endpoint，
        # 可能 STOCK_DAY_ALL 被擋但 t187ap03_L 仍可達）
        df["Name"] = df["Code"]   # 預設 fallback：code 當名稱
        try:
            from . import industry as _ind
            ind_df = _ind.snapshot()
            if ind_df is not None and not ind_df.empty:
                name_map = dict(zip(
                    ind_df["code"].astype(str),
                    ind_df["short_name"].fillna("").astype(str)))
                df["Name"] = df["Code"].map(
                    lambda c: name_map.get(c) or c)
        except Exception:
            pass
        df["Market"] = "TSE"      # 假設（無從區分）
        df = df[df["TradeVolume"].fillna(0) > 0].reset_index(drop=True)
        return df
    except Exception:
        return pd.DataFrame()


def snapshot(max_age_sec: int = 3600) -> pd.DataFrame:
    now = time()
    if _cache["df"] is not None and now - _cache["time"] < max_age_sec:
        return _cache["df"]
    try:
        df = fetch_twse_snapshot()
    except Exception as e:
        # TWSE / TPEX API 在 GitHub Actions 等海外 IP 常被擋
        # → fallback 到 price_cache 內已有的 K 線資料
        df = _fallback_from_price_cache()
        if df.empty:
            raise   # 連 fallback 都沒料才拋
    _cache["df"] = df
    _cache["time"] = now
    return df
