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
        return_pct, pnl,           # 毛利 (gross)
        cost, return_net_pct, pnl_net   # 淨利 (扣手續費/稅/借券費)
        hold_days
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
            "return_pct", "pnl", "cost", "return_net_pct", "pnl_net",
            "hold_days",
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
            # 持有天數（用日曆日近似；做空借券費要用日曆日）
            try:
                hd = (pd.Timestamp(h.exit_date or sess.target_exit_date)
                      - pd.Timestamp(h.entry_date)).days
                hd = max(1, hd)
            except Exception:
                hd = 5
            # 交易成本（手續費 + 證交稅 + 借券費）
            costs = realbacktest.estimate_costs(
                sess.side, h.entry_price, h.exit_price,
                h.position_size, hd)
            cost_total = costs["total"]
            pnl_net = pnl - cost_total
            # 淨報酬率 = 淨損益 / 本金
            net_pct = pnl_net / h.position_size * 100
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
                "cost": cost_total,
                "return_net_pct": net_pct,
                "pnl_net": pnl_net,
                "hold_days": hd,
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["lock_date"] = pd.to_datetime(df["lock_date"])
        df["exit_date"] = pd.to_datetime(df["exit_date"])
    return df


def sessions_df(auto_only: bool = True) -> pd.DataFrame:
    """session 層級 aggregate：每筆 session 平均報酬 / 總 P&L (毛/淨) / 命中率."""
    h = holdings_df(auto_only=auto_only)
    if h.empty:
        return pd.DataFrame()
    g = h.groupby(["session_id", "lock_date", "exit_date", "side", "regime"])
    sess = g.agg(
        n_holdings=("code", "count"),
        avg_return_pct=("return_pct", "mean"),
        avg_return_net_pct=("return_net_pct", "mean"),
        total_pnl=("pnl", "sum"),
        total_pnl_net=("pnl_net", "sum"),
        total_cost=("cost", "sum"),
        capital=("position_size", "sum"),
        win=("return_net_pct", lambda s: int((s > 0).sum())),
        lose=("return_net_pct", lambda s: int((s <= 0).sum())),
    ).reset_index()
    sess["session_return_pct"] = sess["total_pnl"] / sess["capital"] * 100
    sess["session_return_net_pct"] = sess["total_pnl_net"] / sess["capital"] * 100
    sess = sess.sort_values("exit_date").reset_index(drop=True)
    return sess


# ============================================================
# 累積績效曲線
# ============================================================
def equity_curve(initial_capital: float = 1.0,
                  auto_only: bool = True,
                  use_net: bool = True) -> pd.DataFrame:
    """系統累積資金曲線（依 session exit_date 排序，複利累積）.

    use_net=True 用淨報酬（扣交易成本，反映實戰）；False 用毛報酬.
    回傳 columns: date, equity, session_return_pct, equity_gross
    """
    s = sessions_df(auto_only=auto_only)
    if s.empty:
        return pd.DataFrame(columns=[
            "date", "equity", "equity_gross", "session_return_pct"])
    # 複利累積：淨 vs 毛
    s["factor_net"] = 1 + s["session_return_net_pct"] / 100
    s["factor_gross"] = 1 + s["session_return_pct"] / 100
    s["equity"] = initial_capital * (
        s["factor_net"] if use_net else s["factor_gross"]).cumprod()
    s["equity_gross"] = initial_capital * s["factor_gross"].cumprod()
    out_col = "session_return_net_pct" if use_net else "session_return_pct"
    return s[["exit_date", "equity", "equity_gross", out_col]].rename(
        columns={"exit_date": "date", out_col: "session_return_pct"})


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
# 風險調整指標 (Sharpe / Sortino / Profit Factor)
# ============================================================
RISK_FREE_ANNUAL = 0.02   # 台灣 1 年期定存約 1.5-2%
TRADES_PER_YEAR_BASE = 50  # 5 日持有平均 ≈ 50 趟/年（用於年化）


