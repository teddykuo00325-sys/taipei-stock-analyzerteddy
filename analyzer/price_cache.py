"""K 線 OHLCV 增量快取 — SQLite + 增量抓取.

設計：
  1. 每支股票（含 ETF）首次查詢 → 抓 2 年 → 存 SQLite
  2. 之後查詢 → 讀 SQLite，僅對「最後儲存日 → 今日」區間再抓一次
  3. bulk_prepare() 供選股器批次預熱快取（首次跑全市場一次抓完）

對外 API：
  get(code, period='1y')       — 單股取 DataFrame（小寫欄位）
  bulk_prepare(codes, ...)     — 批次預熱 / 增量更新
  clear(code)                  — 清除該股快取
  stats()                      — 快取統計（行數 / DB 大小）
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Callable, Iterable

import pandas as pd
import yfinance as yf

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

DB_PATH = Path(__file__).parent.parent / "data" / "ohlcv.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_lock = Lock()

# 期間 → 回溯天數
PERIOD_DAYS = {
    "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
    "1y": 365, "2y": 730, "5y": 1825, "max": 5000,
}


# ---------------------------------------------------------------
# DB 初始化
# ---------------------------------------------------------------
def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv (
            code TEXT,
            date TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (code, date)
        )
    """)
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_code_date ON ohlcv(code, date)"
    )
    return c


def _normalize(code: str) -> str:
    code = str(code).strip().upper()
    if code.endswith(".TW") or code.endswith(".TWO"):
        return code
    return f"{code}.TW"


def _bare(code: str) -> str:
    """Ticker → bare code (remove .TW/.TWO)."""
    c = str(code).strip().upper()
    if c.endswith(".TW"):
        return c[:-3]
    if c.endswith(".TWO"):
        return c[:-4]
    return c


# ---------------------------------------------------------------
# 讀寫 DB
# ---------------------------------------------------------------
def latest_date(code: str) -> str | None:
    code = _bare(code)
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT MAX(date) FROM ohlcv WHERE code=?", (code,)
        ).fetchone()
    return row[0] if row and row[0] else None


def _latest_dates_bulk(codes: list[str]) -> dict[str, str | None]:
    codes_bare = [_bare(c) for c in codes]
    if not codes_bare:
        return {}
    placeholders = ",".join("?" * len(codes_bare))
    with _lock, _conn() as c:
        rows = c.execute(
            f"SELECT code, MAX(date) FROM ohlcv WHERE code IN ({placeholders}) "
            "GROUP BY code",
            codes_bare,
        ).fetchall()
    result = {r[0]: r[1] for r in rows}
    # 未在 DB 的 code 標示為 None
    return {c: result.get(c) for c in codes_bare}


