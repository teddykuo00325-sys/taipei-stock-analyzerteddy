"""多目標價推算 — 整合技術面、基本面、法人共識.

提供六種目標價參考：
  1. 短線：52 週新高 + 5~8% 緩衝 / 近期壓力
  2. 中線：費波納契 127.2% 延伸
  3. 長線：費波納契 161.8% 延伸
  4. 週線壓力：週 K 近 6 個月最高 pivot
  5. 月線壓力：月 K 近 2 年最高 pivot
  6. 基本面：forward EPS × 合理 PE (trailing PE) - 簡化模型
  7. 法人共識：yfinance analyst targetMeanPrice (+ High/Low range)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd
import yfinance as yf

logging.getLogger("yfinance").setLevel(logging.CRITICAL)


@dataclass
class Target:
    label: str          # 顯示名稱
    icon: str
    price: float
    pct: float          # % 距現價
    note: str           # 依據
    confidence: str     # "高 / 中 / 低"


def _pct(price: float, base: float) -> float:
    if base <= 0:
        return 0
    return (price / base - 1) * 100


def compute_all(df: pd.DataFrame,
                code: str,
                fib=None,
                weekly_df: pd.DataFrame | None = None,
                monthly_df: pd.DataFrame | None = None,
                revenue_info=None) -> dict:
    """回傳 dict of Target 列表 + 法人 range + pe info."""
    if df.empty:
        return {"targets": [], "analyst": None, "fundamental": None}

    price = float(df["close"].iloc[-1])
    out: list[Target] = []
    analyst_info = None
    fundamental_info = None

    # --- 1. 短線：52 週新高 buffer ---
    ath = float(df["high"].max())
    if price >= ath * 0.98:
        # 已接近 / 突破歷史高 → +8%
        st = ath * 1.08
        note = f"突破歷史高 {ath:.2f} 後 +8% 延伸"
    else:
        st = ath
        note = f"回測近期歷史高 {ath:.2f}"
    out.append(Target(
        label="短線目標", icon="⚡", price=round(st, 2),
        pct=round(_pct(st, price), 2),
        note=note, confidence="中",
    ))

    # --- 2. 中線：Fib 127.2% 延伸 ---
    if fib and fib.direction == "up":
        diff = fib.swing_high - fib.swing_low
        mid = fib.swing_low + diff * 1.272
        out.append(Target(
            label="中線目標 (Fib 127.2%)", icon="🎯",
            price=round(mid, 2), pct=round(_pct(mid, price), 2),
            note=f"自 {fib.swing_low:.2f}~{fib.swing_high:.2f} "
                 f"延伸 127.2%",
            confidence="中",
        ))
        # --- 3. 長線：Fib 161.8% ---
        long_p = fib.swing_low + diff * 1.618
        out.append(Target(
            label="長線目標 (Fib 161.8%)", icon="🚀",
            price=round(long_p, 2), pct=round(_pct(long_p, price), 2),
            note=f"黃金延伸比 1.618；波段滿足點",
            confidence="中",
        ))
    elif fib and fib.direction == "down":
        diff = fib.swing_high - fib.swing_low
        mid = fib.swing_high - diff * 1.272
        out.append(Target(
            label="中線目標 (Fib 127.2% 下)", icon="🎯",
            price=round(max(mid, 0), 2),
            pct=round(_pct(max(mid, 0), price), 2),
            note=f"空方延伸 127.2%", confidence="中",
        ))

    # --- 4. 週線壓力 ---
    if weekly_df is not None and not weekly_df.empty and len(weekly_df) >= 26:
        wk_high = float(weekly_df["high"].tail(26).max())  # 近半年
        if wk_high > price * 1.01:
            out.append(Target(
                label="週線壓力", icon="📅",
                price=round(wk_high, 2),
                pct=round(_pct(wk_high, price), 2),
                note="近 6 個月週 K 最高點",
                confidence="中",
            ))

    # --- 5. 月線壓力 ---
    if monthly_df is not None and not monthly_df.empty and len(monthly_df) >= 24:
        mo_high = float(monthly_df["high"].tail(24).max())  # 近 2 年
        if mo_high > price * 1.01:
            out.append(Target(
                label="月線壓力 (2 年高)", icon="📆",
                price=round(mo_high, 2),
                pct=round(_pct(mo_high, price), 2),
                note="近 24 個月月 K 最高點",
                confidence="中",
            ))

    # --- 6. 基本面 + 7. 法人共識 (yfinance) ---
    try:
        info = yf.Ticker(f"{code}.TW").info or {}
    except Exception:
        info = {}

    # 法人共識
    tmp = info.get("targetMeanPrice")
    if tmp and tmp > 0:
        analyst_info = {
            "mean": float(tmp),
            "high": float(info.get("targetHighPrice") or tmp),
            "low": float(info.get("targetLowPrice") or tmp),
            "n": int(info.get("numberOfAnalystOpinions") or 0),
            "recommend": info.get("recommendationKey", "none"),
        }
        out.append(Target(
            label=f"法人目標 (共 {analyst_info['n']} 位)",
            icon="🏦",
            price=round(analyst_info["mean"], 2),
            pct=round(_pct(analyst_info["mean"], price), 2),
            note=f"{analyst_info['low']:.0f} ~ {analyst_info['high']:.0f}　"
                 f"· 評等 {analyst_info['recommend']}",
            confidence="高" if analyst_info["n"] >= 10 else "中",
        ))

    # 基本面：forward EPS × trailing PE
    f_eps = info.get("forwardEps")
    t_pe = info.get("trailingPE")
    f_pe = info.get("forwardPE")
    if f_eps and t_pe and f_eps > 0 and t_pe > 0:
        fair = f_eps * t_pe
        fundamental_info = {
            "forward_eps": float(f_eps),
            "trailing_pe": float(t_pe),
            "forward_pe": float(f_pe or 0),
            "fair_price": float(fair),
        }
        out.append(Target(
            label="基本面合理價", icon="📊",
            price=round(fair, 2),
            pct=round(_pct(fair, price), 2),
            note=f"forwardEPS {f_eps:.2f} × trailingPE {t_pe:.1f}",
            confidence="低" if abs(_pct(fair, price)) > 50 else "中",
        ))

    # 月營收 YoY 加權（對基本面微調）
    if revenue_info and fundamental_info:
        yoy = revenue_info.yoy_pct
        if abs(yoy) >= 10:
            adj = fundamental_info["fair_price"] * (1 + yoy / 200)
            # YoY 加權合理價
            out.append(Target(
                label=f"營收加權合理價 (YoY {yoy:+.1f}%)",
                icon="📈" if yoy > 0 else "📉",
                price=round(adj, 2),
                pct=round(_pct(adj, price), 2),
                note=f"合理價 × (1 + YoY/2)",
                confidence="低",
            ))

    # 依 pct 排序（負 → 正，便於呈現）
    out.sort(key=lambda t: t.pct)

    return {
        "targets": out,
        "analyst": analyst_info,
        "fundamental": fundamental_info,
    }
