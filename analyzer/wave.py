"""波浪理論 — 簡化版艾略特波浪辨識.

本模組採用局部極值 (pivot) 偵測近 N 日波段結構，判讀：
  - 上升五波（impulse up：1 上 2 下 3 上 4 下 5 上）
  - 下降五波（impulse down）
  - 修正三波（A-B-C）
  - 當前所在波次

注意：艾略特波浪本身具主觀性，本簡化版僅作為方向輔助參考。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


@dataclass
class Wave:
    label: str            # 當前波浪標籤（如："第 3 波上漲"）
    direction: str        # "up" / "down" / "corrective" / "unclear"
    position: int         # 1~5 (impulse) 或 1~3 (corrective) 或 0 (unclear)
    confidence: str       # "高" / "中" / "低"
    note: str
    pivots: list[tuple[int, str, float]]   # (index, "H"/"L", price)


def _find_pivots(prices: np.ndarray, order: int) -> list[tuple[int, str, float]]:
    highs = argrelextrema(prices, np.greater, order=order)[0]
    lows = argrelextrema(prices, np.less, order=order)[0]
    pivots = [(int(i), "H", float(prices[i])) for i in highs] + \
             [(int(i), "L", float(prices[i])) for i in lows]
    pivots.sort(key=lambda x: x[0])
    return pivots


def detect(df: pd.DataFrame, lookback: int = 120) -> Wave:
    """辨識近 lookback 日的波浪結構."""
    if len(df) < 20:
        return Wave("資料不足", "unclear", 0, "低", "少於 20 根 K 線", [])

    lookback = min(lookback, len(df))
    tail = df["close"].tail(lookback).values
    order = max(3, lookback // 20)
    pivots = _find_pivots(tail, order)
    if len(pivots) < 3:
        return Wave("趨勢未明", "unclear", 0, "低",
                    "近期無明顯轉折點", pivots)

    # 取最近 6 個轉折（5 波最多 5 個轉折 + 起點 = 6）
    recent = pivots[-6:]
    # 當前價格位置
    last_price = float(tail[-1])
    last_pivot_idx = recent[-1][0]
    bars_since = len(tail) - 1 - last_pivot_idx

    # === 簡化判斷邏輯 ===
    # 1. 取最後 5 個 pivot 判斷波浪結構
    if len(recent) >= 5:
        seq = recent[-5:]
        types = [p[1] for p in seq]
        prices = [p[2] for p in seq]

        # 上升五波起始於 L：L H L H L（或 H L H L H）最後一段仍上升
        # 核心：頭頭高、底底高 + 3 波最長（或不最短）
        lhs = all(t in ("H", "L") for t in types)
        if lhs and types[0] == "L" and types[-1] == "L":
            # L H L H L → 可能結束五波中的第 4 波（尚未漲出第 5 波）
            if prices[1] < prices[3] and prices[2] < prices[4] < prices[1]:
                # 多頭結構：H1<H2, L1<L2<H1
                if last_price > prices[-1]:
                    return Wave("第 5 波上漲中", "up", 5, "中",
                                "進入第 5 波，留意末升段風險", pivots)
                return Wave("第 4 波修正末", "up", 4, "中",
                            "第 4 波尾聲，可能展開第 5 波", pivots)
        if lhs and types[0] == "H" and types[-1] == "H":
            # H L H L H → 空頭結構
            if prices[1] > prices[3] and prices[2] > prices[4] > prices[1]:
                if last_price < prices[-1]:
                    return Wave("下跌第 5 波", "down", 5, "中",
                                "空頭末跌段，留意反彈", pivots)

    # 2. 最近 3~4 轉折判斷方向
    last3 = recent[-3:] if len(recent) >= 3 else recent
    if len(last3) >= 3:
        p0, p1, p2 = last3[-3][2], last3[-2][2], last3[-1][2]
        t0, t1, t2 = last3[-3][1], last3[-2][1], last3[-1][1]
        # 上升：低 → 高 → 低（高更高） or 低 → 高 → 低（創新高趨勢）
        if t0 == "L" and t1 == "H" and t2 == "L" and p2 > p0 and last_price > p1:
            return Wave("第 3 波上漲中", "up", 3, "中",
                        "突破前高，主升段；順勢做多", pivots)
        if t0 == "H" and t1 == "L" and t2 == "H" and last_price > p1:
            if p2 > p0:
                return Wave("第 1 波或第 3 波上漲", "up", 3, "中",
                            "底底高頭頭高，多頭趨勢", pivots)
        if t0 == "H" and t1 == "L" and t2 == "H" and p2 < p0 and last_price < p1:
            return Wave("第 3 波下跌中", "down", 3, "中",
                        "跌破前低，主跌段；不宜接刀", pivots)
        if t0 == "L" and t1 == "H" and t2 == "L" and p2 < p0:
            return Wave("下跌趨勢", "down", 3, "中",
                        "底底低，空頭延續", pivots)

    # 3. 2 個轉折，僅判斷短期方向
    if len(recent) >= 2:
        last2 = recent[-2:]
        if last2[-1][1] == "L" and last_price > last2[-1][2]:
            return Wave("可能反彈波 (2 波)", "up", 2, "低",
                        "自近期低點反彈", pivots)
        if last2[-1][1] == "H" and last_price < last2[-1][2]:
            return Wave("可能修正波 (2 波)", "down", 2, "低",
                        "自近期高點回落", pivots)

    return Wave("波浪結構不明", "unclear", 0, "低",
                "轉折不足或橫盤整理", pivots)


def summarize(df: pd.DataFrame) -> str:
    w = detect(df)
    return f"{w.label}（信心：{w.confidence}）"


def score_adj(df: pd.DataFrame) -> tuple[int, str]:
    """波浪位置給分：
    - 第 3 波上漲 → +15（主升段）
    - 第 5 波上漲 → -5（末升段風險）
    - 第 3 波下跌 → -15（主跌段）
    - 下跌第 5 波 → +5（將轉折）
    - 反彈波 / 修正波 → 小幅調整
    """
    w = detect(df)
    if "第 3 波上漲" in w.label:
        return 15, f"波浪：{w.label}"
    if "第 5 波上漲" in w.label:
        return -5, f"波浪：{w.label}（末升段）"
    if "第 3 波下跌" in w.label:
        return -15, f"波浪：{w.label}"
    if "下跌第 5 波" in w.label:
        return 5, f"波浪：{w.label}（將轉折）"
    if "反彈波" in w.label:
        return 3, f"波浪：{w.label}"
    if "修正波" in w.label:
        return -3, f"波浪：{w.label}"
    if "第 4 波" in w.label:
        return 5, f"波浪：{w.label}"
    return 0, f"波浪：{w.label}"
