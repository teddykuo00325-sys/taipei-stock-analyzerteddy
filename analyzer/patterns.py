"""型態學 — W 底、M 頭、頭肩型態、趨勢線."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


@dataclass
class Pattern:
    name: str
    signal: str           # "bull"/"bear"/"neutral"
    neckline: float | None
    note: str


def _pivots(series: pd.Series, order: int = 5):
    highs = argrelextrema(series.values, np.greater_equal, order=order)[0]
    lows = argrelextrema(series.values, np.less_equal, order=order)[0]
    return highs, lows


def detect(df: pd.DataFrame, order: int = 5, lookback: int = 120) -> list[Pattern]:
    """回溯近 N 天，偵測常見型態."""
    if len(df) < lookback:
        lookback = len(df)
    tail = df.tail(lookback).reset_index(drop=True)
    highs_idx, lows_idx = _pivots(tail["close"], order=order)
    patterns: list[Pattern] = []

    # --- W 底：兩個接近的低點 + 反彈高點突破 ---
    if len(lows_idx) >= 2:
        l1, l2 = lows_idx[-2], lows_idx[-1]
        if l2 - l1 >= 10:
            p1, p2 = tail["close"].iloc[l1], tail["close"].iloc[l2]
            if abs(p1 - p2) / p1 < 0.05:
                peak_seg = tail["close"].iloc[l1:l2]
                if len(peak_seg) > 0:
                    neck = peak_seg.max()
                    last_close = tail["close"].iloc[-1]
                    note = "W 底型態；突破頸線為買點" if last_close < neck else \
                           "W 底突破頸線；確認底部反轉"
                    patterns.append(Pattern("W 底", "bull", float(neck), note))

    # --- M 頭：兩個接近的高點 + 回檔低點跌破 ---
    if len(highs_idx) >= 2:
        h1, h2 = highs_idx[-2], highs_idx[-1]
        if h2 - h1 >= 10:
            p1, p2 = tail["close"].iloc[h1], tail["close"].iloc[h2]
            if abs(p1 - p2) / p1 < 0.05:
                trough_seg = tail["close"].iloc[h1:h2]
                if len(trough_seg) > 0:
                    neck = trough_seg.min()
                    last_close = tail["close"].iloc[-1]
                    note = "M 頭型態；跌破頸線為賣點" if last_close > neck else \
                           "M 頭跌破頸線；確認頭部反轉"
                    patterns.append(Pattern("M 頭", "bear", float(neck), note))

    # --- 頭肩底：三個低點，中間最低，兩肩接近 ---
    if len(lows_idx) >= 3:
        a, b, c = lows_idx[-3], lows_idx[-2], lows_idx[-1]
        pa, pb, pc = tail["close"].iloc[a], tail["close"].iloc[b], tail["close"].iloc[c]
        if pb < pa and pb < pc and abs(pa - pc) / pa < 0.06:
            neck = max(tail["close"].iloc[a:b].max(), tail["close"].iloc[b:c].max())
            patterns.append(Pattern("頭肩底", "bull", float(neck),
                                    "三低點底部反轉；突破頸線為買點"))

    # --- 頭肩頂 ---
    if len(highs_idx) >= 3:
        a, b, c = highs_idx[-3], highs_idx[-2], highs_idx[-1]
        pa, pb, pc = tail["close"].iloc[a], tail["close"].iloc[b], tail["close"].iloc[c]
        if pb > pa and pb > pc and abs(pa - pc) / pa < 0.06:
            neck = min(tail["close"].iloc[a:b].min(), tail["close"].iloc[b:c].min())
            patterns.append(Pattern("頭肩頂", "bear", float(neck),
                                    "三高點頭部反轉；跌破頸線為賣點"))

    return patterns


def trendline(df: pd.DataFrame, lookback: int = 60) -> dict:
    """近 N 天的簡易支撐/壓力（取最高最低點連線斜率）."""
    tail = df.tail(lookback)
    support = tail["low"].min()
    resistance = tail["high"].max()
    recent_low_idx = tail["low"].idxmin()
    recent_high_idx = tail["high"].idxmax()
    return {
        "support": float(support),
        "resistance": float(resistance),
        "support_date": recent_low_idx,
        "resistance_date": recent_high_idx,
    }
