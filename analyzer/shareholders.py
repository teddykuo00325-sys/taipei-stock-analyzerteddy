"""集保股權分散表 — TDCC openData.

URL: https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5
- 每週公布（週五 TDCC 結算資料）
- CSV 欄位：資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%

持股分級 1~15（17 表示合計、16 為差異）：
  1   1 ~ 999 股
  2   1,000 ~ 5,000 股
  3   5,001 ~ 10,000 股
  4   10,001 ~ 15,000 股
  5   15,001 ~ 20,000 股
  6   20,001 ~ 30,000 股
  7   30,001 ~ 40,000 股
  8   40,001 ~ 50,000 股
  9   50,001 ~ 100,000 股
  10  100,001 ~ 200,000 股
  11  200,001 ~ 400,000 股
  12  400,001 ~ 600,000 股
  13  600,001 ~ 800,000 股
  14  800,001 ~ 1,000,000 股
  15  超過 1,000,000 股 (千張大戶)
  17  合計

本模組把分級彙整為：
  散戶 = Level 1~3   (< 10,001 股)
  中戶 = Level 4~9
  大戶 = Level 10~14
  千張 = Level 15
"""
from __future__ import annotations

import io
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import Lock
from time import time

import pandas as pd

from . import http

URL = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"
DB_PATH = Path(__file__).parent.parent / "data" / "shareholders.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_lock = Lock()


@dataclass
class Holder:
    code: str
    date: str              # YYYY-MM-DD
    retail_pct: float      # 散戶 %
    mid_pct: float         # 中戶 %
    big_pct: float         # 大戶 %
    kilo_pct: float        # 千張 %
    total_holders: int     # 總股東人數


