"""籌碼派 — 以三大法人買賣超 + 融資融券為核心判讀.

核心觀念：
  1. 跟隨大戶：外資/投信方向決定短中期走勢
  2. 投信動向：轉買/連買強度判讀
  3. 融券增加：軋空潛力
  4. 融資暴增：散戶追高警訊
"""
from __future__ import annotations

import pandas as pd

from . import chu_chia_hung as _chu
from .base import Signal

NAME = "籌碼派"
FULL_NAME = "籌碼派 — 法人/融資券主導"
DESCRIPTION = (
    "以外資、投信、自營商買賣超及融資融券變化為核心判讀，"
    "順應大戶方向；技術面權重降低，資金面權重加倍。"
)
REFERENCES = ["TWSE 三大法人買賣超 T86", "TWSE 融資融券 MI_MARGN"]


# 重用技術面函式
ma_alignment = _chu.ma_alignment
volume_analysis = _chu.volume_analysis
stop_levels = _chu.stop_levels
trend_summary = _chu.trend_summary


def generate_signals(df: pd.DataFrame) -> list[Signal]:
    """籌碼派訊號：保留關鍵技術交叉 + 弱化其他."""
    signals = _chu.generate_signals(df)
    # 降低非籌碼訊號強度
    filtered: list[Signal] = []
    for s in signals:
        if any(k in s.name for k in ["MACD", "突破 20 日", "跌破 20 日",
                                       "爆量長紅", "爆量長黑"]):
            filtered.append(s)  # 保留
        else:
            # 其他訊號降為 info
            if s.strength >= 2:
                filtered.append(Signal(kind="info", name=s.name,
                                       strength=1, note=s.note))
    return filtered


def score_weights() -> dict:
    """籌碼派：法人/融資券 x2 權重、技術面減半."""
    return {
        "ma_alignment": {"多頭排列": 15, "偏多": 6, "均線糾結": 0, "盤整": 0,
                         "偏空": -6, "空頭排列": -15, "未知": 0},
        "candle_bull": 3, "candle_bear": -3,
        "pattern_bull": 6, "pattern_bear": -6,
        "signal_per_strength": 2,
        "weekly_bias": 4,
        "volume_bonus": 4,
        "institutional_scale": 2.0,   # 法人加倍
        "margin_scale": 2.0,          # 融資券加倍
        "wave_scale": 0.5,
        "econ_scale": 0.5,
        "fib_scale": 0.5,
    }