def _store(code: str, df: pd.DataFrame) -> int:
    """Insert OHLCV rows, skip duplicates.

    df expected columns: Open/High/Low/Close/Volume OR open/high/low/close/volume
    Index: DatetimeIndex
    """
    if df is None or df.empty:
        return 0
    code = _bare(code)
    # normalize columns
    col_map = {}
    for want, candidates in [
        ("open", ["Open", "open"]),
        ("high", ["High", "high"]),
        ("low", ["Low", "low"]),
        ("close", ["Close", "close"]),
        ("volume", ["Volume", "volume"]),
    ]:
        for c in candidates:
            if c in df.columns:
                col_map[want] = c
                break
    if len(col_map) < 5:
        return 0

    rows = []
    for dt, r in df.iterrows():
        try:
            date_str = (dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime")
                        else str(pd.Timestamp(dt).date()))
            rows.append((
                code, date_str,
                float(r[col_map["open"]]),
                float(r[col_map["high"]]),
                float(r[col_map["low"]]),
                float(r[col_map["close"]]),
                float(r[col_map["volume"]]),
            ))
        except Exception:
            continue

    if not rows:
        return 0
    with _lock, _conn() as c:
        c.executemany(
            "INSERT OR REPLACE INTO ohlcv VALUES (?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


def _load(code: str, start: str | None = None,
          end: str | None = None) -> pd.DataFrame:
    code = _bare(code)
    q = ("SELECT date, open, high, low, close, volume "
         "FROM ohlcv WHERE code=?")
    params: list = [code]
    if start:
        q += " AND date >= ?"
        params.append(start)
    if end:
        q += " AND date <= ?"
        params.append(end)
    q += " ORDER BY date"
    with _lock, _conn() as c:
        df = pd.read_sql_query(q, c, params=params)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    return df


# ---------------------------------------------------------------
# yfinance 抓取 helpers
# ---------------------------------------------------------------
def _yf_download(tickers, **kwargs) -> pd.DataFrame:
    """Wrapper with defensive defaults."""
    kwargs.setdefault("interval", "1d")
    kwargs.setdefault("auto_adjust", False)
    kwargs.setdefault("progress", False)
    kwargs.setdefault("threads", True)
    try:
        return yf.download(tickers, **kwargs)
    except Exception:
        return pd.DataFrame()


def _fetch_single_full(code: str, period: str = "2y") -> pd.DataFrame:
    """Single code full fetch（含 .TWO fallback）."""
    for suffix in (".TW", ".TWO"):
        ticker = _bare(code) + suffix
        df = _yf_download(ticker, period=period)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if not df.empty:
            return df
    return pd.DataFrame()


def _fetch_single_since(code: str, start: str) -> pd.DataFrame:
    for suffix in (".TW", ".TWO"):
        ticker = _bare(code) + suffix
        df = _yf_download(ticker, start=start)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if not df.empty:
            return df
    return pd.DataFrame()


# ---------------------------------------------------------------
# 主 API
# ---------------------------------------------------------------
def get(code: str, period: str = "1y",
        warm_period: str = "2y") -> pd.DataFrame:
    """取得股票 K 線（小寫欄位）；增量快取."""
    bare = _bare(code)
    today = date.today()
    latest = latest_date(bare)

    if latest is None:
        # 首次：全量抓 warm_period 存入
        df = _fetch_single_full(bare, period=warm_period)
        if df.empty:
            raise ValueError(f"查無資料：{code}")
        _store(bare, df)
    else:
        latest_dt = datetime.strptime(latest, "%Y-%m-%d").date()
        if latest_dt < today:
            start = (latest_dt + timedelta(days=1)).isoformat()
            new_df = _fetch_single_since(bare, start)
            if not new_df.empty:
                _store(bare, new_df)

    # 依 period 決定回溯天數
    days = PERIOD_DAYS.get(period, 365)
    want_start = (today - timedelta(days=days + 30)).isoformat()
    return _load(bare, start=want_start)


def _extract_ticker_df(data: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """從 yf.download(list, group_by='ticker') 回傳的 MultiIndex df 取出單檔資料.

    yfinance 對「list 形式 tickers」（即使只有 1 檔）一律回傳 MultiIndex columns
    [(ticker, OHLCV)]。直接 df = data 會讓 _store 找不到 'Open'/'open' 欄位
    導致靜默漏存，因此一律以 data[ticker] 取出 single-level df。
    """
    if isinstance(data.columns, pd.MultiIndex):
        if ticker in data.columns.get_level_values(0):
            return data[ticker]
        return pd.DataFrame()
    return data  # 已是 single-level (string-only ticker call)


def _bulk_download_chunk(codes: list[str], suffix: str,
                         period: str | None = None,
                         start: str | None = None) -> dict[str, pd.DataFrame]:
    """以指定 suffix (.TW or .TWO) 批次抓並拆出每檔 df.

    回傳 {bare_code: df}（df 可能為空，代表該 suffix 對該 code 無資料）。
    """
    tickers = [f"{c}{suffix}" for c in codes]
    kwargs = {"group_by": "ticker"}
    if period:
        kwargs["period"] = period
    elif start:
        kwargs["start"] = start
    data = _yf_download(tickers, **kwargs)
    out: dict[str, pd.DataFrame] = {}
    if data is None or data.empty:
        return {c: pd.DataFrame() for c in codes}
    for code, ticker in zip(codes, tickers):
        try:
            df = _extract_ticker_df(data, ticker).dropna(how="all")
            out[code] = df
        except Exception:
            out[code] = pd.DataFrame()
    return out


def bulk_prepare(codes: Iterable[str],
                 warm_period: str = "2y",
                 chunk_size: int = 40,
                 progress_cb: Callable | None = None) -> dict:
    """批次預熱 / 增量更新快取.

    - 未在 DB 的股票 → 批次抓 warm_period（先 .TW 後 .TWO 重試）
    - DB 有資料但非今日 → 批次抓增量
    - DB 已是今日 → 略過

    回傳 {'warmed': N, 'updated': N, 'skipped': N, 'failed': [...]}
    """
    codes = [_bare(c) for c in codes]
    today = date.today()
    latest_map = _latest_dates_bulk(codes)
    today_iso = today.isoformat()

    need_full = [c for c, d in latest_map.items() if d is None]
    need_incr = [c for c, d in latest_map.items()
                 if d is not None and d < today_iso]
    fresh = [c for c, d in latest_map.items() if d == today_iso]

    result = {"warmed": 0, "updated": 0, "skipped": len(fresh),
              "failed": []}

    def _try_store(code: str, df: pd.DataFrame,
                   own_latest: str | None = None) -> int:
        """Store helper：增量時只存比 own_latest 新的列."""
        if df is None or df.empty:
            return 0
        if own_latest:
            try:
                df = df[df.index > pd.Timestamp(own_latest)]
            except Exception:
                pass
            if df.empty:
                return 0
        return _store(code, df)

    # ----- 首次批次抓（先 .TW，失敗的轉 .TWO 重試）-----
    if need_full:
        tw_failed: list[str] = []
        total = len(need_full)
        for i in range(0, total, chunk_size):
            chunk_c = need_full[i:i + chunk_size]
            if progress_cb:
                progress_cb(i / max(total, 1),
                            f"[首次/.TW] 下載 {i + 1}-"
                            f"{min(i + chunk_size, total)} / {total}")
            chunk_data = _bulk_download_chunk(chunk_c, ".TW",
                                              period=warm_period)
            for code in chunk_c:
                df = chunk_data.get(code, pd.DataFrame())
                n = _try_store(code, df)
                if n > 0:
                    result["warmed"] += 1
                else:
                    tw_failed.append(code)

        # 重試 .TWO（OTC 上櫃股）
        if tw_failed:
            for i in range(0, len(tw_failed), chunk_size):
                chunk_c = tw_failed[i:i + chunk_size]
                if progress_cb:
                    progress_cb(i / max(len(tw_failed), 1),
                                f"[首次/.TWO] OTC 重試 "
                                f"{i + 1}-{min(i + chunk_size, len(tw_failed))} "
                                f"/ {len(tw_failed)}")
                chunk_data = _bulk_download_chunk(chunk_c, ".TWO",
                                                  period=warm_period)
                for code in chunk_c:
                    df = chunk_data.get(code, pd.DataFrame())
                    n = _try_store(code, df)
                    if n > 0:
                        result["warmed"] += 1
                    else:
                        result["failed"].append(code)

    # ----- 增量抓（同樣兩階段：.TW 失敗轉 .TWO）-----
    if need_incr:
        earliest_latest = min(latest_map[c] for c in need_incr)
        incr_start_dt = (datetime.strptime(earliest_latest, "%Y-%m-%d").date()
                         + timedelta(days=1))
        incr_start = incr_start_dt.isoformat()

        tw_failed: list[str] = []
        total = len(need_incr)
        for i in range(0, total, chunk_size):
            chunk_c = need_incr[i:i + chunk_size]
            if progress_cb:
                progress_cb(i / max(total, 1),
                            f"[增量/.TW] 自 {incr_start} 更新 "
                            f"{i + 1}-{min(i + chunk_size, total)} / {total}")
            chunk_data = _bulk_download_chunk(chunk_c, ".TW",
                                              start=incr_start)
            for code in chunk_c:
                df = chunk_data.get(code, pd.DataFrame())
                n = _try_store(code, df, own_latest=latest_map[code])
                if n > 0:
                    result["updated"] += 1
                elif df.empty:
                    tw_failed.append(code)

        if tw_failed:
            for i in range(0, len(tw_failed), chunk_size):
                chunk_c = tw_failed[i:i + chunk_size]
                if progress_cb:
                    progress_cb(i / max(len(tw_failed), 1),
                                f"[增量/.TWO] OTC 重試 "
                                f"{i + 1}-{min(i + chunk_size, len(tw_failed))} "
                                f"/ {len(tw_failed)}")
                chunk_data = _bulk_download_chunk(chunk_c, ".TWO",
                                                  start=incr_start)
                for code in chunk_c:
                    df = chunk_data.get(code, pd.DataFrame())
                    n = _try_store(code, df, own_latest=latest_map[code])
                    if n > 0:
                        result["updated"] += 1

    if progress_cb:
        progress_cb(1.0, f"快取準備完成：首次 {result['warmed']} 檔 / "
                    f"增量 {result['updated']} 檔 / "
                    f"已是今日 {result['skipped']} 檔 / "
                    f"失敗 {len(result['failed'])} 檔")
    return result


def clear(code: str) -> None:
    bare = _bare(code)
    with _lock, _conn() as c:
        c.execute("DELETE FROM ohlcv WHERE code=?", (bare,))


def stats() -> dict:
    with _lock, _conn() as c:
        total_rows = c.execute("SELECT COUNT(*) FROM ohlcv").fetchone()[0]
        distinct = c.execute("SELECT COUNT(DISTINCT code) FROM ohlcv").fetchone()[0]
        min_max = c.execute(
            "SELECT MIN(date), MAX(date) FROM ohlcv").fetchone()
    size_kb = DB_PATH.stat().st_size / 1024 if DB_PATH.exists() else 0
    return {
        "rows": total_rows, "codes": distinct,
        "date_range": (min_max[0], min_max[1]) if min_max else (None, None),
        "db_size_kb": round(size_kb, 1),
    }


def purge_older_than(days: int = 365) -> int:
    """刪除超過 N 日的 K 線資料；回傳刪除筆數."""
    from datetime import date as _date, timedelta as _td
    cutoff = (_date.today() - _td(days=days)).isoformat()
    with _lock:
        with _conn() as c:
            n = c.execute("DELETE FROM ohlcv WHERE date < ?",
                          (cutoff,)).rowcount
        # VACUUM 需獨立連線
        try:
            v = sqlite3.connect(DB_PATH, isolation_level=None)
            v.execute("VACUUM")
            v.close()
        except Exception:
            pass
    return n or 0


def purge_stocks_not_in(codes: list[str]) -> int:
    """刪除不在 codes 清單中的股票（清理不常看的冷門股）."""
    codes = [_bare(c) for c in codes]
    if not codes:
        return 0
    placeholders = ",".join("?" * len(codes))
    with _lock:
        with _conn() as c:
            n = c.execute(
                f"DELETE FROM ohlcv WHERE code NOT IN ({placeholders})",
                codes,
            ).rowcount
        try:
            v = sqlite3.connect(DB_PATH, isolation_level=None)
            v.execute("VACUUM")
            v.close()
        except Exception:
            pass
    return n or 0


# ---------------------------------------------------------------
# GitHub 備份 (選配：需設定 secrets)
# ---------------------------------------------------------------
REPO_PATH = "data/ohlcv.db"


def auto_restore() -> tuple[bool, str]:
    """若本機 DB 為空，從 GitHub 下載備份."""
    from . import storage
    if not storage.is_configured():
        return False, "未設定 GitHub secrets"
    s = stats()
    if s["rows"] > 0:
        return False, f"本機已有 {s['rows']} 列"
    return storage.download_db(DB_PATH, repo_path=REPO_PATH)


def backup_now(message: str | None = None) -> tuple[bool, str]:
    """手動備份到 GitHub."""
    from . import storage
    if not storage.is_configured():
        return False, "未設定 GitHub secrets"
    s = stats()
    msg = message or f"auto: ohlcv.db ({s['rows']} rows, {s['codes']} codes)"
    return storage.upload_db(DB_PATH, message=msg, repo_path=REPO_PATH)


# 循環錄影門檻：DB raw size 超過時，先 purge 過期再備份
ROTATION_THRESHOLD_MB = 60
ROTATION_KEEP_DAYS = 365


def backup_with_rotation(
    message: str | None = None,
    threshold_mb: int = ROTATION_THRESHOLD_MB,
    keep_days: int = ROTATION_KEEP_DAYS,
) -> tuple[bool, str]:
    """循環錄影式備份：DB 過大時先刪 keep_days 之前的資料再上傳.

    類似行車紀錄器：日常累積 → 滿了自動覆蓋最舊。
    回傳 (ok, msg)；msg 前綴含 purge 詳情供 UI 顯示。
    """
    from . import storage
    if not storage.is_configured():
        return False, "未設定 GitHub secrets"

    s_before = stats()
    purged_rows = 0
    rotation_note = ""
    if s_before["db_size_kb"] > threshold_mb * 1024:
        purged_rows = purge_older_than(days=keep_days)
        s_after = stats()
        saved_kb = s_before["db_size_kb"] - s_after["db_size_kb"]
        rotation_note = (f"🗑️ 循環刪除 > {keep_days} 日舊資料："
                         f"{purged_rows:,} 列 / 釋放 {saved_kb / 1024:.1f} MB ｜ ")

    s = stats()
    msg = message or (f"auto: ohlcv.db ({s['rows']} rows, "
                      f"{s['codes']} codes"
                      + (f", rotated -{purged_rows}" if purged_rows else "")
                      + ")")
    ok, upload_msg = storage.upload_db(DB_PATH, message=msg,
                                        repo_path=REPO_PATH)
    return ok, rotation_note + upload_msg


def auto_backup_if_changed(min_stocks: int = 10) -> tuple[bool, str]:
    """若最近 bulk_prepare 有新增 >= min_stocks 檔，自動備份（含循環錄影）."""
    return backup_with_rotation()