_cache: dict = {"t": 0.0, "df": None}


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.execute("""
        CREATE TABLE IF NOT EXISTS holders (
            code TEXT, date TEXT,
            retail_pct REAL, mid_pct REAL,
            big_pct REAL, kilo_pct REAL,
            total_holders INTEGER,
            PRIMARY KEY (code, date)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_h_date ON holders(date)")
    return c


def _fetch_raw() -> pd.DataFrame:
    r = http.get(URL, timeout=30)
    r.raise_for_status()
    txt = r.content.decode("utf-8-sig", errors="replace")
    df = pd.read_csv(io.StringIO(txt))
    # 欄位：資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%
    df.columns = [c.strip() for c in df.columns]
    col_map = {}
    for want, cands in [("date", ["資料日期"]),
                        ("code", ["證券代號"]),
                        ("lvl", ["持股分級"]),
                        ("n", ["人數"]),
                        ("shares", ["股數"]),
                        ("pct", ["占集保庫存數比例%",
                                 "占集保庫存數比例 %"])]:
        for c in cands:
            if c in df.columns:
                col_map[want] = c
                break
    df = df.rename(columns={v: k for k, v in col_map.items()})
    for c in ("lvl", "n", "shares"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    df["pct"] = pd.to_numeric(df["pct"], errors="coerce").fillna(0)
    df["code"] = df["code"].astype(str).str.strip()
    return df


def _summarize(df_one_code: pd.DataFrame) -> dict:
    """Aggregate level 1~15 into retail/mid/big/kilo."""
    # exclude level 16 (差異) and 17 (合計)
    df = df_one_code[df_one_code["lvl"].between(1, 15)]
    retail = float(df[df["lvl"].between(1, 3)]["pct"].sum())
    mid = float(df[df["lvl"].between(4, 9)]["pct"].sum())
    big = float(df[df["lvl"].between(10, 14)]["pct"].sum())
    kilo = float(df[df["lvl"] == 15]["pct"].sum())
    total_holders = int(df["n"].sum())
    return {"retail_pct": retail, "mid_pct": mid,
            "big_pct": big, "kilo_pct": kilo,
            "total_holders": total_holders}


def snapshot(max_age_sec: int = 86400) -> pd.DataFrame:
    """回傳原始 TDCC CSV (以 code, lvl 展開)."""
    now = time()
    if _cache["df"] is not None and now - _cache["t"] < max_age_sec:
        return _cache["df"]
    try:
        df = _fetch_raw()
    except Exception:
        return pd.DataFrame()
    _cache["df"] = df
    _cache["t"] = now
    return df


def for_code(code: str) -> Holder | None:
    """取得單一股票的最新股權分布摘要."""
    df = snapshot()
    if df.empty:
        return None
    code = str(code).strip()
    sub = df[df["code"] == code]
    if sub.empty:
        return None
    summary = _summarize(sub)
    date_str = str(sub["date"].iloc[0])
    # YYYYMMDD → YYYY-MM-DD
    if len(date_str) == 8:
        date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    # 寫入歷史 DB
    try:
        with _lock, _conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO holders VALUES (?,?,?,?,?,?,?)",
                (code, date_str, summary["retail_pct"],
                 summary["mid_pct"], summary["big_pct"],
                 summary["kilo_pct"], summary["total_holders"]),
            )
    except Exception:
        pass
    return Holder(code=code, date=date_str, **summary)


def history(code: str) -> pd.DataFrame:
    """取得該股票歷史股權分布（累積於本機 DB 的快照）."""
    with _lock, _conn() as c:
        df = pd.read_sql_query(
            "SELECT * FROM holders WHERE code=? ORDER BY date",
            c, params=(str(code).strip(),),
        )
    return df


def weekly_change(code: str) -> dict | None:
    """計算最新一筆 vs 前一筆的週變化（TDCC 每週公布一次）.

    回傳 {
        'this_week': {date, total_holders, kilo_pct, big_pct, mid_pct, retail_pct},
        'last_week': 同上,
        'delta_holders':  this - last (人),
        'delta_holders_pct': %,
        'delta_kilo_pct':  this - last (大戶持股 %p 變化),
        'delta_retail_pct': this - last (散戶 %p 變化),
        'interpretation': 中文判讀
    } 或 None（資料不足）
    """
    h = history(code)
    if h is None or len(h) < 2:
        return None
    h = h.sort_values("date").reset_index(drop=True)
    last = h.iloc[-1]
    prev = h.iloc[-2]

    delta_holders = int(last["total_holders"]) - int(prev["total_holders"])
    delta_holders_pct = (delta_holders / int(prev["total_holders"]) * 100
                         if prev["total_holders"] else 0.0)
    delta_kilo = float(last["kilo_pct"]) - float(prev["kilo_pct"])
    delta_big = float(last["big_pct"]) - float(prev["big_pct"])
    delta_mid = float(last["mid_pct"]) - float(prev["mid_pct"])
    delta_retail = float(last["retail_pct"]) - float(prev["retail_pct"])

    # 判讀邏輯
    notes = []
    if delta_holders_pct < -0.5:
        notes.append(f"股東總數減少 {abs(delta_holders):,} 人（{delta_holders_pct:+.2f}%），籌碼集中")
    elif delta_holders_pct > 0.5:
        notes.append(f"股東總數增加 {delta_holders:,} 人（{delta_holders_pct:+.2f}%），籌碼分散")
    if delta_kilo > 0.3:
        notes.append(f"千張大戶 {delta_kilo:+.2f}%p（增持）")
    elif delta_kilo < -0.3:
        notes.append(f"千張大戶 {delta_kilo:+.2f}%p（減持）")
    if delta_retail > 0.3:
        notes.append(f"散戶 {delta_retail:+.2f}%p（湧入）")
    elif delta_retail < -0.3:
        notes.append(f"散戶 {delta_retail:+.2f}%p（離場）")

    interp = "； ".join(notes) if notes else "本週變化不顯著"

    return {
        "this_week": {
            "date": str(last["date"]),
            "total_holders": int(last["total_holders"]),
            "kilo_pct": float(last["kilo_pct"]),
            "big_pct": float(last["big_pct"]),
            "mid_pct": float(last["mid_pct"]),
            "retail_pct": float(last["retail_pct"]),
        },
        "last_week": {
            "date": str(prev["date"]),
            "total_holders": int(prev["total_holders"]),
            "kilo_pct": float(prev["kilo_pct"]),
            "big_pct": float(prev["big_pct"]),
            "mid_pct": float(prev["mid_pct"]),
            "retail_pct": float(prev["retail_pct"]),
        },
        "delta_holders": delta_holders,
        "delta_holders_pct": round(delta_holders_pct, 2),
        "delta_kilo_pct": round(delta_kilo, 3),
        "delta_big_pct": round(delta_big, 3),
        "delta_mid_pct": round(delta_mid, 3),
        "delta_retail_pct": round(delta_retail, 3),
        "interpretation": interp,
    }
