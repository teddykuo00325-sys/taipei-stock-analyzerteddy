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

import math
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
    """單一 ticker 抓最近 5 日，回最後一筆 close + 漲跌 + 日期.

    ★ 2026-10-13：yfinance 有時會對某些 symbol 回一列「全 NaN 的佔位
    資料」—— 當日其他 symbol 都正常，就那檔是 NaN。實測 2026-10-12
    的 META 與 SPCX 就是這樣（dropna 後最後一筆退回 10-09）。

    原本直接取 .iloc[-1] 會把 NaN 一路帶到 TG，印出
        🟢 📺 Meta　$nan　(+nan%)
    而且 `NaN >= 0` 為 False，漲跌箭頭固定顯示綠燈。

    更危險的是 overnight_gap_risk()：若 ^SOX 哪天也中這招，
    `NaN <= -2.0` 為 False，跳空保護會**靜默失效**。所以在來源端就
    把 NaN 濾掉，並在算完後再確認一次。
    """
    try:
        h = yf.Ticker(symbol).history(period="5d")
        if h.empty:
            return None
        h = h.dropna(subset=["Close"])
        if len(h) < 2:
            return None
        last = float(h["Close"].iloc[-1])
        prev = float(h["Close"].iloc[-2])
        if not (math.isfinite(last) and math.isfinite(prev)) or prev == 0:
            return None
        chg = last - prev
        pct = chg / prev * 100
        if not math.isfinite(pct):
            return None
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

    def _val(sym: str, attr: str):
        """取指數欄位；缺資料或 NaN 一律回 None（不要當成 0）."""
        q = indices.get(sym)
        if q is None:
            return None
        v = getattr(q, attr, None)
        if v is None:
            return None
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v if math.isfinite(v) else None

    sox_pct = _val("^SOX", "change_pct")
    spx_pct = _val("^GSPC", "change_pct")
    vix = _val("^VIX", "price")

    # ★ 2026-10-13 fail-safe：原本 sox_pct 缺值時給 0，而 `0 <= -2.0`
    # 與 `0 <= -1.0` 都是 False → 直接落到 low risk，跳空保護靜默消失。
    # NaN 更糟：`is not None` 擋不住它，任何比較都是 False。
    # 改為「關鍵指標拿不到 → 視為 medium（做多減碼 50%）」——
    # 資料缺失不等於市場崩盤，停掉做多太重；但當沒事又太輕。
    if sox_pct is None and spx_pct is None:
        return {
            "level": "medium",
            "long_capital_scale": 0.5,
            "reason": "⚠️ 美股 SOX/SPX 資料不可用 → 保守減碼 50%",
        }

    reasons = []
    high_risk = False
    med_risk = False
    if sox_pct is None or spx_pct is None:
        miss = "SOX" if sox_pct is None else "SPX"
        reasons.append(f"⚠️ {miss} 資料不可用")
        med_risk = True

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
