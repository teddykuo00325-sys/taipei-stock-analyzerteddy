"""券商分點買賣超 - SQLite 歷史累積.

每天抓 broker.fetch() → 存入；累積後可做：
  - 連續 N 日買超偵測
  - 券商加權平均成本（VWAP 概念，跨越多日）
  - 券商當前現價 vs 平均成本差%

對外 API：
  append_today(snap)               — 把 BrokerSnapshot 存入今日資料
  load(code, days=30)              — 讀單股近 N 日完整 broker history
  consecutive_buy(code, n=3)       — 偵測連續 N 日買超的券商
  broker_avg_cost(code, broker)    — 計算單一券商的累積平均成本
  weekly_top_brokers(code)         — 本週累積買超 top 5
  stats() / auto_restore() / backup_now()
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from threading import Lock

import pandas as pd

DB_PATH = Path(__file__).parent.parent / "data" / "broker_history.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_lock = Lock()
REPO_PATH = "data/broker_history.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.execute("""
        CREATE TABLE IF NOT EXISTS broker_daily (
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            broker TEXT NOT NULL,
            side TEXT NOT NULL,        -- 'buy' (買超榜) | 'sell' (賣超榜)
            buy_lots INTEGER,
            sell_lots INTEGER,
            net_lots INTEGER,
            avg_price REAL,
            PRIMARY KEY (code, date, broker, side)
        )
    """)
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_bd_code_date "
        "ON broker_daily(code, date)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_bd_broker "
        "ON broker_daily(broker)"
    )
    return c


def append_today(snap) -> int:
    """把 BrokerSnapshot 存入今日資料（INSERT OR REPLACE）.

    回傳新增/更新的列數。
    """
    if snap is None:
        return 0
    rows = []
    for e in snap.top_buy:
        rows.append((snap.code, snap.date, e.broker, "buy",
                     e.buy_lots, e.sell_lots, e.net_lots, e.avg_price))
    for e in snap.top_sell:
        rows.append((snap.code, snap.date, e.broker, "sell",
                     e.buy_lots, e.sell_lots, e.net_lots, e.avg_price))
    if not rows:
        return 0
    with _lock, _conn() as c:
        c.executemany(
            "INSERT OR REPLACE INTO broker_daily "
            "(code, date, broker, side, buy_lots, sell_lots, net_lots, "
            " avg_price) VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


def load(code: str, days: int = 30) -> pd.DataFrame:
    """讀單股近 N 日 broker history (DataFrame, 升冪)."""
    cutoff = (date.today() - timedelta(days=days * 2)).isoformat()
    with _lock, _conn() as c:
        df = pd.read_sql_query(
            "SELECT date, broker, side, buy_lots, sell_lots, net_lots, "
            "avg_price FROM broker_daily WHERE code=? AND date>=? "
            "ORDER BY date, broker",
            c, params=[str(code).strip(), cutoff],
        )
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df


def consecutive_buy(code: str, n: int = 3,
                     min_lots: int = 100) -> list[dict]:
    """偵測連續 N 個交易日（在 history 中）出現於買超榜的券商.

    min_lots: 每日買超至少 N 張（過濾雜訊）
    回傳：[{'broker', 'days', 'total_net_lots', 'avg_price', 'last_date'}, ...]
    """
    df = load(code, days=n * 3 + 5)   # 抓更多備用
    if df.empty:
        return []
    buy_df = df[(df["side"] == "buy") &
                (df["net_lots"] >= min_lots)].copy()
    if buy_df.empty:
        return []
    # 取每個 broker 各日是否上榜
    pivot = buy_df.pivot_table(
        index="broker", columns="date",
        values="net_lots", aggfunc="max",
    )
    # 找最近 N 個交易日（從 history 中真正存在的日期取）
    recent_dates = sorted(buy_df["date"].unique())[-n:]
    if len(recent_dates) < n:
        return []
    out = []
    for broker, row in pivot.iterrows():
        # 該券商是否每個 recent_dates 都有資料
        days_seen = 0
        total_net = 0
        total_cost = 0.0
        total_lots = 0
        for d in recent_dates:
            v = row.get(d)
            if pd.notna(v) and v > 0:
                days_seen += 1
                total_net += int(v)
                # 取該日 broker 的 avg_price
                row_d = buy_df[(buy_df["broker"] == broker) &
                                (buy_df["date"] == d)]
                if not row_d.empty:
                    p = float(row_d.iloc[0]["avg_price"])
                    lots = int(row_d.iloc[0]["buy_lots"])
                    total_cost += p * lots
                    total_lots += lots
        if days_seen >= n:
            avg_price = (total_cost / total_lots) if total_lots else 0
            out.append({
                "broker": broker,
                "days": days_seen,
                "total_net_lots": total_net,
                "avg_price": round(avg_price, 2),
                "last_date": recent_dates[-1].strftime("%Y-%m-%d"),
            })
    out.sort(key=lambda x: x["total_net_lots"], reverse=True)
    return out


def broker_avg_cost(code: str, broker: str,
                     days: int = 30) -> dict | None:
    """計算單一券商在近 N 日的累積買超 / 賣超加權平均成本.

    回傳：
      {'buy_avg_cost': X, 'buy_total_lots': N,
       'sell_avg_cost': X, 'sell_total_lots': N,
       'net_lots': diff, 'days_active': N}
    """
    df = load(code, days)
    if df.empty:
        return None
    sub = df[df["broker"] == broker]
    if sub.empty:
        return None
    buy_lots = (sub["buy_lots"] * (sub["side"] == "buy").astype(int)).sum()
    sell_lots = (sub["sell_lots"] * (sub["side"] == "sell").astype(int)).sum()
    # avg_price × buy_lots 求加權買進均價
    buy_rows = sub[sub["side"] == "buy"]
    sell_rows = sub[sub["side"] == "sell"]
    buy_avg = 0.0
    sell_avg = 0.0
    if not buy_rows.empty:
        bl = buy_rows["buy_lots"]
        if bl.sum() > 0:
            buy_avg = float((buy_rows["avg_price"] * bl).sum() / bl.sum())
    if not sell_rows.empty:
        sl = sell_rows["sell_lots"]
        if sl.sum() > 0:
            sell_avg = float((sell_rows["avg_price"] * sl).sum() / sl.sum())
    return {
        "buy_avg_cost": round(buy_avg, 2),
        "buy_total_lots": int(buy_lots),
        "sell_avg_cost": round(sell_avg, 2),
        "sell_total_lots": int(sell_lots),
        "net_lots": int(buy_lots) - int(sell_lots),
        "days_active": len(sub["date"].unique()),
    }


def weekly_top_brokers(code: str, days: int = 5) -> dict:
    """本週（近 days 個交易日）累積買超 / 賣超 top 5 券商.

    回傳 {top_buy: [{broker, total_net, avg_price}, ...],
          top_sell: [...]}
    """
    df = load(code, days)
    if df.empty:
        return {"top_buy": [], "top_sell": []}

    def _agg(side: str) -> list[dict]:
        s = df[df["side"] == side]
        if s.empty:
            return []
        # 按 broker 聚合
        out = []
        for broker, sub in s.groupby("broker"):
            net = int(sub["net_lots"].sum())
            lots_col = sub[("buy_lots" if side == "buy" else "sell_lots")]
            wavg = (float((sub["avg_price"] * lots_col).sum()
                          / lots_col.sum())
                    if lots_col.sum() > 0 else 0.0)
            out.append({
                "broker": broker,
                "total_net": net,
                "avg_price": round(wavg, 2),
                "days_appeared": len(sub),
            })
        out.sort(key=lambda x: abs(x["total_net"]), reverse=True)
        return out[:5]

    return {"top_buy": _agg("buy"), "top_sell": _agg("sell")}


def stats() -> dict:
    with _lock, _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM broker_daily").fetchone()[0]
        codes = c.execute(
            "SELECT COUNT(DISTINCT code) FROM broker_daily").fetchone()[0]
        rng = c.execute(
            "SELECT MIN(date), MAX(date) FROM broker_daily").fetchone()
    size_kb = DB_PATH.stat().st_size / 1024 if DB_PATH.exists() else 0
    return {
        "rows": n, "codes": codes,
        "date_range": (rng[0], rng[1]) if rng else (None, None),
        "db_size_kb": round(size_kb, 1),
    }


def purge_older_than(days: int = 90) -> int:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with _lock:
        with _conn() as c:
            n = c.execute(
                "DELETE FROM broker_daily WHERE date<?",
                (cutoff,),
            ).rowcount
        try:
            v = sqlite3.connect(DB_PATH, isolation_level=None)
            v.execute("VACUUM")
            v.close()
        except Exception:
            pass
    return n or 0


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
    msg = message or (f"broker_history.db ({s['rows']} rows, "
                      f"{s['codes']} codes)")
    return storage.upload_db(DB_PATH, message=msg, repo_path=REPO_PATH,
                              auto_compress=True)
