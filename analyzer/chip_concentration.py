"""籌碼集中度訊號 — 小散戶 (Level 2+3) 離場偵測.

理論：主力吸收散戶手中籌碼 → Level 2 (1~5張) + Level 3 (5~10張)
人數減少 → 若同時滿足 (未破 4 月低點, 日均量 ≥ 2000 張) 則是強訊號.

觸發條件（用戶原始規則）：
  ① 當週 Level 2+3 人數減少 ≥ 5%
  ② 該週最低價未跌破前 4 個月低點
  ③ 日均成交量 ≥ 2000 張
  ④ (加成) 連續 2 週以上減少

分數（regime-aware）：
  Bull    I_max = 10
  Bear    I_max = 8
  Sideways I_max = 15  ★ 整理盤最有效

對外 API:
  detect_signal(code) -> ChipSignal | None
  verify_hypothesis() -> dict   歷史回測勝率驗證框架
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from . import shareholders, price_cache


# 觸發門檻
WEEKLY_DROP_THRESHOLD = -5.0   # Level 2+3 週減少 ≥ 5% (負值)
MIN_AVG_VOLUME_LOTS = 2000     # 日均量 (張)
LOW_LOOKBACK_MONTHS = 4        # 前 4 個月低點


@dataclass
class ChipSignal:
    code: str
    date: str              # 訊號評估日
    # 核心數據
    l2_count: int          # 本週 Level 2 人數
    l3_count: int          # 本週 Level 3 人數
    l2l3_total: int        # L2+L3 加總
    prev_week_total: int   # 上週 L2+L3 加總
    weekly_change_pct: float  # 週變化率 (%)
    streak: int            # 連續減少週數
    # 過濾條件
    lowest_this_week: float
    low_4m: float
    broke_4m_low: bool
    avg_volume_lots: float
    # 綜合判定
    qualified: bool        # 是否符合原始規則
    score: int             # 綜合分（給 tiebreaker 用）
    note: str


def _load_prices(code: str, days: int = 100) -> pd.DataFrame:
    """讀 K 線；ETF/畸零標的可能沒 cache."""
    try:
        df = price_cache._load(code)
        if df is None or df.empty:
            return pd.DataFrame()
        return df.tail(days)
    except Exception:
        return pd.DataFrame()


def _weekly_totals(code: str) -> list[tuple[str, int]]:
    """讀該 code 歷史 L2+L3 人數清單 [(date, l2+l3), ...] 依時間排序.

    只回傳 l2_count / l3_count 都有值的紀錄（新 schema 之後才有）.
    """
    with shareholders._lock, shareholders._conn() as c:
        rows = c.execute(
            "SELECT date, l2_count, l3_count FROM holders "
            "WHERE code=? AND l2_count IS NOT NULL "
            "  AND l3_count IS NOT NULL "
            "ORDER BY date",
            (str(code).strip(),),
        ).fetchall()
    out = []
    for d, l2, l3 in rows:
        try:
            out.append((d, int(l2) + int(l3)))
        except Exception:
            continue
    return out


def _compute_streak(totals: list[tuple[str, int]]) -> int:
    """從最新一週往回數，連續減少 ≥ 5% 的週數.

    totals: [(date, total)]  時間升序.
    """
    if len(totals) < 2:
        return 0
    streak = 0
    for i in range(len(totals) - 1, 0, -1):
        prev = totals[i - 1][1]
        cur = totals[i][1]
        if prev <= 0:
            break
        pct = (cur / prev - 1) * 100
        if pct <= WEEKLY_DROP_THRESHOLD:
            streak += 1
        else:
            break
    return streak


def detect_signal(code: str) -> ChipSignal | None:
    """為單一標的計算籌碼集中度訊號.

    需要 shareholders DB 已累積 ≥ 2 週 L2/L3 資料；否則回 None.
    """
    totals = _weekly_totals(code)
    if len(totals) < 2:
        return None  # 資料不足

    latest_date, latest_total = totals[-1]
    prev_date, prev_total = totals[-2]
    if prev_total <= 0:
        return None
    weekly_change_pct = (latest_total / prev_total - 1) * 100

    # 拆 L2 / L3（重新查一次拿到分開的欄位）
    with shareholders._lock, shareholders._conn() as c:
        r = c.execute(
            "SELECT l2_count, l3_count FROM holders "
            "WHERE code=? AND date=?", (code, latest_date)).fetchone()
    l2_count = int(r[0]) if r and r[0] is not None else 0
    l3_count = int(r[1]) if r and r[1] is not None else 0

    # 4 月低點 check + 日均量
    df_price = _load_prices(code, days=100)
    if df_price.empty:
        return None

    # 前 4 月低點（不含最近 5 日 = 本週）
    cutoff = date.today() - timedelta(days=LOW_LOOKBACK_MONTHS * 30)
    df_prior = df_price[df_price.index < pd.Timestamp(cutoff)] \
        if len(df_price) >= 20 else df_price
    if df_prior.empty:
        df_prior = df_price.head(-5) if len(df_price) > 5 else df_price
    low_4m = float(df_prior["low"].min()) if not df_prior.empty else 0

    # 本週最低（最近 5 交易日 = 一週）
    df_week = df_price.tail(5)
    lowest_this_week = float(df_week["low"].min())
    broke_4m_low = lowest_this_week < low_4m if low_4m > 0 else False

    # 日均量（近 20 日）
    avg_volume_shares = float(df_price["volume"].tail(20).mean())
    avg_volume_lots = avg_volume_shares / 1000

    # 連續減少週數
    streak = _compute_streak(totals)

    # 綜合判定
    qualified = (
        weekly_change_pct <= WEEKLY_DROP_THRESHOLD
        and not broke_4m_low
        and avg_volume_lots >= MIN_AVG_VOLUME_LOTS
    )

    # 分數（滿分 15，加成到 20）
    score = 0
    notes = []
    if qualified:
        score = 15
        notes.append(f"L2+L3 週減 {weekly_change_pct:+.1f}%")
        if streak >= 2:
            score += 3
            notes.append(f"連 {streak} 週")
        if streak >= 3:
            score += 2
            notes.append(f"× {streak} 週強化")
    elif weekly_change_pct >= 5.0:
        # 反向：散戶湧入警告
        score = -8
        notes.append(f"⚠️ 散戶湧入 {weekly_change_pct:+.1f}%（主力可能出貨）")
    elif weekly_change_pct <= WEEKLY_DROP_THRESHOLD:
        # 減少但條件不完全
        reason = []
        if broke_4m_low:
            reason.append(f"破 4 月低 ({low_4m:.2f})")
        if avg_volume_lots < MIN_AVG_VOLUME_LOTS:
            reason.append(f"量不足 {avg_volume_lots:.0f}<2000")
        notes.append(
            f"L2+L3 -{abs(weekly_change_pct):.1f}% 但守門失敗 "
            f"({', '.join(reason)})")

    return ChipSignal(
        code=code, date=latest_date,
        l2_count=l2_count, l3_count=l3_count,
        l2l3_total=latest_total, prev_week_total=prev_total,
        weekly_change_pct=round(weekly_change_pct, 2),
        streak=streak,
        lowest_this_week=lowest_this_week,
        low_4m=low_4m,
        broke_4m_low=broke_4m_low,
        avg_volume_lots=round(avg_volume_lots, 0),
        qualified=qualified,
        score=score,
        note=" ｜ ".join(notes) if notes else "無明顯籌碼變化",
    )


# ============================================================
# 假設驗證框架 — 上線前跑，勝率 > 55% 才採用
# ============================================================
def verify_hypothesis(
    forward_days_list: tuple = (5, 10, 20),
) -> dict:
    """歷史回測「小散戶連續離場」訊號的勝率.

    方法：
      對每個 code 在 DB 中的每一週 snapshot：
      - 若當週 detect_signal 判定 qualified → 記為觸發點
      - 假設「訊號日買進」，看 forward_days 後報酬
      - 統計 hit_rate / avg_return / vs TWII

    回傳：
      {
        "n_triggers": 累積訊號數,
        "by_forward": {5: {...}, 10: {...}, 20: {...}},
        "note": 顯著性提醒
      }
    """
    # 找所有有 L2/L3 資料的 code
    with shareholders._lock, shareholders._conn() as c:
        codes = [r[0] for r in c.execute(
            "SELECT DISTINCT code FROM holders "
            "WHERE l2_count IS NOT NULL"
        ).fetchall()]

    triggers = []  # [(code, trigger_date, entry_close)]
    by_forward: dict = {fd: [] for fd in forward_days_list}

    for code in codes:
        totals = _weekly_totals(code)
        if len(totals) < 4:
            continue  # 至少 4 週資料才能算連續
        df_price = _load_prices(code, days=400)
        if df_price.empty:
            continue

        # 遍歷歷史每個 snapshot 週
        for i in range(1, len(totals)):
            prev_d, prev_t = totals[i - 1]
            cur_d, cur_t = totals[i]
            if prev_t <= 0:
                continue
            wpct = (cur_t / prev_t - 1) * 100
            if wpct > WEEKLY_DROP_THRESHOLD:
                continue  # 沒減少 5%
            # 檢查該週最低 vs 前 4 月低
            try:
                cur_date_ts = pd.Timestamp(cur_d)
            except Exception:
                continue
            df_week = df_price[
                (df_price.index >= cur_date_ts - pd.Timedelta(days=7))
                & (df_price.index <= cur_date_ts)
            ]
            if df_week.empty:
                continue
            week_low = float(df_week["low"].min())
            df_prior = df_price[
                df_price.index < cur_date_ts - pd.Timedelta(
                    days=LOW_LOOKBACK_MONTHS * 30)
            ]
            if df_prior.empty:
                continue
            low_4m = float(df_prior["low"].min())
            if week_low < low_4m:
                continue  # 破 4 月低點，不算

            # 日均量
            df_recent = df_price[df_price.index <= cur_date_ts].tail(20)
            avg_vol = float(df_recent["volume"].mean()) / 1000
            if avg_vol < MIN_AVG_VOLUME_LOTS:
                continue

            # 觸發成立 — 取觸發後第一個交易日收盤當進場價
            df_after = df_price[df_price.index > cur_date_ts]
            if df_after.empty:
                continue
            entry_price = float(df_after["close"].iloc[0])
            triggers.append((code, cur_d, entry_price))

            for fd in forward_days_list:
                if len(df_after) <= fd:
                    continue
                exit_price = float(df_after["close"].iloc[fd])
                ret = (exit_price / entry_price - 1) * 100
                by_forward[fd].append(ret)

    result_by_fd = {}
    for fd, rets in by_forward.items():
        if not rets:
            result_by_fd[fd] = {"n": 0}
            continue
        wins = sum(1 for r in rets if r > 0)
        result_by_fd[fd] = {
            "n": len(rets),
            "win_rate": round(wins / len(rets) * 100, 1),
            "avg": round(sum(rets) / len(rets), 2),
            "best": round(max(rets), 2),
            "worst": round(min(rets), 2),
            "median": round(sorted(rets)[len(rets) // 2], 2),
        }

    max_n = max((v.get("n", 0) for v in result_by_fd.values()), default=0)
    if max_n < 30:
        note = f"⚠️ 樣本 N={max_n} < 30 統計上無意義，DB 需累積 4+ 週資料"
    elif max_n < 100:
        note = f"📊 樣本 N={max_n} 累積中，達 100 後可信度高"
    else:
        note = f"✅ 樣本 N={max_n} 可信"

    return {
        "n_triggers": len(triggers),
        "by_forward": result_by_fd,
        "note": note,
    }
