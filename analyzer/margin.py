"""融資融券 — TWSE MI_MARGN 每日資料."""
from __future__ import annotations

from time import time

import pandas as pd

from . import http

URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"

# 中文鍵 → 英文鍵
_KEY_MAP = {
    "股票代號": "Code", "股票名稱": "Name",
    "融資買進": "MarginBuy", "融資賣出": "MarginSell",
    "融資現金償還": "MarginRepay",
    "融資前日餘額": "MarginPrev", "融資今日餘額": "MarginToday",
    "融資限額": "MarginQuota",
    "融券買進": "ShortBuy", "融券賣出": "ShortSell",
    "融券現券償還": "ShortRepay",
    "融券前日餘額": "ShortPrev", "融券今日餘額": "ShortToday",
    "融券限額": "ShortQuota",
    "資券互抵": "DayTradeOffset", "註記": "Note",
}


def _to_int(v) -> int:
    try:
        return int(str(v).replace(",", "").strip() or 0)
    except Exception:
        return 0


def _fetch_raw() -> pd.DataFrame:
    r = http.get(URL, timeout=20)
    r.raise_for_status()
    data = r.json()
    df = pd.DataFrame(data)
    df = df.rename(columns=_KEY_MAP)
    for c in df.columns:
        if c not in ("Code", "Name", "Note"):
            df[c] = df[c].map(_to_int)
    return df


_cache: dict = {"time": 0, "df": None}


def snapshot(max_age_sec: int = 3600,
             auto_append_history: bool = True) -> pd.DataFrame:
    now = time()
    if _cache["df"] is not None and now - _cache["time"] < max_age_sec:
        return _cache["df"]
    try:
        df = _fetch_raw()
    except Exception:
        return pd.DataFrame()
    df["Code"] = df["Code"].astype(str).str.strip()
    df = df[df["Code"].str.match(r"^\d{4}$")].reset_index(drop=True)
    df["MarginChange"] = df["MarginToday"] - df["MarginPrev"]
    df["ShortChange"] = df["ShortToday"] - df["ShortPrev"]
    _cache["df"] = df
    _cache["time"] = now

    # 自動把今日資料 append 到歷史 DB（給 5/20 日趨勢分析用）
    if auto_append_history:
        try:
            from . import margin_history
            margin_history.append_today(df)
        except Exception:
            pass

    return df


def for_code(code: str) -> dict | None:
    df = snapshot()
    if df.empty:
        return None
    row = df[df["Code"] == str(code).strip()]
    if row.empty:
        return None
    r = row.iloc[0]
    margin_today = int(r["MarginToday"])
    margin_prev = int(r["MarginPrev"])
    short_today = int(r["ShortToday"])
    short_prev = int(r["ShortPrev"])
    margin_pct = ((margin_today - margin_prev) / margin_prev * 100) if margin_prev else 0.0
    short_pct = ((short_today - short_prev) / short_prev * 100) if short_prev else 0.0
    return {
        "margin_today": margin_today,
        "margin_prev": margin_prev,
        "margin_change": margin_today - margin_prev,
        "margin_change_pct": margin_pct,
        "short_today": short_today,
        "short_prev": short_prev,
        "short_change": short_today - short_prev,
        "short_change_pct": short_pct,
        "day_trade_offset": int(r.get("DayTradeOffset", 0)),
    }


def summarize(code: str) -> str:
    info = for_code(code)
    if info is None:
        return "無資料"
    m = info["margin_change"]
    s = info["short_change"]
    mp = info["margin_change_pct"]
    sp = info["short_change_pct"]
    return (f"融資 {info['margin_today']:,}（{m:+,}／{mp:+.1f}%） · "
            f"融券 {info['short_today']:,}（{s:+,}／{sp:+.1f}%）")


def score_adj(code: str, price_up: bool | None = None) -> tuple[int, str]:
    """籌碼面評分調整：
    - 融資大增 + 股價下跌 → 散戶套牢警訊（-5）
    - 融資大減 + 股價上漲 → 洗清浮額（+5）
    - 融券大增 → 軋空潛力（+5）
    - 融券大減 → 軋空力道消退（-3）
    """
    info = for_code(code)
    if info is None:
        return 0, ""
    score = 0
    notes: list[str] = []
    mp = info["margin_change_pct"]
    sp = info["short_change_pct"]

    if mp >= 5 and price_up is False:
        score -= 5
        notes.append(f"融資+{mp:.1f}% 但股價跌，散戶追高警訊")
    elif mp <= -5 and price_up is True:
        score += 5
        notes.append(f"融資{mp:.1f}% 股價漲，洗清浮額")

    if sp >= 5:
        score += 5
        notes.append(f"融券+{sp:.1f}%，軋空潛力")
    elif sp <= -10:
        score -= 3
        notes.append(f"融券{sp:.1f}%，軋空力道消退")

    return score, "；".join(notes)
