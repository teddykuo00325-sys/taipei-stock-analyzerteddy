"""台股資料抓取 — yfinance 包裝."""
from __future__ import annotations

from functools import lru_cache

import pandas as pd
import yfinance as yf


def _normalize_ticker(code: str) -> str:
    code = code.strip().upper()
    if code.endswith(".TW") or code.endswith(".TWO"):
        return code
    # 預設上市；若失敗再嘗試上櫃
    return f"{code}.TW"


def fetch(code: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """抓取台股 K 線資料.

    code: "2330" / "2330.TW" / "6488.TWO"
    period: "6mo" / "1y" / "2y" / "5y" / "max"
    interval: "1d" / "1wk" / "1mo"
    """
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
    """取得公司名稱；失敗時回傳代號."""
    ticker = _normalize_ticker(code)
    try:
        info = yf.Ticker(ticker).info
        return info.get("longName") or info.get("shortName") or code
    except Exception:
        return code
