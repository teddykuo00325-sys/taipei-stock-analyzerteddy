"""實盤回測 (Forward Backtest) — 鎖定當下系統推薦，追蹤未來 N 日表現.

設計：
  1. lock_today() — 跑當前選股器，鎖定 top_n 做多 + top_n 做空，存入 SQLite
  2. tracking() — 取所有 open 的回測組合，計算當下 P&L
  3. close_position() — 手動結算（或到期自動結算）

資料表：
  realbt_session (id, lock_date, side, top_n, capital, status, note)
  realbt_holding (session_id, code, name, entry_date, entry_price,
                  exit_date, exit_price, score, position_size)
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Literal

import pandas as pd

from . import live, price_cache

DB_PATH = Path(__file__).parent.parent / "data" / "realbacktest.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_lock = Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.execute("""
        CREATE TABLE IF NOT EXISTS realbt_session (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lock_date TEXT NOT NULL,
            side TEXT NOT NULL,           -- 'long' | 'short'
            top_n INTEGER NOT NULL,
            capital REAL NOT NULL,
            target_exit_date TEXT,        -- 預計結算日
            status TEXT DEFAULT 'open',   -- 'open' | 'closed'
            note TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS realbt_holding (
            session_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            score INTEGER,
            entry_date TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_date TEXT,
            exit_price REAL,
            position_size REAL NOT NULL,
            PRIMARY KEY (session_id, code),
            FOREIGN KEY (session_id) REFERENCES realbt_session(id)
        )
    """)
    return c


@dataclass
class Holding:
    session_id: int
    code: str
    name: str
    score: int
    entry_date: str
    entry_price: float
    exit_date: str | None
    exit_price: float | None
    position_size: float

    def current_price(self) -> float | None:
        """從 price_cache 取最新收盤；無資料回 None."""
        try:
            df = price_cache._load(self.code)
            if df.empty:
                return None
            return float(df["close"].iloc[-1])
        except Exception:
            return None

    def pnl(self, side: str, ref_price: float | None = None) -> float | None:
        """回傳 P&L (TWD)；ref_price 沒給則用最新收盤."""
        price = ref_price or self.exit_price or self.current_price()
        if price is None:
            return None
        if side == "long":
            return self.position_size * (price / self.entry_price - 1)
        else:  # short
            return self.position_size * (self.entry_price / price - 1)

    def pnl_pct(self, side: str, ref_price: float | None = None) -> float | None:
        price = ref_price or self.exit_price or self.current_price()
        if price is None:
            return None
        if side == "long":
            return (price / self.entry_price - 1) * 100
        return (self.entry_price / price - 1) * 100


@dataclass
class Session:
    id: int
    lock_date: str
    side: str
    top_n: int
    capital: float
    target_exit_date: str | None
    status: str
    note: str | None


def _live_entry_price(code: str, fallback: float) -> tuple[float, str]:
    """取得最真實的進場參考價.

    優先順序：
      1. 今日 MIS 即時 current（盤中或剛收盤）
      2. price_cache 最新收盤（若已是今日）
      3. fallback（screener 報的價，通常是前一交易日收盤）

    回傳 (price, source)，source ∈ {'live', 'eod', 'fallback'}.
    """
    try:
        quotes = live.quotes([code])
        q = quotes.get(code)
        if q and q.current and q.current > 0:
            return float(q.current), "live"
    except Exception:
        pass
    try:
        df = price_cache._load(code)
        if not df.empty:
            last_date = df.index[-1].date().isoformat()
            if last_date == date.today().isoformat():
                return float(df["close"].iloc[-1]), "eod"
    except Exception:
        pass
    return float(fallback), "fallback"


def lock_session(side: Literal["long", "short"],
                 picks: list[dict],
                 capital: float = 1_000_000,
                 hold_days: int = 5,
                 note: str | None = None,
                 use_live_entry: bool = True) -> int:
    """鎖定一個回測 session.

    picks: [{'代號': '2330', '名稱': '台積電', '收盤': 2185, '分數': 96}, ...]
    use_live_entry: True 時用今日 MIS 即時價當進場價（避免拿到上一交易日收盤）。
    回傳 session_id.
    """
    today = date.today().isoformat()
    target_exit = (date.today() + timedelta(days=hold_days)).isoformat()
    top_n = len(picks)
    if top_n == 0:
        raise ValueError("picks 不可為空")
    per_stock = capital / top_n

    with _lock, _conn() as c:
        # 同一天同方向只允許一個 open session（防止重複鎖定）
        existing = c.execute(
            "SELECT id FROM realbt_session "
            "WHERE lock_date=? AND side=? AND status='open'",
            (today, side),
        ).fetchone()
        if existing:
            raise ValueError(f"今日已有 {side} session（id={existing[0]}），"
                             f"請先結算舊的或選擇隔日鎖定")

        cur = c.execute(
            "INSERT INTO realbt_session "
            "(lock_date, side, top_n, capital, target_exit_date, "
            " status, note) VALUES (?,?,?,?,?,?,?)",
            (today, side, top_n, capital, target_exit, "open", note),
        )
        sid = cur.lastrowid

        for p in picks:
            code = str(p["代號"])
            ref_price = float(p["收盤"])
            if use_live_entry:
                entry_price, _src = _live_entry_price(code, ref_price)
            else:
                entry_price = ref_price
            c.execute(
                "INSERT INTO realbt_holding "
                "(session_id, code, name, score, entry_date, entry_price, "
                " position_size) VALUES (?,?,?,?,?,?,?)",
                (sid, code, str(p["名稱"]),
                 int(p.get("分數", 0)), today,
                 entry_price, per_stock),
            )
    return sid


def reanchor_entry_prices(session_id: int) -> dict:
    """以最新 MIS 即時價（或今日收盤）重置 session 的進場價.

    用於：第一次鎖定時拿到的是前一交易日收盤，需校正為今日真實成交價。
    回傳 {code: (old_price, new_price, source)}.
    """
    sess = get_session(session_id)
    if not sess:
        raise ValueError(f"找不到 session {session_id}")
    if sess.status == "closed":
        raise ValueError(f"session {session_id} 已結算，不可校正")

    today = date.today().isoformat()
    holdings = list_holdings(session_id)
    changes: dict = {}
    with _lock, _conn() as c:
        for h in holdings:
            new_price, src = _live_entry_price(h.code, h.entry_price)
            if src == "fallback":
                # 沒有更新的資料源，跳過
                changes[h.code] = (h.entry_price, h.entry_price, src)
                continue
            if abs(new_price - h.entry_price) < 0.001:
                changes[h.code] = (h.entry_price, h.entry_price, src)
                continue
            c.execute(
                "UPDATE realbt_holding SET entry_price=?, entry_date=? "
                "WHERE session_id=? AND code=?",
                (new_price, today, session_id, h.code),
            )
            changes[h.code] = (h.entry_price, new_price, src)
    return changes


def list_sessions(status: str | None = None) -> list[Session]:
    q = "SELECT id, lock_date, side, top_n, capital, target_exit_date, status, note FROM realbt_session"
    params: tuple = ()
    if status:
        q += " WHERE status=?"
        params = (status,)
    q += " ORDER BY lock_date DESC, id DESC"
    with _lock, _conn() as c:
        rows = c.execute(q, params).fetchall()
    return [Session(*r) for r in rows]


def get_session(session_id: int) -> Session | None:
    with _lock, _conn() as c:
        r = c.execute(
            "SELECT id, lock_date, side, top_n, capital, target_exit_date, "
            "status, note FROM realbt_session WHERE id=?",
            (session_id,),
        ).fetchone()
    return Session(*r) if r else None


def list_holdings(session_id: int) -> list[Holding]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT session_id, code, name, score, entry_date, entry_price, "
            "exit_date, exit_price, position_size "
            "FROM realbt_holding WHERE session_id=? ORDER BY score DESC",
            (session_id,),
        ).fetchall()
    return [Holding(*r) for r in rows]


def close_session(session_id: int) -> tuple[int, float]:
    """以最新收盤結算所有持股；回傳 (結算檔數, 總 P&L)."""
    sess = get_session(session_id)
    if not sess:
        raise ValueError(f"找不到 session {session_id}")
    if sess.status == "closed":
        return 0, 0.0
    today = date.today().isoformat()
    holdings = list_holdings(session_id)
    total_pnl = 0.0
    closed = 0
    with _lock, _conn() as c:
        for h in holdings:
            if h.exit_price is not None:
                continue
            cur = h.current_price()
            if cur is None:
                continue
            c.execute(
                "UPDATE realbt_holding SET exit_date=?, exit_price=? "
                "WHERE session_id=? AND code=?",
                (today, cur, session_id, h.code),
            )
            pnl = h.pnl(sess.side, ref_price=cur)
            if pnl is not None:
                total_pnl += pnl
            closed += 1
        c.execute(
            "UPDATE realbt_session SET status='closed' WHERE id=?",
            (session_id,),
        )
    return closed, total_pnl


def session_summary(session_id: int) -> dict:
    """單一 session 的彙整：總 P&L、勝率、最佳/最差檔."""
    sess = get_session(session_id)
    if not sess:
        return {}
    holdings = list_holdings(session_id)
    rows = []
    total_pnl = 0.0
    win = 0
    miss = 0
    for h in holdings:
        cur = h.exit_price or h.current_price()
        if cur is None:
            miss += 1
            rows.append({
                "code": h.code, "name": h.name, "score": h.score,
                "entry": h.entry_price, "now": None,
                "pct": None, "pnl": None,
            })
            continue
        pct = h.pnl_pct(sess.side, ref_price=cur)
        pnl = h.pnl(sess.side, ref_price=cur)
        if pnl is not None and pnl > 0:
            win += 1
        total_pnl += pnl or 0
        rows.append({
            "code": h.code, "name": h.name, "score": h.score,
            "entry": h.entry_price, "now": cur,
            "pct": pct, "pnl": pnl,
        })
    df = pd.DataFrame(rows)
    valid = len(holdings) - miss
    return {
        "session": sess,
        "holdings_df": df,
        "total_pnl": total_pnl,
        "total_return_pct": total_pnl / sess.capital * 100,
        "win": win, "lose": valid - win, "no_data": miss,
        "win_rate": (win / valid * 100) if valid else 0,
        "final_capital": sess.capital + total_pnl,
    }


def delete_session(session_id: int) -> None:
    """刪除整個 session（含 holdings）— 慎用。"""
    with _lock, _conn() as c:
        c.execute("DELETE FROM realbt_holding WHERE session_id=?",
                  (session_id,))
        c.execute("DELETE FROM realbt_session WHERE id=?", (session_id,))


# ---------------------------------------------------------------
# GitHub 備份 (與 ohlcv.db 同機制)
# ---------------------------------------------------------------
REPO_PATH = "data/realbacktest.db"


def auto_restore() -> tuple[bool, str]:
    """雲端啟動時若本機 DB 為空，從 GitHub 還原."""
    from . import storage
    if not storage.is_configured():
        return False, "未設定 GitHub secrets"
    # 沒有 sessions 表示空 DB
    try:
        with _lock, _conn() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM realbt_session").fetchone()
        if row and row[0] > 0:
            return False, f"本機已有 {row[0]} 個 sessions"
    except Exception:
        pass
    return storage.download_db(DB_PATH, repo_path=REPO_PATH)


def backup_now(message: str | None = None) -> tuple[bool, str]:
    """立即備份回測 DB 至 GitHub."""
    from . import storage
    if not storage.is_configured():
        return False, "未設定 GitHub secrets"
    try:
        with _lock, _conn() as c:
            n_sess = c.execute(
                "SELECT COUNT(*) FROM realbt_session").fetchone()[0]
            n_hold = c.execute(
                "SELECT COUNT(*) FROM realbt_holding").fetchone()[0]
    except Exception:
        n_sess, n_hold = 0, 0
    msg = message or f"realbacktest.db ({n_sess} sessions, {n_hold} holdings)"
    return storage.upload_db(DB_PATH, message=msg, repo_path=REPO_PATH,
                              auto_compress=False)  # 小 DB 不需 gzip
