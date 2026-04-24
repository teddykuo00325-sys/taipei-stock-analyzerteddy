"""歷史訊號回測 — 掃描過去訊號發生點，統計後續 N 日報酬.

支援訊號：
  - MACD 黃金交叉 / 死亡交叉
  - KD 低檔黃金交叉 / 高檔死亡交叉
  - 均線 5/10 黃金 / 死亡交叉
  - 突破 / 跌破 20 日新高低
  - 爆量長紅 / 長黑
  - 紅三兵 / 三烏鴉
  - 早晨之星 / 夜星
  - 跳空上漲 / 跳空下跌
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import candlestick


FORWARD_DAYS = (5, 10, 20, 60)


@dataclass
class Event:
    date: pd.Timestamp
    kind: str          # "bull" / "bear"
    name: str
    price: float
    returns: dict      # {5: pct, 10: pct, ...}


def _detect_events(df: pd.DataFrame) -> list[Event]:
    events: list[Event] = []
    n = len(df)
    if n < 30:
        return events
    # 先算歷史 K 線型態
    cs_hist = candlestick.scan_history(df, lookback=n)

    for i in range(21, n):
        prev = df.iloc[i - 1]
        curr = df.iloc[i]
        date = df.index[i]
        price = float(curr["close"])

        def _add(kind, name):
            events.append(Event(date=date, kind=kind, name=name,
                                price=price, returns={}))

        # MACD 交叉
        if pd.notna(prev.get("macd_hist")) and pd.notna(curr.get("macd_hist")):
            if prev["macd_hist"] < 0 <= curr["macd_hist"]:
                _add("bull", "MACD 黃金交叉")
            elif prev["macd_hist"] >= 0 > curr["macd_hist"]:
                _add("bear", "MACD 死亡交叉")

        # KD 交叉（低檔 / 高檔）
        if pd.notna(prev.get("k")) and pd.notna(curr.get("k")):
            if (prev["k"] <= prev["d"] and curr["k"] > curr["d"]
                    and curr["k"] < 30):
                _add("bull", "KD 低檔黃金交叉")
            elif (prev["k"] >= prev["d"] and curr["k"] < curr["d"]
                    and curr["k"] > 70):
                _add("bear", "KD 高檔死亡交叉")

        # 均線 5/10 交叉
        if pd.notna(prev.get("ma5")) and pd.notna(curr.get("ma5")):
            if prev["ma5"] <= prev["ma10"] and curr["ma5"] > curr["ma10"]:
                _add("bull", "MA5/10 黃金交叉")
            elif prev["ma5"] >= prev["ma10"] and curr["ma5"] < curr["ma10"]:
                _add("bear", "MA5/10 死亡交叉")

        # 突破 / 跌破 20 日新高低
        if i >= 22:
            hi20 = df["high"].iloc[i - 21:i - 1].max()
            lo20 = df["low"].iloc[i - 21:i - 1].min()
            if pd.notna(curr.get("vol_ma5")) and curr["vol_ma5"] > 0:
                vr = curr["volume"] / curr["vol_ma5"]
                if curr["close"] > hi20 and vr > 1.3:
                    _add("bull", "帶量突破 20 日高")
                if curr["close"] < lo20 and vr > 1.3:
                    _add("bear", "帶量跌破 20 日低")

        # 爆量長紅 / 長黑
        if pd.notna(curr.get("vol_ma5")) and curr["vol_ma5"] > 0:
            vr = curr["volume"] / curr["vol_ma5"]
            chg = (curr["close"] - curr["open"]) / curr["open"] * 100 \
                if curr["open"] else 0
            if vr > 2 and chg > 3:
                _add("bull", "爆量長紅")
            if vr > 2 and chg < -3:
                _add("bear", "爆量長黑")

        # 跳空缺口
        if curr["low"] > prev["high"]:
            _add("bull", "向上跳空缺口")
        if curr["high"] < prev["low"]:
            _add("bear", "向下跳空缺口")

    # K 線型態（紅三兵、三烏鴉、早晨之星、夜星、吞噬）
    focus = {"紅三兵", "三烏鴉", "早晨之星", "夜星",
             "多頭吞噬", "空頭吞噬", "鎚子線", "吊人線",
             "流星線", "貫穿線", "烏雲罩頂"}
    for (idx, candles) in cs_hist:
        if idx >= n:
            continue
        date = df.index[idx]
        price = float(df.iloc[idx]["close"])
        for c in candles:
            if c.name in focus:
                events.append(Event(date=date,
                                    kind=("bull" if c.signal == "bull"
                                          else "bear" if c.signal == "bear"
                                          else "neutral"),
                                    name=c.name, price=price, returns={}))

    # 計算 forward 報酬
    for e in events:
        try:
            i = df.index.get_loc(e.date)
        except KeyError:
            continue
        for k in FORWARD_DAYS:
            if i + k < n:
                future_price = float(df["close"].iloc[i + k])
                e.returns[k] = (future_price / e.price - 1) * 100

    return events


def summarize(events: list[Event]) -> pd.DataFrame:
    """依訊號類型匯總：次數、勝率、平均/中位/極值報酬."""
    rows = []
    by_name: dict[str, list[Event]] = {}
    for e in events:
        by_name.setdefault(e.name, []).append(e)

    for name, evs in by_name.items():
        if not evs:
            continue
        kind = evs[0].kind
        # 對每個 forward day 計算
        row: dict = {"訊號": name, "方向": kind, "次數": len(evs)}
        for k in FORWARD_DAYS:
            rs = [e.returns[k] for e in evs if k in e.returns]
            if not rs:
                row[f"T+{k} 勝率%"] = None
                row[f"T+{k} 均報酬%"] = None
                continue
            arr = np.array(rs)
            # 多頭訊號：報酬 > 0 視為勝；空頭：報酬 < 0 視為勝
            if kind == "bull":
                win_rate = float((arr > 0).mean() * 100)
            elif kind == "bear":
                win_rate = float((arr < 0).mean() * 100)
            else:
                win_rate = float((arr > 0).mean() * 100)
            row[f"T+{k} 勝率%"] = round(win_rate, 1)
            row[f"T+{k} 均報酬%"] = round(float(arr.mean()), 2)
        rows.append(row)

    df_out = pd.DataFrame(rows)
    if df_out.empty:
        return df_out
    df_out = df_out.sort_values(["方向", "T+20 勝率%"], ascending=[True, False])
    return df_out.reset_index(drop=True)


def run(df: pd.DataFrame) -> tuple[list[Event], pd.DataFrame]:
    events = _detect_events(df)
    return events, summarize(events)
