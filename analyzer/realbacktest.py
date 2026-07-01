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

from . import live, price_cache, backtest_filter

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


def _current_price(code: str) -> tuple[float | None, str]:
    """取得即時當前價（用於 P&L 計算）.

    優先順序：
      1. live MIS 即時（盤中或剛收盤後最準確）
      2. price_cache 最新收盤（盤後或停牌時）
    回傳 (price, source) 其中 source ∈ {'live', 'cache'} or (None, 'none').
    """
    try:
        qs = live.quotes([code])
        q = qs.get(code)
        if q and q.current and q.current > 0:
            return float(q.current), "live"
    except Exception:
        pass
    try:
        df = price_cache._load(code)
        if not df.empty:
            return float(df["close"].iloc[-1]), "cache"
    except Exception:
        pass
    return None, "none"


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
        """取得即時當前價：優先 live MIS，其次 price_cache 最新收盤."""
        p, _ = _current_price(self.code)
        return p

    def expected_exit_price(self,
                             target_exit_date: str | None) -> float | None:
        """取「持有期到期 vs 今日」較早日期的收盤價（為歷史回測核心邏輯）.

        - target_exit_date 為 None / 未來 → 回最新收盤
        - target_exit_date 已過期 → 回該日（或之前最近交易日）的收盤
        - 防衛：cutoff 早於 entry_date 時回 current_price（避免回未來的負時點價）
        """
        if target_exit_date is None:
            return self.current_price()
        try:
            target_dt = date.fromisoformat(target_exit_date)
        except Exception:
            return self.current_price()
        cutoff = min(target_dt, date.today())
        # 防衛：cutoff 比進場日還早（時鐘異常 / 手動建立的怪資料）→ 回現價
        try:
            entry_dt = date.fromisoformat(self.entry_date)
            if cutoff < entry_dt:
                return self.current_price()
        except Exception:
            pass
        try:
            df = price_cache._load(self.code)
            if df.empty:
                return None
            sub = df[df.index <= pd.Timestamp(cutoff)]
            if sub.empty:
                return None
            return float(sub["close"].iloc[-1])
        except Exception:
            return None

    def pnl(self, side: str, ref_price: float | None = None) -> float | None:
        """回傳 P&L (TWD)；ref_price 沒給則用即時價."""
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
    # 用交易日（business day）計算結算日，避免落到週末
    target_exit = (pd.Timestamp(date.today())
                   + pd.tseries.offsets.BDay(hold_days)).date().isoformat()
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


def check_stop_loss_open_sessions(force_update: bool = False) -> dict:
    """掃描所有 open sessions 的持股，觸發 MA10 技術停損.

    Lv4 自動執行：
      - 多單跌破 MA10 → 立即結算該檔（保留其他持股）
      - 空單突破 MA10 → 立即回補

    force_update=True 時，每檔用 price_cache.get() 強制 fetch 最新 K 線
    （盤中停損 alert 專用；預設 False 用 _load 讀既有 cache）.

    回傳 {session_id: [(code, side, reason, exit_price), ...]}
    """
    from . import indicators
    sessions = list_sessions(status="open")
    triggered: dict = {}
    today = date.today().isoformat()
    for sess in sessions:
        holdings = list_holdings(sess.id)
        for h in holdings:
            if h.exit_price is not None:
                continue
            try:
                if force_update:
                    # 強制取最新 K 線（用於盤中停損 workflow）
                    try:
                        df = price_cache.get(h.code, period="6mo")
                    except Exception:
                        df = price_cache._load(h.code)
                else:
                    df = price_cache._load(h.code)
                if df is None or df.empty:
                    continue
                df = indicators.add_all(df)
                stop, reason = backtest_filter.check_technical_stop(
                    df, sess.side, h.entry_price)
                if stop:
                    cur_price = float(df["close"].iloc[-1])
                    with _lock, _conn() as c:
                        c.execute(
                            "UPDATE realbt_holding SET exit_date=?, "
                            "exit_price=? WHERE session_id=? AND code=?",
                            (today, cur_price, sess.id, h.code),
                        )
                    triggered.setdefault(sess.id, []).append(
                        (h.code, h.name, sess.side, reason, cur_price))
            except Exception:
                continue
    return triggered


