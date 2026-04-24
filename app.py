"""台北股市分析器 (Streamlit)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import logging

from analyzer import (chart, data, diagnosis, etf, etf_scraper,
                      indicators, industry, live, marketdata,
                      moneyflow, schools, screener, storage)

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

st.set_page_config(page_title="台北股市分析器", page_icon="📈", layout="wide")

# === 加寬側邊欄 ===
st.markdown("""
<style>
[data-testid="stSidebar"] {
    min-width: 340px !important;
    max-width: 420px !important;
    width: 360px !important;
}
[data-testid="stSidebar"] > div:first-child {
    width: 360px !important;
}
[data-testid="stSidebar"] .stMetric [data-testid="stMetricLabel"] {
    font-size: 13px !important;
}
[data-testid="stSidebar"] .stMetric [data-testid="stMetricValue"] {
    font-size: 18px !important;
}
</style>
""", unsafe_allow_html=True)

# === 阻擋 Chrome 自動翻譯（透過 iframe 操作 parent document）===
import streamlit.components.v1 as _components
_components.html("""
<script>
(function() {
    try {
        var doc = window.parent.document;
        doc.documentElement.lang = 'zh-TW';
        doc.documentElement.setAttribute('translate', 'no');
        doc.documentElement.classList.add('notranslate');
        // 注入 meta 到 parent head
        if (!doc.querySelector('meta[name="google"]')) {
            var m1 = doc.createElement('meta');
            m1.name = 'google';
            m1.content = 'notranslate';
            doc.head.appendChild(m1);
        }
        if (!doc.querySelector('meta[http-equiv="Content-Language"]')) {
            var m2 = doc.createElement('meta');
            m2.httpEquiv = 'Content-Language';
            m2.content = 'zh-TW';
            doc.head.appendChild(m2);
        }
        // 給所有元素加 notranslate class
        var style = doc.createElement('style');
        style.textContent = 'body, body * { translate: no !important; }';
        doc.head.appendChild(style);
    } catch (e) {}
})();
</script>
""", height=0)
DEFAULT_SCHOOL = schools.DEFAULT

ACTION_ICONS = {"強力買進": "🔴🔴", "買進": "🔴", "觀望": "⚪",
                "賣出": "🟢", "強力賣出": "🟢🟢"}


# ============================================================
# 卡片渲染 (今日選股用)
# ============================================================
def render_card(row: pd.Series, rank: int):
    d = row["_diag"]
    df = row["_df_tail"]
    score_icon = "🔴" if d.score > 0 else "🟢" if d.score < 0 else "⚪"
    chg_sign = "+" if row["漲跌%"] >= 0 else ""
    import datetime as _dtk
    now_str = _dtk.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry_str = ""
    if d.entry_zone:
        lo, hi = d.entry_zone
        price_now = row["收盤"]
        if price_now < lo:
            hint = "✅ 低於進場區"
        elif price_now <= hi:
            hint = "✅ 位於進場區"
        else:
            hint = "⚠️ 高於進場區"
        entry_str = f" · 建議進場 {lo:.2f}~{hi:.2f}  {hint}"

    with st.container(border=True):
        st.markdown(
            f"### #{rank}　{row['名稱']} ({row['代號']})　"
            f"<small>現價 {row['收盤']:.2f} ({chg_sign}{row['漲跌%']:.2f}%)　·　"
            f"🕒 {now_str}</small>　"
            f"{score_icon} **分數 {d.score:+d}**　"
            f"{ACTION_ICONS.get(d.action, '')} **{d.action}**{entry_str}",
            unsafe_allow_html=True,
        )

        col_c, col_i = st.columns([3, 3])
        with col_c:
            p_hist = row.get("_patterns_hist") if "_patterns_hist" in row \
                else None
            fig = chart.mini(df, height=180, patterns_hist=p_hist)
            st.plotly_chart(fig, use_container_width=True,
                            key=f"mini_{rank}_{row['代號']}",
                            config={"displayModeBar": False})
        with col_i:
            vol_brief = d.volume_note.split("（")[0] \
                if "（" in d.volume_note else d.volume_note
            fib_nearest = row.get("費波", "—")
            hurst_val = row.get("Hurst")
            hurst_str = f"{hurst_val:.2f}" if hurst_val is not None else "—"
            # 2 欄資訊（3 列 × 2 欄）
            info_l, info_r = st.columns(2)
            with info_l:
                st.markdown(
                    f"**均線**　{d.ma_state}  \n"
                    f"**量價**　{vol_brief}  \n"
                    f"**法人**　{row['法人(張)']} 張  \n"
                    f"**Hurst**　{hurst_str}",
                )
            with info_r:
                st.markdown(
                    f"**波浪**　{d.wave_label}  \n"
                    f"**KD/RSI**　{row['KD']} / {row['RSI']}  \n"
                    f"**融資/券**　{row['融資/券']}  \n"
                    f"**費波**　{fib_nearest}",
                )
            if d.weekly_note:
                st.caption(f"📅 週線　{d.weekly_note.replace('週線', '').strip()}")

        pa = st.columns([2, 2, 2, 2, 2])
        if d.target_price:
            pa[0].metric("目標價", f"{d.target_price:.2f}",
                         f"{(d.target_price / row['收盤'] - 1) * 100:+.1f}%")
        else:
            pa[0].metric("目標價", "—")
        if d.short_stop:
            pa[1].metric("短線停損", f"{d.short_stop:.2f}",
                         f"{(d.short_stop / row['收盤'] - 1) * 100:+.1f}%")
        else:
            pa[1].metric("短線停損", "—")
        if d.risk_reward is not None:
            pa[2].metric("風險報酬比", f"{d.risk_reward:.2f} : 1")
        else:
            pa[2].metric("風險報酬比", "—")
        pa[3].metric("日均量", f"{row['日均量(張)']:,} 張")
        with pa[4]:
            st.write("")  # 對齊 metric 高度
            if st.button("🔎 完整分析", key=f"detail_{rank}_{row['代號']}",
                         use_container_width=True, type="primary"):
                st.session_state.stock_code = str(row["代號"])
                st.session_state.app_mode = "🔎 個股查詢"
                st.session_state.auto_analyze = True
                st.rerun()

        with st.expander("📋 訊號 / 型態 / 診斷詳情"):
            if d.summary:
                st.caption(d.summary)
            st.markdown("**進出場訊號**")
            if d.signals:
                for s in d.signals:
                    ic = {"entry": "🟢 買", "exit": "🔴 賣", "info": "ℹ️"}[s.kind]
                    st.markdown(f"- {ic} **{s.name}** — {s.note}")
            else:
                st.caption("— 無明顯訊號 —")
            if d.chart_patterns:
                st.markdown("**型態**")
                for p in d.chart_patterns:
                    ic = {"bull": "🔴", "bear": "🟢", "neutral": "⚪"}[p.signal]
                    neck = f"（頸線 {p.neckline:.2f}）" if p.neckline else ""
                    st.markdown(f"- {ic} **{p.name}** {neck} — {p.note}")
            if d.candles:
                st.markdown("**K 線型態**")
                for c in d.candles:
                    ic = {"bull": "🔴", "bear": "🟢", "neutral": "⚪"}[c.signal]
                    st.markdown(f"- {ic} **{c.name}** — {c.note}")


# ============================================================
# Sidebar
# ============================================================
st.sidebar.title("📈 台北股市分析器")

if "app_mode" not in st.session_state:
    st.session_state.app_mode = "🎯 今日選股"

mode = st.sidebar.radio(
    "模式",
    ["🎯 今日選股", "🔎 個股查詢", "📊 主動式ETF", "🔥 資金流向"],
    key="app_mode",
    label_visibility="collapsed",
)

st.sidebar.divider()


# ============================================================
# 📊 國際行情 + 💰 展寬貴金屬（放於模式側邊欄選項底部；各模式呼叫）
# ============================================================
def render_market_sidebar():
    import datetime as _dt_sb
    today_str = _dt_sb.date.today().strftime("%Y-%m-%d")
    weekday_str = "一二三四五六日"[_dt_sb.date.today().weekday()]
    st.sidebar.divider()

    # 日期 + 立即更新按鈕同列
    d_col, b_col = st.sidebar.columns([3, 1])
    with d_col:
        st.markdown(
            f"<div style='padding-top:6px; color:#aaa; font-size:13px;'>"
            f"📅 {today_str}　星期{weekday_str}</div>",
            unsafe_allow_html=True,
        )
    with b_col:
        if st.button("🔄", key="market_refresh",
                     help="立即更新國際行情與貴金屬牌價",
                     use_container_width=True):
            marketdata.invalidate()
            st.rerun()

    intl_upd = marketdata.intl_last_update()
    gck_upd = marketdata.gck_last_update()

    with st.sidebar.expander(f"📊 國際行情　(⏱ {intl_upd})", expanded=True):
        try:
            intl = marketdata.fetch_international()
        except Exception as e:
            intl = {}
            st.caption(f"⚠️ 取得失敗：{e}")
        for key in ("gold", "silver", "brent", "wti", "usd_twd", "jpy_twd"):
            q = intl.get(key)
            if q:
                st.metric(
                    q.label,
                    f"{q.price:,.{q.precision}f}",
                    f"{q.change:+.{q.precision}f} ({q.change_pct:+.2f}%)",
                )
        st.caption("每 60 分鐘自動更新，點上方 🔄 手動立即更新")

    with st.sidebar.expander(
            f"💰 展寬貴金屬當日回收牌價　(⏱ {gck_upd})", expanded=False):
        gck = marketdata.fetch_gck99()
        err = gck.get("_err")
        if err:
            st.caption(f"⚠️ {err}")
        for k, v in gck.items():
            if k.startswith("_") or v == "N/A":
                continue
            st.markdown(f"**{k}**  \n`{v}`")
        st.caption("資料來源：gck99.com.tw（每 60 分鐘更新一次快取）")


# ============================================================
# 🎯 今日選股
# ============================================================
if mode == "🎯 今日選股":
    st.sidebar.subheader("篩選條件")
    min_vol = st.sidebar.number_input(
        "最低 20 日均量 (張)", min_value=100, max_value=20000,
        value=1000, step=100,
    )
    top_n = st.sidebar.number_input(
        "前 N 檔", min_value=5, max_value=50, value=20, step=5,
    )
    pre_filter = st.sidebar.number_input(
        "今日最低成交量 (張)", min_value=50, max_value=5000,
        value=200, step=50,
        help="先依今日成交量排除小量股以加速掃描；預設 200 張",
    )
    go_btn = st.sidebar.button("🚀 開始掃描", use_container_width=True, type="primary")

    st.sidebar.caption("💡 首次掃描約 2~5 分鐘；結果保留於 session，切換頁面後返回會繼續顯示")

    render_market_sidebar()

    st.title("📈 台北股市分析器")
    st.caption(f"🎯 今日選股　·　全體上市　·　20 日均量 > {min_vol} 張　·　做多/做空各前 {top_n} 檔")

    # --- Session state 保留結果 ---
    if "screener_result" not in st.session_state:
        st.session_state.screener_result = None
        st.session_state.screener_params = None
        st.session_state.screener_time = None

    if go_btn:
        cur_params = (int(min_vol), int(top_n), int(pre_filter))
        progress_bar = st.progress(0.0, text="初始化…")

        def _cb(pct, msg):
            progress_bar.progress(min(max(pct, 0.0), 1.0), text=msg)

        try:
            result = screener.screen(
                min_avg_volume_lots=int(min_vol),
                top_n=int(top_n),
                pre_filter_lots_today=int(pre_filter),
                progress_cb=_cb,
            )
            st.session_state.screener_result = result
            st.session_state.screener_params = cur_params
            import datetime as _dt
            st.session_state.screener_time = _dt.datetime.now().strftime(
                "%Y-%m-%d %H:%M")
        except Exception as e:
            st.error(f"掃描失敗：{e}")
            st.stop()
        progress_bar.empty()

    result = st.session_state.screener_result
    if result is None:
        st.info("👈 於左側設定條件後按『開始掃描』")
        st.stop()

    # 顯示上次掃描資訊
    if st.session_state.screener_params:
        p = st.session_state.screener_params
        info_col1, info_col2 = st.columns([5, 1])
        with info_col1:
            st.caption(f"📅 掃描時間：{st.session_state.screener_time} · "
                       f"條件：均量 ≥ {p[0]} 張 · Top {p[1]} · 今日粗篩 ≥ {p[2]} 張")
        with info_col2:
            if st.button("🔴 更新盤中價", use_container_width=True,
                         help="以 TWSE MIS 即時報價更新排名檔的價格與漲跌"):
                with st.spinner("更新中…"):
                    all_codes: list[str] = []
                    for key in ("long", "short"):
                        dfp = result.get(key)
                        if dfp is not None and not dfp.empty:
                            all_codes.extend(dfp["代號"].tolist())
                    qs = live.quotes(list(set(all_codes)))
                    for key in ("long", "short", "full"):
                        dfp = result.get(key)
                        if dfp is None or dfp.empty:
                            continue
                        for idx, row in dfp.iterrows():
                            q = qs.get(str(row["代號"]))
                            if q and q.current:
                                dfp.at[idx, "收盤"] = round(q.current, 2)
                                if q.change_pct is not None:
                                    dfp.at[idx, "漲跌%"] = round(q.change_pct, 2)
                    st.session_state.screener_result = result
                st.rerun()

    c1, c2, c3 = st.columns(3)
    c1.metric("已掃描", f"{result['total']} 檔")
    c2.metric("通過均量篩選", f"{result['passed']} 檔")
    c3.metric("做多 / 做空各取", f"{top_n} 檔")

    long_df = result["long"]
    short_df = result["short"]

    tab_long, tab_short, tab_all = st.tabs([
        f"🔴 做多 Top {top_n}",
        f"🟢 做空 Top {top_n}",
        "📋 全部（表格）",
    ])

    def _render_grid(df_):
        """2 欄網格渲染卡片：1 2 / 3 4 / 5 6..."""
        rows = df_.reset_index(drop=True)
        n = len(rows)
        for i in range(0, n, 2):
            col_l, col_r = st.columns(2, gap="small")
            with col_l:
                render_card(rows.iloc[i], i + 1)
            if i + 1 < n:
                with col_r:
                    render_card(rows.iloc[i + 1], i + 2)

    with tab_long:
        if long_df.empty:
            st.warning("無符合條件的做多標的")
        else:
            _render_grid(long_df)

    with tab_short:
        if short_df.empty:
            st.warning("無符合條件的做空標的")
        else:
            _render_grid(short_df)

    with tab_all:
        if result["full"].empty:
            st.info("—")
        else:
            display = result["full"].drop(
                columns=[c for c in ("_df_tail", "_diag") if c in result["full"].columns]
            ).sort_values("分數", ascending=False).reset_index(drop=True)

            def _color_score(v):
                if pd.isna(v):
                    return ""
                try:
                    x = float(v)
                except Exception:
                    return ""
                if x >= 60:
                    return "background-color: rgba(214,39,40,0.55); color: white"
                if x >= 25:
                    return "background-color: rgba(214,39,40,0.30)"
                if x > 0:
                    return "background-color: rgba(214,39,40,0.12)"
                if x <= -60:
                    return "background-color: rgba(44,160,44,0.55); color: white"
                if x <= -25:
                    return "background-color: rgba(44,160,44,0.30)"
                if x < 0:
                    return "background-color: rgba(44,160,44,0.12)"
                return ""

            styled = (
                display.style
                .map(_color_score, subset=["分數"])
                .format({"收盤": "{:.2f}", "漲跌%": "{:+.2f}",
                         "目標價": "{:.2f}", "短線停損": "{:.2f}",
                         "風報比": "{:.2f}"}, na_rep="—")
            )
            st.dataframe(styled, use_container_width=True)


# ============================================================
# 🔥 資金流向 — 產業族群強弱排行
# ============================================================
elif mode == "🔥 資金流向":
    st.title("📈 台北股市分析器")
    st.caption("🔥 資金流向　·　依產業別匯總漲跌與成交值，追蹤族群輪動")

    # === 資料源切換 ===
    source_label = st.sidebar.radio(
        "資料源",
        ["🔴 盤中即時 (MIS)", "📅 前日收盤 (EOD)"],
        index=0,
        help="盤中即時以 TWSE MIS 批次查詢 1000+ 檔，約需 3~6 秒；"
             "前日收盤為昨日結算快照（盤中更新無意義）",
    )
    source = "live" if "盤中" in source_label else "eod"

    sort_key = st.sidebar.selectbox(
        "排序方式",
        ["均漲跌%（強弱）", "成交值（資金量）",
         "上漲家數比", "中位數漲跌%"],
        index=0,
    )
    min_stocks = st.sidebar.slider("每族群最少家數", 2, 10, 3)
    top_n_movers = st.sidebar.slider("族群內顯示漲跌前 N 名", 3, 10, 5)
    refresh = st.sidebar.button("🔄 重新抓取", use_container_width=True)

    render_market_sidebar()

    if refresh:
        from analyzer import universe
        universe._cache["df"] = None
        moneyflow.live._cache.clear() if hasattr(moneyflow.live, "_cache") else None
        st.session_state.pop("mf_result", None)
        st.rerun()

    # Session state key 依資料源 + 最少家數區分
    cache_key = f"mf_{source}_{min_stocks}"
    import datetime as _dt

    if cache_key not in st.session_state:
        progress = st.progress(0.0, text="初始化…")

        def _cb(pct, msg):
            progress.progress(min(max(pct, 0.0), 1.0), text=msg)

        with st.spinner(f"匯總中…（{source_label}）"):
            summary = moneyflow.market_summary(source=source)
            flows = moneyflow.by_industry(
                min_stocks=min_stocks, source=source,
                progress_cb=_cb if source == "live" else None,
            )
        progress.empty()
        st.session_state[cache_key] = {
            "summary": summary, "flows": flows,
            "time": _dt.datetime.now().strftime("%H:%M:%S"),
            "date": _dt.date.today().isoformat(),
        }

    cached = st.session_state[cache_key]
    summary = cached["summary"]
    flows = cached["flows"]

    if not flows:
        st.error("無資料（市場未開盤 / 資料源故障？）")
        st.stop()

    # 標示資料狀態
    src_badge = "🔴 盤中即時" if source == "live" else "📅 前日收盤"
    st.info(f"{src_badge}　·　更新時間 {cached['date']} {cached['time']}")

    # ===== 市場總覽 =====
    s1, s2, s3, s4 = st.columns(4)
    total = summary.get("total_stocks", 0)
    up = summary.get("up", 0)
    dn = summary.get("down", 0)
    s1.metric("上市檔數", f"{total:,}")
    s2.metric("上漲 / 下跌",
              f"{up} / {dn}",
              f"比值 {up / dn:.2f}" if dn else "—")
    s3.metric("市場均漲跌",
              f"{summary.get('avg_change_pct', 0):+.2f}%")
    s4.metric("總成交值",
              f"{summary.get('total_value', 0) / 1e8:,.0f} 億")

    # ===== 排序 =====
    key_fn_map = {
        "均漲跌%（強弱）": lambda f: f.avg_change_pct,
        "成交值（資金量）": lambda f: f.total_value,
        "上漲家數比": lambda f: f.up_count / max(f.count, 1),
        "中位數漲跌%": lambda f: f.median_change_pct,
    }
    flows_sorted = sorted(flows, key=key_fn_map[sort_key], reverse=True)

    # ===== 產業漲幅 Bar chart =====
    import plotly.graph_objects as go
    top_show = flows_sorted[:20]
    colors = ["#d62728" if f.avg_change_pct >= 0 else "#2ca02c"
              for f in top_show]
    bar_fig = go.Figure(go.Bar(
        x=[f.avg_change_pct for f in top_show],
        y=[f.industry for f in top_show],
        orientation="h",
        marker_color=colors,
        text=[f"{f.avg_change_pct:+.2f}% · {f.count}檔 · "
              f"{f.total_value / 1e8:,.0f}億" for f in top_show],
        textposition="auto",
    ))
    bar_fig.update_layout(
        title="產業族群排行",
        height=620, margin=dict(l=10, r=10, t=40, b=10),
        yaxis=dict(autorange="reversed"),
        xaxis_title="平均漲跌 %",
    )
    st.plotly_chart(bar_fig, use_container_width=True)

    # ===== 各產業詳情 =====
    st.subheader("📂 各族群細項")
    for f in flows_sorted:
        icon = "🔴" if f.avg_change_pct > 0.5 else \
               "🟢" if f.avg_change_pct < -0.5 else "⚪"
        title = (f"{icon} **{f.industry}**　"
                 f"{f.avg_change_pct:+.2f}%　·　"
                 f"{f.count} 檔（{f.up_count}漲 / {f.down_count}跌）　·　"
                 f"成交 {f.total_value / 1e8:,.0f} 億")
        with st.expander(title, expanded=(abs(f.avg_change_pct) >= 2)):
            # 族群內漲跌前 N 名
            movers = f.top_movers[:top_n_movers]
            losers = f.top_movers[top_n_movers:top_n_movers * 2]
            gc, lc = st.columns(2)
            with gc:
                st.markdown("##### 🔴 漲幅 Top")
                if movers:
                    m_df = pd.DataFrame(movers).rename(columns={
                        "Code": "代號", "short_name": "名稱",
                        "Change%": "漲跌%", "ClosingPrice": "收盤",
                        "TradeVolume": "成交量",
                    })
                    m_df["成交量(張)"] = (m_df["成交量"] / 1000).astype(int)
                    m_df = m_df.drop(columns=["成交量"])
                    st.dataframe(
                        m_df.style.format({"漲跌%": "{:+.2f}", "收盤": "{:.2f}"}),
                        use_container_width=True, hide_index=True,
                    )
            with lc:
                st.markdown("##### 🟢 跌幅 Top")
                if losers:
                    l_df = pd.DataFrame(losers).rename(columns={
                        "Code": "代號", "short_name": "名稱",
                        "Change%": "漲跌%", "ClosingPrice": "收盤",
                        "TradeVolume": "成交量",
                    })
                    l_df["成交量(張)"] = (l_df["成交量"] / 1000).astype(int)
                    l_df = l_df.drop(columns=["成交量"])
                    st.dataframe(
                        l_df.style.format({"漲跌%": "{:+.2f}", "收盤": "{:.2f}"}),
                        use_container_width=True, hide_index=True,
                    )


# ============================================================
# 📊 主動式ETF 總覽
# ============================================================
elif mode == "📊 主動式ETF":
    render_market_sidebar()

    st.title("📈 台北股市分析器")
    st.caption("📊 主動式 ETF 持股追蹤 — 依資產規模 (AUM) 自動選出前 5 大（台股專注）")

    # === 持久化：首次載入自 GitHub 拉 DB ===
    if storage.is_configured() and "etf_db_restored" not in st.session_state:
        with st.spinner("從雲端同步 ETF 資料庫…"):
            ok, msg = storage.download_db(etf.DB_PATH)
        st.session_state.etf_db_restored = True
        if ok:
            st.caption(f"☁️ 已從 GitHub 還原 ETF DB：{msg}")

    with st.spinner("抓取各 ETF AUM 中…"):
        metas = etf.top_n(5, taiwan_only=True)

    if not metas:
        st.error("無法取得 ETF 資料")
        st.stop()

    # 首次進入自動擷取（資料庫內無資料時）
    codes_list = [m.code for m in metas]
    any_data = any(etf.list_holding_dates(c) for c in codes_list)
    if not any_data and "etf_auto_fetched" not in st.session_state:
        with st.spinner("首次進入：自動從 MoneyDJ 擷取持股…"):
            etf_scraper.fetch_all(codes_list)
        st.session_state.etf_auto_fetched = True
        # 重新載入 meta 以取得最新中文名
        etf._aum_cache["list"] = []
        etf._aum_cache["time"] = 0.0
        metas = etf.top_n(5, taiwan_only=True)

    # Top 5 摘要
    st.subheader("🏆 主動式ETF Top 5 (依 AUM)")
    cols = st.columns(5)
    for i, m in enumerate(metas):
        with cols[i]:
            short = m.name.replace("Active ETF", "").strip()
            st.metric(f"#{i+1} {m.code}",
                      f"{m.aum / 1e8:,.0f} 億",
                      f"NAV {m.nav}")
            st.caption(short[:28])

    # === 持股資料狀態列 ===
    st.markdown("#### 📅 持股資料狀態")
    status_cols = st.columns(len(metas))
    only_one_day = True
    for i, m in enumerate(metas):
        dates = etf.list_holding_dates(m.code)
        with status_cols[i]:
            if not dates:
                st.metric(m.code, "無資料", "—")
            else:
                if len(dates) >= 2:
                    only_one_day = False
                    delta = f"← 對比 {dates[1]}"
                else:
                    delta = "僅一日，待下次擷取後對比"
                st.metric(m.code, f"最新 {dates[0]}", delta,
                          delta_color="off")
    if only_one_day and any(etf.list_holding_dates(c) for c in codes_list):
        st.info("ℹ️ 目前每檔僅有一日資料，下次擷取（建議每交易日收盤後）將可顯示進出比對。")

    st.divider()

    # === 資料庫狀態區 ===
    st.markdown("#### 💾 資料庫狀態")
    info_cols = st.columns(4)
    db_size = etf.db_size_kb()
    info_cols[0].metric("DB 大小", f"{db_size:.1f} KB")
    total_dates = sum(len(etf.list_holding_dates(c)) for c in codes_list)
    info_cols[1].metric("已記錄筆數", f"{total_dates} 日 × {len(codes_list)} ETF")
    storage_cfg = storage.storage_info()
    if storage_cfg.get("configured"):
        info_cols[2].metric("雲端備份", "✅ 啟用",
                            f"{storage_cfg['owner']}/{storage_cfg['repo']}")
    else:
        info_cols[2].metric("雲端備份", "⚠️ 未設定",
                            "資料僅存本機")
    info_cols[3].metric("保留期限", "90 日",
                        "自動清除過期資料")

    if not storage_cfg.get("configured"):
        st.warning(
            "⚠️ **GitHub 持久化未設定** — Streamlit Cloud 重啟會遺失歷史資料。\n\n"
            "設定方式：到 **Streamlit Cloud → Settings → Secrets** 貼上：\n"
            "```toml\n[github]\ntoken = \"ghp_...\"  # 建 PAT 並給 repo 寫入權限\n"
            "owner = \"teddykuo00325-sys\"\nrepo = \"taipei-stock-analyzerteddy\"\n"
            "branch = \"main\"\ndb_path = \"data/etf.db\"\n```"
        )

    # 操作區
    op_col1, op_col2, op_col3 = st.columns(3)
    with op_col1:
        if st.button("🔄 立即擷取所有 ETF 持股", use_container_width=True,
                     type="primary"):
            with st.spinner("向 MoneyDJ 抓取持股中…"):
                results = etf_scraper.fetch_all(codes_list)
            success_any = False
            for code, r in results.items():
                if r.ok:
                    st.success(f"✅ {code} {r.etf_name}：{len(r.holdings)} 檔 @ {r.date}")
                    success_any = True
                else:
                    st.warning(f"⚠️ {code}：{r.error}")
            # 清除過期 + 雲端備份
            if success_any:
                purged = etf.purge_old(days=90)
                if purged:
                    st.info(f"🗑️ 已清除 {purged} 筆 90 日前舊資料")
                if storage_cfg.get("configured"):
                    with st.spinner("備份至 GitHub…"):
                        ok, msg = storage.upload_db(etf.DB_PATH,
                                                    message="auto: ETF holdings update")
                    if ok:
                        st.success(f"☁️ 已備份：{msg}")
                    else:
                        st.warning(f"☁️ 備份失敗：{msg}")
            st.rerun()

    with op_col3:
        if storage_cfg.get("configured") and st.button(
                "☁️ 手動備份 DB", use_container_width=True):
            with st.spinner("上傳中…"):
                ok, msg = storage.upload_db(etf.DB_PATH,
                                            message="manual: backup")
            if ok:
                st.success(f"✅ {msg}")
            else:
                st.error(f"❌ {msg}")

    with op_col2:
        with st.expander("📥 手動匯入 CSV 持股（備援方案）", expanded=False):
            st.caption("CSV 欄位需含：stock_code / stock_name / shares / weight")
            imp_c1, imp_c2 = st.columns(2)
            imp_etf = imp_c1.selectbox("ETF", [f"{m.code} {m.name[:25]}" for m in metas])
            imp_etf_code = imp_etf.split()[0]
            imp_date = imp_c2.date_input("持股日期")
            uploaded = st.file_uploader("選擇 CSV 檔", type=["csv"])
            if uploaded and st.button("📥 匯入", key="etf_import_btn"):
                ok, msg, n = etf_scraper.import_from_csv(
                    imp_etf_code, str(imp_date), uploaded.read(),
                )
                if ok:
                    st.success(f"✅ {imp_etf_code} @ {imp_date}：{msg}")
                else:
                    st.error(f"❌ {msg}")

    st.divider()

    # 每檔 ETF 詳情
    st.subheader("📊 各 ETF 持股 / 變化")
    for m in metas:
        with st.expander(f"{m.code}　{m.name.replace('Active ETF', '').strip()[:40]}　"
                         f"· AUM {m.aum / 1e8:,.0f} 億",
                         expanded=False):
            dates = etf.list_holding_dates(m.code)
            if not dates:
                st.info("🟡 尚無持股資料。請使用上方「手動匯入 CSV」或等待 adapter 實作。")
                continue

            st.caption(f"已記錄日期：{'、'.join(dates[:5])}"
                       + ("…" if len(dates) > 5 else ""))
            latest = dates[0]
            sub1, sub2 = st.tabs([f"📋 最新持股 ({latest})", "🔄 變化對照"])
            with sub1:
                cur = etf.load_holdings(m.code, latest)
                if cur.empty:
                    st.info("—")
                else:
                    cur_disp = cur.head(30).rename(columns={
                        "stock_code": "代號", "stock_name": "名稱",
                        "shares": "股數", "weight": "權重 %",
                    })
                    st.dataframe(
                        cur_disp.style.format({"股數": "{:,}", "權重 %": "{:.2f}"}),
                        use_container_width=True, hide_index=True,
                    )
            with sub2:
                if len(dates) < 2:
                    st.info("需要至少兩個日期才能比較")
                else:
                    a, b = dates[0], dates[1]
                    diff = etf.diff_holdings(m.code, a, b)
                    if diff.empty:
                        st.info("—")
                    else:
                        changes = diff[diff["action"] != "="].copy()
                        # 中文標示
                        act_map = {"NEW": "🆕 新增", "OUT": "❌ 賣出",
                                   "+INC": "🔺 增持", "-DEC": "🔻 減持"}
                        changes["action"] = changes["action"].map(act_map)
                        changes = changes.rename(columns={
                            "stock_code": "代號", "stock_name": "名稱",
                            "shares_new": f"{a} 股數", "shares_old": f"{b} 股數",
                            "shares_diff": "股數變化",
                            "weight_new": f"{a} 權重%", "weight_old": f"{b} 權重%",
                            "weight_diff": "權重變化",
                            "action": "動作",
                        })
                        st.markdown(f"**{a} vs {b}**　共 {len(changes)} 檔異動")
                        st.dataframe(
                            changes.style.format({
                                f"{a} 股數": "{:,.0f}", f"{b} 股數": "{:,.0f}",
                                "股數變化": "{:+,.0f}",
                                f"{a} 權重%": "{:.2f}", f"{b} 權重%": "{:.2f}",
                                "權重變化": "{:+.2f}",
                            }),
                            use_container_width=True, hide_index=True,
                        )


# ============================================================
# 🔎 個股查詢
# ============================================================
else:
    st.sidebar.subheader("查詢條件")
    if "stock_code" not in st.session_state:
        st.session_state.stock_code = "2330"
    code = st.sidebar.text_input("股票代號", key="stock_code",
                                 help="例：2330、2317、6488.TWO")
    interval_label = st.sidebar.selectbox("主要週期", ["日線", "週線", "月線"], index=0)
    period_label = st.sidebar.selectbox(
        "觀察期間", ["6 個月", "1 年", "2 年", "5 年"], index=1,
    )
    interval_map = {"日線": "1d", "週線": "1wk", "月線": "1mo"}
    period_map = {"6 個月": "6mo", "1 年": "1y", "2 年": "2y", "5 年": "5y"}

    live_on = st.sidebar.checkbox(
        "🔴 盤中即時更新", value=False,
        help="啟用後會抓取 TWSE MIS 即時報價覆蓋今日 K 線；僅在日線模式有效",
    )

    go_btn = st.sidebar.button("🔍 開始分析", use_container_width=True, type="primary")

    render_market_sidebar()

    st.title("📈 台北股市分析器")
    st.caption("🔎 個股查詢")

    # 從今日選股跳轉時自動觸發
    auto_trigger = st.session_state.pop("auto_analyze", False)

    if not (go_btn or auto_trigger):
        st.info("👈 於左側輸入股票代號後按『開始分析』\n\n"
                "本系統綜合：四均線戰法、K 線型態、量價、KD/MACD/RSI、"
                "型態學、波浪理論、三大法人、融資融券 → 產生個股診斷書。")
        st.stop()

    with st.spinner("抓取資料中…"):
        try:
            df_raw = data.fetch(code, period=period_map[period_label],
                                interval=interval_map[interval_label])
        except ValueError as e:
            st.error(str(e))
            st.stop()
        weekly_df = None
        if interval_label == "日線":
            try:
                wk_raw = data.fetch(code, period="2y", interval="1wk")
                weekly_df = indicators.add_all(wk_raw)
            except Exception:
                weekly_df = None
        name = data.get_name(code)

        # --- 盤中即時覆蓋 ---
        live_quote = None
        if live_on and interval_label == "日線":
            live_quote = live.quote(code)
            if live_quote:
                df_raw = live.overlay_today(df_raw, live_quote)

    df = indicators.add_all(df_raw)
    diag = diagnosis.diagnose(df, code=code, weekly_df=weekly_df,
                              school=DEFAULT_SCHOOL)

    # --- 即時狀態 banner ---
    if live_on and interval_label == "日線":
        refresh_col1, refresh_col2 = st.columns([5, 1])
        with refresh_col1:
            if live_quote is not None:
                if live_quote.is_trading:
                    st.success(
                        f"🔴 盤中即時　·　成交價 **{live_quote.current:,.2f}** "
                        f"({live_quote.change:+.2f} / {live_quote.change_pct:+.2f}%)　"
                        f"·　成交量 {live_quote.volume_lots:,} 張"
                        f"　·　{live_quote.date} {live_quote.time}"
                    )
                else:
                    st.info(f"⚪ 尚未成交（五檔：買 {live_quote.bid} / 賣 {live_quote.ask}）"
                            f"　·　{live_quote.date} {live_quote.time}")
            else:
                st.warning("⚠️ 無法取得即時報價（可能為非交易時間或代號錯誤）")
        with refresh_col2:
            if st.button("🔄 重新整理", use_container_width=True):
                st.cache_data.clear()
                st.rerun()

    last = df.iloc[-1]
    prev = df.iloc[-2]
    price = last["close"]
    chg = price - prev["close"]
    chg_pct = chg / prev["close"] * 100

    info = industry.info_for(code)
    ind_name = info["industry"] if info else "—"
    full_name = info["full_name"] if info else name

    # ============================================================
    # 📌 頂部：資訊列 + 診斷書 + 關鍵價位 + 分數構成
    # ============================================================
    import datetime as _dt_ind
    now_str = _dt_ind.datetime.now().strftime("%Y-%m-%d %H:%M")
    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
    c1.metric(f"{name} ({code})　現價", f"{price:,.2f}",
              f"{chg:+.2f} ({chg_pct:+.2f}%)")
    c1.caption(f"🏭 **{ind_name}** · {full_name[:20]} · 🕒 {now_str}")
    c2.metric("成交量", f"{int(last['volume']):,}",
              f"{(last['volume'] / last['vol_ma5'] - 1) * 100:+.1f}% vs 5MA")
    c3.metric("多空評分", f"{diag.score:+d}", diag.stance)
    c4.metric(f"{ACTION_ICONS.get(diag.action, '')} 建議", diag.action)

    st.subheader("🩺 個股診斷書")
    banner = f"**{diag.stance}格局 · {diag.action}** — {diag.action_note}"
    if diag.stance in ("多方", "偏多"):
        st.success(banner)
    elif diag.stance in ("空方", "偏空"):
        st.error(banner)
    else:
        st.warning(banner)
    st.caption(diag.summary)

    # ---- 🎯 關鍵價位 ----
    st.markdown("#### 🎯 關鍵價位")
    col_t, col_e, col_s, col_r = st.columns(4)
    with col_t:
        if diag.target_price:
            pct = (diag.target_price / price - 1) * 100
            st.metric("目標價", f"{diag.target_price:,.2f}", f"{pct:+.2f}%")
            st.caption(f"依據：{diag.target_note}")
        else:
            st.metric("目標價", "—")
    with col_e:
        if diag.entry_zone:
            lo, hi = diag.entry_zone
            st.metric("建議進場區", f"{lo:,.2f} ~ {hi:,.2f}")
            if price < lo:
                st.caption("✅ 現價低於進場區，可分批佈局")
            elif price <= hi:
                st.caption("✅ 現價位於進場區內")
            else:
                st.caption("⚠️ 現價高於進場區，等待拉回")
        else:
            st.metric("建議進場區", "—")
    with col_s:
        if diag.short_stop:
            pct = (diag.short_stop / price - 1) * 100
            st.metric("短線停損 (MA10)", f"{diag.short_stop:,.2f}", f"{pct:+.2f}%")
        if diag.mid_stop:
            pct = (diag.mid_stop / price - 1) * 100
            st.caption(f"中線停損 (MA20)：**{diag.mid_stop:,.2f}**（{pct:+.2f}%）")
        st.caption(f"絕對停損：**{diag.abs_stop:,.2f}**")
    with col_r:
        if diag.risk_reward is not None:
            label = "🟢 優" if diag.risk_reward >= 2 else \
                    ("🟡 可" if diag.risk_reward >= 1 else "🔴 差")
            st.metric("風險報酬比", f"{diag.risk_reward:.2f} : 1", label)
        else:
            st.metric("風險報酬比", "—")

    # ---- 📊 分數構成（各指標貢獻） ----
    with st.expander("📊 分數構成明細（各指標貢獻）", expanded=False):
        mod = schools.get(DEFAULT_SCHOOL)
        weights = mod.score_weights()

        # 估算各項貢獻
        ma_contrib = weights.get("ma_alignment", {}).get(diag.ma_state, 0)
        candle_contrib = sum(weights.get(
            "candle_bull" if c.signal == "bull" else
            "candle_bear" if c.signal == "bear" else "none", 0)
            for c in diag.candles)
        pattern_contrib = sum(weights.get(
            "pattern_bull" if p.signal == "bull" else
            "pattern_bear" if p.signal == "bear" else "none", 0)
            for p in diag.chart_patterns)
        sig_contrib = sum(
            s.strength * weights.get("signal_per_strength", 4) *
            (1 if s.kind == "entry" else -1 if s.kind == "exit" else 0)
            for s in diag.signals)
        vol_contrib = (weights.get("volume_bonus", 8)
                       if "價漲量增" in diag.volume_note else
                       -weights.get("volume_bonus", 8)
                       if ("爆量下殺" in diag.volume_note or
                           "量縮上漲" in diag.volume_note) else 0)
        weekly_contrib = 0
        if "多頭" in diag.weekly_note or "偏多" in diag.weekly_note:
            weekly_contrib = weights.get("weekly_bias", 8)
        elif "空頭" in diag.weekly_note or "偏空" in diag.weekly_note:
            weekly_contrib = -weights.get("weekly_bias", 8)

        items = [
            ("📐 均線排列", ma_contrib, diag.ma_state),
            ("🌊 波浪位置", diag.wave_score, diag.wave_label),
            ("🏦 法人買賣", diag.institutional_score,
             diag.institutional_note or "中性"),
            ("💰 融資券", diag.margin_score,
             diag.margin_note or "中性"),
            ("🔬 計量物理", diag.econ_score,
             diag.econ_note or "中性"),
            ("🌀 黃金切割", diag.fib_score,
             diag.fib_note or "中性"),
            ("📅 週線方向", weekly_contrib,
             diag.weekly_note or "中性"),
            ("🚨 進出場訊號", sig_contrib,
             f"{len(diag.signals)} 個訊號" if diag.signals else "無"),
            ("🕯️ K 線型態", candle_contrib,
             "、".join(c.name for c in diag.candles) or "無"),
            ("📐 型態學", pattern_contrib,
             "、".join(p.name for p in diag.chart_patterns) or "無"),
            ("📊 量價配合", vol_contrib,
             diag.volume_note.split("（")[0] if "（" in diag.volume_note
             else diag.volume_note),
        ]
        items_sorted = sorted(items, key=lambda x: abs(x[1]), reverse=True)

        import plotly.graph_objects as _go
        non_zero = [(lbl, s, note) for lbl, s, note in items_sorted if s != 0]
        if non_zero:
            bar = _go.Figure(_go.Bar(
                x=[s for _, s, _ in non_zero],
                y=[lbl for lbl, _, _ in non_zero],
                orientation="h",
                marker_color=["#d62728" if s > 0 else "#2ca02c"
                              for _, s, _ in non_zero],
                text=[f"{s:+d}" for _, s, _ in non_zero],
                textposition="auto",
                hovertext=[f"{lbl}: {s:+d}<br>{note}"
                           for lbl, s, note in non_zero],
                hoverinfo="text",
            ))
            bar.update_layout(
                height=max(260, 28 * len(non_zero) + 80),
                margin=dict(l=10, r=10, t=30, b=10),
                yaxis=dict(autorange="reversed"),
                xaxis_title="分數貢獻",
                showlegend=False,
            )
            st.plotly_chart(bar, use_container_width=True)
        # 細項表
        items_df = pd.DataFrame(items_sorted,
                                columns=["指標", "貢獻分", "狀態"])
        st.dataframe(items_df, use_container_width=True, hide_index=True)

    # ============================================================
    # 📑 六大分頁：圖表 / 趨勢 / 訊號 / 價位 / 籌碼 / 量化
    # ============================================================
    tab_chart, tab_trend, tab_signal, tab_level, tab_chip, tab_quant = st.tabs(
        ["📉 圖表",
         "📊 趨勢結構",
         "🚨 訊號 & 型態",
         "🎯 關鍵價位",
         "💼 籌碼面",
         "🔬 量化指標"]
    )

    # ---- 📉 圖表 ----
    with tab_chart:
        from analyzer import candlestick as _cs
        from analyzer import wave as _wave
        w_detail = _wave.detect(df)
        candle_hist = _cs.scan_history(df, lookback=90)
        trend_info = {"support": diag.support, "resistance": diag.resistance}
        fig = chart.build(
            df, title=f"{name} ({code}) · {interval_label}",
            patterns=diag.chart_patterns,
            fib=diag.fib, wave_pivots=w_detail.pivots,
            trend=trend_info,
            candle_history=candle_hist,
            econ=diag.econ,
        )
        st.plotly_chart(fig, use_container_width=True,
                        config={
                            "scrollZoom": True,
                            "displaylogo": False,
                            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                            "doubleClick": "reset",
                        })
        st.caption(
            "🖱️ **操作提示**：上方按鈕 1M/3M/6M/1Y/全部 切換時距　·　"
            "滑鼠拖曳平移　·　滾輪縮放　·　雙擊復原　·　"
            "十字線即時顯示當日價格"
        )
        st.caption(
            "📖 **圖例**：🟥 紅實線=壓力　·　🟩 綠實線=支撐　·　"
            "🟪 紫虛線=費波納契　·　綠/紅虛線=上升/下降切線　·　"
            "▲▼(編號)=波浪 · 三角形浮標=K 線型態（**滑鼠移過可看含意**）"
        )

        # ---- 型態解說清單 ----
        if candle_hist:
            with st.expander(f"📋 近期 K 線型態清單（{len(candle_hist)} 個發生點）·"
                             f"點此展開看完整說明", expanded=True):
                rows_list = []
                for cand_idx, candles in reversed(candle_hist[-20:]):
                    if cand_idx >= len(df):
                        continue
                    dt = df.index[cand_idx]
                    for c in candles:
                        ic = {"bull": "🔴 偏多", "bear": "🟢 偏空",
                              "neutral": "⚪ 中性"}[c.signal]
                        rows_list.append({
                            "日期": str(dt.date()),
                            "型態": c.name,
                            "訊號": ic,
                            "含意": c.note,
                        })
                if rows_list:
                    st.dataframe(pd.DataFrame(rows_list),
                                 use_container_width=True, hide_index=True)

    # ---- 📊 趨勢結構（均線 + 波段 + 波浪 + 週線） ----
    with tab_trend:
        # 均線狀態
        st.markdown("#### 📐 均線排列")
        c_ma1, c_ma2 = st.columns([1, 1])
        with c_ma1:
            state_color = {"多頭排列": "🔴", "偏多": "🟠",
                           "均線糾結": "⚪", "盤整": "⚪",
                           "偏空": "🟢", "空頭排列": "🟩",
                           "未知": "⚪"}.get(diag.ma_state, "⚪")
            st.markdown(f"### {state_color} {diag.ma_state}")
            st.caption(diag.ma_note)
        with c_ma2:
            ma_cols = [c for c in ("ma5", "ma10", "ma20", "ma60", "ma120", "ma240")
                       if c in df.columns]
            snap = df[ma_cols].tail(1).T
            snap.columns = ["最新值"]
            snap["距現價 %"] = (snap["最新值"] / price - 1) * 100
            snap.index = [c.upper() for c in snap.index]
            st.dataframe(snap.style.format({"最新值": "{:.2f}",
                                            "距現價 %": "{:+.2f}%"}),
                         use_container_width=True)

        st.markdown("#### 🌊 波浪結構")
        w_dir = {"up": "⬆️ 上升", "down": "⬇️ 下降",
                 "corrective": "↔️ 修正", "unclear": "❓ 不明"}.get(
            diag.wave_direction, "—")
        wc1, wc2, wc3 = st.columns(3)
        wc1.metric("當前波位", diag.wave_label)
        wc2.metric("方向", w_dir, diag.wave_confidence)
        wc3.metric("波浪加權", f"{diag.wave_score:+d}")
        if diag.trend_note:
            st.info(f"📈 **波段結構**：{diag.trend_note}")

        st.markdown("#### 📅 週線輔助")
        if weekly_df is None or len(weekly_df) == 0:
            st.info("週線資料不可用。")
        else:
            wk_diag = diagnosis.diagnose(weekly_df, code=code,
                                         school=DEFAULT_SCHOOL,
                                         include_chips=False)
            kwc1, kwc2, kwc3 = st.columns(3)
            kwc1.metric("週線多空", wk_diag.stance, f"評分 {wk_diag.score:+d}")
            kwc2.metric("週線均線", wk_diag.ma_state)
            kwc3.metric("週線建議", wk_diag.action)
            st.caption(wk_diag.summary)
            with st.expander("📉 週線圖表", expanded=False):
                fig_w = chart.build(weekly_df,
                                    title=f"{name} ({code}) · 週線",
                                    patterns=wk_diag.chart_patterns,
                                    trend={"support": wk_diag.support,
                                           "resistance": wk_diag.resistance})
                st.plotly_chart(fig_w, use_container_width=True)

    # ---- 🚨 訊號 & 型態 ----
    with tab_signal:
        st.markdown("#### 🚨 進出場訊號")
        entries = [s for s in diag.signals if s.kind == "entry"]
        exits = [s for s in diag.signals if s.kind == "exit"]
        infos = [s for s in diag.signals if s.kind == "info"]
        sc_e, sc_x = st.columns(2)
        with sc_e:
            st.markdown("**🟢 買進訊號**")
            if entries:
                for s in entries:
                    st.markdown(f"- **{s.name}** {'★' * s.strength} — {s.note}")
            else:
                st.caption("—")
        with sc_x:
            st.markdown("**🔴 賣出訊號**")
            if exits:
                for s in exits:
                    st.markdown(f"- **{s.name}** {'★' * s.strength} — {s.note}")
            else:
                st.caption("—")
        if infos:
            st.markdown("**ℹ️ 資訊**")
            for s in infos:
                st.markdown(f"- {s.name} — {s.note}")

        st.markdown("#### 🕯️ K 線型態（最新）")
        if diag.candles:
            for c in diag.candles:
                ic = {"bull": "🔴", "bear": "🟢", "neutral": "⚪"}[c.signal]
                st.markdown(f"- {ic} **{c.name}** — {c.note}")
        else:
            st.caption("無明顯單日型態。")

        st.markdown("#### 📐 型態學（W 底 / M 頭 / 頭肩）")
        if diag.chart_patterns:
            for p in diag.chart_patterns:
                ic = {"bull": "🔴", "bear": "🟢", "neutral": "⚪"}[p.signal]
                neck = f"（頸線 {p.neckline:.2f}）" if p.neckline else ""
                st.markdown(f"- {ic} **{p.name}** {neck} — {p.note}")
        else:
            st.caption("近期無明顯型態。")

    # ---- 🎯 關鍵價位（費波 + 支撐壓力） ----
    with tab_level:
        st.markdown("#### 🌀 黃金切割率（費波納契）")
        fa = diag.fib
        if fa is None:
            st.info("—")
        else:
            fc = st.columns(4)
            fc[0].metric("波段方向",
                         "⬆️ 上升後回檔" if fa.direction == "up"
                         else "⬇️ 下降後反彈")
            fc[1].metric("波段高點", f"{fa.swing_high:,.2f}",
                         fa.swing_high_date)
            fc[2].metric("波段低點", f"{fa.swing_low:,.2f}",
                         fa.swing_low_date)
            fc[3].metric("費波加權", f"{diag.fib_score:+d}")
            if "貼近" in (fa.note or ""):
                st.success(fa.note)
            elif fa.note:
                st.caption(fa.note)
            if diag.fib_note:
                st.info(f"📝 {diag.fib_note}")

            rows = []
            for lv in fa.levels:
                dist_pct = (lv.price - price) / price * 100
                rows.append({
                    "級位": lv.name,
                    "價格": round(lv.price, 2),
                    "距現價": f"{dist_pct:+.2f}%",
                    "類型": "回檔" if lv.kind == "retrace" else "延伸",
                    "是否最近": "⭐"
                    if (fa.nearest and lv.name == fa.nearest.name) else "",
                })
            st.dataframe(pd.DataFrame(rows),
                         use_container_width=True, hide_index=True)

        st.markdown("#### 📈 支撐 / 壓力（近 60 日）")
        sp1, sp2 = st.columns(2)
        sp1.metric("近期壓力", f"{diag.resistance:,.2f}",
                   f"{(diag.resistance / price - 1) * 100:+.2f}%")
        sp2.metric("近期支撐", f"{diag.support:,.2f}",
                   f"{(diag.support / price - 1) * 100:+.2f}%")
        st.caption("跌破支撐：轉弱警訊；突破壓力：多頭訊號強化。")

    # ---- 💼 籌碼（法人 / 融資券 / ETF） ----
    with tab_chip:
        st.markdown("#### 🏦 三大法人買賣超")
        inst_info = diag.institutional_info
        if not inst_info:
            st.info("無法人資料")
        else:
            ic = st.columns(4)
            ic[0].metric("外資", f"{inst_info['foreign_net'] // 1000:+,} 張")
            ic[1].metric("投信", f"{inst_info['trust_net'] // 1000:+,} 張")
            ic[2].metric("自營商", f"{inst_info['dealer_net'] // 1000:+,} 張")
            ic[3].metric("三大合計",
                         f"{inst_info['total_net'] // 1000:+,} 張",
                         f"加權 {diag.institutional_score:+d}")
            if diag.institutional_note:
                st.caption(f"📝 {diag.institutional_note}")

        st.markdown("#### 💰 融資融券")
        marg_info = diag.margin_info
        if not marg_info:
            st.info("無融資融券資料")
        else:
            mc = st.columns(4)
            mc[0].metric("融資餘額",
                         f"{marg_info['margin_today']:,} 張",
                         f"{marg_info['margin_change']:+,} ("
                         f"{marg_info['margin_change_pct']:+.1f}%)")
            mc[1].metric("融券餘額",
                         f"{marg_info['short_today']:,} 張",
                         f"{marg_info['short_change']:+,} ("
                         f"{marg_info['short_change_pct']:+.1f}%)")
            mc[2].metric("資券互抵",
                         f"{marg_info['day_trade_offset']:,} 張")
            mc[3].metric("籌碼加權", f"{diag.margin_score:+d}")
            if diag.margin_note:
                st.caption(f"📝 {diag.margin_note}")

        st.markdown("#### 🎯 主動式 ETF 持股")
        holders = etf.holders_of(code)
        if holders.empty:
            st.info("🟡 尚無主動式ETF 持有本股票的紀錄；"
                    "可至「📊 主動式ETF」頁面擷取資料。")
        else:
            st.success(f"✅ 本股票被 {len(holders)} 檔主動式ETF 持有")
            disp = holders.copy()
            disp = disp.rename(columns={
                "etf_code": "ETF 代號", "etf_name": "ETF 名稱",
                "date": "資料日期", "shares": "持股張數",
                "weight": "權重 %",
            })
            if "持股張數" in disp.columns:
                disp["持股張數"] = (disp["持股張數"] / 1000).round().astype(int)
            order = [c for c in ["ETF 代號", "ETF 名稱", "資料日期",
                                 "持股張數", "權重 %"] if c in disp.columns]
            st.dataframe(
                disp[order].style.format({"持股張數": "{:,}",
                                          "權重 %": "{:.2f}"}),
                use_container_width=True, hide_index=True,
            )

    # ---- 🔬 量化指標 ----
    with tab_quant:
        st.markdown("#### 🔬 計量物理學指標")
        e = diag.econ
        if e is None:
            st.info("—")
        else:
            ec = st.columns(4)
            ec[0].metric("Hurst 指數", f"{e.hurst:.3f}", e.hurst_label)
            ec[1].metric("近 20 日波動率",
                         f"{e.vol_recent * 100:.1f}%",
                         f"相對 120 日 x{e.vol_ratio:.2f}")
            ec[2].metric("偏度 / 峰度",
                         f"{e.skew:+.2f} / {e.kurt:+.2f}",
                         e.risk_label)
            ec[3].metric("計量加權", f"{diag.econ_score:+d}")
            if diag.econ_note:
                st.info(f"📝 {diag.econ_note}")

        st.markdown("#### 📚 指標解讀")
        st.markdown("""
- **Hurst 指數 H**
  - `H > 0.55` 趨勢性：均線戰法、順勢交易有效 ✅
  - `H ≈ 0.5`  隨機漫步：技術指標效度中性
  - `H < 0.45` 均值回歸：反向交易 / 區間操作較佳
- **波動率 x 倍數**：近期年化波動率 vs 長期基準
  - `> 2.0x` 突升 → 避險訊號，減碼
  - `< 0.8x` 壓縮 → 變盤前兆
- **偏度**：負值 → 下跌尾部較大（左偏）
- **峰度**：> 3 為肥尾，黑天鵝風險升高
""")

st.divider()
st.caption("免責聲明：本工具僅為技術分析教學用途，非投資建議。投資有風險，請自行判斷。")
