"""選股器 — 批次掃描台股、評分、排名做多/做空前 N.

回傳結構：
  {
    "long": DataFrame,   # top N long（含欄位 _df_tail, _diag）
    "short": DataFrame,  # top N short
    "full": DataFrame,
    "total": int,
    "passed": int,
  }
"""
from __future__ import annotations

from typing import Callable

import pandas as pd
import yfinance as yf

from . import (candlestick, diagnosis, indicators, institutional,
               margin, price_cache, universe)


def _rename(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })


def _score_one(code: str, name: str, df: pd.DataFrame,
               min_avg_volume_lots: int,
               etf_signal: dict | None = None) -> dict | None:
    try:
        df = _rename(df).dropna()
        if len(df) < 60:
            return None
        avg_vol = float(df["volume"].tail(20).mean())
        if avg_vol < min_avg_volume_lots * 1000:
            return None
        dff = indicators.add_all(df)
        # 選股批次：detailed=False 節省 scan_history + multi_sr 時間
        d = diagnosis.diagnose(dff, code=code,
                               include_chips=True, detailed=False)
        last = dff.iloc[-1]
        prev = dff.iloc[-2]
        # 量價簡述
        vol_brief = d.volume_note.split("（")[0] if "（" in d.volume_note else d.volume_note
        # 法人簡述
        inst = d.institutional_info
        inst_brief = "—"
        if inst:
            total_lots = inst["total_net"] // 1000
            inst_brief = f"{'+' if total_lots >= 0 else ''}{total_lots:,}"
        # 融資券簡述
        marg = d.margin_info
        marg_brief = "—"
        if marg:
            marg_brief = f"融資{marg['margin_change_pct']:+.1f}% 券{marg['short_change_pct']:+.1f}%"
        return {
            "代號": code,
            "名稱": name,
            "收盤": round(float(last["close"]), 2),
            "漲跌%": round((last["close"] / prev["close"] - 1) * 100, 2),
            "分數": d.score,
            "評估": d.stance,
            "建議": d.action,
            "均線": d.ma_state,
            "量價": vol_brief,
            "波浪": d.wave_label,
            "葛蘭碧": (f"#{d.granville.last_signal.rule} "
                       f"{d.granville.last_signal.name}"
                       if (getattr(d, "granville", None) and
                           d.granville.last_signal) else "—"),
            "KD": f"{last['k']:.0f}/{last['d']:.0f}",
            "RSI": round(float(last["rsi"]), 1),
            "法人(張)": inst_brief,
            "融資/券": marg_brief,
            "Hurst": round(d.econ.hurst, 2) if d.econ else None,
            "費波": d.fib.nearest.name if (d.fib and d.fib.nearest
                                             and d.fib.nearest_distance_pct <= 2.5)
                   else "—",
            "日均量(張)": int(avg_vol / 1000),
            "目標價": round(d.target_price, 2) if d.target_price else None,
            "短線停損": round(d.short_stop, 2) if d.short_stop else None,
            "風報比": d.risk_reward,
            "_df_tail": dff.tail(90).copy(),
            "_diag": d,
            # 選股列表只標最近 5 根轉折就夠（lookback=30 省時）
            "_patterns_hist": candlestick.scan_history(dff, lookback=30),
            "_in_entry_zone": bool(
                d.entry_zone and d.entry_zone[0] <= float(last["close"])
                <= d.entry_zone[1]
            ),
            # tiebreaker 分數（同分時 3 天勝率排序用，含 ETF 動向 + 籌碼）
            "Tiebreak": _compute_tiebreak(dff, d, etf_signal=etf_signal,
                                            stock_code=code),
            # 把 ETF signal 也存進 row，供 daily_report / app 顯示用
            "_etf_signal": etf_signal,
        }
    except Exception:
        return None


def _compute_tiebreak(df, diag, etf_signal: dict | None = None,
                       stock_code: str | None = None) -> int:
    """計算多方 tiebreak（screener 主要用 long-side ranking）.

    etf_signal: 該股在前 5 大主動式 ETF 的動作分數 (第 8 維 H)
    stock_code: 用於查 chip_concentration (第 9 維 I)
    """
    try:
        from . import tiebreaker
        return tiebreaker.compute(df, diag, etf_signal=etf_signal,
                                    stock_code=stock_code).total
    except Exception:
        return 0


def _fetch_batch(tickers: list[str], period: str) -> pd.DataFrame | None:
    try:
        return yf.download(
            tickers, period=period, interval="1d",
            auto_adjust=False, progress=False, threads=True,
            group_by="ticker",
        )
    except Exception:
        return None


def _load_from_cache(code: str, period: str) -> pd.DataFrame | None:
    """從 price_cache 讀取（欄位已是小寫）."""
    try:
        df = price_cache.get(code, period=period)
        if df.empty:
            return None
        return df
    except Exception:
        return None