def lock_session_historical(side: Literal["long", "short"],
                             as_of_date: str,
                             picks: list[dict],
                             capital: float = 1_000_000,
                             hold_days: int = 5,
                             note: str | None = None) -> int:
    """歷史日期回測：以指定日期當進場日鎖定 session.

    picks: 來自 screener.screen_historical(as_of_date) 的結果
    entry_date 設為 as_of_date；entry_price 為 as_of_date 的收盤價。
    target_exit_date = as_of_date + hold_days。
    """
    try:
        as_of = date.fromisoformat(as_of_date)
    except Exception:
        raise ValueError(f"as_of_date 格式錯誤：{as_of_date}（需 YYYY-MM-DD）")
    # ★ 用交易日（business day）計算 target_exit_date，跟 lock_session 一致
    # 否則 hold_days=5 歷史回測得日曆 5 天 ≠ 實盤回測得交易 5 天
    target_exit = (pd.Timestamp(as_of)
                   + pd.tseries.offsets.BDay(hold_days)).date().isoformat()
    top_n = len(picks)
    if top_n == 0:
        raise ValueError("picks 不可為空")
    per_stock = capital / top_n

    with _lock, _conn() as c:
        # 同一天同方向同 capital 已有 session → 拒絕
        existing = c.execute(
            "SELECT id FROM realbt_session "
            "WHERE lock_date=? AND side=? AND status='open' AND note LIKE ?",
            (as_of_date, side, "%歷史回測%"),
        ).fetchone()
        if existing:
            raise ValueError(
                f"{as_of_date} 已有 {side} 歷史回測 session（id={existing[0]}），"
                f"請先刪除舊的或選擇不同 hold_days")

        full_note = f"歷史回測 ({as_of_date} → {target_exit}) " \
                    + (note or f"持有 {hold_days} 日")
        cur = c.execute(
            "INSERT INTO realbt_session "
            "(lock_date, side, top_n, capital, target_exit_date, "
            " status, note) VALUES (?,?,?,?,?,?,?)",
            (as_of_date, side, top_n, capital, target_exit, "open", full_note),
        )
        sid = cur.lastrowid

        for p in picks:
            c.execute(
                "INSERT INTO realbt_holding "
                "(session_id, code, name, score, entry_date, entry_price, "
                " position_size) VALUES (?,?,?,?,?,?,?)",
                (sid, str(p["代號"]), str(p["名稱"]),
                 int(p.get("分數", 0)),
                 as_of_date,                  # 進場日 = 歷史日期
                 float(p["收盤"]),             # 進場價 = 該日收盤
                 per_stock),
            )
    return sid


# ---------------------------------------------------------------
# TG 自動化：lock / auto-close / track-record
# ---------------------------------------------------------------
AUTO_NOTE_PREFIX = "TG_auto"


def lock_session_auto(side: Literal["long", "short"],
                       picks: list[dict],
                       capital: float = 1_000_000,
                       hold_days: int = 5,
                       note: str | None = None) -> int | None:
    """TG 自動 lock — 同日同方向已存在 auto session 則靜默 skip（回傳 None）.

    用於每日 08:30 TG 推送後自動把推薦 picks 紙上交易，後續結算累積 track record.
    """
    today = date.today().isoformat()
    with _lock, _conn() as c:
        existing = c.execute(
            "SELECT id FROM realbt_session "
            "WHERE lock_date=? AND side=? AND note LIKE ?",
            (today, side, f"{AUTO_NOTE_PREFIX}%"),
        ).fetchone()
        if existing:
            return None
    full_note = f"{AUTO_NOTE_PREFIX} {note or ''}".strip()
    return lock_session(side, picks, capital=capital,
                         hold_days=hold_days, note=full_note,
                         use_live_entry=True)


def auto_close_expired() -> list[tuple[int, int, float]]:
    """結算所有 target_exit_date <= today 的 open sessions.

    回傳 [(session_id, n_closed, total_pnl_gross), ...]
    """
    today = date.today()
    closed = []
    for sess in list_sessions(status="open"):
        if not sess.target_exit_date:
            continue
        try:
            target_dt = date.fromisoformat(sess.target_exit_date)
        except Exception:
            continue
        if today < target_dt:
            continue
        try:
            n, pnl = close_session(sess.id)
            closed.append((sess.id, n, pnl))
        except Exception:
            continue
    return closed


