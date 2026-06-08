"""每日報告組合器 — 把選股 / regime / ETF 變化 / 實盤回測編成 TG 訊息.

對外 API:
    build_daily_report() -> str   組合 HTML 格式報告
    send_daily_report()  -> (ok, msg)  組合 + 發送
"""
from __future__ import annotations

from datetime import date

from . import (backtest_filter, etf, etf_scraper, realbacktest,
               screener, telegram_notify)


def _section_regime() -> str:
    r = backtest_filter.detect_regime()
    return (f"📊 <b>大盤 regime</b>：{r.label_zh}\n"
            f"   TWII <b>{r.twii_close:,.0f}</b> ｜ "
            f"MA20-MA60 差 {r.ma_gap_pct:+.1f}%\n"
            f"   <i>{r.note}</i>")


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

    lines = []
    if rep_l.proceed:
        lines.append(f"\n🚀 <b>系統推薦做多 Top {top_n}</b>（已套 5 層過濾）")
        for i, p in enumerate(rep_l.picks_filtered[:top_n], 1):
            lines.append(f"   {i}. <b>{p['代號']} {p['名稱']}</b>　"
                         f"收 {p['收盤']:.2f}　評分 {p['分數']}")
    else:
        lines.append(f"\n🚫 <b>做多：</b>{rep_l.skip_reason}")

    if rep_s.proceed:
        lines.append(f"\n🐻 <b>系統推薦做空 Top {top_n}</b>（已套 5 層過濾）")
        for i, p in enumerate(rep_s.picks_filtered[:top_n], 1):
            lines.append(f"   {i}. <b>{p['代號']} {p['名稱']}</b>　"
                         f"收 {p['收盤']:.2f}　評分 {p['分數']}")
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
        dates = etf.list_holding_dates(m.code)
        if len(dates) < 2:
            short_name = m.name.replace("Active ETF", "").strip()[:18]
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

        short_name = m.name.replace("Active ETF", "").strip()[:18]
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
        sections = ["regime", "picks", "backtest", "etf"]
    today = date.today().strftime("%Y-%m-%d")
    parts = [
        f"📅 <b>{today} 台北股市分析器每日報告</b>",
        "━━━━━━━━━━━━━━━━━━━",
    ]
    if "regime" in sections:
        parts.append(_section_regime())
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
    parts.append(
        "\n━━━━━━━━━━━━━━━━━━━\n"
        "<i>by Teddy 中央印製廠_台北股市分析器</i>"
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