def _score_one_at_date(code: str, name: str, df_full: pd.DataFrame,
                        as_of_date: str,
                        min_avg_volume_lots: int) -> dict | None:
    """歷史回測版 _score_one：把 df 截斷到 as_of_date 之前再評分.

    跳過 chip 資料（institutional / margin / shareholders 都是 current-only）。
    Tiebreak 用 as_of_date 當下的 regime（避免回測 2025 空頭卻套今天多頭權重）。
    """
    try:
        cutoff = pd.Timestamp(as_of_date)
        df = df_full[df_full.index <= cutoff]
        if len(df) < 60:
            return None
        # 確認 as_of_date 當天附近 ±3 日內有交易（否則該股當時可能未上市/停牌）
        recent_dates = df.index[-5:]
        if (cutoff - recent_dates[-1]).days > 7:
            return None  # 最近一筆距 as_of_date 超過一週 → 該日無效
        avg_vol = float(df["volume"].tail(20).mean())
        if avg_vol < min_avg_volume_lots * 1000:
            return None
        dff = indicators.add_all(df)
        d = diagnosis.diagnose(dff, code=code,
                               include_chips=False, detailed=False)
        last = dff.iloc[-1]
        prev = dff.iloc[-2] if len(dff) >= 2 else last
        return {
            "代號": code,
            "名稱": name,
            "收盤": round(float(last["close"]), 2),
            "漲跌%": round((last["close"] / prev["close"] - 1) * 100, 2)
                       if prev["close"] else 0,
            "分數": d.score,
            "評估": d.stance,
            "建議": d.action,
            "均線": d.ma_state,
            "波浪": d.wave_label,
            "KD": f"{last['k']:.0f}/{last['d']:.0f}",
            "RSI": round(float(last["rsi"]), 1),
            "日均量(張)": int(avg_vol / 1000),
            "葛蘭碧": (f"#{d.granville.last_signal.rule} "
                       f"{d.granville.last_signal.name}"
                       if (getattr(d, "granville", None) and
                           d.granville.last_signal) else "—"),
            "目標價": round(d.target_price, 2) if d.target_price else None,
            "短線停損": round(d.short_stop, 2) if d.short_stop else None,
            # 關鍵：tiebreak 用 as_of_date 當下 regime（不是今天）
            "Tiebreak": _compute_tiebreak_at(dff, d, as_of_date),
        }
    except Exception:
        return None


def _compute_tiebreak_at(df, diag, as_of_date: str) -> int:
    """歷史回測版 tiebreak — 用 as_of_date 當下的 regime."""
    try:
        from . import tiebreaker, backtest_filter
        regime = backtest_filter.detect_regime(
            as_of_date=as_of_date).label
        return tiebreaker.compute(df, diag, regime=regime).total
    except Exception:
        return 0


