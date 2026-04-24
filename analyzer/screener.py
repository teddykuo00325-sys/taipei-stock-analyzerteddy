"""選股器 — 批次掃描台股、評分、排名做多/做空前 N.

回傳結構：
  {
    "long": DataFrame,   # top N long（含欄位 _df_tail, _diag）
    "short": DataFrame,  # top N short
    "full": DataFrame,
    "total": int,
    "passed": int,
  }
"""
from __future__ import annotations

from typing import Callable

import pandas as pd
import yfinance as yf

from . import (candlestick, diagnosis, indicators, institutional,
               margin, price_cache, universe)


def _rename(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })


def _score_one(code: str, name: str, df: pd.DataFrame,
               min_avg_volume_lots: int) -> dict | None:
    try:
        df = _rename(df).dropna()
        if len(df) < 60:
            return None
        avg_vol = float(df["volume"].tail(20).mean())
        if avg_vol < min_avg_volume_lots * 1000:
            return None
        dff = indicators.add_all(df)
        d = diagnosis.diagnose(dff, code=code, include_chips=True)
        last = dff.iloc[-1]
        prev = dff.iloc[-2]
        # 量價簡述
        vol_brief = d.volume_note.split("（")[0] if "（" in d.volume_note else d.volume_note
        # 法人簡述
        inst = d.institutional_info
        inst_brief = "—"
        if inst:
            total_lots = inst["total_net"] // 1000
            inst_brief = f"{'+' if total_lots >= 0 else ''}{total_lots:,}"
        # 融資券簡述
        marg = d.margin_info
        marg_brief = "—"
        if marg:
            marg_brief = f"融資{marg['margin_change_pct']:+.1f}% 券{marg['short_change_pct']:+.1f}%"
        return {
            "代號": code,
            "名稱": name,
            "收盤": round(float(last["close"]), 2),
            "漲跌%": round((last["close"] / prev["close"] - 1) * 100, 2),
            "分數": d.score,
            "評估": d.stance,
            "建議": d.action,
            "均線": d.ma_state,
            "量價": vol_brief,
            "波浪": d.wave_label,
            "KD": f"{last['k']:.0f}/{last['d']:.0f}",
            "RSI": round(float(last["rsi"]), 1),
            "法人(張)": inst_brief,
            "融資/券": marg_brief,
            "Hurst": round(d.econ.hurst, 2) if d.econ else None,
            "費波": d.fib.nearest.name if (d.fib and d.fib.nearest
                                             and d.fib.nearest_distance_pct <= 2.5)
                   else "—",
            "日均量(張)": int(avg_vol / 1000),
            "目標價": round(d.target_price, 2) if d.target_price else None,
            "短線停損": round(d.short_stop, 2) if d.short_stop else None,
            "風報比": d.risk_reward,
            "_df_tail": dff.tail(90).copy(),
            "_diag": d,
            "_patterns_hist": candlestick.scan_history(dff, lookback=60),
            "_in_entry_zone": bool(
                d.entry_zone and d.entry_zone[0] <= float(last["close"])
                <= d.entry_zone[1]
            ),
        }
    except Exception:
        return None


def _fetch_batch(tickers: list[str], period: str) -> pd.DataFrame | None:
    try:
        return yf.download(
            tickers, period=period, interval="1d",
            auto_adjust=False, progress=False, threads=True,
            group_by="ticker",
        )
    except Exception:
        return None


def _load_from_cache(code: str, period: str) -> pd.DataFrame | None:
    """從 price_cache 讀取（欄位已是小寫）."""
    try:
        df = price_cache.get(code, period=period)
        if df.empty:
            return None
        return df
    except Exception:
        return None


def screen(
    min_avg_volume_lots: int = 1000,
    top_n: int = 20,
    period: str = "6mo",
    pre_filter_lots_today: int = 200,
    chunk_size: int = 40,
    progress_cb: Callable[[float, str], None] | None = None,
    limit: int | None = None,
) -> dict:
    snap = universe.snapshot()
    if pre_filter_lots_today > 0:
        snap = snap[snap["TradeVolume"] >= pre_filter_lots_today * 1000]
    snap = snap.sort_values("TradeVolume", ascending=False).reset_index(drop=True)
    if limit:
        snap = snap.head(limit)

    # 預抓法人 & 融資券 快照（共用快取）
    if progress_cb:
        progress_cb(0.01, "抓取三大法人 & 融資融券快照…")
    try:
        institutional.snapshot()
    except Exception:
        pass
    try:
        margin.snapshot()
    except Exception:
        pass

    codes = snap["Code"].tolist()
    names = dict(zip(snap["Code"], snap["Name"]))
    total = len(codes)

    # ===== 步驟 1：預熱 / 增量更新 price_cache (60% 進度) =====
    def _warm_cb(pct, msg):
        if progress_cb:
            progress_cb(0.02 + pct * 0.60, msg)

    price_cache.bulk_prepare(
        codes, warm_period="2y",
        chunk_size=chunk_size, progress_cb=_warm_cb,
    )

    # ===== 步驟 2：自快取讀取並評分（37% 進度）=====
    results: list[dict] = []
    for i, code in enumerate(codes):
        if progress_cb and (i % 20 == 0):
            progress_cb(0.62 + (i / max(total, 1)) * 0.37,
                        f"分析 {i + 1} / {total}…")
        df = _load_from_cache(code, period)
        if df is None:
            continue
        df_upper = df.rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        })
        row = _score_one(code, names.get(code, code),
                         df_upper, min_avg_volume_lots)
        if row:
            results.append(row)

    if progress_cb:
        progress_cb(1.0, f"分析完成，{len(results)} 檔通過均量篩選")

    full_df = pd.DataFrame(results)
    if full_df.empty:
        return {"long": full_df, "short": full_df, "full": full_df,
                "total": total, "passed": 0}
    long_top = full_df.nlargest(top_n, "分數").reset_index(drop=True)
    short_top = full_df.nsmallest(top_n, "分數").reset_index(drop=True)
    return {
        "long": long_top, "short": short_top, "full": full_df,
        "total": total, "passed": len(full_df),
    }
