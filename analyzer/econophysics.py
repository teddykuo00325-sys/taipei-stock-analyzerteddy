"""計量物理學指標 — Hurst 指數、波動率、收益分布.

- Hurst Exponent (H)：測量長期記憶 / 趨勢持續性
    H > 0.55 → 趨勢性 (persistent)：均線/趨勢策略有效
    H ≈ 0.50 → 隨機漫步 (random walk)
    H < 0.45 → 均值回歸 (mean-reverting)：波段/反向策略有效
- 波動率狀態：近期 vs 長期對比；突升為警訊
- 收益分布：偏度、峰度；高峰度代表肥尾風險
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Econ:
    hurst: float             # 0~1（> 0.55 趨勢; < 0.45 回歸）
    hurst_label: str
    vol_recent: float        # 近 20 日年化波動率
    vol_long: float          # 近 120 日年化波動率
    vol_ratio: float         # recent / long
    vol_label: str
    skew: float              # 收益偏度
    kurt: float              # 超額峰度
    risk_label: str          # 分布風險提示


# ---------------------------------------------------------------
# Hurst 指數 (R/S analysis)
# ---------------------------------------------------------------
def hurst(series: pd.Series | np.ndarray,
          lags: tuple = (10, 20, 40, 80)) -> float:
    arr = np.asarray(series, dtype=float)
    n = len(arr)
    valid_lags = [lag for lag in lags if lag <= n // 2]
    if len(valid_lags) < 2:
        return 0.5
    rs_vals: list[float] = []
    for lag in valid_lags:
        seg_count = n // lag
        rs_per = []
        for s in range(seg_count):
            seg = arr[s * lag:(s + 1) * lag]
            if len(seg) < 2:
                continue
            mean = seg.mean()
            dev = seg - mean
            cum = np.cumsum(dev)
            R = cum.max() - cum.min()
            S = seg.std()
            if S > 0:
                rs_per.append(R / S)
        if rs_per:
            rs_vals.append(np.mean(rs_per))
    if len(rs_vals) < 2:
        return 0.5
    slope, _ = np.polyfit(np.log(valid_lags[:len(rs_vals)]), np.log(rs_vals), 1)
    return float(np.clip(slope, 0.0, 1.0))


def _hurst_label(h: float) -> str:
    if h > 0.60:
        return "強趨勢 (H={:.2f})".format(h)
    if h > 0.55:
        return "趨勢性 (H={:.2f})".format(h)
    if h > 0.45:
        return "隨機 (H={:.2f})".format(h)
    if h > 0.40:
        return "均值回歸 (H={:.2f})".format(h)
    return "強均值回歸 (H={:.2f})".format(h)


# ---------------------------------------------------------------
# 波動率
# ---------------------------------------------------------------
def _annualized_vol(returns: pd.Series) -> float:
    if returns.empty or returns.std() == 0:
        return 0.0
    return float(returns.std() * np.sqrt(252))


def _vol_label(ratio: float) -> str:
    if ratio >= 2.0:
        return "波動劇升 (x{:.1f})".format(ratio)
    if ratio >= 1.5:
        return "波動偏高 (x{:.1f})".format(ratio)
    if ratio >= 0.8:
        return "波動穩定 (x{:.1f})".format(ratio)
    return "波動極低 (x{:.1f})".format(ratio)


# ---------------------------------------------------------------
# 收益分布
# ---------------------------------------------------------------
def _risk_label(kurt: float, skew: float) -> str:
    if kurt > 5:
        return "肥尾風險高" + (" · 左偏" if skew < -0.5 else "")
    if kurt > 2:
        return "中度肥尾"
    if skew < -1:
        return "明顯左偏（下跌風險）"
    if skew > 1:
        return "明顯右偏（上漲動能）"
    return "常態分布"


# ---------------------------------------------------------------
# 整合
# ---------------------------------------------------------------
def compute(df: pd.DataFrame) -> Econ:
    prices = df["close"].astype(float)
    log_ret = np.log(prices / prices.shift(1)).dropna()
    h = hurst(prices.tail(200)) if len(prices) >= 40 else 0.5
    vol_r = _annualized_vol(log_ret.tail(20))
    vol_l = _annualized_vol(log_ret.tail(120))
    ratio = vol_r / vol_l if vol_l > 0 else 1.0
    skew = float(log_ret.tail(120).skew()) if len(log_ret) >= 30 else 0.0
    kurt = float(log_ret.tail(120).kurt()) if len(log_ret) >= 30 else 0.0
    return Econ(
        hurst=h, hurst_label=_hurst_label(h),
        vol_recent=vol_r, vol_long=vol_l, vol_ratio=ratio,
        vol_label=_vol_label(ratio),
        skew=skew, kurt=kurt,
        risk_label=_risk_label(kurt, skew),
    )


def score_adj(df: pd.DataFrame) -> tuple[int, str]:
    """計量物理給分（-15 ~ +15）：
    - H > 0.55 與趨勢同向 → +8（趨勢真實）
    - H < 0.45 → 均線策略失效警訊 (-5)
    - 波動率突升 (>2x) → -5（避險）
    - 肥尾風險高 → -3（分布警訊）
    """
    e = compute(df)
    last = df.iloc[-1]
    # 近期趨勢方向
    ma20 = last.get("ma20")
    close = last["close"]
    trend_up = (ma20 is not None) and (not pd.isna(ma20)) and (close > ma20)
    score = 0
    notes: list[str] = []
    if e.hurst > 0.55 and trend_up:
        score += 8
        notes.append(f"Hurst {e.hurst:.2f} 趨勢真實")
    elif e.hurst > 0.55 and not trend_up:
        score -= 5
        notes.append(f"Hurst {e.hurst:.2f} 趨勢向下")
    elif e.hurst < 0.45:
        score -= 5
        notes.append(f"Hurst {e.hurst:.2f} 均值回歸，均線策略效度低")
    if e.vol_ratio >= 2.0:
        score -= 5
        notes.append(f"波動 x{e.vol_ratio:.1f} 突升")
    elif e.vol_ratio >= 1.5:
        score -= 2
        notes.append(f"波動 x{e.vol_ratio:.1f} 偏高")
    if e.kurt > 5:
        score -= 3
        notes.append("肥尾風險")
    return score, "；".join(notes)
