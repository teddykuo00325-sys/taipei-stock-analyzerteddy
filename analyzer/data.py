"""台股資料抓取 — 日線透過 price_cache 增量快取；週/月線直接 yfinance."""
from __future__ import annotations

from functools import lru_cache

import pandas as pd
import yfinance as yf

from . import price_cache


def _normalize_ticker(code: str) -> str:
    code = code.strip().upper()
    if code.endswith(".TW") or code.endswith(".TWO"):
        return code
    return f"{code}.TW"


def fetch(code: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """抓取台股 K 線.

    - interval="1d": 透過 price_cache 增量（首次慢、之後快）
    - interval="1wk" / "1mo": 直接 yfinance（資料量小、不快取）
    """
    if interval == "1d":
        return price_cache.get(code, period=period)
    # 週線 / 月線 — 直接 yfinance
    return _direct_fetch(code, period, interval)


def _direct_fetch(code: str, period: str, interval: str) -> pd.DataFrame:
    ticker = _normalize_ticker(code)
    df = _download(ticker, period, interval)
    if df.empty and not code.upper().endswith(".TWO"):
        df = _download(f"{code.strip()}.TWO", period, interval)
    if df.empty:
        raise ValueError(f"查無資料：{code}")
    df = df.rename(
        columns={"Open": "open", "High": "high", "Low": "low",
                 "Close": "close", "Volume": "volume"}
    )
    df.index = pd.to_datetime(df.index)
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    return df


@lru_cache(maxsize=64)
def _download(ticker: str, period: str, interval: str) -> pd.DataFrame:
    try:
        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def get_name(code: str) -> str:
    ticker = _normalize_ticker(code)
    try:
        info = yf.Ticker(ticker).info
        return info.get("longName") or info.get("shortName") or code
    except Exception:
        return code
