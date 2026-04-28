"""融資融券每日餘額歷史 — SQLite 累積，給維度 5（5/20 日趨勢）使用.

設計：
  - TWSE OpenAPI MI_MARGN 只給「當日」資料
  - 每天 margin.snapshot() 完成後自動 append 一筆到本 DB
  - 雲端透過 storage.py 備份到 GitHub（持久化）
  - 累積 ≥ 20 日後，趨勢分數才會啟用

對外 API：
  append_today(df)         — 把 margin.snapshot() 結果存入今日資料
  load(code, days=30)      — 取單股近 N 日歷史
  load_bulk(codes, days)   — 批次取多檔
  stats()                  — 統計（行數 / 日期範圍）
  cross_section_today()    — 取今日全市場資料（給動態分位數用）
  auto_restore() / backup_now()  — GitHub 備份/還原
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from threading import Lock

import pandas as pd

DB_PATH = Path(__file__).parent.parent / "data" / "margin_history.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_lock = Lock()
REPO_PATH = "data/margin_history.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.execute("""
        CREATE TABLE IF NOT EXISTS margin_daily (
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            margin_today INTEGER,
            margin_prev INTEGER,
            margin_buy INTEGER,
            margin_sell INTEGER,
            margin_quota INTEGER,
            short_today INTEGER,
            short_prev INTEGER,
            short_buy INTEGER,
            short_sell INTEGER,
            short_quota INTEGER,
            day_trade_offset INTEGER,
            PRIMARY KEY (code, date)
        )
    """)
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_md_code_date "
        "ON margin_daily(code, date)"
    )
    return c


def append_today(df: pd.DataFrame, today: str | None = None) -> int:
    """把 margin.snapshot() 的 df 存入今日資料.

    重複日期：INSERT OR REPLACE（同一天可重複呼叫，最後一次覆蓋）
    回傳新增/更新筆數.
    """
    if df is None or df.empty:
        return 0
    today = today or date.today().isoformat()
    rows = []
    for _, r in df.iterrows():
        code = str(r.get("Code", "")).strip()
        if not code or not code.isdigit():
            continue
        rows.append((
            code, today,
            int(r.get("MarginToday", 0) or 0),
            int(r.get("MarginPrev", 0) or 0),
            int(r.get("MarginBuy", 0) or 0),
            int(r.get("MarginSell", 0) or 0),
            int(r.get("MarginQuota", 0) or 0),
            int(r.get("ShortToday", 0) or 0),
            int(r.get("ShortPrev", 0) or 0),
            int(r.get("ShortBuy", 0) or 0),
            int(r.get("ShortSell", 0) or 0),
            int(r.get("ShortQuota", 0) or 0),
            int(r.get("DayTradeOffset", 0) or 0),
        ))
    if not rows:
        return 0
    with _lock, _conn() as c:
        c.executemany(
            "INSERT OR REPLACE INTO margin_daily VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


def load(code: str, days: int = 30) -> pd.DataFrame:
    """取單股近 N 日資料（DataFrame，依日期升冪）."""
    code = str(code).strip()
    cutoff = (date.today() - timedelta(days=days * 2)).isoformat()
    q = ("SELECT date, margin_today, margin_prev, margin_buy, margin_sell, "
         "margin_quota, short_today, short_prev, short_buy, short_sell, "
         "short_quota, day_trade_offset "
         "FROM margin_daily WHERE code=? AND date>=? "
         "ORDER BY date")
    with _lock, _conn() as c:
        df = pd.read_sql_query(q, c, params=[code, cutoff])
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    return df.tail(days)


def load_bulk(codes: list[str], days: int = 30) -> dict[str, pd.DataFrame]:
    """批次取多檔歷史；回傳 {code: df}（缺資料的 code 不出現於回傳）."""
    codes = [str(c).strip() for c in codes]
    if not codes:
        return {}
    placeholders = ",".join("?" * len(codes))
    cutoff = (date.today() - timedelta(days=days * 2)).isoformat()
    q = (f"SELECT code, date, margin_today, margin_prev, margin_buy, "
         f"margin_sell, margin_quota, short_today, short_prev, short_buy, "
         f"short_sell, short_quota, day_trade_offset "
         f"FROM margin_daily WHERE code IN ({placeholders}) AND date>=? "
         f"ORDER BY code, date")
    with _lock, _conn() as c:
        df = pd.read_sql_query(q, c, params=codes + [cutoff])
    if df.empty:
        return {}
    df["date"] = pd.to_datetime(df["date"])
    out: dict[str, pd.DataFrame] = {}
    for code, sub in df.groupby("code"):
        sub = sub.set_index("date").drop(columns=["code"])
        out[str(code)] = sub.tail(days)
    return out


def cross_section_today() -> pd.DataFrame:
    """取今日全市場 margin 餘額分布（給動態分位數計算用）.

    若今日尚未 append，自動往前找最新的一日。
    """
    with _lock, _conn() as c:
        latest = c.execute(
            "SELECT MAX(date) FROM margin_daily").fetchone()
    if not latest or not latest[0]:
        return pd.DataFrame()
    q = ("SELECT code, margin_today, margin_quota, short_today, short_quota "
         "FROM margin_daily WHERE date=?")
    with _lock, _conn() as c:
        df = pd.read_sql_query(q, c, params=[latest[0]])
    return df


def stats() -> dict:
    with _lock, _conn() as c:
        total = c.execute(
            "SELECT COUNT(*) FROM margin_daily").fetchone()[0]
        codes = c.execute(
            "SELECT COUNT(DISTINCT code) FROM margin_daily").fetchone()[0]
        rng = c.execute(
            "SELECT MIN(date), MAX(date) FROM margin_daily").fetchone()
    size_kb = DB_PATH.stat().st_size / 1024 if DB_PATH.exists() else 0
    return {
        "rows": total, "codes": codes,
        "date_range": (rng[0], rng[1]) if rng else (None, None),
        "db_size_kb": round(size_kb, 1),
    }


def purge_older_than(days: int = 90) -> int:
    """刪除 N 日前的舊資料；回傳刪除筆數."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with _lock:
        with _conn() as c:
            n = c.execute(
                "DELETE FROM margin_daily WHERE date<?",
                (cutoff,),
            ).rowcount
        try:
            v = sqlite3.connect(DB_PATH, isolation_level=None)
            v.execute("VACUUM")
            v.close()
        except Exception:
            pass
    return n or 0


# ---------- GitHub 備份 ----------
def auto_restore() -> tuple[bool, str]:
    from . import storage
    if not storage.is_configured():
        return False, "未設定 GitHub secrets"
    try:
        s = stats()
        if s["rows"] > 0:
            return False, f"本機已有 {s['rows']} 筆"
    except Exception:
        pass
    return storage.download_db(DB_PATH, repo_path=REPO_PATH)


def backup_now(message: str | None = None) -> tuple[bool, str]:
    from . import storage
    if not storage.is_configured():
        return False, "未設定 GitHub secrets"
    s = stats()
    msg = message or (f"margin_history.db ({s['rows']} rows, "
                      f"{s['codes']} codes)")
    return storage.upload_db(DB_PATH, message=msg, repo_path=REPO_PATH,
                              auto_compress=False)
