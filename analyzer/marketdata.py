"""國際行情 + 展寬貴金屬當日回收價.

- 國際：yfinance（黃金、白銀、布蘭特/WTI 原油、美日匯率）
- 展寬：https://www.gck99.com.tw 現場解析
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from time import time

import requests
import yfinance as yf

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

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})


@dataclass
class Quote:
    key: str
    label: str
    price: float
    change: float
    change_pct: float
    precision: int


# ---------- 國際 (yfinance) ----------
_intl_cache: dict = {"t": 0.0, "v": {}}


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


def fetch_international(max_age_sec: int = 300) -> dict[str, Quote]:
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
_gck_cache: dict = {"t": 0.0, "v": {}}


def fetch_gck99(max_age_sec: int = 600) -> dict[str, str]:
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
        r = SESSION.get("https://www.gck99.com.tw/", timeout=10)
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
