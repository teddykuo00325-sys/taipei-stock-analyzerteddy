"""美股關鍵指標 — 跟台股關聯度高的指數 + 巨頭 + 相關性分析.

對台股影響：
  ⭐⭐⭐⭐⭐ 費半 SOX     台積電/聯電/聯發科直接同步
  ⭐⭐⭐⭐  NASDAQ        科技股母市
  ⭐⭐⭐   SP500         美股大盤情緒
  ⭐⭐⭐   NASDAQ 100    科技權值股
  ⭐⭐⭐⭐  VIX           恐慌指數，外資進出指標
  ⭐⭐    道瓊          參考用

巨頭：
  Magnificent 7：NVDA / AAPL / MSFT / META / GOOGL / AMZN / TSLA
  + ASML（半導體設備）+ TSM（台積電 ADR）+ SPCX（SpaceX 估值）

對外 API:
  fetch_us_market() -> dict  完整資訊（指數 + 巨頭 + 相關性）
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from time import time

import yfinance as yf


# 指數（含相關性權重給 TG 顯示用）
INDICES = [
    ("^SOX",  "費半 SOX",    "⭐⭐⭐⭐⭐"),
    ("^IXIC", "NASDAQ",     "⭐⭐⭐⭐"),
    ("^NDX",  "NASDAQ 100", "⭐⭐⭐⭐"),
    ("^GSPC", "SP500",      "⭐⭐⭐"),
    ("^VIX",  "VIX 恐慌",   "⭐⭐⭐⭐"),
    ("^DJI",  "道瓊",        "⭐⭐"),
]

# 美股巨頭 + 台積電 ADR + SpaceX
GIANTS = [
    ("NVDA",  "NVIDIA",   "⭐⭐⭐⭐⭐", "🤖"),   # 對 TSMC/AI 概念股
    ("ASML",  "ASML",     "⭐⭐⭐⭐⭐", "🔬"),   # 半導體設備
    ("TSM",   "TSM ADR",  "⭐⭐⭐⭐⭐", "🇹🇼"),  # 台積電美股
    ("AAPL",  "Apple",    "⭐⭐⭐⭐", "🍎"),
    ("MSFT",  "Microsoft", "⭐⭐⭐⭐", "💻"),
    ("META",  "Meta",     "⭐⭐⭐", "📺"),
    ("GOOGL", "Google",   "⭐⭐⭐", "🔍"),
    ("AMZN",  "Amazon",   "⭐⭐⭐", "📦"),
    ("TSLA",  "Tesla",    "⭐⭐⭐", "🚗"),
    ("SPCX",  "SpaceX",   "⭐⭐", "🚀"),
]


@dataclass
class USQuote:
    symbol: str
    label: str
    correlation: str        # ⭐⭐⭐⭐⭐ 表示跟台股相關性
    icon: str               # emoji
    price: float
    change: float
    change_pct: float
    last_date: str          # yfinance 最後一筆日期 (UTC)


_cache: dict = {"t": 0.0, "v": None}
_CACHE_TTL = 1800  # 30 分鐘


def _fetch_one(symbol: str) -> tuple[float, float, float, str] | None:
    """單一 ticker 抓最近 5 日，回最後一筆 close + 漲跌 + 日期."""
    try:
        h = yf.Ticker(symbol).history(period="5d")
        if h.empty or len(h) < 2:
            return None
        last = float(h["Close"].iloc[-1])
        prev = float(h["Close"].iloc[-2])
        chg = last - prev
        pct = (chg / prev * 100) if prev else 0.0
        date_str = h.index[-1].strftime("%Y-%m-%d")
        return last, chg, pct, date_str
    except Exception:
        return None


def _fetch_correlation_with_tw() -> dict[str, float]:
    """30 日：費半 vs 台積電(2330) 滾動相關性.

    ★ 時區對齊修正：
    台股 T 日（早上 9 點開盤）反映的是美股 T-1 日（紐約時間 16:00 收盤
    = 台北 T 日凌晨 4 點）的訊息。所以正確的對齊方式是：
      ^SOX_{T-1} 的日報酬 ↔ 2330_{T} 的日報酬
    把 SOX 日期 +1 後 join，等同於「TW 同一天交易反映前夜 SOX 收盤」。
    """
    try:
        import pandas as pd
        sox_raw = yf.download("^SOX", period="60d", progress=False,
                               auto_adjust=False)
        tsmc_raw = yf.download("2330.TW", period="60d", progress=False,
                                auto_adjust=False)
        if sox_raw.empty or tsmc_raw.empty:
            return {}
        # 拆出 Close 欄位（yfinance 可能回 MultiIndex 或單層）
        def _close(df):
            if isinstance(df.columns, pd.MultiIndex):
                return df["Close"].iloc[:, 0]
            return df["Close"]
        sox = _close(sox_raw)
        tsmc = _close(tsmc_raw)
        # 去 tz 統一索引
        if sox.index.tz is not None:
            sox.index = sox.index.tz_localize(None)
        if tsmc.index.tz is not None:
            tsmc.index = tsmc.index.tz_localize(None)
        # 日報酬
        sox_ret = sox.pct_change().dropna()
        tsmc_ret = tsmc.pct_change().dropna()
        # ★ 關鍵：SOX 日期 +1，讓「美股 T-1 收盤 → 台股 T 開盤反應」對齊
        # 即 SOX_2026-06-18 的報酬與 2330_2026-06-19 的報酬配對
        sox_shifted = sox_ret.copy()
        sox_shifted.index = sox_shifted.index + pd.Timedelta(days=1)
        df = (tsmc_ret.to_frame("tsmc")
              .join(sox_shifted.to_frame("sox_prev_us"), how="inner")
              .dropna())
        if len(df) < 10:
            return {}
        corr = float(df["sox_prev_us"].corr(df["tsmc"]))
        return {"sox_vs_2330_30d": round(corr, 3),
                "n_days": len(df)}
    except Exception:
        return {}


def fetch_us_market(max_age_sec: int = _CACHE_TTL) -> dict:
    """完整抓取美股關鍵指標 + 相關性分析.

    回傳：
      {
        "indices": [USQuote, ...],
        "giants": [USQuote, ...],
        "correlation": {"sox_vs_2330_30d": 0.85, ...},
        "last_date": "2026-06-19",   # 最近一筆資料日期
      }
    """
    now = time()
    if _cache["v"] and now - _cache["t"] < max_age_sec:
        return _cache["v"]

    # 平行抓所有 tickers
    all_targets = ([(s, l, corr, "") for s, l, corr in INDICES]
                   + [(s, l, corr, ic) for s, l, corr, ic in GIANTS])
    results: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_fetch_one, sym): sym
                for sym, _, _, _ in all_targets}
        for fut in as_completed(futs):
            sym = futs[fut]
            try:
                r = fut.result()
                if r:
                    results[sym] = r
            except Exception:
                continue

    def _build(items):
        out = []
        for tup in items:
            if len(tup) == 4:
                sym, label, corr, icon = tup
            else:
                sym, label, corr = tup
                icon = ""
            r = results.get(sym)
            if not r:
                continue
            price, chg, pct, dt = r
            out.append(USQuote(
                symbol=sym, label=label, correlation=corr, icon=icon,
                price=price, change=chg, change_pct=pct, last_date=dt,
            ))
        return out

    indices = _build(INDICES)
    giants = _build(GIANTS)
    correlation = _fetch_correlation_with_tw()

    # last_date 取最常見的（多數 yfinance 應給同一天）
    last_dates = [q.last_date for q in indices + giants if q.last_date]
    last_date = max(last_dates) if last_dates else ""

    result = {
        "indices": indices,
        "giants": giants,
        "correlation": correlation,
        "last_date": last_date,
    }
    _cache["v"] = result
    _cache["t"] = now
    return result


# ============================================================
# Tier1-2B：Overnight US gap-down 風險評估
# ============================================================
def overnight_gap_risk() -> dict:
    """基於美股 T-1 收盤變動，評估台股 T 開盤跳空風險.

    邏輯：
      SOX（費半）跌 &gt; 2% → 台積電/聯電/聯發科高機率同步跳空下殺 → 高風險
      SPX 跌 &gt; 2%         → 大盤級恐慌情緒 → 高風險
      VIX &gt; 30            → 極端恐慌 → 高風險

    回傳：
      {
        "level": "high" / "medium" / "low",
        "long_capital_scale": 0.0 / 0.5 / 1.0,   # 做多資金乘數
        "reason": "SOX -3.5% overnight"
      }

    使用場景：
      screener 或 lock_session_auto 依此決定是否減碼 / skip long entries
    """
    try:
        d = fetch_us_market()
    except Exception:
        return {"level": "low", "long_capital_scale": 1.0, "reason": "US 資料無法取得"}
    indices = {q.symbol: q for q in d.get("indices", [])}
    sox_pct = indices.get("^SOX").change_pct if indices.get("^SOX") else 0
    spx_pct = indices.get("^GSPC").change_pct if indices.get("^GSPC") else 0
    vix = indices.get("^VIX").price if indices.get("^VIX") else 0

    reasons = []
    high_risk = False
    med_risk = False

    if sox_pct is not None and sox_pct <= -2.0:
        high_risk = True
        reasons.append(f"SOX {sox_pct:+.2f}%")
    elif sox_pct is not None and sox_pct <= -1.0:
        med_risk = True
        reasons.append(f"SOX {sox_pct:+.2f}%")

    if spx_pct is not None and spx_pct <= -2.0:
        high_risk = True
        reasons.append(f"SPX {spx_pct:+.2f}%")
    elif spx_pct is not None and spx_pct <= -1.0 and not high_risk:
        med_risk = True
        reasons.append(f"SPX {spx_pct:+.2f}%")

    if vix and vix >= 30:
        high_risk = True
        reasons.append(f"VIX {vix:.1f}")
    elif vix and vix >= 25 and not high_risk:
        med_risk = True
        reasons.append(f"VIX {vix:.1f}")

    if high_risk:
        return {
            "level": "high",
            "long_capital_scale": 0.0,   # 完全 skip long
            "reason": " ｜ ".join(reasons) or "美股大跌",
        }
    if med_risk:
        return {
            "level": "medium",
            "long_capital_scale": 0.5,   # 減碼 50%
            "reason": " ｜ ".join(reasons) or "美股走弱",
        }
    return {
        "level": "low",
        "long_capital_scale": 1.0,
        "reason": "美股平穩",
    }
