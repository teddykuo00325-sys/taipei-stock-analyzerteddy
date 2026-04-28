"""融資融券 5 維度評分（B 完整版）.

5 大維度：
  1. 四象限（融資 × 5 日累積股價）— 30%  ← 朱家泓資增/資減 × 價漲/價跌
  2. 券資比（融券/融資，動態分位數）— 20%   ← 軋空潛力
  3. 融券回補壓力（融券餘額/5日均量）— 15%  ← 軋空催化
  4. 融資使用率（融資餘額/限額）— 15%      ← 散戶槓桿水位
  5. 5/20 日趨勢（需歷史 ≥ 20 日）— 20%   ← 資金累積方向

設計選擇（已與 user 確認）：
  - 股價方向用「5 日累積漲跌」（>+1% 漲、< -1% 跌、其他持平）
  - 券資比閾值用「全市場今日分布的 20/40/60/80 分位數」動態調整
  - 規模化用「融資使用率」（融資餘額/限額），不額外抓股本
  - ETF / 無融資商品（margin_quota < 100）回 None（N/A）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from . import margin, margin_history, price_cache


# === 權重 ===
WEIGHTS = {
    "quadrant": 0.30,
    "short_ratio": 0.20,
    "short_pressure": 0.15,
    "margin_usage": 0.15,
    "trend": 0.20,
}


@dataclass
class MarginScore:
    code: str
    total: float                      # 加權總分 (-10 ~ +10)
    quadrant: int                     # 維度 1
    short_ratio: int                  # 維度 2
    short_pressure: int               # 維度 3
    margin_usage: int                 # 維度 4
    trend: int                        # 維度 5
    notes: list[str]                  # 各維度說明
    # 原始輔助數據
    price_5d_pct: float | None = None
    margin_chg: int | None = None
    short_chg: int | None = None
    short_to_margin_ratio: float | None = None
    days_to_cover: float | None = None
    margin_usage_pct: float | None = None
    n_history_days: int = 0


# ---------- 維度 1：四象限 ----------
def _score_quadrant(margin_chg: int, price_5d_pct: float) -> tuple[int, str]:
    """融資增減 × 5 日股價方向."""
    margin_up = margin_chg > 0
    margin_dn = margin_chg < 0
    # 股價：>+1% 算漲、< -1% 算跌、其他持平
    if price_5d_pct >= 1.0:
        price_dir = "up"
    elif price_5d_pct <= -1.0:
        price_dir = "dn"
    else:
        price_dir = "flat"

    if margin_up and price_dir == "up":
        return +2, f"資增價漲（{margin_chg:+,}張 / {price_5d_pct:+.1f}%）：散戶追多"
    if margin_up and price_dir == "dn":
        return -10, (f"⚠️ 資增價跌（{margin_chg:+,}張 / {price_5d_pct:+.1f}%）："
                     f"散戶套牢，賣壓累積")
    if margin_dn and price_dir == "up":
        return +10, (f"✅ 資減價漲（{margin_chg:+,}張 / {price_5d_pct:+.1f}%）："
                     f"洗清浮額，主力推升")
    if margin_dn and price_dir == "dn":
        return +4, (f"資減價跌（{margin_chg:+,}張 / {price_5d_pct:+.1f}%）："
                    f"散戶停損出場，可能近底")
    return 0, "融資/股價持平，無明顯訊號"


# ---------- 維度 2：券資比（動態分位數）----------
def _score_short_ratio(short_today: int, margin_today: int,
                        cross_df: pd.DataFrame) -> tuple[int, str]:
    """券資比 = 融券/融資；用全市場今日 20/40/60/80 分位數定義閾值."""
    if margin_today <= 0:
        return 0, "無融資餘額（券資比無意義）"
    ratio = short_today / margin_today
    # 全市場分位數
    if cross_df.empty or "margin_today" not in cross_df.columns:
        # 沒分位數資料，退回固定閾值
        if ratio >= 0.30:
            return +10, f"券資比 {ratio*100:.1f}% （>30% 軋空潛力極大）"
        if ratio >= 0.15:
            return +5, f"券資比 {ratio*100:.1f}%（15-30% 偏空合理）"
        if ratio >= 0.05:
            return 0, f"券資比 {ratio*100:.1f}%（正常範圍）"
        return -2, f"券資比 {ratio*100:.1f}%（< 5% 空方冷清）"
    cross = cross_df.copy()
    cross["ratio"] = (cross["short_today"] /
                      cross["margin_today"].replace(0, pd.NA))
    valid = cross["ratio"].dropna()
    if len(valid) < 50:
        # 樣本太少，退回固定閾值
        if ratio >= 0.30:
            return +10, f"券資比 {ratio*100:.1f}% （>30% 軋空潛力極大）"
        if ratio >= 0.15:
            return +5, f"券資比 {ratio*100:.1f}%（15-30% 偏空合理）"
        return 0, f"券資比 {ratio*100:.1f}%"
    qs = valid.quantile([0.20, 0.40, 0.60, 0.80])
    q20, q40, q60, q80 = qs[0.20], qs[0.40], qs[0.60], qs[0.80]
    if ratio > q80:
        return +10, (f"券資比 {ratio*100:.1f}%（市場 P{int(qs.index[-1]*100)}+，"
                     f"軋空潛力極大）")
    if ratio > q60:
        return +5, f"券資比 {ratio*100:.1f}%（市場 P60-80，偏空合理）"
    if ratio > q40:
        return 0, f"券資比 {ratio*100:.1f}%（市場 P40-60，正常）"
    if ratio > q20:
        return -1, f"券資比 {ratio*100:.1f}%（市場 P20-40，偏弱）"
    return -2, f"券資比 {ratio*100:.1f}%（市場 P20-，空方冷清）"


# ---------- 維度 3：融券回補壓力 ----------
def _score_short_pressure(short_today: int, avg_vol_5d: float
                           ) -> tuple[int, str, float | None]:
    """融券餘額 × 1000 / 5 日均量 = 完全回補需要幾天."""
    if not avg_vol_5d or avg_vol_5d <= 0:
        return 0, "無均量資料", None
    days = (short_today * 1000) / avg_vol_5d
    if days > 5:
        return +8, f"回補天數 {days:.1f} 日（>5 強烈軋空催化）", days
    if days > 3:
        return +4, f"回補天數 {days:.1f} 日（3-5 中等回補壓力）", days
    if days > 1:
        return +1, f"回補天數 {days:.1f} 日（1-3 輕微）", days
    return 0, f"回補天數 {days:.1f} 日（流通量大、無壓力）", days


# ---------- 維度 4：融資使用率 ----------
def _score_margin_usage(margin_today: int, margin_quota: int
                         ) -> tuple[int, str, float | None]:
    """融資餘額/限額；高使用率=散戶過度槓桿."""
    if margin_quota <= 0:
        return 0, "無融資限額資料", None
    usage = margin_today / margin_quota
    if usage > 0.80:
        return -6, (f"融資使用率 {usage*100:.1f}%（>80% 散戶過度槓桿，"
                    f"續漲風險高）"), usage
    if usage > 0.50:
        return -2, f"融資使用率 {usage*100:.1f}%（50-80% 中等）", usage
    if usage > 0.20:
        return +2, f"融資使用率 {usage*100:.1f}%（20-50% 健康）", usage
    return +4, f"融資使用率 {usage*100:.1f}%（<20% 籌碼乾淨）", usage


# ---------- 維度 5：5/20 日趨勢 ----------
def _score_trend(history: pd.DataFrame, price_5d_pct: float
                  ) -> tuple[int, str, int]:
    """5 日均 vs 20 日均，配合股價方向給分."""
    if history.empty or len(history) < 20:
        return 0, f"歷史不足 20 日（目前 {len(history)} 日，趨勢分數 N/A）", \
                  len(history)

    margin_5ma = history["margin_today"].tail(5).mean()
    margin_20ma = history["margin_today"].tail(20).mean()
    short_5ma = history["short_today"].tail(5).mean()
    short_20ma = history["short_today"].tail(20).mean()

    score = 0
    notes_local: list[str] = []
    price_up = price_5d_pct >= 1.0

    # 融資加速進場 + 股價漲
    if margin_5ma > margin_20ma * 1.1 and price_up:
        score += 5
        notes_local.append("融資 5MA > 20MA × 1.1 + 股價漲 (+5)")
    # 融資持續清洗 + 股價漲（更健康）
    elif margin_5ma < margin_20ma * 0.9 and price_up:
        score += 8
        notes_local.append("融資 5MA < 20MA × 0.9 + 股價漲 (+8)")
    # 融券加碼 + 股價漲 → 軋空醞釀
    if short_5ma > short_20ma * 1.2 and price_up:
        score += 10
        notes_local.append("融券 5MA > 20MA × 1.2 + 股價漲 (+10 軋空醞釀)")
    elif short_5ma < short_20ma * 0.8 and price_up:
        score -= 3
        notes_local.append("融券 5MA < 20MA × 0.8 + 股價漲 (-3 軋空力道消退)")

    note = ("； ".join(notes_local) if notes_local
            else f"5/20MA 趨勢無明顯訊號（融資 5MA={margin_5ma:.0f}/20MA="
                 f"{margin_20ma:.0f}，融券 5MA={short_5ma:.0f}/20MA="
                 f"{short_20ma:.0f}）")
    return score, note, len(history)


# ---------- 主入口 ----------
import re

# ETF 代號 regex（前 2 碼為 00，如 0050, 0052, 00878, 006208 等）
_ETF_CODE_RE = re.compile(r"^(00\d{2,4})$")


def is_etf_code(code: str) -> bool:
    """以代號規則判斷是否為 ETF：
       - 4 碼以 00 開頭（0050、0052、0056...）
       - 5-6 碼以 00 開頭（00878、006203、00692...）
    """
    return bool(_ETF_CODE_RE.match(str(code).strip()))


def is_etf_or_unsupported(code: str | None,
                          today: dict | None) -> bool:
    """判斷是否為 ETF 或無融資商品（融資限額 < 100 張）."""
    if code and is_etf_code(code):
        return True
    if today is None:
        return True
    quota = today.get("margin_quota") or 0
    return quota < 100


def score(code: str,
          price_df: pd.DataFrame | None = None) -> MarginScore | None:
    """5 維度融資融券評分.

    price_df: 該股 K 線（小寫欄位）；若 None 則自動從 price_cache 取。
    回傳 MarginScore，ETF / 無融資商品回 None。
    """
    today = margin.for_code(code)
    today_full = today  # 別名
    # 取 quota（margin.for_code 沒回 quota，需要再從 snapshot 取）
    snap = margin.snapshot()
    if not snap.empty:
        row = snap[snap["Code"] == str(code).strip()]
        if not row.empty:
            today_full = dict(today or {})
            today_full["margin_quota"] = int(row.iloc[0]["MarginQuota"])
            today_full["short_quota"] = int(row.iloc[0]["ShortQuota"])
    if is_etf_or_unsupported(code, today_full):
        return None

    # 5 日累積股價漲跌
    if price_df is None:
        try:
            price_df = price_cache._load(code)
        except Exception:
            price_df = pd.DataFrame()
    price_5d_pct = 0.0
    avg_vol_5d = 0.0
    if not price_df.empty and len(price_df) >= 6:
        price_5d_pct = (float(price_df["close"].iloc[-1])
                        / float(price_df["close"].iloc[-6]) - 1) * 100
        avg_vol_5d = float(price_df["volume"].tail(5).mean())

    # 取歷史 + cross-section
    try:
        history = margin_history.load(code, days=20)
    except Exception:
        history = pd.DataFrame()
    try:
        cross = margin_history.cross_section_today()
    except Exception:
        cross = pd.DataFrame()

    margin_chg = today_full.get("margin_change", 0)
    short_chg = today_full.get("short_change", 0)
    margin_today_v = today_full.get("margin_today", 0)
    short_today_v = today_full.get("short_today", 0)
    margin_quota_v = today_full.get("margin_quota", 0)

    # === 五維度 ===
    d1, n1 = _score_quadrant(margin_chg, price_5d_pct)
    d2, n2 = _score_short_ratio(short_today_v, margin_today_v, cross)
    d3, n3, days_cover = _score_short_pressure(short_today_v, avg_vol_5d)
    d4, n4, usage = _score_margin_usage(margin_today_v, margin_quota_v)
    d5, n5, n_hist = _score_trend(history, price_5d_pct)

    # 加權加總
    total = (d1 * WEIGHTS["quadrant"]
             + d2 * WEIGHTS["short_ratio"]
             + d3 * WEIGHTS["short_pressure"]
             + d4 * WEIGHTS["margin_usage"]
             + d5 * WEIGHTS["trend"])

    short_to_margin = (short_today_v / margin_today_v
                       if margin_today_v > 0 else None)

    return MarginScore(
        code=str(code), total=round(total, 2),
        quadrant=d1, short_ratio=d2, short_pressure=d3,
        margin_usage=d4, trend=d5,
        notes=[n1, n2, n3, n4, n5],
        price_5d_pct=price_5d_pct,
        margin_chg=margin_chg, short_chg=short_chg,
        short_to_margin_ratio=short_to_margin,
        days_to_cover=days_cover,
        margin_usage_pct=usage,
        n_history_days=n_hist,
    )
