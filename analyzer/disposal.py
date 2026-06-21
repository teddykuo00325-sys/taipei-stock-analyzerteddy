"""處置股追蹤 — TWSE 處置公告 (第一次處置 = 每 20 分鐘揭示成交資訊).

設計：
  - 第一次處置：每隔 20 分鐘揭示一次（最常見、影響流動性中等）
  - 第二次處置：每 5 分鐘揭示 + 預收款券
  - 第三次處置：每筆委託逐筆撮合 + 預收款券（最嚴）

用途：
  - 避免買到剛進處置（流動性差、波動大）的標的
  - 或主動研究：剛進處置代表前期漲幅過大 / 異常 → 可能反轉
  - Filter：剛進處置 (days_in ≤ 3) 或即將開始 (start_date > today)

對外 API:
  fetch_all() -> list[DisposalStock]
  recent_disposals(max_days_in=3, interval_filter=20) -> list[DisposalStock]
  format_for_tg(stocks) -> str
  to_dataframe(stocks) -> pd.DataFrame
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from time import time

import requests


TWSE_URL = "https://openapi.twse.com.tw/v1/announcement/punish"

_cache: dict = {"t": 0.0, "v": None}
_TTL = 600  # 10 分鐘 cache


@dataclass
class DisposalStock:
    code: str
    name: str
    announce_date: date           # 公告日
    start_date: date              # 處置開始日
    end_date: date                # 處置結束日
    reason: str                   # 處置原因（連續三次/連續六次/異常波動…）
    measure: str                  # 第一次/第二次/第三次處置
    interval_min: int             # 揭示間隔分鐘 (20/5/0=逐筆)
    days_in: int                  # 處置第 N 日（1-based；未開始=0）
    days_remaining: int           # 剩餘日數
    # 價格資料（with_price_data 填）
    entry_price: float | None = None       # 處置開始前一交易日收盤
    current_price: float | None = None     # 最新收盤
    price_3d_after: float | None = None    # 處置開始後第 3 交易日收盤
    drop_pct: float | None = None          # (current - entry) / entry %
    drop_3d_pct: float | None = None       # (price_3d_after - entry) / entry %


def _parse_roc_date(s: str) -> date | None:
    """民國日期 → date.

    支援格式：
      '1150611'       (ROC 115 年 06 月 11 日)
      '115/06/11'     (slash 分隔)
      '115年6月11日'  (中文)
    """
    if not s:
        return None
    s = s.strip()
    # 處理中文格式
    s = s.replace("年", "/").replace("月", "/").replace("日", "")
    if "/" in s:
        parts = [p.strip() for p in s.split("/") if p.strip()]
        if len(parts) == 3:
            try:
                y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                return date(y + 1911, m, d)
            except Exception:
                return None
    elif len(s) >= 6 and s.isdigit():
        try:
            y = int(s[:-4])
            m = int(s[-4:-2])
            d = int(s[-2:])
            return date(y + 1911, m, d)
        except Exception:
            return None
    return None


def _parse_period(s: str) -> tuple[date | None, date | None]:
    """'115/06/12～115/06/26' → (date(2026,6,12), date(2026,6,26))"""
    if not s:
        return None, None
    # 全形 ～ 跟半形 ~ 都支援
    parts = re.split(r"[～~]", s)
    if len(parts) != 2:
        return None, None
    start = _parse_roc_date(parts[0])
    end = _parse_roc_date(parts[1])
    return start, end


def _measure_to_interval(measure: str) -> int:
    """處置方式 → 揭示間隔分鐘.

    第一次處置 → 20 分鐘（最常見、流動性影響中等）
    第二次處置 → 5 分鐘（影響大）
    第三次處置 → 0（逐筆撮合，影響最大）
    """
    if not measure:
        return 20
    if "第一" in measure or "一次" in measure:
        return 20
    if "第二" in measure or "二次" in measure:
        return 5
    if "第三" in measure or "三次" in measure:
        return 0
    return 20  # 默認


def fetch_all(max_age_sec: int = _TTL) -> list[DisposalStock]:
    """從 TWSE 抓全部處置股清單 + parse 成 DisposalStock list.

    含 cache（10 分鐘）。失敗回 [].
    """
    now = time()
    if _cache["v"] and now - _cache["t"] < max_age_sec:
        return _cache["v"]

    try:
        r = requests.get(TWSE_URL, timeout=15,
                          headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    today = date.today()
    out: list[DisposalStock] = []
    for d in data:
        code = str(d.get("Code", "")).strip()
        if not code:
            continue
        # 排除權證等非股票（純股票代號為 4 位或 5 位數字，權證 6 位）
        if len(code) >= 6 and code[0].isdigit():
            continue
        name = str(d.get("Name", "")).strip()
        ann_d = _parse_roc_date(str(d.get("Date", "")))
        start, end = _parse_period(str(d.get("DispositionPeriod", "")))
        if not start or not end:
            continue
        measure = str(d.get("DispositionMeasures", "")).strip()
        reason = str(d.get("ReasonsOfDisposition", "")).strip()
        days_in = (today - start).days + 1 if today >= start else 0
        days_remaining = max(0, (end - today).days) if today <= end else 0
        out.append(DisposalStock(
            code=code, name=name,
            announce_date=ann_d or today,
            start_date=start, end_date=end,
            reason=reason, measure=measure,
            interval_min=_measure_to_interval(measure),
            days_in=days_in,
            days_remaining=days_remaining,
        ))
    _cache["v"] = out
    _cache["t"] = now
    return out


def recent_disposals(
    max_days_in: int = 3,
    interval_filter: int | None = 20,
    include_upcoming: bool = True,
) -> list[DisposalStock]:
    """篩出「剛進處置」+「即將開始」.

    Args:
        max_days_in: 已開始的 → days_in 必須 ≤ 此值（預設 3）
        interval_filter: 20=只看 20 分鐘揭示（第一次處置）;
                          None=全部
        include_upcoming: True 包含 start_date 還沒到的（即將開始）

    回傳：依 (未開始優先 → 已開始 days_in 由小到大) 排序
    """
    all_disp = fetch_all()
    today = date.today()
    out = []
    for s in all_disp:
        if interval_filter is not None and s.interval_min != interval_filter:
            continue
        # 已結束的 skip
        if s.end_date < today:
            continue
        if s.start_date > today:
            if include_upcoming:
                out.append(s)
        elif 0 < s.days_in <= max_days_in:
            out.append(s)
    # 排序：未開始（start > today）優先，再來 days_in 越小越前
    out.sort(key=lambda x: (
        0 if x.start_date > today else 1,
        x.start_date.toordinal() if x.start_date > today else x.days_in,
    ))
    return out


def format_for_tg(stocks: list[DisposalStock],
                   header: bool = True,
                   max_n: int = 10) -> str:
    """TG 私人訊息用格式 (HTML)，含跌幅資訊（如果 with_price_data 跑過）.

    Returns '' 若無資料。
    """
    if not stocks:
        return ""
    today = date.today()
    lines: list[str] = []
    if header:
        lines.append(
            "\n🚨 <b>處置股名單（20 分鐘揭示，剛進處置 / 即將開始）</b>"
        )
    for s in stocks[:max_n]:
        if s.start_date > today:
            days_until = (s.start_date - today).days
            status = (f"⏳ <b>{days_until} 日後開始</b> "
                      f"({s.start_date.isoformat()} → "
                      f"{s.end_date.isoformat()})")
        else:
            status = (f"📅 <b>處置第 {s.days_in} 日</b> "
                      f"({s.start_date.isoformat()} → "
                      f"{s.end_date.isoformat()})")
        reason_short = s.reason[:30] if s.reason else "—"
        # 跌幅 line（如果有資料）
        drop_line = ""
        if s.entry_price and s.current_price:
            drop_emoji = "📉" if (s.drop_pct or 0) < 0 else "📈"
            drop_line = (
                f"\n     {drop_emoji} 進場前 {s.entry_price:.2f} → "
                f"最新 {s.current_price:.2f} "
                f"<b>({s.drop_pct:+.2f}%)</b>"
            )
            if s.drop_3d_pct is not None:
                drop_line += (
                    f" ｜ 3 日內 <b>{s.drop_3d_pct:+.2f}%</b>"
                )
        lines.append(
            f"   • <b>{s.code} {s.name}</b>\n"
            f"     {status}{drop_line}\n"
            f"     <i>原因：{reason_short}</i>"
        )
    remaining = len(stocks) - max_n
    if remaining > 0:
        lines.append(f"   <i>…另有 {remaining} 檔（已截斷）</i>")
    return "\n".join(lines)


def to_dataframe(stocks: list[DisposalStock]):
    """Web 用 DataFrame（含價格資料如果 with_price_data 跑過）."""
    import pandas as pd
    today = date.today()
    rows = []
    for s in stocks:
        status = ("即將開始" if s.start_date > today
                  else f"第 {s.days_in} 日")
        rows.append({
            "代號": s.code,
            "名稱": s.name,
            "狀態": status,
            "處置起": s.start_date.isoformat(),
            "處置迄": s.end_date.isoformat(),
            "剩餘日": s.days_remaining,
            "揭示間隔": f"{s.interval_min} 分" if s.interval_min > 0 else "逐筆",
            "進場前收": s.entry_price,
            "3日後收": s.price_3d_after,
            "最新收": s.current_price,
            "3日跌幅%": s.drop_3d_pct,
            "累計跌幅%": s.drop_pct,
            "處置原因": s.reason,
            "處置等級": s.measure,
            "公告日": s.announce_date.isoformat(),
        })
    return pd.DataFrame(rows)


# ============================================================
# 價格比較 — 處置開始前 vs 開始 3 日後 vs 最新
# ============================================================
def with_price_data(stocks: list[DisposalStock]) -> list[DisposalStock]:
    """為每個處置股補上價格資料.

    entry_price = 處置開始日「前一交易日」收盤（基準）
    price_3d_after = 處置開始日 + 3 個交易日收盤
    current_price = 最新收盤
    """
    from . import price_cache
    import pandas as pd
    for s in stocks:
        try:
            df = price_cache._load(s.code)
            if df is None or df.empty:
                continue
            # entry: 處置開始前的最後一個交易日
            entry_mask = df.index < pd.Timestamp(s.start_date)
            if entry_mask.any():
                s.entry_price = float(df.loc[entry_mask, "close"].iloc[-1])
            # current: 最新
            s.current_price = float(df["close"].iloc[-1])
            # 3-day after start: 處置開始當日 + 後 2 個交易日 = 第 3 個交易日
            after_mask = df.index >= pd.Timestamp(s.start_date)
            after = df.loc[after_mask]
            if len(after) >= 3:
                s.price_3d_after = float(after["close"].iloc[2])
            # 計算跌幅
            if s.entry_price and s.entry_price > 0:
                if s.current_price:
                    s.drop_pct = (s.current_price / s.entry_price - 1) * 100
                if s.price_3d_after:
                    s.drop_3d_pct = (
                        s.price_3d_after / s.entry_price - 1) * 100
        except Exception:
            continue
    return stocks


def dropped_during_disposal(
    stocks: list[DisposalStock],
    threshold_pct: float = -3.0,
) -> list[DisposalStock]:
    """篩出處置 3 日內已下跌 ≤ threshold_pct% 的標的.

    threshold_pct = -3.0 → 跌幅 ≥ 3% 才入選
    """
    return [
        s for s in stocks
        if s.drop_3d_pct is not None and s.drop_3d_pct <= threshold_pct
    ]


# ============================================================
# 假設驗證 — 「處置 3 日內下跌 → 後續勝率高」
# ============================================================
def verify_hypothesis(
    drop_threshold_pct: float = -3.0,
    forward_days_list: tuple = (5, 10, 20),
    min_days_after_start: int = 3,
) -> dict:
    """驗證「處置 3 日內下跌 X% → 後續 N 日勝率高」假設.

    方法：
      1. 取所有 fetch_all() 的處置股
      2. 用 K 線算 entry_price, price_3d_after
      3. 篩 drop_3d_pct ≤ drop_threshold_pct 的（已跌超過門檻）
      4. 假設「day_3 收盤買進」，看 forward_days_list 後的報酬
      5. 計算 hit rate / avg return / vs TWII

    回傳：
      {
        "n_total": 全部處置股數,
        "n_qualified": 跌幅符合條件數,
        "by_forward": {
            5: {"n":..., "win_rate":..., "avg":..., "best":..., "worst":...},
            10: {...},
            20: {...},
        },
        "details": [...]   逐檔列表
      }
    """
    from . import price_cache
    import pandas as pd

    stocks = with_price_data(fetch_all())
    qualified = [s for s in stocks
                 if s.drop_3d_pct is not None
                 and s.drop_3d_pct <= drop_threshold_pct]
    if not qualified:
        return {
            "n_total": len(stocks),
            "n_qualified": 0,
            "by_forward": {},
            "details": [],
            "note": (f"目前無「處置 3 日內跌 ≥ {abs(drop_threshold_pct):.1f}%」"
                     f"的標的（含歷史 {len(stocks)} 筆）"),
        }

    details = []
    by_forward: dict = {fd: {"rets": []} for fd in forward_days_list}

    for s in qualified:
        try:
            df = price_cache._load(s.code)
            if df is None or df.empty:
                continue
            after_mask = df.index >= pd.Timestamp(s.start_date)
            after = df.loc[after_mask]
            if len(after) < min_days_after_start:
                continue
            buy_price = float(after["close"].iloc[min_days_after_start - 1])
            row = {
                "code": s.code, "name": s.name,
                "start_date": s.start_date.isoformat(),
                "entry_price": s.entry_price,
                "drop_3d_pct": s.drop_3d_pct,
                "buy_price_day3": buy_price,
                "forward": {},
            }
            for fd in forward_days_list:
                idx = (min_days_after_start - 1) + fd
                if len(after) <= idx:
                    row["forward"][fd] = None
                    continue
                sell_price = float(after["close"].iloc[idx])
                ret = (sell_price / buy_price - 1) * 100
                row["forward"][fd] = round(ret, 2)
                by_forward[fd]["rets"].append(ret)
            details.append(row)
        except Exception:
            continue

    # 彙總統計
    result_by_fd = {}
    for fd, data in by_forward.items():
        rets = data["rets"]
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

    return {
        "n_total": len(stocks),
        "n_qualified": len(qualified),
        "by_forward": result_by_fd,
        "details": details,
    }


# ============================================================
# 歷史快照 DB — 累積處置事件供長期驗證
# ============================================================
def _snapshot_db_path():
    from pathlib import Path
    p = Path(__file__).parent.parent / "data" / "disposal_history.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_db():
    import sqlite3
    p = _snapshot_db_path()
    c = sqlite3.connect(p)
    c.execute("""
        CREATE TABLE IF NOT EXISTS disposal_event (
            code TEXT NOT NULL,
            name TEXT,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            announce_date TEXT,
            measure TEXT,
            interval_min INTEGER,
            reason TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            PRIMARY KEY (code, start_date)
        )
    """)
    c.commit()
    return c


def snapshot_today() -> dict:
    """把今日 fetch_all() 結果記進 DB（idempotent，重複 snapshot 只更新 last_seen）.

    每天 GH Actions 跑一次即可累積歷史。
    """
    stocks = fetch_all()
    if not stocks:
        return {"saved": 0, "new": 0, "updated": 0}
    today_str = date.today().isoformat()
    new_count = 0
    updated_count = 0
    c = _ensure_db()
    try:
        for s in stocks:
            existing = c.execute(
                "SELECT 1 FROM disposal_event "
                "WHERE code=? AND start_date=?",
                (s.code, s.start_date.isoformat()),
            ).fetchone()
            if existing:
                c.execute(
                    "UPDATE disposal_event SET last_seen=? "
                    "WHERE code=? AND start_date=?",
                    (today_str, s.code, s.start_date.isoformat()),
                )
                updated_count += 1
            else:
                c.execute(
                    "INSERT INTO disposal_event "
                    "(code, name, start_date, end_date, announce_date, "
                    " measure, interval_min, reason, first_seen, last_seen) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (s.code, s.name, s.start_date.isoformat(),
                     s.end_date.isoformat(),
                     s.announce_date.isoformat(),
                     s.measure, s.interval_min, s.reason,
                     today_str, today_str),
                )
                new_count += 1
        c.commit()
    finally:
        c.close()
    return {
        "saved": len(stocks),
        "new": new_count,
        "updated": updated_count,
    }


def db_event_count() -> int:
    """DB 內已累積的處置事件數（用於統計顯著性判斷）."""
    import sqlite3
    p = _snapshot_db_path()
    if not p.exists():
        return 0
    c = sqlite3.connect(p)
    try:
        return c.execute(
            "SELECT COUNT(*) FROM disposal_event").fetchone()[0]
    except Exception:
        return 0
    finally:
        c.close()
