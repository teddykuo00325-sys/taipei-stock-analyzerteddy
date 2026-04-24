"""K 線型態辨識 — 朱家泓常用單日/雙日型態."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Candle:
    name: str        # 型態名稱
    signal: str      # "bull" / "bear" / "neutral"
    note: str        # 說明


def _body(row) -> float:
    return abs(row["close"] - row["open"])


def _range(row) -> float:
    return row["high"] - row["low"]


def _upper_shadow(row) -> float:
    return row["high"] - max(row["open"], row["close"])


def _lower_shadow(row) -> float:
    return min(row["open"], row["close"]) - row["low"]


def classify_last(df: pd.DataFrame) -> list[Candle]:
    """辨識最後一根（含前一根組合）可能的型態."""
    if len(df) < 2:
        return []
    last = df.iloc[-1]
    prev = df.iloc[-2]
    patterns: list[Candle] = []

    body = _body(last)
    rng = _range(last)
    if rng == 0:
        return patterns
    body_ratio = body / rng
    up = _upper_shadow(last)
    lo = _lower_shadow(last)
    change_pct = (last["close"] - last["open"]) / last["open"] * 100

    # --- 單日型態 ---
    if body_ratio < 0.1:
        patterns.append(Candle("十字線", "neutral", "變盤訊號，多空拉鋸"))
    if change_pct >= 3 and body_ratio > 0.7:
        patterns.append(Candle("長紅 K", "bull", "強勢攻擊，買方壓倒賣方"))
    if change_pct <= -3 and body_ratio > 0.7:
        patterns.append(Candle("長黑 K", "bear", "空方強勢，留意續跌"))

    # 鎚子/吊人：下影線長、實體小、上影線短
    if lo >= 2 * body and up <= body * 0.3 and body_ratio < 0.4:
        prev_trend = df["close"].iloc[-6:-1].mean()
        if last["close"] > prev_trend:
            patterns.append(Candle("吊人線", "bear", "高檔出現，留意反轉"))
        else:
            patterns.append(Candle("鎚子線", "bull", "低檔打底訊號"))

    # 流星/倒鎚：上影線長
    if up >= 2 * body and lo <= body * 0.3 and body_ratio < 0.4:
        prev_trend = df["close"].iloc[-6:-1].mean()
        if last["close"] > prev_trend:
            patterns.append(Candle("流星線", "bear", "高檔殺盤，反轉訊號"))
        else:
            patterns.append(Candle("倒鎚線", "bull", "低檔試探，注意反彈"))

    # --- 雙日組合 ---
    prev_bull = prev["close"] > prev["open"]
    last_bull = last["close"] > last["open"]

    # 多頭吞噬
    if (not prev_bull) and last_bull and \
       last["open"] < prev["close"] and last["close"] > prev["open"]:
        patterns.append(Candle("多頭吞噬", "bull", "紅棒完全包覆前黑棒，反攻訊號"))

    # 空頭吞噬
    if prev_bull and (not last_bull) and \
       last["open"] > prev["close"] and last["close"] < prev["open"]:
        patterns.append(Candle("空頭吞噬", "bear", "黑棒吞噬前紅棒，轉弱訊號"))

    # 貫穿線
    mid_prev = (prev["open"] + prev["close"]) / 2
    if (not prev_bull) and last_bull and \
       last["open"] < prev["low"] and last["close"] > mid_prev:
        patterns.append(Candle("貫穿線", "bull", "低開高走，收復前日一半以上"))

    # 烏雲罩頂
    if prev_bull and (not last_bull) and \
       last["open"] > prev["high"] and last["close"] < mid_prev:
        patterns.append(Candle("烏雲罩頂", "bear", "高開低走，吃掉前日一半以上"))

    return patterns