def track_record(days: int | None = None,
                  auto_only: bool = True) -> dict | None:
    """彙整系統累積績效（僅 closed sessions）.

    Args:
        days: 取最近 N 日 lock_date 的 sessions；None = 全部
        auto_only: True 只算 TG 自動 lock 的（排除手動回測）

    回傳：
        {
            "n_sessions": int,
            "n_holdings": int,         # 展開到單檔
            "win": int, "lose": int,
            "win_rate": float,         # 0-100
            "avg_return_pct": float,   # 單檔平均報酬 %
            "best": float, "worst": float,
            "period_days": int | None,
        }
        若無資料回傳 None.
    """
    sessions = list_sessions(status="closed")
    if auto_only:
        sessions = [s for s in sessions
                    if s.note and AUTO_NOTE_PREFIX in s.note]
    if days:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        sessions = [s for s in sessions if s.lock_date >= cutoff]

    win = lose = 0
    pcts: list[float] = []
    for sess in sessions:
        for h in list_holdings(sess.id):
            if h.exit_price is None or h.entry_price <= 0:
                continue
            if sess.side == "long":
                pct = (h.exit_price / h.entry_price - 1) * 100
            else:
                pct = (h.entry_price / h.exit_price - 1) * 100
            pcts.append(pct)
            if pct > 0:
                win += 1
            else:
                lose += 1

    if not pcts:
        return None
    return {
        "n_sessions": len(sessions),
        "n_holdings": len(pcts),
        "win": win, "lose": lose,
        "win_rate": win / len(pcts) * 100,
        "avg_return_pct": sum(pcts) / len(pcts),
        "best": max(pcts),
        "worst": min(pcts),
        "period_days": days,
    }


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
    """以即時 live MIS（盤中或剛收盤）結算所有持股；回傳 (結算檔數, 總 P&L 毛利).

    與 session_summary 同樣使用 live → cache fallback 策略，避免結算時拿到
    過期的 EOD 收盤而誤算 P&L。
    """
    sess = get_session(session_id)
    if not sess:
        raise ValueError(f"找不到 session {session_id}")
    if sess.status == "closed":
        return 0, 0.0
    today = date.today().isoformat()
    holdings = list_holdings(session_id)
    open_codes = [h.code for h in holdings if h.exit_price is None]
    # 批次抓 live
    live_map: dict = {}
    if open_codes:
        try:
            qs = live.quotes(open_codes)
            for code, q in qs.items():
                if q and q.current and q.current > 0:
                    live_map[code] = float(q.current)
        except Exception:
            pass

    total_pnl = 0.0
    closed = 0
    with _lock, _conn() as c:
        for h in holdings:
            if h.exit_price is not None:
                continue
            cur = live_map.get(h.code)
            if cur is None:
                # fallback: price_cache 最新收盤
                try:
                    df = price_cache._load(h.code)
                    if not df.empty:
                        cur = float(df["close"].iloc[-1])
                except Exception:
                    pass
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
    """單一 session 的彙整：總 P&L、勝率、最佳/最差檔.

    批次抓 live 報價（一次 API 取所有 holdings），再退到 price_cache。
    """
    sess = get_session(session_id)
    if not sess:
        return {}
    holdings = list_holdings(session_id)
    if not holdings:
        return {}

    # 批次抓 live MIS（10 檔以內一次 API 解決，比 holding-by-holding 快數倍）
    open_codes = [h.code for h in holdings if h.exit_price is None]
    live_map: dict = {}
    if open_codes:
        try:
            qs = live.quotes(open_codes)
            for code, q in qs.items():
                if q and q.current and q.current > 0:
                    live_map[code] = float(q.current)
        except Exception:
            pass

    # 持有期到期判斷：歷史回測 / 普通回測共用
    target_exit_passed = False
    if sess.target_exit_date:
        try:
            target_dt = date.fromisoformat(sess.target_exit_date)
            target_exit_passed = date.today() >= target_dt
        except Exception:
            pass

    def _ref_price(h: Holding) -> tuple[float | None, str]:
        if h.exit_price is not None:
            return h.exit_price, "exit"
        # 若持有期已到期 → 用 target_exit_date 那日收盤（鎖定 P&L）
        # 否則 → 用 live MIS 或 price_cache 最新（追蹤中）
        if target_exit_passed:
            p = h.expected_exit_price(sess.target_exit_date)
            if p is not None:
                return p, "expired"
        if h.code in live_map:
            return live_map[h.code], "live"
        try:
            df = price_cache._load(h.code)
            if not df.empty:
                return float(df["close"].iloc[-1]), "cache"
        except Exception:
            pass
        return None, "none"

    # 計算實際持有天數（用交易日）
    today_dt = pd.Timestamp(date.today())
    lock_dt = pd.Timestamp(sess.lock_date)
    actual_hold_days = max(0, (today_dt - lock_dt).days)

    rows = []
    total_pnl_gross = 0.0
    total_costs = 0.0
    win = 0
    flat = 0
    miss = 0
    for h in holdings:
        cur, src = _ref_price(h)
        if cur is None:
            miss += 1
            rows.append({
                "code": h.code, "name": h.name, "score": h.score,
                "entry": h.entry_price, "now": None,
                "pct": None, "pnl": None, "cost": 0,
                "net": None, "source": "no_data",
            })
            continue
        pct = h.pnl_pct(sess.side, ref_price=cur)
        pnl_gross = h.pnl(sess.side, ref_price=cur) or 0
        # 估算進出場成本
        costs = estimate_costs(sess.side, h.entry_price, cur,
                                h.position_size, actual_hold_days)
        cost_total = costs["total"]
        pnl_net = pnl_gross - cost_total
        if pnl_net > 1:
            win += 1
        elif pnl_net > -1:
            flat += 1
        total_pnl_gross += pnl_gross
        total_costs += cost_total
        rows.append({
            "code": h.code, "name": h.name, "score": h.score,
            "entry": h.entry_price, "now": cur,
            "pct": pct, "pnl": pnl_gross,
            "cost": cost_total, "net": pnl_net,
            "source": src,
        })
    df = pd.DataFrame(rows)
    valid = len(holdings) - miss
    lose = valid - win - flat
    total_pnl_net = total_pnl_gross - total_costs
    return {
        "session": sess,
        "holdings_df": df,
        "total_pnl": total_pnl_gross,           # 毛利
        "total_costs": total_costs,             # 總成本
        "total_pnl_net": total_pnl_net,         # 淨利（扣手續費 / 證交稅 / 借券）
        "total_return_pct": total_pnl_gross / sess.capital * 100,
        "total_return_net_pct": total_pnl_net / sess.capital * 100,
        "actual_hold_days": actual_hold_days,
        "win": win, "lose": lose, "flat": flat, "no_data": miss,
        "win_rate": (win / valid * 100) if valid else 0,
        "final_capital": sess.capital + total_pnl_net,
    }


