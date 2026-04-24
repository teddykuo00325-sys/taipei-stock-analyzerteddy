"""資金流向 — 依產業別匯總今日漲跌與成交值，找出強勢/弱勢族群.

資料源支援：
  "eod"  — TWSE STOCK_DAY_ALL（前一交易日收盤快照，盤中非即時）
  "live" — TWSE MIS 批次即時報價（盤中真實當下）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from . import industry, live, universe


@dataclass
class SectorFlow:
    industry: str
    count: int
    up_count: int
    down_count: int
    avg_change_pct: float
    median_change_pct: float
    total_value: int       # 總成交值 (NTD)
    total_volume: int      # 總成交張數
    top_movers: list[dict]


def _enrich_eod() -> pd.DataFrame:
    snap = universe.snapshot()
    if snap.empty:
        return snap
    ind_df = industry.snapshot()[["code", "short_name", "industry", "ind_code"]]
    merged = snap.merge(ind_df, left_on="Code", right_on="code", how="left")
    merged["industry"] = merged["industry"].fillna("未分類")
    close = pd.to_numeric(merged["ClosingPrice"], errors="coerce")
    change = pd.to_numeric(merged["Change"], errors="coerce")
    prev = close - change
    merged["Change%"] = (change / prev * 100).round(2)
    merged = merged.dropna(subset=["Change%"])
    return merged


def _enrich_live(progress_cb: Callable | None = None) -> pd.DataFrame:
    """透過 MIS 批次取得盤中真實報價，組成與 EOD 相同結構的 DataFrame."""
    ind_df = industry.snapshot()
    if ind_df.empty:
        return pd.DataFrame()
    codes = ind_df[ind_df["code"].str.match(r"^\d{4}$")]["code"].tolist()
    quotes = live.quotes(codes, chunk_size=100, progress_cb=progress_cb)
    rows = []
    for code, q in quotes.items():
        if q.current is None or q.yesterday is None or q.yesterday == 0:
            continue
        change = q.current - q.yesterday
        vol_shares = (q.volume_lots or 0) * 1000
        rows.append({
            "Code": code, "Name": q.name,
            "ClosingPrice": q.current,
            "Change": change,
            "TradeVolume": vol_shares,
            "TradeValue": int(vol_shares * q.current),
            "Change%": round(change / q.yesterday * 100, 2),
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    merged = df.merge(ind_df[["code", "short_name", "industry", "ind_code"]],
                      left_on="Code", right_on="code", how="left")
    merged["industry"] = merged["industry"].fillna("未分類")
    return merged


def _enrich(source: str = "eod",
            progress_cb: Callable | None = None) -> pd.DataFrame:
    if source == "live":
        return _enrich_live(progress_cb=progress_cb)
    return _enrich_eod()


def by_industry(min_stocks: int = 3,
                exclude_etf: bool = True,
                source: str = "eod",
                progress_cb: Callable | None = None) -> list[SectorFlow]:
    df = _enrich(source=source, progress_cb=progress_cb)
    if df.empty:
        return []
    if exclude_etf:
        df = df[df["industry"] != "受益證券"]
        df = df[df["industry"] != "管理股票"]
        df = df[df["industry"] != "存託憑證"]
    out: list[SectorFlow] = []
    for ind, grp in df.groupby("industry"):
        if len(grp) < min_stocks:
            continue
        up = int((grp["Change"] > 0).sum())
        dn = int((grp["Change"] < 0).sum())
        total_val = int(grp["TradeValue"].fillna(0).sum())
        total_vol = int(grp["TradeVolume"].fillna(0).sum())
        # 族群內 top 5 漲幅
        movers = grp.nlargest(5, "Change%")[
            ["Code", "short_name", "Change%", "ClosingPrice", "TradeVolume"]
        ].to_dict("records")
        # 族群內 top 5 跌幅
        losers = grp.nsmallest(5, "Change%")[
            ["Code", "short_name", "Change%", "ClosingPrice", "TradeVolume"]
        ].to_dict("records")
        top_mixed = movers + losers
        out.append(SectorFlow(
            industry=ind,
            count=len(grp),
            up_count=up,
            down_count=dn,
            avg_change_pct=float(grp["Change%"].mean()),
            median_change_pct=float(grp["Change%"].median()),
            total_value=total_val,
            total_volume=total_vol,
            top_movers=top_mixed,
        ))
    out.sort(key=lambda x: x.avg_change_pct, reverse=True)
    return out


def market_summary(source: str = "eod") -> dict:
    df = _enrich(source=source)
    if df.empty:
        return {}
    up = int((df["Change"] > 0).sum())
    dn = int((df["Change"] < 0).sum())
    flat = int((df["Change"] == 0).sum())
    total_val = int(df["TradeValue"].fillna(0).sum())
    return {
        "total_stocks": len(df),
        "up": up, "down": dn, "flat": flat,
        "avg_change_pct": float(df["Change%"].mean()),
        "total_value": total_val,  # 總成交值（元）
    }
