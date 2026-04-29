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
    # 強化版欄位（黃金切割率驗證）
    wave_ratios: dict | None = None        # 波長比例 {"w3_w1": 1.65, ...}
    fib_validated: bool = False            # 是否符合 Fibonacci 黃金切割比
    sub_pattern: str = ""                  # 子型態：Impulse/Zigzag/Flat/Triangle


def _find_pivots(prices: np.ndarray, order: int) -> list[tuple[int, str, float]]:
    highs = argrelextrema(prices, np.greater, order=order)[0]
    lows = argrelextrema(prices, np.less, order=order)[0]
    pivots = [(int(i), "H", float(prices[i])) for i in highs] + \
             [(int(i), "L", float(prices[i])) for i in lows]
    pivots.sort(key=lambda x: x[0])
    return pivots


# === 黃金切割比例（Elliott 經典） ===
# 第 3 波長度應 ≥ 第 1 波 × 1.618（最常見），或 1.0/2.618
# 第 2 波回檔幅度 0.382 ~ 0.618 of 第 1 波
# 第 4 波回檔幅度 0.236 ~ 0.382 of 第 3 波
# 第 5 波長度約 = 第 1 波（等長）或 0.618 of (第 1 波 + 第 3 波)
def _validate_impulse_ratios(seq: list[tuple[int, str, float]]
                              ) -> tuple[bool, dict, str]:
    """驗證上升 5 波結構是否符合 Fibonacci 比例.

    seq = [L0, H1, L2, H3, L4, H5]（六個 pivot）
    回傳 (是否符合, ratios dict, 子型態)
    """
    if len(seq) < 6:
        return False, {}, "Incomplete"
    L0 = seq[0][2]; H1 = seq[1][2]; L2 = seq[2][2]
    H3 = seq[3][2]; L4 = seq[4][2]; H5 = seq[5][2]
    w1 = H1 - L0
    w2 = H1 - L2
    w3 = H3 - L2
    w4 = H3 - L4
    w5 = H5 - L4
    if w1 <= 0 or w3 <= 0 or w5 <= 0:
        return False, {}, "Invalid"
    ratios = {
        "w2/w1_retrace": round(w2 / w1, 3) if w1 > 0 else None,
        "w3/w1": round(w3 / w1, 3),
        "w4/w3_retrace": round(w4 / w3, 3) if w3 > 0 else None,
        "w5/w1": round(w5 / w1, 3),
    }
    # 經典條件
    cond_w3 = w3 >= w1 * 1.0           # 第 3 波 ≥ 第 1 波（最低）
    cond_w3_strong = w3 >= w1 * 1.618  # 強勢第 3 波
    cond_w2 = 0.3 <= ratios["w2/w1_retrace"] <= 0.7
    cond_w4 = 0.15 <= ratios["w4/w3_retrace"] <= 0.5
    cond_w4_no_overlap = L4 > H1       # 第 4 波不可跌入第 1 波區（鐵律）

    n_ok = sum([cond_w3, cond_w2, cond_w4, cond_w4_no_overlap])
    valid = n_ok >= 3
    pattern = "Impulse-Strong" if cond_w3_strong and valid \
        else "Impulse" if valid \
        else "Impulse-Doubtful"
    return valid, ratios, pattern


