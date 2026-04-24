"""朱家泓 — 四均線戰法 + K 線型態.

參考：《抓住 K 線獲利無限》
核心觀念：
  1. 週線定多空，日線找買賣點
  2. 四均線（5/10/20/60）多頭排列 → 順勢做多
  3. 買進三訊號：突破盤整、回測不破、均線多頭排列
  4. 賣出三訊號：跌破盤整、反彈遇壓、均線空頭排列
  5. 停損：短線破 MA10、中線破 MA20、絕對破前波低
  6. 量價配合：價漲量增為真、量縮上漲為背離
  7. 趨勢：頭頭高底底高為多頭、頭頭低底底低為空頭
"""
from __future__ import annotations

import pandas as pd

from .base import Signal

NAME = "朱家泓"
FULL_NAME = "朱家泓四均線 K 線戰法"
DESCRIPTION = (
    "四均線戰法 + K 線型態學；週線定多空、日線找買點；"
    "強調順勢交易、停損紀律、量價配合。"
)
REFERENCES = ["抓住K線獲利無限 — 朱家泓"]


# ===================================================================
# 均線排列
# ===================================================================
def ma_alignment(df: pd.DataFrame) -> tuple[str, str]:
    """朱式四均線：多頭排列 / 空頭排列 / 糾結 / 盤整."""
    row = df.iloc[-1]
    try:
        ma5, ma10, ma20, ma60 = row["ma5"], row["ma10"], row["ma20"], row["ma60"]
    except KeyError:
        return "未知", "均線資料不足"
    if any(pd.isna(x) for x in (ma5, ma10, ma20, ma60)):
        return "未知", "均線資料不足"

    if ma5 > ma10 > ma20 > ma60:
        up = all(df[f"ma{p}"].iloc[-1] > df[f"ma{p}"].iloc[-5] for p in (5, 10, 20))
        return ("多頭排列", "四均線多頭排列，趨勢向上；順勢做多") if up else \
               ("偏多", "均線多頭排列但斜率轉平，留意轉折")
    if ma5 < ma10 < ma20 < ma60:
        dn = all(df[f"ma{p}"].iloc[-1] < df[f"ma{p}"].iloc[-5] for p in (5, 10, 20))
        return ("空頭排列", "四均線空頭排列，趨勢向下；反彈即賣") if dn else \
               ("偏空", "均線空頭排列但斜率轉平")
    spread = (max(ma5, ma10, ma20, ma60) - min(ma5, ma10, ma20, ma60)) / row["close"]
    if spread < 0.02:
        return "均線糾結", "四均線糾結於 2% 內，等待方向選擇；觀望為宜"
    return "盤整", "均線交錯，無明確方向"


# ===================================================================
# 量價分析
# ===================================================================
def volume_analysis(df: pd.DataFrame) -> str:
    row = df.iloc[-1]
    prev = df.iloc[-2]
    if pd.isna(row.get("vol_ma5")):
        return "量能資料不足"
    vol_ratio = row["volume"] / row["vol_ma5"]
    price_up = row["close"] > prev["close"]
    if vol_ratio > 1.5 and price_up:
        return f"爆量長紅（{vol_ratio:.1f}x 5MA），價漲量增"
    if vol_ratio > 1.5 and not price_up:
        return f"爆量下殺（{vol_ratio:.1f}x 5MA），留意出貨"
    if vol_ratio < 0.6 and price_up:
        return f"量縮上漲（{vol_ratio:.1f}x 5MA），背離警訊"
    if vol_ratio < 0.6 and not price_up:
        return f"量縮整理（{vol_ratio:.1f}x 5MA），觀望"
    return f"量能正常（{vol_ratio:.1f}x 5MA）"


# ===================================================================
# 趨勢判斷（頭頭高底底高 / 頭頭低底底低）
# ===================================================================
def _trend_structure(df: pd.DataFrame, lookback: int = 40) -> str:
    """簡易波段趨勢判讀：比較近期高低點結構."""
    if len(df) < lookback:
        return "不明"
    tail = df.tail(lookback)
    mid = len(tail) // 2
    first_high = tail["high"].iloc[:mid].max()
    second_high = tail["high"].iloc[mid:].max()
    first_low = tail["low"].iloc[:mid].min()
    second_low = tail["low"].iloc[mid:].min()
    if second_high > first_high and second_low > first_low:
        return "頭頭高底底高（多頭趨勢）"
    if second_high < first_high and second_low < first_low:
        return "頭頭低底底低（空頭趨勢）"
    return "盤整"