def risk_metrics(initial_capital: float = 1.0,
                  auto_only: bool = True,
                  use_net: bool = True) -> dict:
    """計算風險調整指標.

    use_net=True 用淨報酬（扣交易成本，反映真實風險回報）

    Returns dict:
      sharpe: Sharpe Ratio（年化，越大越好；> 1.0 算好；> 2.0 優秀）
      sortino: Sortino Ratio（只懲罰下行波動；> 1.5 算好）
      profit_factor: 毛利 / 毛損（> 1.5 算好；> 2.0 很好）
      max_consec_loss: 最長連續虧損次數
      avg_hold_days: 平均持有天數（用於年化）
      n_trades: 樣本數（< 30 統計上無意義）
    """
    h = holdings_df(auto_only=auto_only)
    if h.empty:
        return {
            "sharpe": 0.0, "sortino": 0.0,
            "profit_factor": 0.0,
            "max_consec_loss": 0, "avg_hold_days": 0,
            "n_trades": 0,
        }
    col = "return_net_pct" if use_net else "return_pct"
    returns = h[col].astype(float)
    avg_hold = float(h["hold_days"].mean()) if "hold_days" in h.columns else 5.0
    # 年化趟數：250 交易日 / 平均持有日數
    trades_per_year = 250 / max(avg_hold, 1)
    rf_per_trade = RISK_FREE_ANNUAL / trades_per_year * 100  # %
    excess = returns - rf_per_trade

    # Sharpe（年化）
    std_ret = float(returns.std()) if len(returns) > 1 else 0
    sharpe = (
        float(excess.mean()) / std_ret * (trades_per_year ** 0.5)
        if std_ret > 0 else 0.0
    )
    # Sortino — 只用下行波動
    downside = returns[returns < rf_per_trade]
    downside_std = float(downside.std()) if len(downside) > 1 else 0
    sortino = (
        float(excess.mean()) / downside_std * (trades_per_year ** 0.5)
        if downside_std > 0 else 0.0
    )
    # Profit Factor
    wins = returns[returns > 0].sum()
    losses = abs(returns[returns < 0].sum())
    profit_factor = float(wins / losses) if losses > 0 else float("inf")

    # 最長連續虧損
    is_loss = (returns <= 0).astype(int).tolist()
    max_consec = 0
    cur = 0
    for x in is_loss:
        cur = cur + 1 if x else 0
        max_consec = max(max_consec, cur)

    return {
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "profit_factor": round(profit_factor, 2)
                          if profit_factor != float("inf") else float("inf"),
        "max_consec_loss": max_consec,
        "avg_hold_days": round(avg_hold, 1),
        "n_trades": len(returns),
        "trades_per_year": round(trades_per_year, 1),
    }


# ============================================================
# 頂部 KPIs
# ============================================================
def summary_kpis(initial_capital: float = 1.0,
                  auto_only: bool = True) -> dict:
    """4 個關鍵指標：總報酬（毛/淨）/ 勝率 / 平均單檔報酬 / 最大回撤."""
    h = holdings_df(auto_only=auto_only)
    if h.empty:
        return {
            "n_sessions": 0,
            "n_holdings": 0,
            "total_return_pct": 0.0,
            "total_return_net_pct": 0.0,
            "win_rate": 0.0,
            "win_rate_net": 0.0,
            "avg_return_pct": 0.0,
            "avg_return_net_pct": 0.0,
            "max_dd_pct": 0.0,
            "max_dd_pct_gross": 0.0,
            "max_dd_peak": "",
            "max_dd_trough": "",
            "first_date": None,
            "last_date": None,
        }
    eq_net = equity_curve(initial_capital=initial_capital,
                          auto_only=auto_only, use_net=True)
    dd_net = max_drawdown(eq_net["equity"], eq_net["date"])
    dd_gross = max_drawdown(eq_net["equity_gross"], eq_net["date"])
    total_return_net = (float(eq_net["equity"].iloc[-1])
                        - initial_capital) / initial_capital * 100
    total_return_gross = (float(eq_net["equity_gross"].iloc[-1])
                          - initial_capital) / initial_capital * 100
    win_gross = int((h["return_pct"] > 0).sum())
    win_net = int((h["return_net_pct"] > 0).sum())
    risk = risk_metrics(initial_capital=initial_capital,
                        auto_only=auto_only, use_net=True)
    return {
        "n_sessions": h["session_id"].nunique(),
        "n_holdings": len(h),
        "total_return_pct": total_return_gross,
        "total_return_net_pct": total_return_net,
        "win_rate": win_gross / len(h) * 100,
        "win_rate_net": win_net / len(h) * 100,
        "avg_return_pct": float(h["return_pct"].mean()),
        "avg_return_net_pct": float(h["return_net_pct"].mean()),
        "max_dd_pct": dd_net.max_dd_pct,
        "max_dd_pct_gross": dd_gross.max_dd_pct,
        "max_dd_peak": dd_net.peak_date,
        "max_dd_trough": dd_net.trough_date,
        "first_date": pd.Timestamp(h["lock_date"].min()).strftime("%Y-%m-%d"),
        "last_date": pd.Timestamp(h["exit_date"].max()).strftime("%Y-%m-%d"),
        # Risk-adjusted（淨）
        "sharpe": risk["sharpe"],
        "sortino": risk["sortino"],
        "profit_factor": risk["profit_factor"],
        "max_consec_loss": risk["max_consec_loss"],
        "avg_hold_days": risk["avg_hold_days"],
    }
