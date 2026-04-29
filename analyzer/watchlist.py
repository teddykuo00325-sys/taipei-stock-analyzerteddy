"""收藏清單 — SQLite 持久化 + URL params 同步.

優先順序：
  1. SQLite 是 single source of truth（雲端重啟/換 browser tab 都保留）
  2. session_state 是 per-session 快取
  3. URL params 用於分享/書籤；變更時雙向同步

GitHub 備份（auto_restore / backup_now）讓雲端持久化。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Iterable

import streamlit as st

PARAM_KEY = "watch"
DB_PATH = Path(__file__).parent.parent / "data" / "watchlist.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_lock = Lock()
REPO_PATH = "data/watchlist.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            code TEXT PRIMARY KEY,
            added_at TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0
        )
    """)
    return c


def _load_from_db() -> list[str]:
    try:
        with _lock, _conn() as c:
            rows = c.execute(
                "SELECT code FROM watchlist "
                "ORDER BY sort_order, added_at"
            ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def _save_to_db(codes: list[str]) -> None:
    """全量覆蓋；保留 added_at 若 code 已存在."""
    try:
        now = datetime.now().isoformat(timespec="seconds")
        with _lock, _conn() as c:
            existing = {r[0]: r[1] for r in c.execute(
                "SELECT code, added_at FROM watchlist").fetchall()}
            c.execute("DELETE FROM watchlist")
            for i, code in enumerate(codes):
                added = existing.get(code, now)
                c.execute(
                    "INSERT INTO watchlist (code, added_at, sort_order) "
                    "VALUES (?, ?, ?)",
                    (code, added, i),
                )
    except Exception:
        pass


def get() -> list[str]:
    """讀取收藏清單.

    優先順序：session_state > URL params > SQLite.
    讀到 SQLite 後寫回 session_state + URL。
    """
    if "watchlist" in st.session_state:
        return list(st.session_state.watchlist)

    # 從 URL 看有沒有（外部進來）
    raw = st.query_params.get(PARAM_KEY, "")
    url_codes = [c.strip() for c in raw.split(",") if c.strip()] if raw else []

    # 從 DB 載入
    db_codes = _load_from_db()

    # 合併策略：URL 帶來的優先（分享連結覆蓋本機），但合併 DB 中已存在的
    if url_codes:
        # URL 有指定 → 完全採用 URL（讓分享連結說了算），但寫回 DB
        codes = url_codes
        _save_to_db(codes)
    else:
        # URL 沒指定 → 用 DB
        codes = db_codes
        if codes:
            _sync_url(codes)

    st.session_state.watchlist = codes
    return codes


def _sync_url(codes: list[str]) -> None:
    if codes:
        st.query_params[PARAM_KEY] = ",".join(codes)
    elif PARAM_KEY in st.query_params:
        del st.query_params[PARAM_KEY]


def _persist(codes: list[str]) -> None:
    """同步到 session_state + URL + DB + GitHub 備份."""
    st.session_state.watchlist = codes
    _sync_url(codes)
    _save_to_db(codes)
    # 雲端有設定 GitHub 才備份
    try:
        from . import storage
        if storage.is_configured():
            storage.upload_db(DB_PATH,
                               message=f"watchlist update ({len(codes)} 檔)",
                               repo_path=REPO_PATH,
                               auto_compress=False)
    except Exception:
        pass


def add(code: str) -> None:
    code = str(code).strip().upper()
    if not code:
        return
    lst = get()
    if code not in lst:
        lst.append(code)
        _persist(lst)


def remove(code: str) -> None:
    code = str(code).strip().upper()
    lst = get()
    if code in lst:
        lst.remove(code)
        _persist(lst)


def set_all(codes: Iterable[str]) -> None:
    lst = [str(c).strip().upper() for c in codes if str(c).strip()]
    _persist(lst)


def contains(code: str) -> bool:
    return str(code).strip().upper() in get()


# ---------- GitHub 備份（與 ohlcv.db / realbacktest.db 同機制）----------
def auto_restore() -> tuple[bool, str]:
    """雲端啟動時若本機 DB 為空，從 GitHub 還原."""
    from . import storage
    if not storage.is_configured():
        return False, "未設定 GitHub secrets"
    try:
        with _lock, _conn() as c:
            n = c.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        if n > 0:
            return False, f"本機已有 {n} 檔"
    except Exception:
        pass
    return storage.download_db(DB_PATH, repo_path=REPO_PATH)


def backup_now() -> tuple[bool, str]:
    from . import storage
    if not storage.is_configured():
        return False, "未設定 GitHub secrets"
    return storage.upload_db(DB_PATH,
                              message=f"watchlist manual backup",
                              repo_path=REPO_PATH,
                              auto_compress=False)
