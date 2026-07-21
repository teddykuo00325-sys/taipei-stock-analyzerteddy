"""個股診斷書 — 呼叫指定流派模組 + 整合 法人 / 融資券 / 波浪 資料."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import ModuleType

import pandas as pd

from . import (candlestick, econophysics, fibonacci, granville,
               institutional, margin, patterns, schools, wave)


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
    # 續漲/續跌標籤
    continuation_label: str = ""   # "續漲" / "續跌" / "震盪" / ""
    # --- 新增欄位 ---
    institutional_info: dict | None = None
    institutional_note: str = ""
    institutional_score: int = 0
    margin_info: dict | None = None
    margin_note: str = ""
    margin_score: int = 0
    margin_score_detail: object | None = None  # MarginScore 五維度物件
    # 葛蘭碧八大法則
    granville: object | None = None  # GranvilleAnalysis
    granville_score: int = 0
    granville_note: str = ""
    wave_label: str = ""
    wave_direction: str = ""
    wave_confidence: str = ""
    wave_note: str = ""
    wave_score: int = 0
    wave_pivots: list = field(default_factory=list)  # (idx, H/L, price)
    candle_history: list = field(default_factory=list)  # [(idx, [Candle])]
    multi_supports: list = field(default_factory=list)
    multi_resistances: list = field(default_factory=list)
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
    """計算目標價；含 sanity check 確保 long target > price / short target < price.

    Bug fix：原邏輯用「近期壓力」當多方目標，但壓力已跌破時 target 可能低於
    現價，讓 TG 出現「目標價 < 現價」的荒謬推薦.
    """
    price = float(df["close"].iloc[-1])
    raw_target: float | None = None
    note = ""

    for p in pats:
        if p.signal == "bull" and p.neckline:
            bottom = float(df["low"].tail(60).min())
            raw_target = float(p.neckline + (p.neckline - bottom))
            note = f"{p.name} 突破頸線幅度推算"
            break
        if p.signal == "bear" and p.neckline:
            top = float(df["high"].tail(60).max())
            raw_target = float(max(p.neckline - (top - p.neckline), 0))
            note = f"{p.name} 跌破頸線幅度推算"
            break

    if raw_target is None:
        if stance in ("多方", "偏多"):
            raw_target = (resistance * 1.05
                          if price >= resistance * 0.98 else resistance)
            note = "近期壓力 / 突破後延伸 5%"
        elif stance in ("空方", "偏空"):
            raw_target = (support * 0.95
                          if price <= support * 1.02 else support)
            note = "近期支撐 / 跌破後延伸 5%"
        else:
            raw_target = float(resistance)
            note = "壓力價（區間震盪上緣）"

    # ★ Sanity check — 目標價必須合理相對於現價
    # Long/偏多：target 必須 > 現價，否則 fallback 至少 +5%
    # Short/偏空：target 必須 < 現價，否則 fallback 至少 -5%
    if stance in ("多方", "偏多"):
        if raw_target <= price:
            # 用計量方式重算：近 20 日高點或 +5% 取較大者
            recent_high = float(df["high"].tail(20).max())
            raw_target = max(recent_high, price * 1.05)
            note = "壓力已被突破/失效 → 用近 20 日高點或 +5% (fallback)"
    elif stance in ("空方", "偏空"):
        if raw_target >= price:
            recent_low = float(df["low"].tail(20).min())
            raw_target = min(recent_low, price * 0.95)
            note = "支撐已破 → 用近 20 日低點或 -5% (fallback)"

    return float(raw_target), note


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
             include_chips: bool = True,
             detailed: bool = True) -> Diagnosis:
    """
    detailed=True  : 計算完整 candle_history + multi_sr (個股查詢)
    detailed=False : 略過，節省時間 (選股器批次用)
    """
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

    # --- 新增資料：波浪 / 法人 / 融資券 / 計量 / 費波納契 / 葛蘭碧 ---
    w = wave.detect(df)
    wave_s, wave_s_note = wave.score_adj(df)
    econ_obj = econophysics.compute(df)
    econ_s, econ_note = econophysics.score_adj(df)
    fib_obj = fibonacci.analyze(df)
    fib_s, fib_note = fibonacci.score_adj(df)
    # 葛蘭碧八大法則（以 20MA 為主）
    try:
        gv_obj = granville.analyze(df, ma_period=20)
        gv_s = gv_obj.score
        gv_note = gv_obj.note
    except Exception:
        gv_obj, gv_s, gv_note = None, 0, ""
    # 一併算好 candle_history 與 multi S/R 供下游重用（僅 detailed 模式）
    if detailed:
        candle_hist = candlestick.scan_history(df, lookback=90)
        try:
            msup, mres = patterns.multi_sr(df, n=3)
        except Exception:
            msup, mres = [], []
    else:
        candle_hist = []
        msup, mres = [], []

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
    marg_score_obj = None  # 5 維度詳細物件（給 UI 拆解顯示）
    if include_chips and code:
        try:
            marg_info = margin.for_code(code)
            # 優先用 5 維度 margin_score；ETF / 無融資商品回 None
            try:
                from . import margin_score as _ms
                ms = _ms.score(code, price_df=df)
                if ms is not None:
                    marg_score_obj = ms
                    # 將加權總分 (-10~+10) 線性映射到 score 系統 (~ -15~+15)
                    marg_s = int(round(ms.total * 1.5))
                    # 取「絕對值最大」的那項當主要說明
                    dims = [
                        ("4 象限", ms.quadrant, ms.notes[0]),
                        ("券資比", ms.short_ratio, ms.notes[1]),
                        ("回補壓力", ms.short_pressure, ms.notes[2]),
                        ("融資使用率", ms.margin_usage, ms.notes[3]),
                        ("5/20MA 趨勢", ms.trend, ms.notes[4]),
                    ]
                    dims.sort(key=lambda x: abs(x[1]), reverse=True)
                    marg_note = f"[{dims[0][0]}] {dims[0][2]}"
                else:
                    # ETF / 無融資資料 → 退回原邏輯
                    price_up = (df["close"].iloc[-1] > df["close"].iloc[-2]
                                if len(df) >= 2 else None)
                    marg_s, marg_note = margin.score_adj(
                        code, price_up=price_up)
            except Exception:
                # 任何例外 → 退回原邏輯
                price_up = (df["close"].iloc[-1] > df["close"].iloc[-2]
                            if len(df) >= 2 else None)
                marg_s, marg_note = margin.score_adj(
                    code, price_up=price_up)
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
    # 新增加權：波浪 / 法人 / 融資券 / 計量 / 費波納契 / 葛蘭碧
    score += int(round(wave_s * weights.get("wave_scale", 1.0)))
    score += int(round(inst_s * weights.get("institutional_scale", 1.0)))
    score += int(round(marg_s * weights.get("margin_scale", 1.0)))
    score += int(round(econ_s * weights.get("econ_scale", 1.0)))
    score += int(round(fib_s * weights.get("fib_scale", 1.0)))
    score += int(round(gv_s * weights.get("granville_scale", 1.0)))

    score = max(-100, min(100, score))

    stance = _stance(score)
    action, action_note = _action(score, ma_state, weekly_bull)

    # 續漲/續跌 判斷：MA 排列 + 近 5 日收盤方向
    cont_label = ""
    if len(df) >= 5:
        recent5 = df.tail(5)
        delta5 = (recent5["close"].iloc[-1] / recent5["close"].iloc[0]
                  - 1) * 100
        if ma_state in ("多頭排列", "偏多") and delta5 >= 0:
            cont_label = "續漲"
        elif ma_state in ("空頭排列", "偏空") and delta5 <= 0:
            cont_label = "續跌"
        elif ma_state in ("均線糾結", "盤整"):
            cont_label = "震盪"
    target_price, target_note = _target(df, pats, stance,
                                        trend["resistance"], trend["support"])

    price = float(df["close"].iloc[-1])
    ma5 = df["ma5"].iloc[-1] if "ma5" in df.columns else None
    ma10 = df["ma10"].iloc[-1] if "ma10" in df.columns else None
    ma20 = df["ma20"].iloc[-1] if "ma20" in df.columns else None
    entry_zone = None
    if stance in ("多方", "偏多"):
        # 多頭回測買點：MA10 (下緣) ~ MA5 (上緣) 或現價回檔 3%
        candidates = []
        if not pd.isna(ma10):
            candidates.append(float(ma10))
        if not pd.isna(ma5):
            candidates.append(float(ma5))
        candidates.append(price * 0.97)
        if len(candidates) >= 2:
            candidates_sorted = sorted(candidates)
            lo = candidates_sorted[0]
            hi = candidates_sorted[min(1, len(candidates_sorted) - 1)]
            if abs(hi - lo) / max(lo, 1) < 0.005 and not pd.isna(ma5) \
                    and not pd.isna(ma10):
                lo = min(float(ma10), float(ma5))
                hi = max(float(ma10), float(ma5))
            entry_zone = (round(lo, 2), round(hi, 2))
    elif stance in ("空方", "偏空"):
        # 空方反彈放空區：MA5 (下緣) ~ MA10 (上緣) 或現價反彈 3%
        candidates = []
        if not pd.isna(ma10):
            candidates.append(float(ma10))
        if not pd.isna(ma5):
            candidates.append(float(ma5))
        candidates.append(price * 1.03)
        if len(candidates) >= 2:
            candidates_sorted = sorted(candidates, reverse=True)
            hi = candidates_sorted[0]
            lo = candidates_sorted[min(1, len(candidates_sorted) - 1)]
            if abs(hi - lo) / max(hi, 1) < 0.005 and not pd.isna(ma5) \
                    and not pd.isna(ma10):
                lo = min(float(ma10), float(ma5))
                hi = max(float(ma10), float(ma5))
            entry_zone = (round(lo, 2), round(hi, 2))
    elif stance == "中立":
        entry_zone = (float(trend["support"]),
                      float(trend["support"]) * 1.02)

    # R:R 改以「實際進場價」計算：
    # 若現價已高於進場區，預期等拉回至進場區上緣執行 → 以進場上緣計算
    # 否則以現價計算
    # ★ Sanity check：停損 vs 進場區間位置
    # Long/偏多：停損必須 < entry_zone.lower × 0.98（至少 2% 保護距離）
    # Short/偏空：停損必須 > entry_zone.upper × 1.02（至少 2% 保護距離）
    # 若違反 → 用 abs_stop (前 20 日低) 或 entry_zone 邊界外 2%
    # MIN_STOP_PCT = 2% 是為了防止 MA10 × 0.98 剛好貼近 entry_lower 導致
    # R:R 灌水到 13+（真實：0.5% 停損被任何盤中噪音打到就出場）
    MIN_STOP_PCT = 0.02
    if entry_zone and stops.get("short_stop") is not None:
        stop = float(stops["short_stop"])
        if stance in ("多方", "偏多"):
            entry_low = float(entry_zone[0])
            max_stop_allowed = entry_low * (1 - MIN_STOP_PCT)
            if stop >= max_stop_allowed:
                # 停損跑到進場區內或距離太近 → 用 abs_stop 或 entry_lower × 0.98
                abs_s = stops.get("abs_stop")
                fallback = min(
                    float(abs_s) if abs_s is not None else max_stop_allowed,
                    max_stop_allowed,
                )
                stops["short_stop"] = round(fallback, 2)
        elif stance in ("空方", "偏空"):
            entry_high = float(entry_zone[1])
            min_stop_allowed = entry_high * (1 + MIN_STOP_PCT)
            if stop <= min_stop_allowed:
                abs_s = stops.get("abs_stop")
                fallback = max(
                    float(abs_s) if abs_s is not None else min_stop_allowed,
                    min_stop_allowed,
                )
                stops["short_stop"] = round(fallback, 2)

    # R:R 進場基準（同時作 target cap 基準，兩者對齊）：
    # 現價 > entry_upper → 用 entry_upper（等拉回情境）
    # 現價 < entry_lower → 用 entry_lower（等突破情境，多空皆可能）
    # 其他 → 用現價
    entry_ref = price
    if entry_zone:
        if price > entry_zone[1]:
            entry_ref = float(entry_zone[1])
        elif price < entry_zone[0]:
            entry_ref = float(entry_zone[0])

    # ★ Sanity check：目標價空間上限（短線 5-10 日推薦不合理超過 ±20%）
    # 型態突破推算 (neckline + gap) 有時 gap 太大導致 target = +50%+，
    # 超過現實可達到範圍 → 截斷至 ±20%
    # 基準對齊 TG 顯示：daily_report._pick_trade_details 用 entry midpoint 算
    # target_pct，這裡也用 midpoint（若無 entry_zone 則回落至 price），
    # 確保 TG 上顯示的 target_pct 也 ≤ 20%
    cap_ref = ((entry_zone[0] + entry_zone[1]) / 2
               if entry_zone else price)
    if target_price is not None:
        if stance in ("多方", "偏多"):
            target_price = min(target_price, cap_ref * 1.20)
        elif stance in ("空方", "偏空"):
            target_price = max(target_price, cap_ref * 0.80)

    risk_reward = None
    if target_price and stops.get("short_stop"):
        reward = abs(target_price - entry_ref)
        risk = abs(entry_ref - stops["short_stop"])
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
        margin_score_detail=marg_score_obj,
        granville=gv_obj, granville_score=gv_s, granville_note=gv_note,
        wave_label=w.label, wave_direction=w.direction,
        wave_confidence=w.confidence, wave_note=w.note, wave_score=wave_s,
        econ=econ_obj, econ_score=econ_s, econ_note=econ_note,
        fib=fib_obj, fib_score=fib_s, fib_note=fib_note,
        continuation_label=cont_label,
        wave_pivots=w.pivots,
        candle_history=candle_hist,
        multi_supports=msup,
        multi_resistances=mres,
    )
