"""國際行情 + 展寬貴金屬當日回收價.

- 國際：yfinance（黃金、白銀、布蘭特/WTI 原油、美日匯率）
- 展寬：https://www.gck99.com.tw 現場解析
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from time import time

import yfinance as yf

from . import http as _http

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    BeautifulSoup = None  # type: ignore
    _HAS_BS4 = False

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

YF_TICKERS = {
    "gold":    ("GC=F",    "🪙 黃金 (USD/oz)", 2),
    "silver":  ("SI=F",    "🥈 白銀 (USD/oz)", 2),
    "brent":   ("BZ=F",    "🛢 布蘭特 (USD)", 2),
    "wti":     ("CL=F",    "🛢 西德州 (USD)", 2),
    "usd_twd": ("TWD=X",   "💵 美元/台幣",    3),
    "jpy_twd": ("JPYTWD=X", "💴 日圓/台幣",    4),
}



@dataclass
class Quote:
    key: str
    label: str
    price: float
    change: float
    change_pct: float
    precision: int


# ---------- Caches ----------
_intl_cache: dict = {"t": 0.0, "v": {}}
_gck_cache: dict = {"t": 0.0, "v": {}}
_idx_cache: dict = {"t": 0.0, "v": {}}


def intl_last_update() -> str:
    """回傳國際行情上次更新時間字串."""
    import datetime as _dt
    if _intl_cache["t"] == 0:
        return "—"
    return _dt.datetime.fromtimestamp(_intl_cache["t"]).strftime("%H:%M")


def gck_last_update() -> str:
    import datetime as _dt
    if _gck_cache["t"] == 0:
        return "—"
    return _dt.datetime.fromtimestamp(_gck_cache["t"]).strftime("%H:%M")


def idx_last_update() -> str:
    import datetime as _dt
    if _idx_cache["t"] == 0:
        return "—"
    return _dt.datetime.fromtimestamp(_idx_cache["t"]).strftime("%H:%M")


def invalidate() -> None:
    """強制清除快取（立即更新時呼叫）."""
    _intl_cache["v"] = {}
    _intl_cache["t"] = 0.0
    _gck_cache["v"] = {}
    _gck_cache["t"] = 0.0
    _idx_cache["v"] = {}
    _idx_cache["t"] = 0.0


# ---------- 台股指數 + 台指期 ----------
TWSE_MIS = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TAIFEX_URL = "https://mis.taifex.com.tw/futures/api/getQuoteList"


@dataclass
class IndexQuote:
    label: str
    last: float | None
    prev: float | None
    change: float | None
    change_pct: float | None
    time: str


def _safe_float(v):
    try:
        if v in (None, "", "-"):
            return None
        return float(v)
    except Exception:
        return None


def _fetch_twse_indices() -> dict:
    """加權 + 櫃買指數 (TWSE MIS)."""
    try:
        import requests as _rq
        r = _rq.get(TWSE_MIS,
                    params={"ex_ch": "tse_t00.tw_|otc_o00.tw_",
                            "json": "1", "delay": "0"},
                    headers={"User-Agent": "Mozilla/5.0",
                             "Referer": "https://mis.twse.com.tw/stock/fibest.jsp"},
                    timeout=6)
        r.raise_for_status()
        j = r.json()
    except Exception:
        return {}
    out = {}
    for row in j.get("msgArray", []):
        last = _safe_float(row.get("z"))
        prev = _safe_float(row.get("y"))
        chg = (last - prev) if (last is not None and prev is not None) else None
        pct = (chg / prev * 100) if (chg is not None and prev) else None
        label = "🇹🇼 加權指數" if row.get("c") == "t00" \
            else "🇹🇼 櫃買指數" if row.get("c") == "o00" \
            else row.get("n", row.get("c"))
        key = "twse" if row.get("c") == "t00" \
            else "otc" if row.get("c") == "o00" else row.get("c")
        out[key] = IndexQuote(
            label=label, last=last, prev=prev,
            change=chg, change_pct=pct,
            time=row.get("t", ""),
        )
    return out


def _fetch_taifex() -> dict:
    """台指期日盤 + 夜盤 (近月合約) via TAIFEX MIS POST."""
    try:
        import requests as _rq
        r = _rq.post(TAIFEX_URL,
                     json={"objType": "1"},
                     headers={"User-Agent": "Mozilla/5.0",
                              "Content-Type": "application/json",
                              "Referer": "https://mis.taifex.com.tw/futures/"},
                     timeout=6)
        r.raise_for_status()
        j = r.json()
    except Exception:
        return {}

    qs = j.get("RtData", {}).get("QuoteList", [])
    day = None
    night = None
    for q in qs:
        sid = q.get("SymbolID", "")
        # 近月合約 = 第一個找到的 -F / -M 且 SymbolID 不是 TXF-F/S/P
        if sid.startswith("TXF") and "-" in sid \
                and not sid.startswith(("TXF-", )):
            if sid.endswith("-F") and day is None:
                day = q
            elif sid.endswith("-M") and night is None:
                night = q
        if day and night:
            break

    out = {}
    for key, q, label in (("tx_day", day, "📈 台指期 (日盤)"),
                          ("tx_night", night, "🌙 台指期 (電子盤)")):
        if not q:
            continue
        last = _safe_float(q.get("CLastPrice"))
        ref = _safe_float(q.get("CRefPrice"))
        diff = _safe_float(q.get("CDiff"))
        pct = _safe_float(q.get("CDiffRate"))
        t = q.get("CTime", "")
        t_fmt = f"{t[:2]}:{t[2:4]}" if len(t) >= 4 else ""
        out[key] = IndexQuote(
            label=label, last=last, prev=ref,
            change=diff, change_pct=pct,
            time=t_fmt,
        )
    return out


def fetch_indices(max_age_sec: int = 300) -> dict:
    """整合加權 + 櫃買 + 台指期日夜盤，5 分鐘快取."""
    now = time()
    if _idx_cache["v"] and now - _idx_cache["t"] < max_age_sec:
        return _idx_cache["v"]
    out = {}
    out.update(_fetch_twse_indices())
    out.update(_fetch_taifex())
    if out:
        _idx_cache["v"] = out
        _idx_cache["t"] = now
    return out


def _fetch_one(key: str) -> Quote | None:
    sym, label, prec = YF_TICKERS[key]
    try:
        h = yf.Ticker(sym).history(period="5d", interval="1d")
        if h.empty:
            return None
        last = float(h["Close"].iloc[-1])
        prev = float(h["Close"].iloc[-2]) if len(h) >= 2 else last
        chg = last - prev
        pct = (chg / prev * 100) if prev else 0.0
        return Quote(key=key, label=label, price=last,
                     change=chg, change_pct=pct, precision=prec)
    except Exception:
        return None


def fetch_international(max_age_sec: int = 3600) -> dict[str, Quote]:
    now = time()
    if _intl_cache["v"] and now - _intl_cache["t"] < max_age_sec:
        return _intl_cache["v"]
    out: dict[str, Quote] = {}
    for key in YF_TICKERS:
        q = _fetch_one(key)
        if q:
            out[key] = q
    if out:
        _intl_cache["v"] = out
        _intl_cache["t"] = now
    return out


# ---------- 展寬貴金屬 (GCK99) ----------
def fetch_gck99(max_age_sec: int = 3600) -> dict[str, str]:
    """回傳 {品項: 顯示字串}；失敗則全部為 N/A."""
    now = time()
    if _gck_cache["v"] and now - _gck_cache["t"] < max_age_sec:
        return _gck_cache["v"]
    prices = {k: "N/A" for k in (
        "黃金賣出牌價", "黃金條塊回收", "飾金回收",
        "白金回收即時價格", "999白銀加價回收",
    )}
    if not _HAS_BS4:
        prices["_err"] = "未安裝 beautifulsoup4"
        return prices
    try:
        r = _http.get("https://www.gck99.com.tw/", timeout=10)
        r.raise_for_status()
    except Exception as e:
        prices["_err"] = f"連線失敗：{e}"
        return prices
    soup = BeautifulSoup(r.text, "html.parser")
    for div in soup.select("div.form-box-yellow.clearfix"):
        cap = div.select_one("div.caption-yellow")
        col = div.select_one("div.column-yellow")
        if not (cap and col):
            continue
        text = col.get_text(" ", strip=True)
        m = re.search(r"([\d,\.]+)\s*/?\s*每(錢|克)", text)
        if not m:
            continue
        try:
            price = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = m.group(2)
        if unit == "錢":
            per_gram = price / 3.75
            val = f"{price:,.0f} / 錢 ({per_gram:,.0f} / 克)"
        else:
            val = f"{price:,.2f} / 克"
        txt = cap.get_text()
        if "黃金賣出" in txt:
            prices["黃金賣出牌價"] = val
        elif "黃金條塊" in txt:
            prices["黃金條塊回收"] = val
        elif "飾金回收" in txt:
            prices["飾金回收"] = val
        elif "白金" in txt:
            prices["白金回收即時價格"] = val
        elif "白銀" in txt:
            prices["999白銀加價回收"] = val
    _gck_cache["v"] = prices
    _gck_cache["t"] = now
    return prices
