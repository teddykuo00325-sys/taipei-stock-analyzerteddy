"""每日報告組合器 — 把選股 / regime / ETF 變化 / 實盤回測編成 TG 訊息.

對外 API:
    build_daily_report() -> str   組合 HTML 格式報告
    send_daily_report()  -> (ok, msg)  組合 + 發送
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import (backtest_filter, dca_alert, disposal, etf, etf_scraper,
               etf_signal, marketdata, performance, realbacktest, screener,
               telegram_notify, us_market)


# 台北時區 (UTC+8) — 確保 GitHub Actions / 雲端 cron 跑時用台灣時間
TPE_TZ = timezone(timedelta(hours=8))


def _now_tpe() -> datetime:
    """取得當前台北時間（GH Actions UTC 也對）."""
    return datetime.now(TPE_TZ)


DISCLAIMER = (
    "<i>⚠️ 本系統不提供任何具體的股票、基金、虛擬貨幣等投資買賣建議。"
    "所有內容僅為客觀資訊分享，投資理財具有潛在風險，"
    "任何決策皆須自行評估並自負盈虧。</i>"
)


def _section_regime() -> str:
    r = backtest_filter.detect_regime()
    # 額外標記「tiebreaker 動態權重」資訊
    weight_note = {
        "bull":     "強多頭 → tiebreaker 重「不過熱+甜蜜起漲」",
        "bear":     "強空頭 → tiebreaker 重「動能+爆量」",
        "sideways": "整理 → tiebreaker 多空中性權重",
    }.get(r.label, "")
    return (f"📊 <b>大盤 regime</b>：{r.label_zh}\n"
            f"   TWII <b>{r.twii_close:,.0f}</b> ｜ "
            f"MA20-MA60 差 {r.ma_gap_pct:+.1f}%\n"
            f"   <i>{r.note}</i>\n"
            f"   <i>⚙️ {weight_note}</i>")


def _section_dca_alerts() -> str:
    """0050 / 2330 撿便宜警示 — 即使未觸發也顯示「續抱觀察」一行."""
    try:
        alerts = dca_alert.evaluate_targets()
    except Exception:
        return ""
    if not alerts:
        return ""
    lines = ["\n💰 <b>長期持股撿便宜訊號</b>"]
    for a in alerts:
        if a.level == "NONE":
            # 簡短一行：⚪ 標的 現價 + 回檔% + RSI
            lines.append(a.note + f"\n   <i>📝 {a.suggestion}</i>")
        else:
            lines.append(a.note)
            lines.append(f"   <i>📝 {a.suggestion}</i>")
    return "\n".join(lines)


def _section_us_market() -> str:
    """🇺🇸 美股關鍵指標 + 巨頭 + 跟台股相關性."""
    try:
        data = us_market.fetch_us_market()
    except Exception:
        return ""
    indices = data.get("indices", [])
    giants = data.get("giants", [])
    if not indices and not giants:
        return ""

    lines: list[str] = []
    last_date = data.get("last_date", "")
    lines.append(f"\n🇺🇸 <b>美股關鍵指標</b>"
                 + (f"（{last_date} 收盤）" if last_date else ""))

    # 指數
    for q in indices:
        arrow = "🔴" if q.change_pct >= 0 else "🟢"
        # VIX 是反向：上漲代表恐慌升高（給綠標）
        if q.symbol == "^VIX":
            arrow = "🟢" if q.change_pct >= 0 else "🔴"
        lines.append(
            f"   {arrow} {q.label}　<b>{q.price:,.2f}</b>　"
            f"({q.change_pct:+.2f}%)　<i>{q.correlation}</i>"
        )

    # 相關性 hint（費半 vs 台積電 30 日）
    corr = data.get("correlation", {})
    if "sox_vs_2330_30d" in corr:
        c = corr["sox_vs_2330_30d"]
        sox_q = next((q for q in indices if q.symbol == "^SOX"), None)
        if sox_q:
            interp = "高度同步" if abs(c) > 0.7 else \
                     "中度相關" if abs(c) > 0.4 else "弱相關"
            sox_dir = "漲" if sox_q.change_pct > 0 else "跌"
            tsmc_hint = ("偏多" if c > 0.4 and sox_q.change_pct > 0 else
                         "偏空" if c > 0.4 and sox_q.change_pct < 0 else
                         "中性")
            lines.append(
                f"   <i>📌 費半 vs 台積電 30 日相關 "
                f"<b>{c:+.2f}</b>（{interp}）；費半{sox_dir}"
                f" → 預期 2330 開盤 <b>{tsmc_hint}</b></i>"
            )

    # 巨頭
    if giants:
        lines.append(f"\n🦾 <b>美股巨頭</b>")
        for q in giants:
            arrow = "🔴" if q.change_pct >= 0 else "🟢"
            # > ±1.5% 加 ⭐ 標重大異動
            star = " ⭐" if abs(q.change_pct) >= 1.5 else ""
            lines.append(
                f"   {arrow} {q.icon} {q.label}　"
                f"<b>${q.price:,.2f}</b>　"
                f"({q.change_pct:+.2f}%){star}　<i>{q.correlation}</i>"
            )

    return "\n".join(lines)


def _section_commodities() -> str:
    """國際商品 + 展寬貴金屬牌價."""
    lines: list[str] = []
    # === 國際商品（yfinance + stooq）===
    try:
        intl = marketdata.fetch_international()
    except Exception:
        intl = {}
    if intl:
        lines.append("\n💎 <b>國際商品行情</b>")
        # 取我們要的 4 個 + 匯率
        order = [
            ("gold",    "🥇 黃金",    "USD/oz"),
            ("silver",  "🥈 白銀",    "USD/oz"),
            ("brent",   "🛢 布蘭特",  "USD"),
            ("wti",     "🛢 西德州",  "USD"),
            ("usd_twd", "💵 美元/台幣", ""),
            ("jpy_twd", "💴 日圓/台幣", ""),
        ]
        for key, label, unit in order:
            q = intl.get(key)
            if not q:
                continue
            arrow = "🔴" if q.change >= 0 else "🟢"
            unit_str = f" {unit}" if unit else ""
            lines.append(
                f"   {arrow} {label}　<b>{q.price:,.{q.precision}f}</b>"
                f"{unit_str}　"
                f"({q.change:+.{q.precision}f} / {q.change_pct:+.2f}%)"
            )

    # === 展寬貴金屬當日回收牌價 (gck99.com.tw) ===
    try:
        gck = marketdata.fetch_gck99()
    except Exception:
        gck = {}
    if gck:
        valid = {k: v for k, v in gck.items()
                 if not k.startswith("_") and v != "N/A"}
        if valid:
            lines.append("\n💰 <b>展寬貴金屬當日回收牌價</b>")
            for k, v in valid.items():
                lines.append(f"   • <b>{k}</b>：{v}")

    return "\n".join(lines)


# 常見 ETF / 標的硬編碼 fallback（最後一道保險）
_HARDCODED_NAMES = {
    "0050": "元大台灣50",
    "0052": "富邦科技",
    "0055": "元大MSCI金融",
    "0056": "元大高股息",
    "006203": "元大MSCI台灣",
    "006208": "富邦台50",
    "00679B": "元大美債20年",
    "00692": "富邦公司治理",
    "00713": "元大台灣高息低波",
    "00878": "國泰永續高股息",
    "00881": "國泰台灣5G+",
    "00891": "中信關鍵半導體",
    "00892": "富邦台灣半導體",
    "00935": "野村臺灣優選",
    # 主動式 ETF
    "00980A": "野村臺灣優選",
    "00981A": "主動統一台股增長",
    "00982A": "主動群益台灣強棒",
    "00988A": "主動全球創新",
    "00990A": "主動中信臺灣 AI 新經濟",
    "00991A": "主動復華未來 50",
    "00992A": "主動群益科技創新",
    "00993A": "主動安聯台灣",
    "00997A": "主動國泰美國成長",
}


def _resolve_name(code: str, fallback_name: str) -> str:
    """四層名稱 fallback：
    fallback_name 非 code → 用它；
    否則查 industry.db；
    再查 etf_aum；
    再查 hardcoded ETF dict；
    都失敗 → code。
    """
    code = str(code).strip()
    if fallback_name and fallback_name != code:
        return fallback_name
    # 1. industry (含 industry.db DB fallback)
    try:
        from . import industry as _ind
        info = _ind.info_for(code)
        if info and info.get("short_name"):
            nm = str(info["short_name"]).strip()
            if nm and nm != code:
                return nm
    except Exception:
        pass
    # 2. ETF 從 etf_aum 表
    try:
        from . import etf as _etf
        with _etf._db_lock, _etf._conn() as c:
            r = c.execute(
                "SELECT name FROM etf_aum WHERE code=? "
                "ORDER BY date DESC LIMIT 1",
                (code,),
            ).fetchone()
        if r and r[0]:
            nm = str(r[0]).strip()
            if nm and nm != code:
                return nm
    except Exception:
        pass
    # 3. Hardcoded ETF（最後保險）
    if code in _HARDCODED_NAMES:
        return _HARDCODED_NAMES[code]
    return code


# 模組級快取：_section_picks 算完的 picks，供 send_daily_report 之後 auto-lock
_LAST_PICKS: dict = {
    "long": [], "short": [],
    "long_hold_days": 5, "short_hold_days": 5,
    "long_capital_scale": 1.0, "short_capital_scale": 1.0,
    "long_proceed": False, "short_proceed": False,
}


def _section_picks(top_n: int = 5) -> str:
    """跑當前選股，列出 long / short top N."""
    try:
        res = screener.screen(
            min_avg_volume_lots=1000,
            top_n=max(top_n * 3, 15),  # 多取讓 filter 篩
            pre_filter_lots_today=200,
        )
    except Exception as e:
        return f"⚠️ 選股失敗：{str(e)[:100]}"
    if res["passed"] == 0:
        return "⚠️ 今日無通過篩選的股票"

    ind_map = res.get("industry_map", {})
    long_raw = res["long"].to_dict("records")
    short_raw = res["short"].to_dict("records")

    rep_l = backtest_filter.apply_all_filters(
        "long", long_raw, industry_map=ind_map)
    rep_s = backtest_filter.apply_all_filters(
        "short", short_raw, industry_map=ind_map)

    # 緩存到模組級供之後 auto-lock 使用
    _LAST_PICKS["long"] = (
        list(rep_l.picks_filtered[:top_n]) if rep_l.proceed else [])
    _LAST_PICKS["short"] = (
        list(rep_s.picks_filtered[:top_n]) if rep_s.proceed else [])
    _LAST_PICKS["long_hold_days"] = rep_l.hold_days or 5
    _LAST_PICKS["short_hold_days"] = rep_s.hold_days or 5
    _LAST_PICKS["long_capital_scale"] = rep_l.capital_scale or 1.0
    _LAST_PICKS["short_capital_scale"] = rep_s.capital_scale or 1.0
    _LAST_PICKS["long_proceed"] = rep_l.proceed
    _LAST_PICKS["short_proceed"] = rep_s.proceed

    def _fmt_pick(i: int, p: dict) -> str:
        code = str(p['代號'])
        name = _resolve_name(code, str(p.get('名稱', code)))
        # 含 ETF 動作標籤（從 _etf_signal 取得）
        etf_tag = etf_signal.format_signal_for_tg(p.get('_etf_signal'))
        return (f"   {i}. <b>{code} {name}</b>　"
                f"收 {p['收盤']:.2f}　評分 {p['分數']}"
                + etf_tag)

    lines = []
    if rep_l.proceed:
        n_l = len(rep_l.picks_filtered[:top_n])
        lines.append(f"\n🚀 <b>系統推薦做多 Top {n_l}</b>"
                     f"（已套 5 層過濾）")
        for i, p in enumerate(rep_l.picks_filtered[:top_n], 1):
            lines.append(_fmt_pick(i, p))
    else:
        lines.append(f"\n🚫 <b>做多：</b>{rep_l.skip_reason}")

    if rep_s.proceed:
        n_s = len(rep_s.picks_filtered[:top_n])
        lines.append(f"\n🐻 <b>系統推薦做空 Top {n_s}</b>"
                     f"（已套 5 層過濾）")
        for i, p in enumerate(rep_s.picks_filtered[:top_n], 1):
            lines.append(_fmt_pick(i, p))
    else:
        lines.append(f"\n🚫 <b>做空：</b>{rep_s.skip_reason}")
    return "\n".join(lines)


def _section_disposal() -> str:
    """處置股名單 (20 分鐘揭示，剛進處置 ≤3 日 或 即將開始) + 跌幅 + 驗證.

    僅 **私人版本** 推送顯示。資料源：TWSE openapi/announcement/punish.
    """
    try:
        stocks = disposal.recent_disposals(
            max_days_in=3,
            interval_filter=20,
            include_upcoming=True,
        )
        stocks = disposal.with_price_data(stocks)
    except Exception:
        return ""
    fallback_used = False
    if not stocks:
        try:
            stocks = disposal.recent_disposals(
                max_days_in=3, interval_filter=None,
                include_upcoming=True,
            )
            stocks = disposal.with_price_data(stocks)
            fallback_used = True
        except Exception:
            stocks = []
    if not stocks:
        return ""

    if fallback_used:
        body = ("\n🚨 <b>處置股名單 — 暫無 20 分鐘剛進處置者</b>\n"
                "   <i>近 3 日其他揭示間隔的處置股：</i>\n"
                + disposal.format_for_tg(stocks, header=False, max_n=5))
    else:
        body = disposal.format_for_tg(stocks)

    # 加上「處置 3 日跌 → 後續勝率」驗證一行
    try:
        verify = disposal.verify_hypothesis(
            drop_threshold_pct=-3.0, forward_days_list=(5, 10))
        n_q = verify.get("n_qualified", 0)
        n_total = verify.get("n_total", 0)
        if n_q > 0:
            stats_5 = verify.get("by_forward", {}).get(5, {})
            stats_10 = verify.get("by_forward", {}).get(10, {})
            n5 = stats_5.get("n", 0)
            sig_warn = " ⚠️ 樣本不足" if n5 < 30 else ""
            verify_line = (
                f"\n   <b>🔬 假設驗證</b>（3 日跌 ≥ 3% → Day-3 買進）{sig_warn}"
                f"\n   N={n_q}/{n_total} ｜ "
                f"+5 日 勝率 <b>{stats_5.get('win_rate', 0):.0f}%</b> "
                f"平均 <b>{stats_5.get('avg', 0):+.2f}%</b> ｜ "
                f"+10 日 勝率 <b>{stats_10.get('win_rate', 0):.0f}%</b> "
                f"平均 <b>{stats_10.get('avg', 0):+.2f}%</b>"
            )
            body += verify_line
    except Exception:
        pass
    return body


def _section_capital_allocation() -> str:
    """資金配置建議 — 依當前 regime + Lv4 capital_scale + 推薦檔數.

    ★ 資金規模追蹤累積：若 Track Record 已有資料，base_capital 從
    100 萬 × (1 + 累積淨報酬) 計算，反映「跟隨系統至今實際資金」。

    依賴 _LAST_PICKS 緩存（_section_picks 跑過後才有資料）。
    僅 **私人版本** 推送顯示，不走公開 channel。
    """
    if not (_LAST_PICKS.get("long_proceed") or _LAST_PICKS.get("short_proceed")):
        return ""
    try:
        r = backtest_filter.detect_regime()
    except Exception:
        return ""
    # ★ 累積資金追蹤 — 從 performance.summary_kpis 拿累積淨報酬
    base_capital = 1_000_000
    cap_note = "起始 100 萬"
    try:
        kpi = performance.summary_kpis(initial_capital=1.0)
        if kpi and kpi.get("n_holdings", 0) > 0:
            net_ret = kpi.get("total_return_net_pct", 0)
            new_base = 1_000_000 * (1 + net_ret / 100)
            cap_note = (f"跟系統累積至今 ≈ <b>{new_base/10000:.1f} 萬</b> "
                        f"(原 100 萬 → 淨 {net_ret:+.2f}%)")
            base_capital = new_base
    except Exception:
        pass
    lines = [f"\n💵 <b>資金配置建議</b>（依當前 regime 動態）"]
    lines.append(f"   大盤：{r.label_zh}　基準資金：{cap_note}")

    for side, zh, emoji in (("long", "做多", "🚀"), ("short", "做空", "🐻")):
        proceed = _LAST_PICKS.get(f"{side}_proceed")
        scale = _LAST_PICKS.get(f"{side}_capital_scale", 1.0) or 0.0
        n_picks = len(_LAST_PICKS.get(side) or [])
        hd = _LAST_PICKS.get(f"{side}_hold_days", 5)
        if not proceed or n_picks == 0 or scale <= 0:
            lines.append(f"   {emoji} {zh}：<b>0%</b>（跳過此方向）")
            continue
        side_capital = base_capital * scale
        per_stock = side_capital / n_picks
        lines.append(
            f"   {emoji} {zh}：<b>{scale*100:.0f}%</b> = "
            f"<b>{side_capital/10000:.0f} 萬</b> ｜ "
            f"{n_picks} 檔 → 每檔 <b>{per_stock/10000:.1f} 萬</b> ｜ "
            f"持有 {hd} 日"
        )
    # 整理判斷
    if r.label == "sideways":
        lines.append("   <i>📌 整理盤建議減倉至 50%，多空對沖降風險</i>")
    elif r.label == "bull":
        lines.append("   <i>📌 強多頭可全押多單，空單嚴格停損</i>")
    else:
        lines.append("   <i>📌 強空頭可全押空單，多單嚴格停損</i>")
    return "\n".join(lines)


def _section_track_record() -> str:
    """系統累積績效 — 7 / 30 日 / all-time，僅看 TG 自動 lock 的 closed sessions.

    新增：
    - vs TWII Alpha 對照（同期間加權指數）
    - Sharpe / Profit Factor 風險調整
    - 統計顯著性警示（N<30 標 ⚠️）
    """
    rows = []
    for days, label in [(7, "過去 7 日"), (30, "過去 30 日"),
                         (None, "累積全期")]:
        try:
            tr = realbacktest.track_record(days=days, auto_only=True)
        except Exception:
            tr = None
        if not tr or tr["n_holdings"] == 0:
            rows.append(f"   {label}：<i>累積中</i>")
            continue
        # 統計顯著性符號
        n = tr["n_holdings"]
        sig_mark = "⚠️" if n < 30 else "📊" if n < 100 else "✅"
        rows.append(
            f"   {label}：命中 <b>{tr['win']}/{n}</b> "
            f"({tr['win_rate']:.0f}%) ｜ 平均 <b>{tr['avg_return_pct']:+.2f}%</b>"
            f" ｜ 最佳 {tr['best']:+.1f}% / 最差 {tr['worst']:+.1f}% {sig_mark}"
        )

    # ★ 累積期 alpha vs TWII + Sharpe / PF（只在有資料時顯示）
    extra_lines = []
    try:
        kpi = performance.summary_kpis(initial_capital=1.0)
        if kpi and kpi.get("n_holdings", 0) > 0:
            sys_net = kpi.get("total_return_net_pct", 0)
            # 同期 TWII
            first = kpi.get("first_date")
            last = kpi.get("last_date")
            twii_ret = None
            if first and last:
                bench = performance.twii_benchmark(first, last)
                if not bench.empty:
                    twii_ret = (float(bench["twii_norm"].iloc[-1]) - 1) * 100
            alpha_str = ""
            if twii_ret is not None:
                alpha = sys_net - twii_ret
                alpha_icon = "🔴" if alpha > 0 else "🟢"
                alpha_str = (f"\n   {alpha_icon} 累積 vs TWII：系統 "
                             f"<b>{sys_net:+.2f}%</b> ｜ "
                             f"TWII {twii_ret:+.2f}% ｜ "
                             f"Alpha <b>{alpha:+.2f}%</b>")
            else:
                alpha_str = (f"\n   📈 累積淨報酬：<b>{sys_net:+.2f}%</b>")
            extra_lines.append(alpha_str)
            # 風險調整
            sharpe = kpi.get("sharpe", 0)
            pf = kpi.get("profit_factor", 0)
            pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
            sharpe_icon = "🏆" if sharpe > 1.0 else "⚠️" if sharpe > 0 else "❌"
            extra_lines.append(
                f"   {sharpe_icon} Sharpe <b>{sharpe:.2f}</b> ｜ "
                f"Profit Factor <b>{pf_str}</b> ｜ "
                f"最長連虧 {kpi.get('max_consec_loss', 0)} 次"
            )
    except Exception:
        pass

    # 若三個全 "累積中" → 顯示首次啟動說明
    all_empty = all("累積中" in r for r in rows)
    header = "📊 <b>系統 Track Record</b>（自動追蹤、無人為干預）"
    if all_empty:
        return (f"\n{header}\n"
                + "\n".join(rows)
                + "\n   <i>📝 5 日後首批 session 結算，"
                + "30 個交易日後數字才有統計意義</i>")
    result = f"\n{header}\n" + "\n".join(rows)
    if extra_lines:
        result += "\n" + "\n".join(extra_lines)
    return result


def _section_realbacktest() -> str:
    """進行中的實盤回測 sessions 當前 P&L."""
    sessions = realbacktest.list_sessions(status="open")
    if not sessions:
        return ""
    lines = ["\n📋 <b>進行中實盤回測</b>"]
    for sess in sessions[:6]:   # 最多 6 個避免過長
        try:
            summary = realbacktest.session_summary(sess.id)
        except Exception:
            continue
        if not summary:
            continue
        side_emoji = "🚀" if sess.side == "long" else "🐻"
        pnl_pct = summary.get("total_return_net_pct",
                               summary.get("total_return_pct", 0))
        pnl = summary.get("total_pnl_net", summary.get("total_pnl", 0))
        win = summary.get("win", 0)
        lose = summary.get("lose", 0)
        target = sess.target_exit_date or "—"
        lines.append(
            f"   {side_emoji} #{sess.id} {sess.lock_date}→{target} "
            f"｜ P&L <b>{pnl:+,.0f}</b> ({pnl_pct:+.2f}%) "
            f"｜ 勝 {win} 負 {lose}"
        )
    return "\n".join(lines)


def _section_etf_changes(max_etfs: int = 5) -> str:
    """主動式 ETF 持股變化（最新一日 vs 前一日）."""
    try:
        metas = etf.top_n(max_etfs, taiwan_only=True)
    except Exception as e:
        return f"\n📊 <b>主動式 ETF</b>：抓取失敗 ({str(e)[:60]})"
    if not metas:
        return ("\n📊 <b>主動式 ETF</b>：暫無資料"
                "（yfinance 抓 AUM 失敗 + DB 無快照）")
    lines = ["\n📊 <b>主動式 ETF 持股變化</b>"]
    for m in metas:
        # ETF 名稱 fallback：如果 m.name 等於 code 或是英文長串，
        # 重新查 etf_aum 表取最新中文名
        raw_name = (m.name or "").replace("Active ETF", "").strip()
        if raw_name == m.code or not raw_name or len(raw_name) > 25:
            raw_name = _resolve_name(m.code, raw_name)
        short_name = raw_name[:18] if raw_name != m.code else m.code

        dates = etf.list_holding_dates(m.code)
        if len(dates) < 2:
            lines.append(f"   • {m.code} {short_name}　<i>(僅一日，待累積)</i>")
            continue
        try:
            diff = etf.diff_holdings(m.code, dates[0], dates[1])
        except Exception:
            continue
        if diff.empty:
            continue
        new_in = diff[diff["action"] == "NEW"]
        out = diff[diff["action"] == "OUT"]
        inc = diff[diff["action"] == "+INC"].head(3)
        dec = diff[diff["action"] == "-DEC"].head(3)

        lines.append(f"\n   <b>{m.code} {short_name}</b>　"
                     f"({dates[1]} → {dates[0]})")
        if not new_in.empty:
            names = "、".join(f"{r['stock_code']} {r['stock_name']}"
                              for _, r in new_in.head(4).iterrows())
            lines.append(f"     🆕 新進：{names}")
        if not out.empty:
            names = "、".join(f"{r['stock_code']} {r['stock_name']}"
                              for _, r in out.head(4).iterrows())
            lines.append(f"     ❌ 退出：{names}")
        if not inc.empty:
            top_inc = "、".join(
                f"{r['stock_code']} {r['stock_name']}"
                f"(+{int(r['shares_diff']/1000):,}張)"
                for _, r in inc.iterrows())
            lines.append(f"     📈 加碼：{top_inc}")
        if not dec.empty:
            top_dec = "、".join(
                f"{r['stock_code']} {r['stock_name']}"
                f"({int(r['shares_diff']/1000):,}張)"
                for _, r in dec.iterrows())
            lines.append(f"     📉 減碼：{top_dec}")
    return "\n".join(lines)


def build_daily_report(top_n: int = 5,
                        sections: list[str] | None = None) -> str:
    """組合完整報告.

    sections: 控制要包含哪些區塊，None = 全部
              可選: ['regime', 'picks', 'backtest', 'etf']
    """
    if sections is None:
        # ★ 公開版（送 channel）：不含 track_record / capital_allocation
        # 這兩段只送給「TELEGRAM_CHAT_ID_PRIVATE」個人 chat（見 send_daily_report）
        sections = ["regime", "dca", "us_market", "commodities",
                    "picks", "backtest", "etf"]
    now = _now_tpe()
    weekday_zh = "一二三四五六日"[now.weekday()]
    ts_full = now.strftime("%Y-%m-%d %H:%M")
    parts = [
        f"📅 <b>{ts_full} (星期{weekday_zh}) 台北股市分析器每日報告</b>",
        "━━━━━━━━━━━━━━━━━━━",
    ]
    if "track_record" in sections:
        parts.append(_section_track_record())
    if "capital_allocation" in sections:
        sect = _section_capital_allocation()
        if sect:
            parts.append(sect)
    if "regime" in sections:
        parts.append(_section_regime())
    if "dca" in sections:
        sect = _section_dca_alerts()
        if sect:
            parts.append(sect)
    if "us_market" in sections:
        sect = _section_us_market()
        if sect:
            parts.append(sect)
    if "commodities" in sections:
        sect = _section_commodities()
        if sect:
            parts.append(sect)
    if "picks" in sections:
        parts.append(_section_picks(top_n=top_n))
    if "backtest" in sections:
        sect = _section_realbacktest()
        if sect:
            parts.append(sect)
    if "etf" in sections:
        sect = _section_etf_changes()
        if sect:
            parts.append(sect)
    # 偵測執行環境：GitHub Actions 設 GITHUB_ACTIONS=true
    import os as _os
    is_cloud = (_os.environ.get("GITHUB_ACTIONS") == "true"
                or _os.environ.get("STREAMLIT_RUNTIME_ENV") == "cloud"
                or "/mount/src" in __file__.replace("\\", "/"))
    source_tag = "<i>☁️ 雲端推送</i>\n" if is_cloud else ""
    parts.append(
        "\n━━━━━━━━━━━━━━━━━━━\n"
        + source_tag
        + "<i>by Teddy 中央印製廠_台北股市分析器</i>\n\n"
        + DISCLAIMER
    )
    return "\n".join(parts)


def _auto_lock_today_picks(top_n: int) -> list[str]:
    """把 _LAST_PICKS 緩存的 long / short 推薦 lock 進 realbacktest.

    呼叫前 _section_picks 必須已執行過（緩存才有資料）。
    每邊資金預設 100 萬 × capital_scale（regime-aware）。
    回傳 ['long #123 (5 檔)', ...] log 訊息。
    """
    msgs = []
    base_capital = 1_000_000
    for side in ("long", "short"):
        picks = _LAST_PICKS.get(side) or []
        if not picks or not _LAST_PICKS.get(f"{side}_proceed"):
            continue
        scale = _LAST_PICKS.get(f"{side}_capital_scale", 1.0)
        hold_days = _LAST_PICKS.get(f"{side}_hold_days", 5)
        try:
            sid = realbacktest.lock_session_auto(
                side, picks,
                capital=base_capital * scale,
                hold_days=hold_days,
                note=f"08:30 daily (n={len(picks)}, hold={hold_days}d)",
            )
            if sid is None:
                msgs.append(f"{side}: skip (今日已 lock)")
            else:
                msgs.append(f"{side} #{sid} ({len(picks)} 檔)")
        except Exception as e:
            msgs.append(f"{side} 失敗: {str(e)[:60]}")
    return msgs


def build_private_addendum() -> str:
    """組合「私人加值資訊」訊息 — Track Record + 資金配置.

    這份訊息只送 TELEGRAM_CHAT_ID_PRIVATE，不走公開 channel。
    依賴 _LAST_PICKS 已被 _section_picks 填充（呼叫前需先 build_daily_report）。
    """
    now = _now_tpe()
    parts = [
        f"🔒 <b>{now.strftime('%Y-%m-%d %H:%M')} 私人加值資訊</b>",
        "━━━━━━━━━━━━━━━━━━━",
    ]
    tr = _section_track_record()
    if tr:
        parts.append(tr)
    ca = _section_capital_allocation()
    if ca:
        parts.append(ca)
    disp = _section_disposal()
    if disp:
        parts.append(disp)
    parts.append(
        "\n━━━━━━━━━━━━━━━━━━━\n"
        "<i>🔒 僅本人可見 ｜ 不送公開 channel</i>"
    )
    return "\n".join(parts)


def send_daily_report(top_n: int = 5,
                       sections: list[str] | None = None,
                       auto_fetch_etf: bool = True,
                       auto_track: bool = True) -> tuple[bool, str]:
    """組合並發送每日報告.

    auto_fetch_etf: 發送前先自動抓主動式 ETF 最新持股（True=確保資料最新）。
    auto_track: True 時自動結算到期 session + lock 今日推薦進 realbacktest，
               用於累積 Track Record。

    雙軌推送：
      ◦ 公開 channel（TELEGRAM_CHAT_ID）：行情/regime/推薦/ETF/美股
      ◦ 私人 chat（TELEGRAM_CHAT_ID_PRIVATE）：上面那份 + Track Record + 資金配置
        若 TELEGRAM_CHAT_ID_PRIVATE 未設定，私人部分跳過。
    """
    import os as _os

    # === Phase 0: 處置股快照（累積 disposal_history.db 給長期驗證用）===
    try:
        disposal.snapshot_today()
    except Exception:
        pass

    # === Phase 2: 結算到期 sessions（在算 track record 之前） ===
    expired_log = []
    if auto_track:
        try:
            for sid, n, pnl in realbacktest.auto_close_expired():
                expired_log.append(f"#{sid} n={n} P&L={pnl:+,.0f}")
        except Exception as e:
            expired_log.append(f"auto_close 失敗: {str(e)[:60]}")

    if auto_fetch_etf:
        try:
            metas = etf.top_n(5, taiwan_only=True)
            if metas:
                etf_scraper.fetch_all([m.code for m in metas])
        except Exception:
            pass

    # 1) 公開版 → 預設 TELEGRAM_CHAT_ID（channel）
    public_text = build_daily_report(top_n=top_n, sections=sections)
    ok, msg = telegram_notify.send_long(public_text, parse_mode="HTML")

    # === Phase 1: 公開推送成功 → 自動 lock 今日推薦（須在私人 addendum 前） ===
    lock_log = []
    if ok and auto_track:
        try:
            lock_log = _auto_lock_today_picks(top_n=top_n)
        except Exception as e:
            lock_log.append(f"auto_lock 失敗: {str(e)[:60]}")

    # 2) 私人加值版 → 只送 TELEGRAM_CHAT_ID_PRIVATE
    private_log = []
    private_chat = _os.environ.get("TELEGRAM_CHAT_ID_PRIVATE", "").strip()
    if not private_chat:
        # 也可從 streamlit secrets 讀
        try:
            import streamlit as _st
            private_chat = str(_st.secrets.get("telegram", {})
                                .get("chat_id_private", "")).strip()
        except Exception:
            private_chat = ""
    if ok and private_chat:
        try:
            addendum = build_private_addendum()
            ok_p, msg_p = telegram_notify.send_long_to(
                addendum, private_chat, parse_mode="HTML")
            private_log.append(("✅" if ok_p else "❌") + f" 私人 → {msg_p}")
        except Exception as e:
            private_log.append(f"私人推送 EXC: {str(e)[:60]}")
    elif not private_chat:
        private_log.append("⏭️ 私人推送跳過（未設 TELEGRAM_CHAT_ID_PRIVATE）")

    # 把 auto_track + 私人推送訊息附在回傳 msg 後面（給 GH Actions log 看）
    suffix_parts = []
    if expired_log:
        suffix_parts.append(f"結算 {len(expired_log)}: " + "; ".join(expired_log))
    if lock_log:
        suffix_parts.append(f"鎖入: " + "; ".join(lock_log))
    if private_log:
        suffix_parts.append("; ".join(private_log))
    if suffix_parts:
        msg = (msg or "") + " ｜ " + " ｜ ".join(suffix_parts)

    return ok, msg
