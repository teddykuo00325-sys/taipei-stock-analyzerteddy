"""個股診斷書 — 呼叫指定流派模組 + 整合 法人 / 融資券 / 波浪 資料."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import ModuleType

import pandas as pd

from . import (candlestick, econophysics, fibonacci, institutional,
               margin, patterns, schools, wave)


@dataclass
class Diagnosis:
    school: str
    score: int
    stance: str
    action: str
    action_note: str
    summary: str
    ma_state: str
    ma_note: str
    volume_note: str
    trend_note: str = ""
    weekly_note: str = ""
    candles: list = field(default_factory=list)
    chart_patterns: list = field(default_factory=list)
    signals: list = field(default_factory=list)
    support: float = 0.0
    resistance: float = 0.0
    short_stop: float | None = None
    mid_stop: float | None = None
    abs_stop: float = 0.0
    target_price: float | None = None
    target_note: str = ""
    risk_reward: float | None = None
    entry_zone: tuple[float, float] | None = None
    # --- 新增欄位 ---
    institutional_info: dict | None = None
    institutional_note: str = ""
    institutional_score: int = 0
    margin_info: dict | None = None
    margin_note: str = ""
    margin_score: int = 0
    wave_label: str = ""
    wave_direction: str = ""
    wave_confidence: str = ""
    wave_note: str = ""
    wave_score: int = 0
    # 計量物理
    econ: "econophysics.Econ | None" = None
    econ_score: int = 0
    econ_note: str = ""
    # 費波納契
    fib: "fibonacci.FibAnalysis | None" = None
    fib_score: int = 0
    fib_note: str = ""


def _stance(score: int) -> str:
    if score >= 60:
        return "多方"
    if score >= 25:
        return "偏多"
    if score > -25:
        return "中立"
    if score > -60:
        return "偏空"
    return "空方"


def _action(score: int, ma_state: str, weekly_bull: bool | None) -> tuple[str, str]:
    if weekly_bull is True and score >= 50:
        return "強力買進", "日週雙多頭確認，順勢做多；回測均線不破加碼"
    if weekly_bull is True and score >= 20:
        return "買進", "週線偏多，日線找買點進場"
    if weekly_bull is False and score <= -50:
        return "強力賣出", "日週雙空頭確認，反彈即賣；持股出清"
    if weekly_bull is False and score <= -20:
        return "賣出", "週線偏空，反彈遇壓賣出"
    if score >= 60:
        return "強力買進", "日線強勢多頭，建議順勢追多"
    if score >= 25:
        return "買進", "日線多頭，拉回可買"
    if score <= -60:
        return "強力賣出", "日線弱勢空頭，反彈即賣"
    if score <= -25:
        return "賣出", "日線偏空，持股減碼"
    if ma_state == "均線糾結":
        return "觀望", "均線糾結，等待方向表態再進場"
    return "觀望", "方向不明，建議觀望等待訊號"


def _target(df: pd.DataFrame, pats: list, stance: str,
            resistance: float, support: float) -> tuple[float | None, str]:
    price = df["close"].iloc[-1]
    for p in pats:
        if p.signal == "bull" and p.neckline:
            bottom = df["low"].tail(60).min()
            return float(p.neckline + (p.neckline - bottom)), \
                   f"{p.name} 突破頸線幅度推算"
        if p.signal == "bear" and p.neckline:
            top = df["high"].tail(60).max()
            return float(max(p.neckline - (top - p.neckline), 0)), \
                   f"{p.name} 跌破頸線幅度推算"
    if stance in ("多方", "偏多"):
        target = resistance * 1.05 if price >= resistance * 0.98 else resistance
        return float(target), "近期壓力 / 突破後延伸 5%"
    if stance in ("空方", "偏空"):
        target = support * 0.95 if price <= support * 1.02 else support
        return float(target), "近期支撐 / 跌破後延伸 5%"
    return float(resistance), "壓力價（區間震盪上緣）"


def _weekly_bias(weekly_df: pd.DataFrame | None,
                 school_mod: ModuleType) -> tuple[bool | None, str]:
    if weekly_df is None or len(weekly_df) < 20:
        return None, ""
    try:
        state, note = school_mod.ma_alignment(weekly_df)
    except Exception:
        return None, ""
    if state in ("多頭排列", "偏多"):
        return True, f"週線{state} — {note}"
    if state in ("空頭排列", "偏空"):
        return False, f"週線{state} — {note}"
    return None, f"週線{state} — {note}"


def diagnose(df: pd.DataFrame,
             code: str | None = None,
             weekly_df: pd.DataFrame | None = None,
             school: str | None = None,
             include_chips: bool = True) -> Diagnosis:
    mod = schools.get(school)
    weights = mod.score_weights() if hasattr(mod, "score_weights") else {}

    ma_state, ma_note = mod.ma_alignment(df)
    vol_note = mod.volume_analysis(df)
    sigs = mod.generate_signals(df)
    stops = mod.stop_levels(df)
    trend_note = mod.trend_summary(df) if hasattr(mod, "trend_summary") else ""

    candles = candlestick.classify_last(df)
    pats = patterns.detect(df)
    trend = patterns.trendline(df)
    weekly_bull, weekly_note = _weekly_bias(weekly_df, mod)

    # --- 新增資料：波浪 / 法人 / 融資券 / 計量 / 費波納契 ---
    w = wave.detect(df)
    wave_s, wave_s_note = wave.score_adj(df)
    econ_obj = econophysics.compute(df)
    econ_s, econ_note = econophysics.score_adj(df)
    fib_obj = fibonacci.analyze(df)
    fib_s, fib_note = fibonacci.score_adj(df)

    inst_info = None
    inst_s = 0
    inst_note = ""
    if include_chips and code:
        try:
            inst_info = institutional.for_code(code)
            inst_s, inst_note_raw = institutional.score_adj(code)
            inst_note = inst_note_raw
        except Exception:
            pass

    marg_info = None
    marg_s = 0
    marg_note = ""
    if include_chips and code:
        try:
            price_up = df["close"].iloc[-1] > df["close"].iloc[-2] \
                if len(df) >= 2 else None
            marg_info = margin.for_code(code)
            marg_s, marg_note_raw = margin.score_adj(code, price_up=price_up)
            marg_note = marg_note_raw
        except Exception:
            pass

    # ===== 綜合評分 =====
    score = 0
    w_ma = weights.get("ma_alignment", {})
    score += w_ma.get(ma_state, 0)
    for c in candles:
        score += weights.get("candle_bull", 6) if c.signal == "bull" else \
                 weights.get("candle_bear", -6) if c.signal == "bear" else 0
    for p in pats:
        score += weights.get("pattern_bull", 12) if p.signal == "bull" else \
                 weights.get("pattern_bear", -12) if p.signal == "bear" else 0
    ss = weights.get("signal_per_strength", 4)
    for s in sigs:
        if s.kind == "entry":
            score += s.strength * ss
        elif s.kind == "exit":
            score -= s.strength * ss
    if "價漲量增" in vol_note:
        score += weights.get("volume_bonus", 8)
    elif "爆量下殺" in vol_note or "量縮上漲" in vol_note:
        score -= weights.get("volume_bonus", 8)
    wb = weights.get("weekly_bias", 8)
    if weekly_bull is True:
        score += wb
    elif weekly_bull is False:
        score -= wb
    # 新增加權：波浪 / 法人 / 融資券 / 計量 / 費波納契
    score += int(round(wave_s * weights.get("wave_scale", 1.0)))
    score += int(round(inst_s * weights.get("institutional_scale", 1.0)))
    score += int(round(marg_s * weights.get("margin_scale", 1.0)))
    score += int(round(econ_s * weights.get("econ_scale", 1.0)))
    score += int(round(fib_s * weights.get("fib_scale", 1.0)))

    score = max(-100, min(100, score))

    stance = _stance(score)
    action, action_note = _action(score, ma_state, weekly_bull)
    target_price, target_note = _target(df, pats, stance,
                                        trend["resistance"], trend["support"])

    price = float(df["close"].iloc[-1])
    ma10 = df["ma10"].iloc[-1]
    ma20 = df["ma20"].iloc[-1]
    entry_zone = None
    if stance in ("多方", "偏多") and not pd.isna(ma10) and not pd.isna(ma20):
        lo, hi = sorted([float(ma10), float(ma20)])
        entry_zone = (lo, hi)
    elif stance == "中立":
        entry_zone = (float(trend["support"]), float(trend["support"]) * 1.02)

    risk_reward = None
    if target_price and stops.get("short_stop"):
        reward = abs(target_price - price)
        risk = abs(price - stops["short_stop"])
        if risk > 0:
            risk_reward = round(reward / risk, 2)

    bits: list[str] = [f"{ma_state}；{vol_note}"]
    if trend_note:
        bits.append(f"趨勢：{trend_note}")
    if w.label:
        bits.append(f"波浪：{w.label}")
    if econ_obj:
        bits.append(f"{econ_obj.hurst_label}；{econ_obj.vol_label}")
    if fib_obj and fib_obj.nearest and fib_obj.nearest_distance_pct <= 2.5:
        bits.append(f"費波：{fib_obj.nearest.name}")
    if inst_note:
        bits.append(f"法人：{inst_note}")
    if marg_note:
        bits.append(marg_note)
    if weekly_note:
        bits.append(weekly_note)
    if candles:
        bits.append("K 線：" + "、".join(c.name for c in candles))
    if pats:
        bits.append("型態：" + "、".join(p.name for p in pats))
    entries = [s for s in sigs if s.kind == "entry"]
    exits = [s for s in sigs if s.kind == "exit"]
    if entries:
        bits.append("買訊：" + "、".join(s.name for s in entries))
    if exits:
        bits.append("賣訊：" + "、".join(s.name for s in exits))
    summary = "；".join(bits)

    return Diagnosis(
        school=mod.FULL_NAME,
        score=score, stance=stance, action=action, action_note=action_note,
        summary=summary, ma_state=ma_state, ma_note=ma_note,
        volume_note=vol_note, trend_note=trend_note, weekly_note=weekly_note,
        candles=candles, chart_patterns=pats, signals=sigs,
        support=trend["support"], resistance=trend["resistance"],
        short_stop=stops["short_stop"], mid_stop=stops["mid_stop"],
        abs_stop=stops["abs_stop"],
        target_price=target_price, target_note=target_note,
        risk_reward=risk_reward, entry_zone=entry_zone,
        institutional_info=inst_info, institutional_note=inst_note,
        institutional_score=inst_s,
        margin_info=marg_info, margin_note=marg_note, margin_score=marg_s,
        wave_label=w.label, wave_direction=w.direction,
        wave_confidence=w.confidence, wave_note=w.note, wave_score=wave_s,
        econ=econ_obj, econ_score=econ_s, econ_note=econ_note,
        fib=fib_obj, fib_score=fib_s, fib_note=fib_note,
    )