# ===================================================================
# 訊號引擎 — 朱家泓買賣三訊號 + 輔助
# ===================================================================
def generate_signals(df: pd.DataFrame) -> list[Signal]:
    signals: list[Signal] = []
    if len(df) < 61:
        return signals

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # ===== 1. 均線黃金 / 死亡交叉 =====
    if prev["ma5"] <= prev["ma10"] and last["ma5"] > last["ma10"]:
        signals.append(Signal("entry", "5/10 日均線黃金交叉", 2, "短線買進訊號"))
    if prev["ma5"] >= prev["ma10"] and last["ma5"] < last["ma10"]:
        signals.append(Signal("exit", "5/10 日均線死亡交叉", 2, "短線賣出訊號"))
    if prev["ma20"] <= prev["ma60"] and last["ma20"] > last["ma60"]:
        signals.append(Signal("entry", "月/季線黃金交叉", 3, "中長線多頭確立"))
    if prev["ma20"] >= prev["ma60"] and last["ma20"] < last["ma60"]:
        signals.append(Signal("exit", "月/季線死亡交叉", 3, "中長線空頭確立"))

    # ===== 2. 回測均線不破（朱家泓買點 #2）=====
    for p, level in [(10, "短"), (20, "中"), (60, "長")]:
        ma = last.get(f"ma{p}")
        prev_ma = prev.get(f"ma{p}")
        if pd.isna(ma) or pd.isna(prev_ma):
            continue
        if last["low"] <= ma * 1.01 and last["close"] > ma and last["close"] > last["open"]:
            signals.append(Signal("entry", f"回測 {p} 日均線支撐",
                                  2 if p == 20 else 1,
                                  f"{level}線不破收紅，朱式進場訊號"))
        if prev["close"] >= prev_ma and last["close"] < ma:
            signals.append(Signal("exit", f"跌破 {p} 日均線",
                                  2 if p == 20 else 1,
                                  f"{level}線失守，空方抬頭"))

    # ===== 3. 突破盤整區 / 跌破盤整區（朱家泓買點 #1 / 賣點 #1）=====
    # 需求：量 > 2x VMA20 且價格突破 20 日高低點
    hi20 = df["high"].iloc[-22:-1].max()
    lo20 = df["low"].iloc[-22:-1].min()
    vr5 = last["volume"] / last["vol_ma5"] if last["vol_ma5"] else 0
    vr20 = (last["volume"] / last["vol_ma20"]
            if last.get("vol_ma20") else 0)
    if last["close"] > hi20:
        if vr20 >= 2.0:
            signals.append(Signal(
                "entry", "大量突破 20 日高點", 3,
                f"突破 {hi20:.2f}，量 {vr20:.1f}x VMA20；強勢買點"))
        elif vr5 >= 1.3:
            signals.append(Signal(
                "entry", "帶量突破 20 日高點", 2,
                f"突破 {hi20:.2f}，量 {vr5:.1f}x VMA5；但量能不足 2x VMA20"))
    if last["close"] < lo20:
        if vr20 >= 2.0:
            signals.append(Signal(
                "exit", "大量跌破 20 日低點", 3,
                f"跌破 {lo20:.2f}，量 {vr20:.1f}x VMA20；強勢賣點"))
        elif vr5 >= 1.3:
            signals.append(Signal(
                "exit", "帶量跌破 20 日低點", 2,
                f"跌破 {lo20:.2f}，量 {vr5:.1f}x VMA5"))

    # ===== 4. MACD 交叉 =====
    if prev["macd_dif"] <= prev["macd_dem"] and last["macd_dif"] > last["macd_dem"]:
        pos = last["macd_dif"] > 0
        signals.append(Signal("entry", "MACD 黃金交叉",
                              3 if pos else 2,
                              "零軸上交叉（強勢）" if pos else "零軸下交叉（反彈）"))
    if prev["macd_dif"] >= prev["macd_dem"] and last["macd_dif"] < last["macd_dem"]:
        neg = last["macd_dif"] < 0
        signals.append(Signal("exit", "MACD 死亡交叉",
                              3 if neg else 2,
                              "零軸下交叉（弱勢）" if neg else "零軸上交叉（轉弱）"))

    # ===== 5. KD 交叉 =====
    if prev["k"] <= prev["d"] and last["k"] > last["d"] and last["k"] < 30:
        signals.append(Signal("entry", "KD 低檔黃金交叉", 2, "超賣區反彈"))
    if prev["k"] >= prev["d"] and last["k"] < last["d"] and last["k"] > 70:
        signals.append(Signal("exit", "KD 高檔死亡交叉", 2, "超買區反轉"))

    # ===== 6. RSI 極值 =====
    if last["rsi"] < 30:
        signals.append(Signal("info", "RSI 超賣", 1, f"RSI={last['rsi']:.1f}"))
    elif last["rsi"] > 70:
        signals.append(Signal("info", "RSI 超買", 1, f"RSI={last['rsi']:.1f}"))

    # ===== 7. 爆量長紅 / 爆量長黑 =====
    chg = (last["close"] - last["open"]) / last["open"] * 100
    if vr5 > 2 and chg > 3:
        signals.append(Signal("entry", "爆量長紅", 3,
                              f"量 {vr5:.1f}x VMA5，漲 {chg:.1f}%"))
    if vr5 > 2 and chg < -3:
        signals.append(Signal("exit", "爆量長黑", 3,
                              f"量 {vr5:.1f}x VMA5，跌 {chg:.1f}%"))

    # ===== 8. 三關紅 / 三關黑（連三紅 / 連三黑）=====
    if len(df) >= 3:
        last3 = df.iloc[-3:]
        all_red = all(r["close"] > r["open"] for _, r in last3.iterrows())
        all_grn = all(r["close"] < r["open"] for _, r in last3.iterrows())
        step_up = last3["close"].is_monotonic_increasing
        step_dn = last3["close"].is_monotonic_decreasing
        if all_red and step_up:
            signals.append(Signal("entry", "三關紅", 2, "連三日收紅且逐日攀升"))
        if all_grn and step_dn:
            signals.append(Signal("exit", "三關黑", 2, "連三日收黑且逐日下探"))

    # ===== 9. 跳空缺口 =====
    if last["low"] > prev["high"]:
        signals.append(Signal("entry", "向上跳空缺口", 2,
                              f"開高 {last['open']:.2f} > 昨高 {prev['high']:.2f}"))
    if last["high"] < prev["low"]:
        signals.append(Signal("exit", "向下跳空缺口", 2,
                              f"開低 {last['open']:.2f} < 昨低 {prev['low']:.2f}"))

    return signals