def screen_historical(
    as_of_date: str,
    min_avg_volume_lots: int = 1000,
    top_n: int = 5,
    pre_filter_lots_today: int = 200,
    progress_cb=None,
    limit: int | None = None,
) -> dict:
    """以 as_of_date 那天的 K 線為基準跑選股（歷史回測用）.

    使用 price_cache 既有資料；不會去 yfinance 取新資料。
    回傳結構同 screen()，但無 _diag/_df_tail（簡化）。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from . import industry as _ind

    # ★ 關鍵修正：不用 universe.snapshot()（那是今天的）
    # 改從 ohlcv 表查「as_of_date 之前最後一個交易日」每檔的交易量
    # 並擋掉 as_of_date 當下未上市 / 停牌的股票
    with price_cache._lock, price_cache._conn() as c:
        # 每個 code 取 as_of_date 之前最近 20 日的均量
        rows = c.execute("""
            SELECT code, AVG(volume) as avg_vol, COUNT(*) as n,
                   MAX(date) as last_dt
            FROM ohlcv
            WHERE date <= ? AND date >= date(?, '-40 days')
            GROUP BY code
            HAVING COUNT(*) >= 15 AND AVG(volume) >= ?
                   AND MAX(date) >= date(?, '-7 days')
        """, (as_of_date, as_of_date,
              pre_filter_lots_today * 1000, as_of_date)).fetchall()
    if not rows:
        return {"long": pd.DataFrame(), "short": pd.DataFrame(),
                "full": pd.DataFrame(),
                "total": 0, "passed": 0,
                "as_of_date": as_of_date,
                "industry_map": {}}
    # 排序：as_of_date 當下日均量 desc
    rows.sort(key=lambda r: r[1], reverse=True)
    if limit:
        rows = rows[:limit]
    codes = [r[0] for r in rows]
    # 一次拉 industry（給 names + industry_map 兩用）
    names: dict = {}
    industry_map: dict = {}
    try:
        ind_df = _ind.snapshot()
        if not ind_df.empty:
            name_map = dict(zip(ind_df["code"].astype(str),
                                 ind_df["short_name"].astype(str)))
            industry_map = dict(zip(
                ind_df["code"].astype(str),
                ind_df["industry"].fillna("未分類").astype(str)))
            for c in codes:
                names[c] = name_map.get(c, c)
    except Exception:
        pass
    if not names:
        names = {c: c for c in codes}
    total = len(codes)

    if progress_cb:
        progress_cb(0.01, f"從快取載入 {total} 檔 K 線（截至 {as_of_date}）…")

    # 並行載入 cache + 評分
    results: list[dict] = []
    done = 0

    def _process(code: str) -> dict | None:
        try:
            df = price_cache._load(code)
            if df is None or df.empty:
                return None
            return _score_one_at_date(
                code, names.get(code, code), df, as_of_date,
                min_avg_volume_lots)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_process, c): c for c in codes}
        for fut in as_completed(futures):
            done += 1
            if progress_cb and done % 50 == 0:
                progress_cb(0.05 + (done / max(total, 1)) * 0.90,
                            f"分析 {done}/{total}…")
            row = fut.result()
            if row:
                results.append(row)

    if progress_cb:
        progress_cb(1.0, f"完成：{len(results)} 檔通過篩選")

    full_df = pd.DataFrame(results)
    # 加上產業欄位（給 Lv3 過濾用）
    if not full_df.empty:
        full_df["產業"] = full_df["代號"].astype(str).map(
            industry_map).fillna("未分類")
    if full_df.empty:
        return {"long": full_df, "short": full_df, "full": full_df,
                "total": total, "passed": 0,
                "as_of_date": as_of_date,
                "industry_map": industry_map}
    # 歷史回測也用 Tiebreak 排序（同分用 3 天勝率代理指標）
    if "Tiebreak" not in full_df.columns:
        full_df["Tiebreak"] = 0
    long_top = full_df.sort_values(
        by=["分數", "Tiebreak"], ascending=[False, False]
    ).head(top_n).reset_index(drop=True)
    short_top = full_df.sort_values(
        by=["分數", "Tiebreak"], ascending=[True, True]
    ).head(top_n).reset_index(drop=True)
    return {
        "long": long_top, "short": short_top, "full": full_df,
        "total": total, "passed": len(full_df),
        "as_of_date": as_of_date,
        "industry_map": industry_map,
    }


def screen(
    min_avg_volume_lots: int = 1000,
    top_n: int = 20,
    period: str = "6mo",
    pre_filter_lots_today: int = 200,
    chunk_size: int = 40,
    progress_cb: Callable[[float, str], None] | None = None,
    limit: int | None = None,
    skip_yfinance_warm: bool = False,
) -> dict:
    """選股器主入口.

    skip_yfinance_warm=True 時跳過 bulk_prepare 的 yfinance 增量更新，
    純用 price_cache 既有資料。給雲端 cron 用 — Yahoo 對 GH Actions IP
    擋下時，硬抓會 timeout 累積到 15+ 分鐘導致 workflow 被 cancel。
    """
    # 雲端自動偵測：GitHub Actions 環境強制 skip
    import os as _os
    if _os.environ.get("GITHUB_ACTIONS") == "true":
        skip_yfinance_warm = True
    # ★ Cloud breadcrumb — 雲端 cron debug 用，雲端 picks 慢時可定位
    import os as _osc, time as _tc
    _is_cloud_dbg = _osc.environ.get("GITHUB_ACTIONS") == "true"
    def _sc_bc(msg):
        if _is_cloud_dbg:
            print(f"[screener] {_tc.strftime('%H:%M:%S')} {msg}", flush=True)

    _sc_bc("universe.snapshot start")
    snap = universe.snapshot()
    _sc_bc(f"universe.snapshot done, raw={len(snap)}")
    if pre_filter_lots_today > 0:
        snap = snap[snap["TradeVolume"] >= pre_filter_lots_today * 1000]
    snap = snap.sort_values("TradeVolume", ascending=False).reset_index(drop=True)
    # ★ 雲端自動 limit — GH Actions runner 偶爾 5-10x 慢，跑 1200+ 檔
    # 會超過 60 分鐘 timeout（06-30 實證）. 限前 300 檔（依成交量降序）
    # 仍涵蓋所有主流股 + 中型熱門，picks 品質影響有限
    if _is_cloud_dbg and (limit is None or limit > 300):
        snap = snap.head(300)
        _sc_bc(f"cloud auto-limit applied: codes={len(snap)} (max 300)")
    elif limit:
        snap = snap.head(limit)
    _sc_bc(f"pre-filter done, codes={len(snap)}")

    # 預抓法人 & 融資券 快照（共用快取）
    if progress_cb:
        progress_cb(0.01, "抓取三大法人 & 融資融券快照…")
    _sc_bc("institutional.snapshot start")
    try:
        institutional.snapshot()
    except Exception as e:
        _sc_bc(f"institutional.snapshot ERR: {str(e)[:60]}")
    _sc_bc("margin.snapshot start")
    try:
        margin.snapshot()
    except Exception as e:
        _sc_bc(f"margin.snapshot ERR: {str(e)[:60]}")
    _sc_bc("snapshots done")

    codes = snap["Code"].tolist()
    names = dict(zip(snap["Code"], snap["Name"]))
    total = len(codes)

    # ===== 步驟 0.5：抓主動式 ETF 動作訊號（給 tiebreaker H 維用）=====
    if progress_cb:
        progress_cb(0.015, "抓主動式 ETF 動作訊號（新進/加碼/減碼/退出）…")
    try:
        from . import etf_signal
        etf_sig_map = etf_signal.fetch_etf_signal_map(top_etf_n=5)
    except Exception:
        etf_sig_map = {}

    # ===== 步驟 1：預熱 / 增量更新 price_cache (60% 進度) =====
    def _warm_cb(pct, msg):
        if progress_cb:
            progress_cb(0.02 + pct * 0.60, msg)

    if skip_yfinance_warm:
        # 雲端跳過 yfinance bulk_prepare，純用 cache
        if progress_cb:
            progress_cb(0.05, "雲端模式：跳過 yfinance 增量更新")
        cache_result = {"warmed": 0, "updated": 0, "failed": []}
    else:
        cache_result = price_cache.bulk_prepare(
            codes, warm_period="2y",
            chunk_size=chunk_size, progress_cb=_warm_cb,
        )

    # ===== 步驟 2：自快取讀取並評分（37% 進度）=====
    _sc_bc(f"scoring loop start, n={total}")
    results: list[dict] = []
    for i, code in enumerate(codes):
        if progress_cb and (i % 20 == 0):
            progress_cb(0.62 + (i / max(total, 1)) * 0.37,
                        f"分析 {i + 1} / {total}…")
        # cloud breadcrumb 每 200 檔印一次定位卡哪
        if _is_cloud_dbg and i > 0 and i % 200 == 0:
            _sc_bc(f"scoring progress {i}/{total}, accepted={len(results)}")
        df = _load_from_cache(code, period)
        if df is None:
            continue
        df_upper = df.rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        })
        row = _score_one(code, names.get(code, code),
                         df_upper, min_avg_volume_lots,
                         etf_signal=etf_sig_map.get(code))
        if row:
            results.append(row)
    _sc_bc(f"scoring loop done, accepted={len(results)}")

    if progress_cb:
        progress_cb(1.0, f"分析完成，{len(results)} 檔通過均量篩選")

    # === 自動備份（有顯著變動時，含循環錄影：超過 60 MB 自動刪 1 年前舊資料）===
    new_data = cache_result.get("warmed", 0) + cache_result.get("updated", 0)
    if new_data >= 10:
        try:
            from . import storage
            if storage.is_configured():
                if progress_cb:
                    progress_cb(1.0,
                                f"備份 K 線 DB 至 GitHub（新增 {new_data} 檔）…")
                price_cache.backup_with_rotation(
                    message=f"auto: +{new_data} codes via screener"
                )
        except Exception:
            pass

    # 抓產業 map 給 filter 用
    try:
        from . import industry as _ind
        ind_df = _ind.snapshot()
        industry_map = dict(zip(
            ind_df["code"].astype(str),
            ind_df["industry"].fillna("未分類").astype(str))) \
            if not ind_df.empty else {}
    except Exception:
        industry_map = {}

    full_df = pd.DataFrame(results)
    if not full_df.empty:
        full_df["產業"] = full_df["代號"].astype(str).map(
            industry_map).fillna("未分類")
    if full_df.empty:
        return {"long": full_df, "short": full_df, "full": full_df,
                "total": total, "passed": 0,
                "industry_map": industry_map}
    # 兩級排序：主分數先比，同分時用 Tiebreak（3 天勝率代理指標）
    if "Tiebreak" not in full_df.columns:
        full_df["Tiebreak"] = 0
    long_top = full_df.sort_values(
        by=["分數", "Tiebreak"], ascending=[False, False]
    ).head(top_n).reset_index(drop=True)
    short_top = full_df.sort_values(
        by=["分數", "Tiebreak"], ascending=[True, True]
    ).head(top_n).reset_index(drop=True)
    return {
        "long": long_top, "short": short_top, "full": full_df,
        "total": total, "passed": len(full_df),
        "industry_map": industry_map,
    }
