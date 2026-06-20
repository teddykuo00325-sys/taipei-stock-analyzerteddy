"""系統累積績效計算 — 用於 Web 端「📊 系統績效儀表板」.

資料來源：realbacktest.db 的 closed sessions，過濾 note 含 'TG_auto'。

對外 API：
    holdings_df()         — 全部 closed holdings flat dataframe（含 side, regime）
    sessions_df()         — session 層級 aggregate
    equity_curve()        — 系統累積資金曲線（按 session 結算日序列）
    twii_benchmark()      — 同期 TWII 漲跌幅，normalize 到起始 1.0
    win_rate_by()         — 依 side / regime 分群勝率
    max_drawdown()        — 最大回撤金額 / %
    summary_kpis()        — 頂部 4 個關鍵指標
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import pandas as pd

from . import realbacktest


# ============================================================
# 資料載入
# ============================================================
def _regime_label_at(d: str) -> str:
    """retroactive regime lookup（bull/bear/sideways）."""
    try:
        from . import backtest_filter
        r = backtest_filter.detect_regime(as_of_date=d)
        return r.label  # 'bull' | 'bear' | 'sideways'
    except Exception:
        return "unknown"


def holdings_df(auto_only: bool = True) -> pd.DataFrame:
    """全部 closed holdings → flat dataframe.

    每列一檔持股，欄位：
        session_id, lock_date, exit_date, side, regime,
        code, name, entry_price, exit_price, position_size,
        return_pct, pnl
    """
    sessions = realbacktest.list_sessions(status="closed")
    if auto_only:
        sessions = [
            s for s in sessions
            if s.note and realbacktest.AUTO_NOTE_PREFIX in s.note
        ]
    if not sessions:
        return pd.DataFrame(columns=[
            "session_id", "lock_date", "exit_date", "side", "regime",
            "code", "name", "entry_price", "exit_price", "position_size",
            "return_pct", "pnl",
        ])
    # 預先批次 regime lookup（同一 lock_date 多 session 共用）
    unique_dates = {s.lock_date for s in sessions}
    regime_map = {d: _regime_label_at(d) for d in unique_dates}

    rows = []
    for sess in sessions:
        for h in realbacktest.list_holdings(sess.id):
            if h.exit_price is None or h.entry_price <= 0:
                continue
            if sess.side == "long":
                pct = (h.exit_price / h.entry_price - 1) * 100
            else:
                pct = (h.entry_price / h.exit_price - 1) * 100
            pnl = h.position_size * pct / 100
            rows.append({
                "session_id": sess.id,
                "lock_date": sess.lock_date,
                "exit_date": h.exit_date or sess.target_exit_date,
                "side": sess.side,
                "regime": regime_map.get(sess.lock_date, "unknown"),
                "code": h.code,
                "name": h.name,
                "entry_price": h.entry_price,
                "exit_price": h.exit_price,
                "position_size": h.position_size,
                "return_pct": pct,
                "pnl": pnl,
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["lock_date"] = pd.to_datetime(df["lock_date"])
        df["exit_date"] = pd.to_datetime(df["exit_date"])
    return df


def sessions_df(auto_only: bool = True) -> pd.DataFrame:
    """session 層級 aggregate：每筆 session 平均報酬 / 總 P&L / 命中率."""
    h = holdings_df(auto_only=auto_only)
    if h.empty:
        return pd.DataFrame()
    g = h.groupby(["session_id", "lock_date", "exit_date", "side", "regime"])
    sess = g.agg(
        n_holdings=("code", "count"),
        avg_return_pct=("return_pct", "mean"),
        total_pnl=("pnl", "sum"),
        capital=("position_size", "sum"),
        win=("return_pct", lambda s: int((s > 0).sum())),
        lose=("return_pct", lambda s: int((s <= 0).sum())),
    ).reset_index()
    sess["session_return_pct"] = sess["total_pnl"] / sess["capital"] * 100
    sess = sess.sort_values("exit_date").reset_index(drop=True)
    return sess


# ============================================================
# 累積績效曲線
# ============================================================
def equity_curve(initial_capital: float = 1.0,
                  auto_only: bool = True) -> pd.DataFrame:
    """系統累積資金曲線（依 session exit_date 排序，複利累積）.

    回傳 columns: date, equity, session_return_pct
    """
    s = sessions_df(auto_only=auto_only)
    if s.empty:
        return pd.DataFrame(columns=["date", "equity", "session_return_pct"])
    # 用 session_return_pct 複利累積
    s["factor"] = 1 + s["session_return_pct"] / 100
    s["equity"] = initial_capital * s["factor"].cumprod()
    return s[["exit_date", "equity", "session_return_pct"]].rename(
        columns={"exit_date": "date"})


def twii_benchmark(start: str, end: str,
                   normalize_to: float = 1.0) -> pd.DataFrame:
    """同期間 ^TWII 漲跌幅，normalize 到 normalize_to 為基準.

    Returns df with columns: date, twii_close, twii_norm
    """
    try:
        import yfinance as yf
        # end +1 day for inclusive
        end_plus = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        df = yf.Ticker("^TWII").history(start=start, end=end_plus)
        if df.empty:
            return pd.DataFrame()
        df = df.reset_index()
        if df["Date"].dt.tz is not None:
            df["Date"] = df["Date"].dt.tz_localize(None)
        first_close = float(df["Close"].iloc[0])
        df["twii_norm"] = df["Close"] / first_close * normalize_to
        return df[["Date", "Close", "twii_norm"]].rename(
            columns={"Date": "date", "Close": "twii_close"})
    except Exception:
        return pd.DataFrame()


# ============================================================
# 分群勝率
# ============================================================
def win_rate_by(dim: Literal["side", "regime"],
                 auto_only: bool = True) -> pd.DataFrame:
    """依 side ('long'|'short') 或 regime ('bull'|'bear'|'sideways') 分群."""
    h = holdings_df(auto_only=auto_only)
    if h.empty:
        return pd.DataFrame()
    g = h.groupby(dim)
    out = g.agg(
        n_holdings=("code", "count"),
        win=("return_pct", lambda s: int((s > 0).sum())),
        lose=("return_pct", lambda s: int((s <= 0).sum())),
        avg_return_pct=("return_pct", "mean"),
        median_return_pct=("return_pct", "median"),
        std_return_pct=("return_pct", "std"),
        best_pct=("return_pct", "max"),
        worst_pct=("return_pct", "min"),
    ).reset_index()
    out["win_rate"] = out["win"] / out["n_holdings"] * 100
    return out


# ============================================================
# 最大回撤
# ============================================================
@dataclass
class Drawdown:
    max_dd_pct: float       # 負數，如 -12.5
    peak_date: str          # 高點日期
    trough_date: str        # 谷底日期
    recovery_date: str | None  # 復原至 peak 的日期；None=尚未復原


def max_drawdown(equity: pd.Series, dates: pd.Series) -> Drawdown:
    """從 equity 序列計算最大回撤.

    equity / dates 須對齊，長度相同。
    """
    if equity.empty or len(equity) < 2:
        return Drawdown(0.0, "", "", None)
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max * 100
    idx_min = int(dd.idxmin())
    max_dd = float(dd.iloc[idx_min])
    trough_date = pd.Timestamp(dates.iloc[idx_min]).strftime("%Y-%m-%d")
    # peak 為 trough 之前 running_max 等於該點 max 的最早日
    peak_val = float(running_max.iloc[idx_min])
    peak_idx = int(equity.iloc[:idx_min + 1].eq(peak_val).idxmax())
    peak_date = pd.Timestamp(dates.iloc[peak_idx]).strftime("%Y-%m-%d")
    # recovery: 從 trough 開始之後，何時 equity 重回 peak_val
    after = equity.iloc[idx_min + 1:]
    rec_match = after[after >= peak_val]
    recovery_date = (pd.Timestamp(dates.iloc[rec_match.index[0]])
                     .strftime("%Y-%m-%d")) if not rec_match.empty else None
    return Drawdown(max_dd, peak_date, trough_date, recovery_date)


# ============================================================
# 頂部 KPIs
# ============================================================
def summary_kpis(initial_capital: float = 1.0,
                  auto_only: bool = True) -> dict:
    """4 個關鍵指標：總報酬 / 勝率 / 平均單檔報酬 / 最大回撤."""
    h = holdings_df(auto_only=auto_only)
    if h.empty:
        return {
            "n_sessions": 0,
            "n_holdings": 0,
            "total_return_pct": 0.0,
            "win_rate": 0.0,
            "avg_return_pct": 0.0,
            "max_dd_pct": 0.0,
            "first_date": None,
            "last_date": None,
        }
    eq = equity_curve(initial_capital=initial_capital, auto_only=auto_only)
    dd = max_drawdown(eq["equity"], eq["date"])
    total_return = (float(eq["equity"].iloc[-1]) - initial_capital) \
                   / initial_capital * 100
    win = int((h["return_pct"] > 0).sum())
    return {
        "n_sessions": h["session_id"].nunique(),
        "n_holdings": len(h),
        "total_return_pct": total_return,
        "win_rate": win / len(h) * 100,
        "avg_return_pct": float(h["return_pct"].mean()),
        "max_dd_pct": dd.max_dd_pct,
        "max_dd_peak": dd.peak_date,
        "max_dd_trough": dd.trough_date,
        "first_date": pd.Timestamp(h["lock_date"].min()).strftime("%Y-%m-%d"),
        "last_date": pd.Timestamp(h["exit_date"].max()).strftime("%Y-%m-%d"),
    }
