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
  recommended_hold_days(regime)   — Lv4 持有上限（安全網，非出場日）
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
    label: str                  # "bull" / "bear" / "sideways" / "weak_bull" / "weak_bear"
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


import threading as _threading

_regime_cache: dict = {}  # key=as_of_date or '' → {"t":ts, "v":MarketRegime}
_regime_lock = _threading.Lock()  # 防 detect_regime 多執行緒 race
_REGIME_TTL = 1800  # 30 分鐘


def detect_regime(as_of_date: str | None = None) -> MarketRegime:
    """偵測加權指數 regime.

    as_of_date='YYYY-MM-DD' 可指定歷史日期；None 為今天。
    30 分鐘 in-memory cache（每次 Streamlit rerun 都會打網路太貴）。
    """
    from time import time as _t
    cache_key = as_of_date or ""
    now = _t()
    with _regime_lock:
        cached = _regime_cache.get(cache_key)
        if cached and now - cached["t"] < _REGIME_TTL:
            return cached["v"]

    def _ret(r: "MarketRegime") -> "MarketRegime":
        with _regime_lock:
            _regime_cache[cache_key] = {"t": now, "v": r}
        return r

    try:
        end = date.fromisoformat(as_of_date) if as_of_date \
            else date.today()
        start = (end.replace(year=end.year - 1)).isoformat()
        # yfinance.history 的 end 是 exclusive，加 1 天緩衝確保包含 end 當天
        end_plus = date.fromordinal(end.toordinal() + 1).isoformat()
        # ★ thread timeout 防 yfinance 雲端 hang（curl_cffi 底層忽略 socket
        # timeout）。25 秒沒回 → 視為失敗，return 預設 sideways
        from concurrent.futures import (ThreadPoolExecutor,
                                          TimeoutError as _TO)
        with ThreadPoolExecutor(max_workers=1) as _ex:
            _fut = _ex.submit(
                lambda: yf.Ticker("^TWII").history(start=start, end=end_plus))
            try:
                twii = _fut.result(timeout=25)
            except _TO:
                return _ret(MarketRegime(
                    "sideways", "整理（yfinance 超時）",
                    0, 0, 0, 0, True, True, 1.0,
                    "yfinance 25 秒未回應，預設整理"))
        if twii.empty:
            return _ret(MarketRegime(
                "sideways", "整理（無資料）",
                0, 0, 0, 0, True, True, 1.0,
                "加權指數抓取失敗，預設整理"))
        twii["MA20"] = twii["Close"].rolling(20).mean()
        twii["MA60"] = twii["Close"].rolling(60).mean()
        # 取 as_of_date 之前最後一根
        if as_of_date:
            twii = twii[twii.index.date <= end]
        if twii.empty or pd.isna(twii["MA60"].iloc[-1]):
            return _ret(MarketRegime(
                "sideways", "整理（資料不足）",
                0, 0, 0, 0, True, True, 1.0,
                "MA60 未成形"))
        last = twii.iloc[-1]
        close = float(last["Close"])
        ma20 = float(last["MA20"])
        ma60 = float(last["MA60"])
        gap = (ma20 / ma60 - 1) * 100
        if gap >= REGIME_BULL_GAP and close >= ma20:
            return _ret(MarketRegime(
                "bull", "🔴 強多頭",
                close, ma20, ma60, gap,
                allow_long=True, allow_short=False, capital_scale=1.0,
                note=f"MA20 ({ma20:.0f}) > MA60 ({ma60:.0f}) "
                     f"+{gap:.1f}%，禁開空單"))
        if gap <= REGIME_BEAR_GAP and close <= ma20:
            return _ret(MarketRegime(
                "bear", "🟢 強空頭",
                close, ma20, ma60, gap,
                allow_long=False, allow_short=True, capital_scale=1.0,
                note=f"MA20 ({ma20:.0f}) &lt; MA60 ({ma60:.0f}) "
                     f"{gap:.1f}%，禁開多單"))
        # ★ Tier1-1C：加「弱多頭 / 弱空頭」中間層
        # 目的：MA 排列偏多但收盤回檔跌破 MA20 → 禁多、允空、資金 0.7
        #      MA 排列偏空但收盤反彈突破 MA20 → 允多、禁空、資金 0.7
        # 動機：近月 TWII −7.26% 期間，系統仍在「sideways 雙向開倉」推做多
        #       導致 42 筆早停虧損。改後熊市回檔時做多會被擋住。
        if gap >= REGIME_BULL_GAP and close < ma20:
            return _ret(MarketRegime(
                "weak_bull", "🟡 弱多頭（回檔）",
                close, ma20, ma60, gap,
                allow_long=False, allow_short=True, capital_scale=0.7,
                note=(f"MA20-MA60 展 +{gap:.1f}% 趨勢向上，但收盤 "
                      f"{close:.0f} &lt; MA20 ({ma20:.0f}) 正在回檔；"
                      f"暫禁多單、允空 70% 資金")))
        if gap <= REGIME_BEAR_GAP and close > ma20:
            return _ret(MarketRegime(
                "weak_bear", "🟠 弱空頭（反彈）",
                close, ma20, ma60, gap,
                allow_long=True, allow_short=False, capital_scale=0.7,
                note=(f"MA20-MA60 展 {gap:+.1f}% 趨勢向下，但收盤 "
                      f"{close:.0f} > MA20 ({ma20:.0f}) 正在反彈；"
                      f"暫禁空單、允多 70% 資金")))
        # 真正的整理：|gap| < 3%
        note_txt = (f"MA20-MA60 差距 {gap:+.1f}% 在 ±3% 內，"
                    f"雙向開倉但資金縮減 50%")
        return _ret(MarketRegime(
            "sideways", "⚪ 整理",
            close, ma20, ma60, gap,
            allow_long=True, allow_short=True, capital_scale=0.5,
            note=note_txt))
    except Exception as e:
        return _ret(MarketRegime(
            "sideways", "整理（例外）",
            0, 0, 0, 0, True, True, 1.0,
            f"regime 偵測例外：{str(e)[:60]}"))


