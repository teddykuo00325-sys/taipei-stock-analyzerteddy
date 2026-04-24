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

    # --- 三重底：三個低點接近且間距足夠 ---
    if len(lows_idx) >= 3:
        a, b, c = lows_idx[-3], lows_idx[-2], lows_idx[-1]
        if c - a >= 25 and b - a >= 8 and c - b >= 8:
            pa = float(tail["close"].iloc[a])
            pb = float(tail["close"].iloc[b])
            pc = float(tail["close"].iloc[c])
            avg = (pa + pb + pc) / 3
            if all(abs(p - avg) / avg < 0.05 for p in (pa, pb, pc)):
                neck = max(tail["close"].iloc[a:b].max(),
                           tail["close"].iloc[b:c].max())
                patterns.append(Pattern(
                    "三重底", "bull", float(neck),
                    "三次測試同一底部未破；突破頸線為強烈買進訊號"))

    # --- 三重頂 ---
    if len(highs_idx) >= 3:
        a, b, c = highs_idx[-3], highs_idx[-2], highs_idx[-1]
        if c - a >= 25 and b - a >= 8 and c - b >= 8:
            pa = float(tail["close"].iloc[a])
            pb = float(tail["close"].iloc[b])
            pc = float(tail["close"].iloc[c])
            avg = (pa + pb + pc) / 3
            if all(abs(p - avg) / avg < 0.05 for p in (pa, pb, pc)):
                neck = min(tail["close"].iloc[a:b].min(),
                           tail["close"].iloc[b:c].min())
                patterns.append(Pattern(
                    "三重頂", "bear", float(neck),
                    "三次測試同一壓力未過；跌破頸線為強烈賣出訊號"))

    # --- ABC 修正：下跌波 - 反彈 B - 續跌 C（多方回檔結束判讀）---
    if len(highs_idx) >= 2 and len(lows_idx) >= 2:
        last_highs = sorted(highs_idx)[-2:]
        last_lows = sorted(lows_idx)[-2:]
        # 交錯序列 H-L-H-L 或 L-H-L-H 判讀
        seq = sorted(list(last_highs) + list(last_lows))
        if len(seq) >= 4:
            # 判斷最後 4 個轉折的 HLHL 結構
            last4 = seq[-4:]
            types = ["H" if i in last_highs else "L" for i in last4]
            prices = [float(tail["close"].iloc[i]) for i in last4]
            # 下降 ABC: H-L-H-L 且第二 H < 第一 H、第二 L < 第一 L
            if types == ["H", "L", "H", "L"]:
                if prices[2] < prices[0] and prices[3] < prices[1]:
                    close_now = float(tail["close"].iloc[-1])
                    if close_now > prices[2]:  # 突破 B 高點
                        patterns.append(Pattern(
                            "ABC 修正突破", "bull", prices[2],
                            "下跌 ABC 三波修正結束，突破 B 波高點；多頭延續訊號"))
                    else:
                        patterns.append(Pattern(
                            "ABC 修正進行中", "neutral", prices[2],
                            "下跌 ABC 波結構，C 波底部形成中；突破 B 高確認反彈"))
            # 上升 ABC: L-H-L-H
            elif types == ["L", "H", "L", "H"]:
                if prices[2] > prices[0] and prices[3] > prices[1]:
                    close_now = float(tail["close"].iloc[-1])
                    if close_now < prices[2]:
                        patterns.append(Pattern(
                            "ABC 反彈結束", "bear", prices[2],
                            "上升 ABC 三波反彈結束，跌破 B 波低點；空頭延續"))

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
