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
    # 未截斷的原始分數（可超出 ±100）。score 仍為截斷值，供 stance /
    # action / min_score 門檻使用；raw_score 專供排序解飽和用。
    raw_score: int = 0
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
    # R:R 用的「操作停損」— 對齊 realbacktest 實際的 MA10 移動停利出場，
    # 而非 stop_levels 的結構支撐（見 _rr_stop 說明）
    rr_stop: float | None = None
    rr_stop_note: str = ""
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


# ============================================================
# 前波漲幅投射（measured move）2026-09-22
# ============================================================
# 背景：原本目標價在「創新高、上方無壓力」時會退回機械式
# 「當日高點 x 1.05」（40 檔實測佔 35%），沒有任何結構依據。
#
# 為什麼不用純 ATR 倍數投射：
#   R:R 的分母已經是 max(MA10 距離, 1.5 x ATR)，實測 65% 的標的由
#   ATR 下限決定。若分子也用 k x ATR，R:R 會變成接近固定的 k/1.5，
#   完全失去鑑別力 —— 過濾器會退化成一個常數。
#   所以分子必須用**與波動度無關**的結構量，ATR 只保留為最小距離。
#
# 採用「量測波幅」(measured move)：取最後一段完整推進波的幅度，
# 自其後的回檔基準投射。這也是朱家泓派量波幅的標準作法。
TARGET_ATR_MIN_MULT = 2.0   # 目標價最小距離 = 2 x ATR14


def _normalize_pivots(pivots: list) -> list:
    """把 wave._find_pivots 的輸出整理成 H/L 交替序列.

    _find_pivots 是高低點各自獨立找再合併排序，會出現連續同型
    （例如 2454 出現 H4345 → H3875）。連續同型只保留極值：
    H 取最高、L 取最低。
    """
    out: list = []
    for p in (pivots or []):
        if out and out[-1][1] == p[1]:
            keep_new = ((p[1] == "H" and p[2] > out[-1][2]) or
                        (p[1] == "L" and p[2] < out[-1][2]))
            if keep_new:
                out[-1] = p
        else:
            out.append(p)
    return out


def _measured_move(pivots: list, stance: str) -> tuple[float | None, str]:
    """前波幅度投射；回傳 (target, note)，無法計算時 (None, "").

    多方：由後往前找最後一組相鄰的 (L, H)，幅度 amp = H - L。
          若該 H 之後還有回檔低點 L2，以 L2 為投射基準（突破後量測），
          否則以 H 本身為基準。target = base + amp。
    空方對稱。
    """
    ps = _normalize_pivots(pivots)
    if len(ps) < 3:
        return None, ""

    if stance in ("多方", "偏多"):
        for i in range(len(ps) - 1, 0, -1):
            if ps[i][1] == "H" and ps[i - 1][1] == "L":
                amp = float(ps[i][2]) - float(ps[i - 1][2])
                if amp <= 0:
                    return None, ""
                base = float(ps[i][2])
                if i + 1 < len(ps) and ps[i + 1][1] == "L":
                    base = float(ps[i + 1][2])
                return (base + amp,
                        f"前波漲幅投射（波幅 {amp:.1f} 自 {base:.1f} 起算）")
        return None, ""

    if stance in ("空方", "偏空"):
        for i in range(len(ps) - 1, 0, -1):
            if ps[i][1] == "L" and ps[i - 1][1] == "H":
                amp = float(ps[i - 1][2]) - float(ps[i][2])
                if amp <= 0:
                    return None, ""
                base = float(ps[i][2])
                if i + 1 < len(ps) and ps[i + 1][1] == "H":
                    base = float(ps[i + 1][2])
                return (max(base - amp, 0.0),
                        f"前波跌幅投射（波幅 {amp:.1f} 自 {base:.1f} 起算）")
        return None, ""

    return None, ""


def _target(df: pd.DataFrame, pats: list, stance: str,
            resistance: float, support: float,
            pivots: list | None = None) -> tuple[float | None, str]:
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

    # ★ 2026-09-22：型態頸線之後、機械式壓力之前，先試前波幅度投射。
    # 這一層專門接住「創新高、上方無壓力」的情形 —— 原本會掉進
    # 「當日高點 x 1.05」那種沒有結構依據的機械值。
    if raw_target is None:
        mm, mm_note = _measured_move(pivots, stance)
        if mm is not None:
            if stance in ("多方", "偏多") and mm > price:
                raw_target, note = mm, mm_note
            elif stance in ("空方", "偏空") and mm < price:
                raw_target, note = mm, mm_note

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

    # ★ 目標價最小距離 = 2 x ATR14。
    # 比這更近的目標在雜訊之內，R:R 算出來沒有意義。
    # 這只是下限（很少觸發），上限仍由 diagnose() 的 ±20% cap 控制。
    if "atr14" in df.columns and not pd.isna(df["atr14"].iloc[-1]):
        atr = float(df["atr14"].iloc[-1])
        if atr > 0:
            floor = TARGET_ATR_MIN_MULT * atr
            if stance in ("多方", "偏多") and raw_target < price + floor:
                raw_target = price + floor
                note += f"（已抬升至 {TARGET_ATR_MIN_MULT}xATR 下限）"
            elif stance in ("空方", "偏空") and raw_target > price - floor:
                raw_target = max(price - floor, 0.0)
                note += f"（已下修至 {TARGET_ATR_MIN_MULT}xATR 下限）"

    return float(raw_target), note


