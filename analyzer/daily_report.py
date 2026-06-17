"""每日報告組合器 — 把選股 / regime / ETF 變化 / 實盤回測編成 TG 訊息.

對外 API:
    build_daily_report() -> str   組合 HTML 格式報告
    send_daily_report()  -> (ok, msg)  組合 + 發送
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import (backtest_filter, dca_alert, etf, etf_scraper,
               marketdata, realbacktest, screener, telegram_notify)


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

    def _fmt_pick(i: int, p: dict) -> str:
        code = str(p['代號'])
        name = _resolve_name(code, str(p.get('名稱', code)))
        return (f"   {i}. <b>{code} {name}</b>　"
                f"收 {p['收盤']:.2f}　評分 {p['分數']}")

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
        sections = ["regime", "dca", "commodities", "picks",
                    "backtest", "etf"]
    now = _now_tpe()
    weekday_zh = "一二三四五六日"[now.weekday()]
    ts_full = now.strftime("%Y-%m-%d %H:%M")
    parts = [
        f"📅 <b>{ts_full} (星期{weekday_zh}) 台北股市分析器每日報告</b>",
        "━━━━━━━━━━━━━━━━━━━",
    ]
    if "regime" in sections:
        parts.append(_section_regime())
    if "dca" in sections:
        sect = _section_dca_alerts()
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


def send_daily_report(top_n: int = 5,
                       sections: list[str] | None = None,
                       auto_fetch_etf: bool = True) -> tuple[bool, str]:
    """組合並發送每日報告.

    auto_fetch_etf: 發送前先自動抓主動式 ETF 最新持股（True=確保資料最新）。
    """
    if auto_fetch_etf:
        try:
            metas = etf.top_n(5, taiwan_only=True)
            if metas:
                etf_scraper.fetch_all([m.code for m in metas])
        except Exception:
            pass

    text = build_daily_report(top_n=top_n, sections=sections)
    ok, msg = telegram_notify.send_long(text, parse_mode="HTML")
    return ok, msg