def delete_session(session_id: int) -> None:
    """刪除整個 session（含 holdings）— 慎用。"""
    with _lock, _conn() as c:
        c.execute("DELETE FROM realbt_holding WHERE session_id=?",
                  (session_id,))
        c.execute("DELETE FROM realbt_session WHERE id=?", (session_id,))


# ---------------------------------------------------------------
# 交易成本估算（台股實際費率）
# ---------------------------------------------------------------
COMMISSION_RATE = 0.001425   # 手續費 0.1425% (買、賣各收一次)
TAX_RATE_LONG = 0.003        # 證交稅 0.3%（賣出時）
TAX_RATE_SHORT = 0.0015      # 當沖賣出證交稅減半 0.15%；融券先不用稅
SHORT_BORROW_ANNUAL = 0.06   # 融券借券費年化 ~6%（券商而異）


def estimate_costs(side: str, entry_price: float, exit_price: float,
                   position_size: float, hold_days: int) -> dict:
    """估算單一持股的進出場成本.

    side='long': 買進 + 賣出 → 手續費×2 + 賣出證交稅
    side='short': 融券賣出 + 回補買進 → 手續費×2 + 賣出證交稅 + 借券利息
    回傳 {commission, tax, borrow, total}.
    """
    # 手續費（買 + 賣各一次）
    commission = (position_size + position_size *
                  (exit_price / entry_price)) * COMMISSION_RATE
    if side == "long":
        # 賣出端的部位金額 ≈ position_size * (exit/entry)
        tax = position_size * (exit_price / entry_price) * TAX_RATE_LONG
        borrow = 0.0
    else:
        tax = position_size * TAX_RATE_LONG  # 融券回補時賣出端是進場
        borrow = position_size * SHORT_BORROW_ANNUAL * (hold_days / 365)
    total = commission + tax + borrow
    return {
        "commission": commission, "tax": tax, "borrow": borrow,
        "total": total,
    }


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
