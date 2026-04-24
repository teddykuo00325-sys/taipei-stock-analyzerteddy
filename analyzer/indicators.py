"""技術指標 — MA、MACD、KD、RSI、量能."""
from __future__ import annotations

import numpy as np
import pandas as pd


def add_ma(df: pd.DataFrame, periods=(5, 10, 20, 60, 120, 240)) -> pd.DataFrame:
    """朱式四均線 + 季線/半年線/年線."""
    out = df.copy()
    for p in periods:
        out[f"ma{p}"] = out["close"].rolling(p).mean()
    out["vol_ma5"] = out["volume"].rolling(5).mean()
    out["vol_ma20"] = out["volume"].rolling(20).mean()
    return out


def add_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
    out = df.copy()
    ema_fast = out["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = out["close"].ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dem = dif.ewm(span=signal, adjust=False).mean()
    out["macd_dif"] = dif
    out["macd_dem"] = dem
    out["macd_hist"] = dif - dem
    return out


def add_kd(df: pd.DataFrame, n=9, m1=3, m2=3) -> pd.DataFrame:
    """隨機指標 KD (台股習慣 9-3-3)."""
    out = df.copy()
    low_n = out["low"].rolling(n).min()
    high_n = out["high"].rolling(n).max()
    rsv = (out["close"] - low_n) / (high_n - low_n) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(alpha=1 / m1, adjust=False).mean()
    d = k.ewm(alpha=1 / m2, adjust=False).mean()
    out["k"] = k
    out["d"] = d
    return out


def add_rsi(df: pd.DataFrame, period=14) -> pd.DataFrame:
    out = df.copy()
    delta = out["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out["rsi"] = 100 - 100 / (1 + rs)
    return out


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """平均真實區間 (ATR) — 用於波動率調整的停損."""
    out = df.copy()
    high_low = out["high"] - out["low"]
    high_close = (out["high"] - out["close"].shift()).abs()
    low_close = (out["low"] - out["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    out["atr14"] = tr.rolling(period).mean()
    return out


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    return add_atr(add_rsi(add_kd(add_macd(add_ma(df)))))
