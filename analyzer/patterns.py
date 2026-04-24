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

    # --- 上升直角三角形（水平壓力 + 低點墊高）---
    if len(highs_idx) >= 2 and len(lows_idx) >= 2:
        last_highs = highs_idx[-3:] if len(highs_idx) >= 3 else highs_idx[-2:]
        last_lows = lows_idx[-3:] if len(lows_idx) >= 3 else lows_idx[-2:]
        if len(last_highs) >= 2 and len(last_lows) >= 2:
            hp = [float(tail["close"].iloc[i]) for i in last_highs]
            lp = [float(tail["close"].iloc[i]) for i in last_lows]
            # 高點水平 (差距 < 3%) + 低點逐個墊高
            highs_flat = max(hp) - min(hp) < max(hp) * 0.03
            lows_rising = all(lp[i] < lp[i + 1] for i in range(len(lp) - 1))
            if highs_flat and lows_rising:
                res = sum(hp) / len(hp)
                patterns.append(Pattern(
                    "上升直角三角形底", "bull", float(res),
                    "水平壓力 + 低點逐步墊高，多頭積累；突破上方壓力為買點"))
            # 下降直角：低點水平 + 高點逐個走低
            lows_flat = max(lp) - min(lp) < max(lp) * 0.03
            highs_falling = all(hp[i] > hp[i + 1]
                                for i in range(len(hp) - 1))
            if lows_flat and highs_falling:
                sup = sum(lp) / len(lp)
                patterns.append(Pattern(
                    "下降直角三角形頂", "bear", float(sup),
                    "水平支撐 + 高點逐步走低，空頭積累；跌破下方支撐為賣點"))

    # --- 對稱三角形（高點下降 + 低點墊高）---
    if len(highs_idx) >= 2 and len(lows_idx) >= 2:
        last_highs = highs_idx[-2:]
        last_lows = lows_idx[-2:]
        hp = [float(tail["close"].iloc[i]) for i in last_highs]
        lp = [float(tail["close"].iloc[i]) for i in last_lows]
        if hp[-1] < hp[0] and lp[-1] > lp[0]:
            # 距離夠（至少 15 bar）
            span = (max(last_highs + last_lows)
                    - min(last_highs + last_lows))
            if span >= 15:
                mid = (hp[-1] + lp[-1]) / 2
                patterns.append(Pattern(
                    "對稱三角收斂", "neutral", float(mid),
                    "高點下降、低點墊高，向尖端收斂；突破方向為趨勢訊號"))

    # --- 旗形整理（急漲後小範圍平行通道）---
    if len(tail) >= 30:
        # 近 20 日前 10 日漲幅 > 10%、後 10 日區間窄 (< 5%)
        before = tail["close"].iloc[-25:-15]
        after = tail["close"].iloc[-12:]
        if not before.empty and not after.empty:
            rise = (before.iloc[-1] / before.iloc[0] - 1) * 100
            drop = (before.iloc[0] / before.iloc[-1] - 1) * 100
            after_range = (after.max() - after.min()) / after.mean() * 100
            if rise > 10 and after_range < 6:
                patterns.append(Pattern(
                    "上升旗形整理", "bull", float(after.max()),
                    f"急漲 {rise:.1f}% 後窄幅整理 {after_range:.1f}%；"
                    "突破上緣續漲機率高"))
            if drop > 10 and after_range < 6:
                patterns.append(Pattern(
                    "下降旗形整理", "bear", float(after.min()),
                    f"急跌 {drop:.1f}% 後窄幅反彈 {after_range:.1f}%；"
                    "跌破下緣續跌機率高"))

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


def multi_sr(df: pd.DataFrame, n: int = 3,
             lookback: int = 250,
             cluster_pct: float = 0.025) -> tuple[list[float], list[float]]:
    """找出多層級的支撐與壓力（從歷史轉折點聚類）.

    支撐 = 低點聚類中心，依「被測試次數」排序
    壓力 = 高點聚類中心
    僅回傳 < 或 > 現價的層級
    """
    tail = df.tail(lookback)
    if len(tail) < 20:
        return [], []

    highs_idx = argrelextrema(tail["high"].values, np.greater, order=4)[0]
    lows_idx = argrelextrema(tail["low"].values, np.less, order=4)[0]
    high_prices = [float(tail["high"].iloc[i]) for i in highs_idx]
    low_prices = [float(tail["low"].iloc[i]) for i in lows_idx]

    def _cluster(prices: list[float]) -> list[tuple[float, int]]:
        """(mean, count) — count 越多代表越重要的層級."""
        if not prices:
            return []
        prices_sorted = sorted(prices)
        clusters: list[list[float]] = []
        for p in prices_sorted:
            if clusters and (p - clusters[-1][-1]) / max(p, 1) < cluster_pct:
                clusters[-1].append(p)
            else:
                clusters.append([p])
        return [(sum(c) / len(c), len(c)) for c in clusters]

    sup_clusters = _cluster(low_prices)
    res_clusters = _cluster(high_prices)
    price_now = float(df["close"].iloc[-1])

    # 支撐：取低於現價且被測試次數多者
    sup_below = [(p, cnt) for p, cnt in sup_clusters if p < price_now * 1.02]
    sup_below.sort(key=lambda x: -x[1])
    supports = [round(p, 2) for p, _ in sup_below[:n]]
    supports.sort(reverse=True)  # 接近現價者在前

    # 壓力：取高於現價且被測試次數多者
    res_above = [(p, cnt) for p, cnt in res_clusters if p > price_now * 0.98]
    res_above.sort(key=lambda x: -x[1])
    resistances = [round(p, 2) for p, _ in res_above[:n]]
    resistances.sort()  # 接近現價者在前

    return supports, resistances
