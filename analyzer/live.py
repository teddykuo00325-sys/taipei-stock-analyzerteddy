"""TWSE 盤中即時報價 — 透過 MIS API 取得當下成交資訊.

MIS API：https://mis.twse.com.tw/stock/api/getStockInfo.jsp
依市場代碼前綴區分：
  tse_XXXX.tw  上市
  otc_XXXX.tw  上櫃

取得內容：
  z=成交價、o=開盤、h=最高、l=最低、y=昨收
  v=累計成交量(張)、d=日期 t=時間
  b=五檔買價、a=五檔賣價、u=漲停、w=跌停
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from time import time

import pandas as pd
import requests

MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36"),
    "Referer": "https://mis.twse.com.tw/stock/fibest.jsp",
}


@dataclass
class Quote:
    code: str
    name: str
    current: float | None
    open: float | None
    high: float | None
    low: float | None
    yesterday: float | None
    change: float | None           # 漲跌
    change_pct: float | None
    volume_lots: int | None        # 累計成交張數
    bid: float | None
    ask: float | None
    limit_up: float | None
    limit_down: float | None
    date: str                      # YYYY-MM-DD
    time: str                      # HH:MM:SS
    timestamp: int                 # epoch ms
    is_trading: bool               # 今日是否有成交


def _f(v) -> float | None:
    try:
        if v in (None, "", "-"):
            return None
        return float(v)
    except Exception:
        return None


def _i(v) -> int | None:
    try:
        if v in (None, "", "-"):
            return None
        return int(v)
    except Exception:
        return None


def _parse(row: dict) -> Quote:
    bid = row.get("b", "")
    ask = row.get("a", "")
    b0 = _f(bid.split("_")[0]) if bid else None
    a0 = _f(ask.split("_")[0]) if ask else None
    cur = _f(row.get("z"))
    # 若 z 為 "-"（尚未開盤或停牌），用最近買/賣作參考
    if cur is None:
        cur = b0 or a0
    y = _f(row.get("y"))
    chg = (cur - y) if (cur is not None and y is not None) else None
    chg_pct = (chg / y * 100) if (chg is not None and y) else None
    d = row.get("d") or ""
    date_s = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else ""
    return Quote(
        code=row.get("c", ""),
        name=row.get("n", ""),
        current=cur,
        open=_f(row.get("o")),
        high=_f(row.get("h")),
        low=_f(row.get("l")),
        yesterday=y,
        change=chg, change_pct=chg_pct,
        volume_lots=_i(row.get("v")),
        bid=b0, ask=a0,
        limit_up=_f(row.get("u")),
        limit_down=_f(row.get("w")),
        date=date_s,
        time=row.get("t", ""),
        timestamp=int(row.get("tlong", 0) or 0),
        is_trading=_f(row.get("z")) is not None,
    )


# ------ 短暫 memory 快取（5 秒）------
_cache: dict = {}


def _get(ex_ch: str, max_age_sec: float = 5.0):
    now = time()
    c = _cache.get(ex_ch)
    if c and now - c["t"] < max_age_sec:
        return c["v"]
    try:
        r = requests.get(MIS_URL,
                         params={"ex_ch": ex_ch, "json": "1", "delay": "0"},
                         headers=HEADERS, timeout=6)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None
    if data.get("rtcode") != "0000":
        return None
    _cache[ex_ch] = {"t": now, "v": data.get("msgArray", [])}
    return _cache[ex_ch]["v"]


def quote(code: str) -> Quote | None:
    """取單一股票即時報價（先試上市，再試上櫃）."""
    code = code.strip().upper()
    if code.endswith(".TW"):
        code = code[:-3]
    elif code.endswith(".TWO"):
        code = code[:-4]
    # 上市
    rows = _get(f"tse_{code}.tw")
    if rows:
        return _parse(rows[0])
    # 上櫃
    rows = _get(f"otc_{code}.tw")
    if rows:
        return _parse(rows[0])
    return None


def quotes(codes: list[str], chunk_size: int = 100,
           progress_cb=None) -> dict[str, Quote]:
    """批次取即時報價；大清單自動分段 (MIS 限制 100 檔/請求)."""
    out: dict[str, Quote] = {}
    norm: list[str] = []
    for c in codes:
        c = c.strip().upper()
        if c.endswith(".TW"):
            c = c[:-3]
        elif c.endswith(".TWO"):
            c = c[:-4]
        norm.append(c)
    total = len(norm)
    if total == 0:
        return out
    for i in range(0, total, chunk_size):
        chunk = norm[i:i + chunk_size]
        ex_ch = "|".join(f"tse_{c}.tw_" for c in chunk)
        rows = _get(ex_ch, max_age_sec=30) or []
        for row in rows:
            q = _parse(row)
            if q.code:
                out[q.code] = q
        if progress_cb:
            progress_cb(min(1.0, (i + chunk_size) / total),
                        f"抓取盤中 {min(i + chunk_size, total)} / {total}")
    return out


def overlay_today(df: pd.DataFrame, q: Quote | None) -> pd.DataFrame:
    """將即時報價覆蓋到 daily DataFrame 的今日 K 線.

    若今日已在 df 內（yfinance 已有當日盤中條），更新 high/low/close/volume；
    若不在（例如早盤前、資料未同步），追加一筆.
    """
    if q is None or q.current is None:
        return df
    try:
        today_date = datetime.fromtimestamp(q.timestamp / 1000).date()
    except Exception:
        today_date = datetime.now().date()
    out = df.copy()
    # 取現有的開盤：若 df 今日已有，保留其 open；否則用即時 open or current
    existing_today = [i for i in out.index if i.date() == today_date]
    if existing_today:
        idx = existing_today[0]
        prev_open = float(out.at[idx, "open"]) if "open" in out.columns else None
        open_val = prev_open if prev_open is not None else \
                   (q.open if q.open is not None else q.current)
        prev_high = float(out.at[idx, "high"]) if "high" in out.columns else 0
        prev_low = float(out.at[idx, "low"]) if "low" in out.columns else float("inf")
        high_val = max(prev_high, q.high or q.current, q.current)
        low_val = min(prev_low, q.low or q.current, q.current)
        out.at[idx, "open"] = open_val
        out.at[idx, "high"] = high_val
        out.at[idx, "low"] = low_val
        out.at[idx, "close"] = q.current
        out.at[idx, "volume"] = (q.volume_lots or 0) * 1000
    else:
        new_row = pd.DataFrame([{
            "open": q.open if q.open is not None else q.current,
            "high": q.high if q.high is not None else q.current,
            "low": q.low if q.low is not None else q.current,
            "close": q.current,
            "volume": (q.volume_lots or 0) * 1000,
        }], index=[pd.Timestamp(today_date)])
        out = pd.concat([out, new_row])
    return out
