"""三大法人買賣超 — TWSE T86 每日資料."""
from __future__ import annotations

from datetime import datetime, timedelta
from time import time

import pandas as pd

from . import http

URL = "https://www.twse.com.tw/rwd/zh/fund/T86"

# TWSE T86 欄位（以取得時順序）
_FIELDS = [
    "Code", "Name",
    "ForeignBuy", "ForeignSell", "ForeignNet",          # 外陸資（不含自營）
    "ForeignDealerBuy", "ForeignDealerSell", "ForeignDealerNet",  # 外資自營
    "TrustBuy", "TrustSell", "TrustNet",                # 投信
    "DealerNet",                                        # 自營商（合計）
    "DealerOwnBuy", "DealerOwnSell", "DealerOwnNet",    # 自營 - 自行買賣
    "DealerHedgeBuy", "DealerHedgeSell", "DealerHedgeNet",  # 自營 - 避險
    "TotalNet",                                         # 三大法人合計
]


def _to_int(v) -> int:
    try:
        return int(str(v).replace(",", "").strip() or 0)
    except Exception:
        return 0


def _fetch_for(date_str: str) -> pd.DataFrame | None:
    params = {"date": date_str, "selectType": "ALLBUT0999", "response": "json"}
    try:
        r = http.get(URL, params=params, timeout=15)
        r.raise_for_status()
        j = r.json()
    except Exception:
        return None
    if j.get("stat") != "OK" or not j.get("data"):
        return None
    df = pd.DataFrame(j["data"], columns=_FIELDS[:len(j["fields"])])
    for c in _FIELDS[2:]:
        if c in df.columns:
            df[c] = df[c].map(_to_int)
    df["Code"] = df["Code"].astype(str).str.strip()
    df = df[df["Code"].str.match(r"^\d{4}$")].reset_index(drop=True)
    return df


_cache: dict = {"time": 0, "df": None}


def snapshot(max_age_sec: int = 3600) -> pd.DataFrame:
    """取得最新可用交易日的三大法人買賣超.

    若今日尚未公告會往前追溯（週末/假日亦同）.
    """
    now = time()
    if _cache["df"] is not None and now - _cache["time"] < max_age_sec:
        return _cache["df"]
    # 從今日往前找 5 個交易日
    today = datetime.now()
    for offset in range(6):
        d = today - timedelta(days=offset)
        if d.weekday() >= 5:
            continue
        df = _fetch_for(d.strftime("%Y%m%d"))
        if df is not None and not df.empty:
            _cache["df"] = df
            _cache["time"] = now
            return df
    return pd.DataFrame()


def for_code(code: str) -> dict | None:
    """單一股票的三大法人買賣超（股數）."""
    df = snapshot()
    if df.empty:
        return None
    row = df[df["Code"] == str(code).strip()]
    if row.empty:
        return None
    r = row.iloc[0]
    return {
        "foreign_net": int(r.get("ForeignNet", 0)),
        "trust_net": int(r.get("TrustNet", 0)),
        "dealer_net": int(r.get("DealerNet", 0)),
        "total_net": int(r.get("TotalNet", 0)),
    }


def summarize(code: str, lots_threshold: int = 500) -> str:
    """產出簡短中文摘要（買超/賣超張數）."""
    info = for_code(code)
    if info is None:
        return "無資料"
    parts = []
    labels = [("外資", "foreign_net"), ("投信", "trust_net"), ("自營", "dealer_net")]
    for label, key in labels:
        shares = info[key]
        lots = round(shares / 1000)
        if abs(lots) < lots_threshold / 10:
            continue
        sign = "+" if lots >= 0 else ""
        parts.append(f"{label}{sign}{lots:,}")
    total_lots = round(info["total_net"] / 1000)
    summary = " / ".join(parts) if parts else "法人無明顯動作"
    return f"{summary}（三大合計 {total_lots:+,} 張）"


def score_adj(code: str) -> tuple[int, str]:
    """依三大法人買賣超給分（±15）與說明."""
    info = for_code(code)
    if info is None:
        return 0, ""
    total = info["total_net"]
    foreign = info["foreign_net"]
    trust = info["trust_net"]
    lots = total / 1000
    if total >= 5_000_000 and foreign > 0 and trust > 0:
        return 15, "外資+投信雙買超"
    if total >= 2_000_000:
        return 10, "三大法人買超"
    if total >= 500_000:
        return 5, "法人小幅買超"
    if total <= -5_000_000 and foreign < 0:
        return -15, "外資大幅賣超"
    if total <= -2_000_000:
        return -10, "三大法人賣超"
    if total <= -500_000:
        return -5, "法人小幅賣超"
    return 0, f"法人中性（淨 {lots:+.0f} 張）"
