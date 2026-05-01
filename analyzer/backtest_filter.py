"""回測進場/出場過濾器 — 提高勝率的 5 層篩選邏輯.

實作分析師討論結論的 5 層改善（依優先級排列）：

  Lv1 大盤 regime 過濾 — 多頭禁 short / 空頭禁 long
  Lv2 絕對分數門檻     — long ≥ 70、short ≤ -70 才開倉
  Lv3 產業分散約束     — 同產業最多 2 檔
  Lv4 動態持有期+停損  — 強趨勢 10 日／整理 3 日；MA10 強制停損
  Lv5 訊號構成過濾     — 葛蘭碧方向 + 波浪位置 + 月線方向

對外 API：
  detect_regime()                 — 偵測大盤 regime
  filter_picks(picks, side, ...)  — Lv2/3/5 過濾候選股
  recommended_hold_days(regime)   — Lv4 動態持有期
  check_technical_stop(...)       — Lv4 技術停損檢查
  apply_all_filters(...)          — 一站式呼叫所有過濾
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import pandas as pd
import yfinance as yf


# ============================================================
# Lv1：大盤 regime 偵測
# ============================================================
@dataclass
class MarketRegime:
    label: str                  # "bull" / "bear" / "sideways"
    label_zh: str               # 中文標示
    twii_close: float
    ma20: float
    ma60: float
    ma_gap_pct: float           # (MA20-MA60)/MA60 × 100
    allow_long: bool
    allow_short: bool
    capital_scale: float        # 0.0 ~ 1.0（整理時縮減）
    note: str


# 加權指數收盤 vs 移動平均（MA20-MA60 差距）判定 regime
REGIME_BULL_GAP = 3.0           # MA20 > MA60 × 1.03 為強多頭
REGIME_BEAR_GAP = -3.0          # MA20 < MA60 × 0.97 為強空頭


def detect_regime(as_of_date: str | None = None) -> MarketRegime:
    """偵測加權指數 regime.

    as_of_date='YYYY-MM-DD' 可指定歷史日期；None 為今天。
    """
    try:
        end = date.fromisoformat(as_of_date) if as_of_date \
            else date.today()
        start = (end.replace(year=end.year - 1)).isoformat()
        twii = yf.Ticker("^TWII").history(
            start=start, end=(end.toordinal() + 2 and
                              date.fromordinal(end.toordinal() + 2)
                              .isoformat()))
        if twii.empty:
            return MarketRegime(
                "sideways", "整理（無資料）",
                0, 0, 0, 0, True, True, 1.0,
                "加權指數抓取失敗，預設整理")
        twii["MA20"] = twii["Close"].rolling(20).mean()
        twii["MA60"] = twii["Close"].rolling(60).mean()
        # 取 as_of_date 之前最後一根
        if as_of_date:
            twii = twii[twii.index.date <= end]
        if twii.empty or pd.isna(twii["MA60"].iloc[-1]):
            return MarketRegime(
                "sideways", "整理（資料不足）",
                0, 0, 0, 0, True, True, 1.0,
                "MA60 未成形")
        last = twii.iloc[-1]
        close = float(last["Close"])
        ma20 = float(last["MA20"])
        ma60 = float(last["MA60"])
        gap = (ma20 / ma60 - 1) * 100
        if gap >= REGIME_BULL_GAP and close >= ma20:
            return MarketRegime(
                "bull", "🔴 強多頭",
                close, ma20, ma60, gap,
                allow_long=True, allow_short=False, capital_scale=1.0,
                note=f"MA20 ({ma20:.0f}) > MA60 ({ma60:.0f}) "
                     f"+{gap:.1f}%，禁開空單")
        if gap <= REGIME_BEAR_GAP and close <= ma20:
            return MarketRegime(
                "bear", "🟢 強空頭",
                close, ma20, ma60, gap,
                allow_long=False, allow_short=True, capital_scale=1.0,
                note=f"MA20 ({ma20:.0f}) < MA60 ({ma60:.0f}) "
                     f"{gap:.1f}%，禁開多單")
        return MarketRegime(
            "sideways", "⚪ 整理",
            close, ma20, ma60, gap,
            allow_long=True, allow_short=True, capital_scale=0.5,
            note=f"MA20-MA60 差距 {gap:+.1f}% 在 ±3% 內，"
                 f"雙向開倉但資金縮減 50%")
    except Exception as e:
        return MarketRegime(
            "sideways", "整理（例外）",
            0, 0, 0, 0, True, True, 1.0,
            f"regime 偵測例外：{str(e)[:60]}")


# ============================================================
# Lv4：動態持有期 + 技術停損
# ============================================================
def recommended_hold_days(regime: MarketRegime,
                           default: int = 5) -> tuple[int, str]:
    """根據 regime 推薦持有天數.

    強趨勢 → 10 日（讓贏家跑）
    整理 → 3 日（快進快出）
    """
    abs_gap = abs(regime.ma_gap_pct)
    if abs_gap >= 5:
        return 10, f"強趨勢市（MA20-MA60 差 {regime.ma_gap_pct:+.1f}%）"
    if abs_gap >= 3:
        return 7, f"中度趨勢市（差 {regime.ma_gap_pct:+.1f}%）"
    return 3, f"整理市，建議快進快出"


def check_technical_stop(df: pd.DataFrame, side: str,
                          entry_price: float) -> tuple[bool, str]:
    """檢查當前 K 線是否觸發技術停損.

    df: 該股最新 K 線 + indicators（含 ma10）
    side: 'long' or 'short'
    回傳 (是否觸發, 原因)
    """
    if df is None or df.empty:
        return False, ""
    if "ma10" not in df.columns or "close" not in df.columns:
        return False, ""
    last = df.iloc[-1]
    close = float(last["close"])
    ma10 = float(last["ma10"]) if not pd.isna(last["ma10"]) else None
    if ma10 is None:
        return False, ""
    # 多單跌破 MA10 + 收紅 → 停損
    if side == "long" and close < ma10:
        loss_pct = (close / entry_price - 1) * 100
        return True, (f"多單跌破 MA10 ({ma10:.2f})，"
                      f"當日 {close:.2f}，相對進場 {loss_pct:+.2f}%")
    # 空單突破 MA10 → 回補
    if side == "short" and close > ma10:
        gain_pct = (entry_price / close - 1) * 100
        return True, (f"空單突破 MA10 ({ma10:.2f})，"
                      f"當日 {close:.2f}，相對進場 {gain_pct:+.2f}%")
    return False, ""


# ============================================================
# Lv2/3/5：候選股過濾
# ============================================================
@dataclass
class FilterResult:
    accepted: list[dict] = field(default_factory=list)
    rejected: list[tuple[dict, str]] = field(default_factory=list)
    note: str = ""


# Lv2 絕對分數門檻
SCORE_LONG_MIN = 70
SCORE_SHORT_MAX = -70

# Lv3 同產業上限
INDUSTRY_LIMIT = 2


def filter_picks(picks: list[dict], side: str,
                 regime: MarketRegime | None = None,
                 industry_map: dict[str, str] | None = None,
                 score_threshold: bool = True,
                 industry_diversify: bool = True,
                 signal_filter: bool = True,
                 ) -> FilterResult:
    """套用 Lv2/3/5 過濾.

    picks: screener 回傳的 records list
    side: 'long' or 'short'
    industry_map: {code: industry_name}（None 時跳過 Lv3）
    回傳 FilterResult，含通過清單與被拒原因。
    """
    res = FilterResult()
    if regime is not None:
        # Lv1 已在 lock 階段做（這邊純過濾候選股，不做 regime 阻擋）
        pass

    industry_count: dict[str, int] = {}

    for p in picks:
        score = int(p.get("分數", 0))
        code = str(p.get("代號", ""))
        name = str(p.get("名稱", ""))

        # === Lv2 絕對分數門檻 ===
        if score_threshold:
            if side == "long" and score < SCORE_LONG_MIN:
                res.rejected.append(
                    (p, f"分數 {score} < {SCORE_LONG_MIN}（Lv2）"))
                continue
            if side == "short" and score > SCORE_SHORT_MAX:
                res.rejected.append(
                    (p, f"分數 {score} > {SCORE_SHORT_MAX}（Lv2）"))
                continue

        # === Lv3 產業分散 ===
        if industry_diversify and industry_map:
            ind = industry_map.get(code, "未知")
            if industry_count.get(ind, 0) >= INDUSTRY_LIMIT:
                res.rejected.append(
                    (p, f"同產業 {ind} 已達 {INDUSTRY_LIMIT} 檔上限（Lv3）"))
                continue

        # === Lv5 訊號構成 ===
        if signal_filter:
            wave_label = str(p.get("波浪", ""))
            granville = str(p.get("葛蘭碧", ""))

            # Long 不買 5 波末端（追高）
            if side == "long":
                if "上升 5 波" in wave_label or "第 5 波上漲" in wave_label:
                    res.rejected.append(
                        (p, f"波浪位置 {wave_label}（5 波末追高風險，Lv5）"))
                    continue
                # 葛蘭碧需是買進類 (#1~4) — 若有資料時才檢查
                if granville and granville != "—":
                    if any(s in granville for s in ("賣出", "#5", "#6", "#7", "#8")):
                        res.rejected.append(
                            (p, f"葛蘭碧 {granville} 為賣訊（Lv5）"))
                        continue

            # Short 不空 5 波末端（殺低）
            if side == "short":
                if "下跌 5 波" in wave_label or "下跌第 5 波" in wave_label:
                    res.rejected.append(
                        (p, f"波浪位置 {wave_label}（殺低反彈風險，Lv5）"))
                    continue
                if granville and granville != "—":
                    if any(s in granville for s in ("買進", "#1", "#2", "#3", "#4")):
                        res.rejected.append(
                            (p, f"葛蘭碧 {granville} 為買訊（Lv5）"))
                        continue

        # 通過所有過濾
        res.accepted.append(p)
        if industry_diversify and industry_map:
            ind = industry_map.get(code, "未知")
            industry_count[ind] = industry_count.get(ind, 0) + 1

    res.note = (f"通過 {len(res.accepted)} 檔，"
                f"剔除 {len(res.rejected)} 檔")
    return res


# ============================================================
# 一站式：apply_all_filters
# ============================================================
@dataclass
class FilterReport:
    regime: MarketRegime
    side: str
    proceed: bool                       # 該方向是否可開倉
    picks_filtered: list[dict]          # 過濾後的清單
    filter_result: FilterResult         # 過濾詳情
    hold_days: int
    hold_days_note: str
    capital_scale: float
    skip_reason: str = ""               # 若 proceed=False 的原因


def apply_all_filters(side: Literal["long", "short"],
                       picks: list[dict],
                       industry_map: dict[str, str] | None = None,
                       as_of_date: str | None = None,
                       ) -> FilterReport:
    """一站式套用 Lv1~5 過濾.

    回傳 FilterReport：
      proceed=False 表示 regime 不允許該方向開倉
      picks_filtered 為通過 Lv2/3/5 的候選股
      hold_days 為 Lv4 推薦持有期
    """
    regime = detect_regime(as_of_date=as_of_date)
    # Lv1 regime
    proceed = regime.allow_long if side == "long" else regime.allow_short
    skip_reason = ""
    if not proceed:
        skip_reason = (f"Lv1 regime 過濾：{regime.label_zh}（{regime.note}），"
                       f"禁開 {side}")
        return FilterReport(
            regime=regime, side=side, proceed=False,
            picks_filtered=[],
            filter_result=FilterResult(note=skip_reason),
            hold_days=0, hold_days_note="",
            capital_scale=0.0,
            skip_reason=skip_reason,
        )
    # Lv2/3/5
    fr = filter_picks(picks, side=side, regime=regime,
                       industry_map=industry_map)
    # Lv4 hold days
    hd, hd_note = recommended_hold_days(regime)
    return FilterReport(
        regime=regime, side=side, proceed=True,
        picks_filtered=fr.accepted,
        filter_result=fr,
        hold_days=hd, hold_days_note=hd_note,
        capital_scale=regime.capital_scale,
    )
