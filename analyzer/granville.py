"""葛蘭碧 (Granville) 八大法則 — 移動平均線進出場訊號.

8 條法則以股價 vs MA 之關係 + MA 趨勢方向綜合判讀：

買進訊號 (Buy):
  1. 突破買進 (Breakout)  — MA 由跌轉平/向上 + 價格上穿 MA
  2. 回測買進 (Pullback)  — 價格在 MA 上 + 短暫跌破但 MA 仍向上
  3. 乖離買進 (Bounce)    — 價格未破 MA 但靠近 + MA 仍向上
  4. 超賣買進 (Oversold)  — 價格遠低於上升 MA（過大負乖離）→ 均值回歸

賣出訊號 (Sell):
  5. 跌破賣出 (Breakdown) — MA 由漲轉平/向下 + 價格下穿 MA
  6. 反彈賣出 (Bounce-S)  — 價格在 MA 下 + 短暫站上但 MA 仍向下
  7. 反壓賣出 (Resist)    — 價格未站上 MA 但靠近 + MA 仍向下
  8. 超買賣出 (Overbought)— 價格遠高於下跌 MA（過大正乖離）→ 均值回歸

設計：
  - 預設用 20MA 偵測（朱家泓常用波段中軸）；可選 60MA（中長線）
  - 每根 K 棒只能對應一條法則（取最相關的）
  - 訊號強度依：MA 斜率、突破幅度、乖離率
  - 最後一根 K 的訊號用於評分；近 60 根的訊號用於圖表標記
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class GranvilleSignal:
    rule: int                  # 1~8
    name: str                  # 法則名稱
    side: str                  # "buy" / "sell"
    bar_idx: int               # df 中的位置（負數為從末尾算）
    date: str                  # YYYY-MM-DD
    price: float
    ma_value: float
    ma_slope: float            # MA 斜率（每日 % 變化）
    deviation_pct: float       # 乖離率 (price - ma) / ma * 100
    strength: int              # 1~3 訊號強度
    note: str


@dataclass
class GranvilleAnalysis:
    ma_period: int                          # 使用哪條 MA（20/60）
    last_signal: GranvilleSignal | None    # 最近一根 K 的訊號（評分用）
    history: list[GranvilleSignal]         # 近 60 根所有訊號（圖表標記）
    score: int                              # -15 ~ +15
    note: str                               # 文字說明


# === 各參數 ===
# MA 斜率閾值：每日變化百分比
SLOPE_FLAT = 0.05         # |slope| < 0.05% → 平
SLOPE_RISING = 0.10       # slope >= 0.10% → 向上
SLOPE_FALLING = -0.10     # slope <= -0.10% → 向下
# 乖離率閾值
DEV_NEAR = 1.5            # |dev| <= 1.5% → 接近 MA
DEV_BIG = 8.0             # |dev| >= 8% → 過大（超買/超賣）
# 突破/跌破容忍：以 ATR 或 0.5% 為單位


def _ma_direction(ma_series: pd.Series, idx: int,
                   lookback: int = 5) -> tuple[str, float]:
    """判斷 MA 方向：'up' / 'flat' / 'down'，並回傳近 lookback 日的平均斜率%."""
    start = max(0, idx - lookback)
    if start >= idx or pd.isna(ma_series.iloc[idx]) \
            or pd.isna(ma_series.iloc[start]):
        return "flat", 0.0
    days = idx - start
    pct_per_day = ((ma_series.iloc[idx] / ma_series.iloc[start]) ** (1 / days)
                   - 1) * 100
    if pct_per_day >= SLOPE_RISING:
        return "up", pct_per_day
    if pct_per_day <= SLOPE_FALLING:
        return "down", pct_per_day
    return "flat", pct_per_day


def _detect_at(df: pd.DataFrame, ma_col: str, idx: int
                ) -> GranvilleSignal | None:
    """對 idx 這根 K 棒檢查 8 條法則，回傳第一個匹配的訊號（或 None）."""
    if idx < 1 or idx >= len(df):
        return None
    ma = df[ma_col]
    if pd.isna(ma.iloc[idx]):
        return None

    cur_close = float(df["close"].iloc[idx])
    cur_low = float(df["low"].iloc[idx])
    cur_high = float(df["high"].iloc[idx])
    prev_close = float(df["close"].iloc[idx - 1])
    cur_ma = float(ma.iloc[idx])
    prev_ma = float(ma.iloc[idx - 1]) if not pd.isna(ma.iloc[idx - 1]) \
        else cur_ma

    direction, slope_pct = _ma_direction(ma, idx)
    dev_pct = (cur_close / cur_ma - 1) * 100

    date_str = df.index[idx].strftime("%Y-%m-%d") \
        if hasattr(df.index[idx], "strftime") else str(idx)

    def _make(rule: int, name: str, side: str, strength: int,
              note: str) -> GranvilleSignal:
        return GranvilleSignal(
            rule=rule, name=name, side=side,
            bar_idx=idx, date=date_str,
            price=cur_close, ma_value=cur_ma,
            ma_slope=round(slope_pct, 3),
            deviation_pct=round(dev_pct, 2),
            strength=strength, note=note,
        )

    # === 買進法則 ===
    # 1. 突破買進：MA 平/上 + 價格上穿 MA（前一根在下，今根收上）
    if direction in ("up", "flat") and prev_close <= prev_ma \
            and cur_close > cur_ma:
        # 強度：MA 已轉向上 3 ☆，仍平 2 ☆，乖離過大降 1 ☆
        s = 3 if direction == "up" else 2
        if dev_pct > 5:
            s = max(1, s - 1)
        return _make(1, "突破買進", "buy", s,
                     f"MA{('向上' if direction=='up' else '走平')}，價格上穿"
                     f"（乖離 {dev_pct:+.1f}%）")

    # 2. 回測買進：MA 向上 + 今天最低跌破 MA 但收盤站回 + 前一根在 MA 上
    if direction == "up" and prev_close > prev_ma \
            and cur_low < cur_ma and cur_close >= cur_ma:
        s = 3 if slope_pct > 0.3 else 2
        return _make(2, "回測買進", "buy", s,
                     f"MA 上升中 ({slope_pct:+.2f}%/日)，盤中跌破 MA "
                     f"但收盤守穩")

    # 3. 乖離買進：MA 向上 + 價格在 MA 上但接近（跌深反彈靠近 MA）
    #    觸發條件：今天 close 距 MA 在 [-DEV_NEAR, +DEV_NEAR]，前 3 日有更接近 MA 但未破
    if direction == "up" and 0 <= dev_pct <= DEV_NEAR \
            and cur_close > cur_ma:
        # 確認近期有真的回測（下跌段）— 過去 5 日內最低 / cur_close < 1
        recent_low = float(df["low"].iloc[max(0, idx - 4):idx + 1].min())
        if recent_low < cur_close * 0.97:  # 5 日內曾下跌超過 3%
            return _make(3, "乖離買進", "buy", 2,
                         f"MA 仍上升，價格回靠 MA（乖離 {dev_pct:+.1f}%）"
                         f"未破支撐")

    # 4. 超賣買進：MA 向上 + 乖離極小（負）
    if direction == "up" and dev_pct <= -DEV_BIG:
        s = 3 if dev_pct <= -12 else 2
        return _make(4, "超賣買進", "buy", s,
                     f"上升 MA 過大負乖離 {dev_pct:.1f}%，均值回歸機會")

    # === 賣出法則 ===
    # 5. 跌破賣出：MA 平/下 + 價格下穿 MA
    if direction in ("down", "flat") and prev_close >= prev_ma \
            and cur_close < cur_ma:
        s = 3 if direction == "down" else 2
        if dev_pct < -5:
            s = max(1, s - 1)
        return _make(5, "跌破賣出", "sell", s,
                     f"MA{('向下' if direction=='down' else '走平')}，價格下穿"
                     f"（乖離 {dev_pct:+.1f}%）")

    # 6. 反彈賣出：MA 向下 + 今天最高站上 MA 但收盤回到下方 + 前一根在 MA 下
    if direction == "down" and prev_close < prev_ma \
            and cur_high > cur_ma and cur_close <= cur_ma:
        s = 3 if slope_pct < -0.3 else 2
        return _make(6, "反彈賣出", "sell", s,
                     f"MA 下降中 ({slope_pct:+.2f}%/日)，盤中觸 MA "
                     f"但收盤受壓")

    # 7. 反壓賣出：MA 向下 + 價格在 MA 下但接近
    if direction == "down" and -DEV_NEAR <= dev_pct < 0 \
            and cur_close < cur_ma:
        recent_high = float(df["high"].iloc[max(0, idx - 4):idx + 1].max())
        if recent_high > cur_close * 1.03:
            return _make(7, "反壓賣出", "sell", 2,
                         f"MA 仍下降，價格反彈靠 MA（乖離 {dev_pct:+.1f}%）"
                         f"未過壓力")

    # 8. 超買賣出：MA 向下 + 乖離極大（正）
    if direction == "down" and dev_pct >= DEV_BIG:
        s = 3 if dev_pct >= 12 else 2
        return _make(8, "超買賣出", "sell", s,
                     f"下降 MA 過大正乖離 +{dev_pct:.1f}%，反轉機率高")

    return None


def analyze(df: pd.DataFrame, ma_period: int = 20,
            history_lookback: int = 60) -> GranvilleAnalysis:
    """主函式：分析整個 df，回傳近 history_lookback 根所有 Granville 訊號 + 評分.

    df 需含 'close'/'low'/'high' 欄位 + maN 欄位（由 indicators.add_all 提供）。
    """
    ma_col = f"ma{ma_period}"
    if ma_col not in df.columns:
        return GranvilleAnalysis(ma_period, None, [], 0,
                                  f"無 {ma_col} 欄位")
    if len(df) < ma_period + 5:
        return GranvilleAnalysis(ma_period, None, [], 0,
                                  f"資料不足（< {ma_period + 5} 根）")

    history: list[GranvilleSignal] = []
    start = max(ma_period, len(df) - history_lookback)
    for i in range(start, len(df)):
        sig = _detect_at(df, ma_col, i)
        if sig is not None:
            history.append(sig)

    last = history[-1] if history else None
    # 最近 K 棒（即使沒訊號也可能要 fallback）
    if last is None:
        # 沒新訊號 → 看最後一根的 MA 關係給粗略偏向
        last_close = float(df["close"].iloc[-1])
        last_ma = float(df[ma_col].iloc[-1]) if not pd.isna(
            df[ma_col].iloc[-1]) else last_close
        direction, slope = _ma_direction(df[ma_col], len(df) - 1)
        if direction == "up" and last_close > last_ma:
            return GranvilleAnalysis(
                ma_period, None, history, 3,
                f"MA{ma_period} 向上，價在線上（無新進出場訊號，多頭結構）")
        if direction == "down" and last_close < last_ma:
            return GranvilleAnalysis(
                ma_period, None, history, -3,
                f"MA{ma_period} 向下，價在線下（無新進出場訊號，空頭結構）")
        return GranvilleAnalysis(
            ma_period, None, history, 0,
            f"MA{ma_period} 走平，無明確訊號")

    # 有訊號 → 依規則 + 強度給分
    BASE = {
        1: 12,   # 突破買進（最強買訊）
        2: 8,    # 回測買進
        3: 5,    # 乖離買進
        4: 7,    # 超賣買進
        5: -12,  # 跌破賣出（最強賣訊）
        6: -8,   # 反彈賣出
        7: -5,   # 反壓賣出
        8: -7,   # 超買賣出
    }
    base = BASE.get(last.rule, 0)
    # strength 1~3 → 0.6 / 0.85 / 1.0 倍
    mult = {1: 0.6, 2: 0.85, 3: 1.0}.get(last.strength, 0.85)
    score = int(round(base * mult))
    note = (f"葛蘭碧 #{last.rule} {last.name}"
            f"（{last.side.upper()} 強度 {last.strength}/3）：{last.note}")

    return GranvilleAnalysis(
        ma_period=ma_period, last_signal=last, history=history,
        score=score, note=note,
    )


def summarize(df: pd.DataFrame, ma_period: int = 20) -> str:
    a = analyze(df, ma_period=ma_period)
    if a.last_signal:
        return f"葛蘭碧 #{a.last_signal.rule} {a.last_signal.name}"
    return a.note


def score_adj(df: pd.DataFrame, ma_period: int = 20) -> tuple[int, str]:
    """供 diagnosis 直接呼叫的評分介面."""
    a = analyze(df, ma_period=ma_period)
    return a.score, a.note