# ============================================================
# R:R 操作停損（2026-09-22）
# ============================================================
# 問題：realbacktest.check_technical_stop() 實際上是「跌破 MA10 出場」
# （未實現獲利 >= 10% 時收緊到 MA5），但 risk_reward 的分母卻取
# stop_levels 算出的結構支撐 —— 兩者是不同的東西。
#
# 2454 實例（2026-09-21）：
#     進場區中值 4646 ｜ 結構停損 3655（-21.3%）｜ 實際出場 MA10 ≈ 4644
#     R:R = 0.64 → 被 _rr_ok 濾掉
# 分母用一個系統根本不會執行的停損，R:R 就不描述系統真正在做的事。
#
# 另外實測（40 檔）：目標價走「機械式 +5%」分支者佔 35%，其通過
# R:R >= 1.5 的比率只有 29%（型態頸線分支是 75%）。單純把目標價換成
# 3xATR 只讓通過數 4/14 → 5/14，證明病灶在分母不在分子。
#
# 改法：以 MA10 為風險基準，並以 1.5xATR 當「最小風險距離」——
# 因為進場區本身常常就是 MA5/MA10，距離趨近 0 會讓 R:R 爆成無限大。
RR_ATR_FLOOR_MULT = 1.5


def _rr_stop(df: pd.DataFrame, stance: str,
             entry_ref: float) -> tuple[float | None, str]:
    """回傳 (R:R 用的操作停損, 說明)；無法計算時回 (None, "")."""
    if not entry_ref or entry_ref <= 0:
        return None, ""
    ma10 = None
    if "ma10" in df.columns and not pd.isna(df["ma10"].iloc[-1]):
        ma10 = float(df["ma10"].iloc[-1])
    atr = None
    if "atr14" in df.columns and not pd.isna(df["atr14"].iloc[-1]):
        atr = float(df["atr14"].iloc[-1])
    if atr is None or atr <= 0:
        return None, ""

    floor = RR_ATR_FLOOR_MULT * atr
    if stance in ("多方", "偏多"):
        ma_dist = (entry_ref - ma10) if ma10 is not None else 0.0
        dist = max(ma_dist, floor)
        src = "MA10" if dist == ma_dist and ma_dist > 0 else "1.5xATR"
        return entry_ref - dist, f"操作停損（{src}）"
    if stance in ("空方", "偏空"):
        ma_dist = (ma10 - entry_ref) if ma10 is not None else 0.0
        dist = max(ma_dist, floor)
        src = "MA10" if dist == ma_dist and ma_dist > 0 else "1.5xATR"
        return entry_ref + dist, f"操作停損（{src}）"
    return None, ""


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

    # ★ 2026-09-03 (C)：保留未截斷值供排序用。
    # 實測 08-05~09-03：|score|=100 觸頂者佔 51%（18/35），主分數在頂端
    # 完全失去排序能力，只能靠 Tiebreak（0-8 共 9 級）決勝；且觸頂那群
    # 期望值 -1.07% / P&L -17,431，而 85-94 那群 +0.64% / +23,609。
    # 截斷後的 score 維持 ±100 → stance / action / min_score 語意不變。
    raw_score = int(score)
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
                                        trend["resistance"], trend["support"],
                                        pivots=w.pivots)

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

    # ★ 2026-09-22：R:R 分母改用「操作停損」（對齊 MA10 實際出場規則），
    # 取不到時才退回原本的結構停損，保持向後相容。
    rr_stop, rr_stop_note = _rr_stop(df, stance, entry_ref)
    if rr_stop is None:
        rr_stop = stops.get("short_stop")
        rr_stop_note = "結構停損（無 ATR，fallback）"

    risk_reward = None
    if target_price and rr_stop:
        reward = abs(target_price - entry_ref)
        risk = abs(entry_ref - rr_stop)
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
        score=score, raw_score=raw_score, stance=stance, action=action, action_note=action_note,
        summary=summary, ma_state=ma_state, ma_note=ma_note,
        volume_note=vol_note, trend_note=trend_note, weekly_note=weekly_note,
        candles=candles, chart_patterns=pats, signals=sigs,
        support=trend["support"], resistance=trend["resistance"],
        short_stop=stops["short_stop"], mid_stop=stops["mid_stop"],
        abs_stop=stops["abs_stop"],
        target_price=target_price, target_note=target_note,
        risk_reward=risk_reward, entry_zone=entry_zone,
        rr_stop=(round(float(rr_stop), 2) if rr_stop else None),
        rr_stop_note=rr_stop_note,
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
