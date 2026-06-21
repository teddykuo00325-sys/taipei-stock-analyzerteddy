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
    """TG 私人訊息用格式 (HTML).

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
        lines.append(
            f"   • <b>{s.code} {s.name}</b>\n"
            f"     {status}\n"
            f"     <i>原因：{reason_short}</i>"
        )
    remaining = len(stocks) - max_n
    if remaining > 0:
        lines.append(f"   <i>…另有 {remaining} 檔（已截斷）</i>")
    return "\n".join(lines)


def to_dataframe(stocks: list[DisposalStock]):
    """Web 用 DataFrame."""
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
            "處置原因": s.reason,
            "處置等級": s.measure,
            "公告日": s.announce_date.isoformat(),
        })
    return pd.DataFrame(rows)