# ===================================================================
# 停損停利
# ===================================================================
def stop_levels(df: pd.DataFrame) -> dict:
    """朱式三層停損（停損價為均線「跌破確認」= MA * 0.98）：
    - 短線：跌破 MA10（= MA10 × 0.98 視為確認跌破）
    - 中線：跌破 MA20（= MA20 × 0.98）
    - 絕對：前 20 日低點（絕不破）
    """
    last = df.iloc[-1]
    recent_low = df["low"].tail(20).min()
    ma10 = last.get("ma10")
    ma20 = last.get("ma20")
    return {
        # 停損設在 MA 下方 2%：代表「確認跌破」，給均線一個緩衝
        "short_stop": float(ma10) * 0.98 if not pd.isna(ma10) else None,
        "mid_stop": float(ma20) * 0.98 if not pd.isna(ma20) else None,
        "abs_stop": float(recent_low),
    }


# ===================================================================
# 趨勢結構摘要（供診斷書使用）
# ===================================================================
def trend_summary(df: pd.DataFrame) -> str:
    return _trend_structure(df)


# ===================================================================
# 評分權重（可被 diagnosis 呼叫）
# ===================================================================
def score_weights() -> dict:
    return {
        "ma_alignment": {"多頭排列": 30, "偏多": 12, "均線糾結": 0, "盤整": 0,
                         "偏空": -12, "空頭排列": -30, "未知": 0},
        "candle_bull": 6, "candle_bear": -6,
        "pattern_bull": 12, "pattern_bear": -12,
        "signal_per_strength": 4,
        "weekly_bias": 8,
        "volume_bonus": 8,
        # 法人：藉 institutional.score_adj() 直接取用 (±15)
        "institutional_scale": 1.0,
        # 融資券：藉 margin.score_adj() 取用 (±5)
        "margin_scale": 1.0,
        # 波浪：藉 wave.score_adj() 取用 (±15)
        "wave_scale": 1.0,
        # 計量物理 (Hurst/波動/分布)：±15
        "econ_scale": 1.0,
        # 黃金切割：±10
        "fib_scale": 1.0,
    }