def _validate_corrective_abc(seq: list[tuple[int, str, float]]
                              ) -> tuple[bool, dict, str]:
    """ABC 修正結構驗證 + Zigzag/Flat/Triangle 分類.

    seq = [Start, A, B, C]（4 個 pivot；上漲後修正：H → L → H → L）
    """
    if len(seq) < 4:
        return False, {}, "Incomplete"
    P0 = seq[0][2]; A = seq[1][2]; B = seq[2][2]; C = seq[3][2]
    wa = abs(P0 - A)   # A 波幅度
    wb = abs(A - B)    # B 波反彈幅度
    wc = abs(B - C)    # C 波幅度
    if wa <= 0 or wc <= 0:
        return False, {}, "Invalid"
    ratios = {
        "B/A_retrace": round(wb / wa, 3),
        "C/A": round(wc / wa, 3),
    }
    # Zigzag: B 反彈 < 0.618A，C ≥ A（深修正）
    if ratios["B/A_retrace"] < 0.618 and ratios["C/A"] >= 1.0:
        return True, ratios, "Zigzag"
    # Flat: B 反彈 ≈ A（>= 0.9），C ≈ A
    if ratios["B/A_retrace"] >= 0.9 and 0.9 <= ratios["C/A"] <= 1.1:
        return True, ratios, "Flat"
    # Triangle: 各波收斂（C < A 且 B 介於）
    if ratios["C/A"] < 0.7 and 0.4 <= ratios["B/A_retrace"] <= 0.9:
        return True, ratios, "Triangle"
    return False, ratios, "Irregular"


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

    # === 強化判斷：6 個 pivot 驗證上升 5 波（含黃金切割率） ===
    if len(recent) >= 6:
        seq6 = recent[-6:]
        types6 = [p[1] for p in seq6]
        # 上升 5 波 = L H L H L H（起點低、終點高）
        if types6 == ["L", "H", "L", "H", "L", "H"]:
            ok, ratios, sub = _validate_impulse_ratios(seq6)
            conf = "高" if sub == "Impulse-Strong" else "中" if ok else "低"
            note = (f"完整 5 波結構 [{sub}]"
                    + (f"，w3/w1={ratios.get('w3/w1')}"
                       f"，w4 不入 w1 區 ✓" if ok else "，比例不符"))
            return Wave("已完成上升 5 波（高位風險）", "up", 5, conf,
                        note, pivots,
                        wave_ratios=ratios, fib_validated=ok,
                        sub_pattern=sub)
        # 下跌 5 波 = H L H L H L
        if types6 == ["H", "L", "H", "L", "H", "L"]:
            # 鏡像驗證：把高低互換做 impulse 檢查
            inv = [(i, "H" if t == "L" else "L", -p) for i, t, p in seq6]
            ok, ratios, sub = _validate_impulse_ratios(inv)
            conf = "高" if sub == "Impulse-Strong" else "中" if ok else "低"
            return Wave("已完成下跌 5 波（低位反彈機會）", "down", 5, conf,
                        f"完整下跌 5 波 [{sub}]", pivots,
                        wave_ratios=ratios, fib_validated=ok,
                        sub_pattern=sub)

    # 1. 取最後 5 個 pivot 判斷未完成 5 波結構
    if len(recent) >= 5:
        seq = recent[-5:]
        types = [p[1] for p in seq]
        prices = [p[2] for p in seq]

        lhs = all(t in ("H", "L") for t in types)
        if lhs and types[0] == "L" and types[-1] == "L":
            # L H L H L → 5 波之 4 波末（尚未漲出 5 波）或 ABC 修正末
            if prices[1] < prices[3] and prices[2] < prices[4] < prices[1]:
                if last_price > prices[-1]:
                    # 嘗試驗證 w3/w1 比例
                    seq_ext = seq + [(len(tail) - 1, "H", last_price)]
                    ok, ratios, sub = _validate_impulse_ratios(seq_ext)
                    conf = "中" if ok else "低"
                    return Wave("第 5 波上漲中", "up", 5, conf,
                                f"進入第 5 波 [{sub}]，留意末升段風險",
                                pivots,
                                wave_ratios=ratios, fib_validated=ok,
                                sub_pattern=sub)
                return Wave("第 4 波修正末", "up", 4, "中",
                            "第 4 波尾聲，可能展開第 5 波", pivots,
                            sub_pattern="Wave-4-end")
        if lhs and types[0] == "H" and types[-1] == "H":
            if prices[1] > prices[3] and prices[2] > prices[4] > prices[1]:
                if last_price < prices[-1]:
                    return Wave("下跌第 5 波", "down", 5, "中",
                                "空頭末跌段，留意反彈", pivots,
                                sub_pattern="Wave-5-down")

    # 2. ABC 修正辨識（4 個 pivot：起點 → A → B → C）
    if len(recent) >= 4:
        seq4 = recent[-4:]
        types4 = [p[1] for p in seq4]
        # 上漲後修正：H L H L
        if types4 == ["H", "L", "H", "L"]:
            ok, ratios, sub = _validate_corrective_abc(seq4)
            if ok:
                conf = "中"
                if last_price > seq4[-1][2]:
                    return Wave(f"ABC 修正末 ({sub})", "corrective", 3, conf,
                                f"{sub} 修正完成，反彈訊號"
                                f"（B/A={ratios.get('B/A_retrace')}，"
                                f"C/A={ratios.get('C/A')}）", pivots,
                                wave_ratios=ratios, fib_validated=True,
                                sub_pattern=sub)
                return Wave(f"ABC 修正進行中 ({sub})", "corrective", 3, conf,
                            f"修正型態 {sub}，建議觀望", pivots,
                            wave_ratios=ratios, fib_validated=True,
                            sub_pattern=sub)

    # 3. 最近 3 轉折判斷方向
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