# ============================================================
# Lv4：動態持有期 + 技術停損
# ============================================================
def recommended_hold_days(regime: MarketRegime,
                           default: int = 20) -> tuple[int, str]:
    """根據 regime 推薦「最長持有上限」（交易日）.

    ★ 2026-09-03 語意變更：原本回傳「預定出場日」（3/7/10 日），
      現在只是防呆安全網 — 出場主控權交給 check_technical_stop 的
      MA 移動停利。

    改動依據（08-05~09-03 實測 N=35）：
      獲利單 13 筆有 8 筆（62%）撞到日曆天花板，前 4 大贏家有 3 筆
      是在最後一天被強制平倉（+13.1%/6d、+9.3%/6d、+8.3%/6d），
      壓低均賺至 +5.10%，而打平需要 +6.37%。
      虧損單則由 MA10 提前砍（中位 4 日）→「停損看趨勢、停利看日曆」
      的錯置，是盈虧比只有 1.354（需 1.692）的主因。
    """
    abs_gap = abs(regime.ma_gap_pct)
    if abs_gap >= 5:
        return 30, (f"強趨勢市（MA20-MA60 差 {regime.ma_gap_pct:+.1f}%）"
                    f"→ 持有上限 30 日")
    if abs_gap >= 3:
        return 20, (f"中度趨勢市（差 {regime.ma_gap_pct:+.1f}%）"
                    f"→ 持有上限 20 日")
    return 10, "整理市 → 持有上限 10 日（出場仍以 MA 移動停利為主）"


# 移動停利門檻：未實現獲利達此 % 後，出場基準由 MA10 收緊到 MA5。
# 目的是讓「還在趨勢中」的贏家繼續跑（MA10 較寬、容忍拉回），
# 但一旦利潤變厚就改用較緊的 MA5 鎖住，避免大幅回吐。
TRAIL_TIGHTEN_PCT = 10.0


def check_technical_stop(df: pd.DataFrame, side: str,
                          entry_price: float,
                          trail: bool = True) -> tuple[bool, str]:
    """檢查當前 K 線是否觸發技術停損 / 移動停利.

    df: 該股最新 K 線 + indicators（含 ma5 / ma10）
    side: 'long' or 'short'
    trail: True 時啟用獲利分層收緊（>= TRAIL_TIGHTEN_PCT 改用 MA5）

    出場基準（多空對稱）：
      未實現獲利 <  10%  → 跌破/突破 MA10 出場
      未實現獲利 >= 10%  → 改用 MA5（移動停利，鎖住趨勢末端利潤）

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
    ma5 = None
    if "ma5" in df.columns and not pd.isna(last["ma5"]):
        ma5 = float(last["ma5"])

    # 未實現獲利（多空對稱；entry_price 異常時退回 0 → 一律用 MA10）
    if entry_price and entry_price > 0 and close > 0:
        gain_pct = ((close / entry_price - 1) * 100 if side == "long"
                    else (entry_price / close - 1) * 100)
    else:
        gain_pct = 0.0

    ref_name, ref = "MA10", ma10
    if trail and gain_pct >= TRAIL_TIGHTEN_PCT and ma5 is not None:
        ref_name, ref = "MA5", ma5

    # 多單跌破基準均線 → 出場
    if side == "long" and close < ref:
        return True, (f"多單跌破 {ref_name} ({ref:.2f})，"
                      f"當日 {close:.2f}，相對進場 {gain_pct:+.2f}%")
    # 空單突破基準均線 → 回補
    if side == "short" and close > ref:
        return True, (f"空單突破 {ref_name} ({ref:.2f})，"
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
