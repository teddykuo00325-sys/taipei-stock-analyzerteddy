"""券商分點買賣超 — histock.tw 爬取.

資料源：https://histock.tw/stock/branch.aspx?no={code}
  - 左半邊：賣超前 15 券商（券商名稱、買張、賣張、賣超、均價）
  - 右半邊：買超前 15 券商（券商名稱、買張、賣張、買超、均價）
  - 包含當日「均價」= 該券商當日該股的平均成交價

對外 API：
  fetch_top_brokers(code) -> dict
      回傳 {date, top_buy: [...], top_sell: [...]}
      每個 entry: {broker, buy_lots, sell_lots, net_lots, avg_price}
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from time import time

from . import http


URL = "https://histock.tw/stock/branch.aspx"


@dataclass
class BrokerEntry:
    broker: str
    buy_lots: int
    sell_lots: int
    net_lots: int       # buy - sell（買超）；賣超為負
    avg_price: float


@dataclass
class BrokerSnapshot:
    code: str
    date: str            # YYYY-MM-DD
    top_buy: list[BrokerEntry]    # 買超 top 15
    top_sell: list[BrokerEntry]   # 賣超 top 15


_cache: dict = {}


def _to_int(s: str) -> int:
    try:
        return int(s.replace(",", "").strip() or 0)
    except Exception:
        return 0


def _to_float(s: str) -> float:
    try:
        return float(s.replace(",", "").strip() or 0)
    except Exception:
        return 0.0


def _normalize_date(s: str) -> str:
    """histock 日期 'YYYY/MM/DD' 轉 'YYYY-MM-DD'."""
    s = s.strip()
    if len(s) == 10 and s[4] == "/" and s[7] == "/":
        return s.replace("/", "-")
    return s


def fetch(code: str, max_age_sec: int = 1800) -> BrokerSnapshot | None:
    """抓單檔今日券商分點買賣超.

    30 分鐘 in-memory 快取。回傳 None 表示資料不可得。
    """
    code = str(code).strip()
    now = time()
    cached = _cache.get(code)
    if cached and now - cached["t"] < max_age_sec:
        return cached["v"]

    try:
        r = http.get(URL, params={"no": code},
                      headers={"User-Agent":
                               "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "Chrome/120.0.0.0"},
                      timeout=10)
        if r.status_code != 200 or not r.text:
            return None
        text = r.text
    except Exception:
        return None

    # 取日期
    m = re.search(r"(\d{4}/\d{2}/\d{2})", text)
    snap_date = _normalize_date(m.group(1)) if m else date.today().isoformat()

    # 抽 broker rows（10 cols：左半 5 col + 右半 5 col）
    tr_blocks = re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.DOTALL)
    top_buy: list[BrokerEntry] = []
    top_sell: list[BrokerEntry] = []
    for tr in tr_blocks:
        cells_raw = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.DOTALL)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells_raw]
        if len(cells) != 10 or cells[0] == "券商名稱":
            continue
        # 左半：賣超榜
        try:
            sell_entry = BrokerEntry(
                broker=cells[0],
                buy_lots=_to_int(cells[1]),
                sell_lots=_to_int(cells[2]),
                net_lots=_to_int(cells[3]),    # 已是負數（賣超）
                avg_price=_to_float(cells[4]),
            )
            if sell_entry.broker:
                top_sell.append(sell_entry)
        except Exception:
            pass
        # 右半：買超榜
        try:
            buy_entry = BrokerEntry(
                broker=cells[5],
                buy_lots=_to_int(cells[6]),
                sell_lots=_to_int(cells[7]),
                net_lots=_to_int(cells[8]),    # 正數（買超）
                avg_price=_to_float(cells[9]),
            )
            if buy_entry.broker:
                top_buy.append(buy_entry)
        except Exception:
            pass

    if not top_buy and not top_sell:
        return None

    snap = BrokerSnapshot(
        code=code, date=snap_date,
        top_buy=top_buy, top_sell=top_sell,
    )
    _cache[code] = {"t": now, "v": snap}
    return snap
