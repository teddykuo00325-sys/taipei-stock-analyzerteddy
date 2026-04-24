"""黃金切割率 — 費波納契回檔 / 延伸目標.

用法：
  1. 找近期顯著波段：最高點、最低點
  2. 計算回檔位：23.6 / 38.2 / 50 / 61.8 / 78.6 (%)
  3. 計算延伸目標：127.2 / 161.8 / 200 / 261.8 (%)
  4. 當股價停在某一級位附近 → 產生訊號
  5. 延伸位可作為停利目標
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

RATIOS = [0.236, 0.382, 0.5, 0.618, 0.786]
EXTS = [1.272, 1.382, 1.618, 2.0, 2.618]
PHI = 1.618033988749895


@dataclass
class FibLevel:
    name: str      # e.g. "38.2%"、"161.8% 延伸"
    price: float
    kind: str      # "retrace" / "extension"


@dataclass
class FibAnalysis:
    direction: str               # "up" / "down"
    swing_high: float
    swing_low: float
    swing_high_date: str | None
    swing_low_date: str | None
    levels: list[FibLevel]       # 依 price 升冪
    nearest: FibLevel | None
    nearest_distance_pct: float  # 現價與最近級位之距離 (%)
    note: str


def _swing(df: pd.DataFrame, lookback: int) -> tuple[float, float, str, str]:
    tail = df.tail(lookback)
    hi_idx = tail["high"].idxmax()
    lo_idx = tail["low"].idxmin()
    return (float(tail.loc[hi_idx, "high"]),
            float(tail.loc[lo_idx, "low"]),
            str(hi_idx.date()) if hasattr(hi_idx, "date") else str(hi_idx),
            str(lo_idx.date()) if hasattr(lo_idx, "date") else str(lo_idx))


def analyze(df: pd.DataFrame, lookback: int = 90,
            tolerance_pct: float = 2.0) -> FibAnalysis:
    lookback = min(lookback, len(df))
    high, low, hi_d, lo_d = _swing(df, lookback)
    diff = high - low
    if diff <= 0:
        return FibAnalysis("unknown", high, low, hi_d, lo_d, [], None,
                           float("inf"), "無法計算：區間為零")

    tail = df.tail(lookback)
    hi_loc = tail["high"].values.argmax()
    lo_loc = tail["low"].values.argmin()
    # 若低點在高點之前 → 目前為上升 (impulse up 後的修正回檔)
    direction = "up" if lo_loc < hi_loc else "down"

    levels: list[FibLevel] = []
    if direction == "up":
        # 上升後回檔：自 high 往下計
        for r in RATIOS:
            levels.append(FibLevel(f"{r * 100:.1f}% 回檔",
                                   high - diff * r, "retrace"))
        for r in EXTS:
            levels.append(FibLevel(f"{r * 100:.1f}% 延伸",
                                   low + diff * r, "extension"))
        levels.insert(0, FibLevel("0% (高點)", high, "retrace"))
        levels.append(FibLevel("100% (低點)", low, "retrace"))
    else:
        # 下降後反彈：自 low 往上計
        for r in RATIOS:
            levels.append(FibLevel(f"{r * 100:.1f}% 反彈",
                                   low + diff * r, "retrace"))
        for r in EXTS:
            levels.append(FibLevel(f"{r * 100:.1f}% 延伸",
                                   high - diff * r, "extension"))
        levels.insert(0, FibLevel("0% (低點)", low, "retrace"))
        levels.append(FibLevel("100% (高點)", high, "retrace"))

    levels.sort(key=lambda x: x.price)

    # 找最接近現價者
    price = float(df["close"].iloc[-1])
    nearest = None
    min_dist = float("inf")
    for lv in levels:
        if price == 0:
            continue
        d = abs(lv.price - price) / price * 100
        if d < min_dist:
            min_dist = d
            nearest = lv

    note = ""
    if nearest and min_dist <= tolerance_pct:
        note = f"現價貼近 **{nearest.name}** (差 {min_dist:.2f}%)"
    else:
        note = "現價不在主要費波納契級位附近"

    return FibAnalysis(
        direction=direction,
        swing_high=high, swing_low=low,
        swing_high_date=hi_d, swing_low_date=lo_d,
        levels=levels, nearest=nearest,
        nearest_distance_pct=min_dist, note=note,
    )


def score_adj(df: pd.DataFrame) -> tuple[int, str]:
    """黃金切割給分（-5 ~ +10）：
    - 上升波段中，現價位於 38.2% / 50% / 61.8% 回檔且收紅 → +10（主要買點）
    - 下降波段中，現價貼近 38.2% / 50% / 61.8% 反彈且收黑 → -10（主要賣點）
    - 價格突破 161.8% 延伸 → +5（動能延續）
    - 價格跌破 0% 低點 → -5（破低）
    """
    try:
        fa = analyze(df)
    except Exception:
        return 0, ""
    if fa.nearest is None or fa.nearest_distance_pct > 2.5:
        return 0, ""

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last
    is_red = last["close"] > last["open"]
    close_up = last["close"] > prev["close"]
    name = fa.nearest.name

    if fa.direction == "up" and "回檔" in name:
        if any(k in name for k in ["38.2", "50.0", "61.8"]):
            if is_red or close_up:
                return 10, f"上升波回檔 {name} 不破，費波納契買點"
            return 3, f"靠近 {name}，觀察是否守住"
        if "0%" in name:
            return -3, f"跌至波段低點 0%，留意破低"
    if fa.direction == "down" and "反彈" in name:
        if any(k in name for k in ["38.2", "50.0", "61.8"]):
            if (not is_red) or (not close_up):
                return -10, f"下降波反彈 {name} 遇壓，費波納契賣點"
            return -3, f"靠近 {name}，觀察是否跌破"
    if "延伸" in name and "161.8" in name:
        if close_up:
            return 5, f"突破 {name}，黃金延伸動能"
    return 0, f"近 {name}"
