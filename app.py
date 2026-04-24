"""台北股市分析器 (Streamlit)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import logging

from analyzer import (chart, data, diagnosis, etf, etf_scraper,
                      indicators, industry, live, marketdata,
                      moneyflow, schools, screener, storage, watchlist)

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

st.set_page_config(page_title="中央印製廠 · 台北股市分析器 · 一起掙大錢",
                   page_icon="📈", layout="wide")

# === 側邊欄寬度 + 手機版響應式 ===
st.markdown("""
<style>
/* 桌面版側邊欄 */
@media (min-width: 769px) {
    [data-testid="stSidebar"] {
        min-width: 340px !important;
        max-width: 420px !important;
        width: 360px !important;
    }
    [data-testid="stSidebar"] > div:first-child {
        width: 360px !important;
    }
}
[data-testid="stSidebar"] .stMetric [data-testid="stMetricLabel"] {
    font-size: 13px !important;
}
[data-testid="stSidebar"] .stMetric [data-testid="stMetricValue"] {
    font-size: 18px !important;
}

/* 手機版：768px 以下 */
@media (max-width: 768px) {
    .main .block-container {
        padding: 0.5rem 0.6rem !important;
    }
    /* 卡片內現價縮小一點 */
    div[data-testid="stVerticalBlockBorderWrapper"] span[style*="font-size:30px"] {
        font-size: 24px !important;
    }
    /* 標題列縮小 */
    h1 { font-size: 1.4rem !important; }
    h2 { font-size: 1.2rem !important; }
    h3 { font-size: 1.05rem !important; }
    /* metric 壓縮 */
    [data-testid="stMetricValue"] {
        font-size: 1rem !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.75rem !important;
    }
    /* pills 縮小間距 */
    span[style*="border-radius:12px"] {
        font-size: 11px !important;
    }
}

/* 統一 expander 標題字型 */
[data-testid="stExpander"] summary p {
    font-size: 0.95rem !important;
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
    chg_color = "#e55353" if row["漲跌%"] > 0 else "#3dbd6e" \
        if row["漲跌%"] < 0 else "#aaa"
    import datetime as _dtk
    now_str = _dtk.datetime.now().strftime("%m-%d %H:%M")
    entry_str = ""
    if d.entry_zone:
        lo, hi = d.entry_zone
        price_now = row["收盤"]
        if price_now < lo:
            hint = "可佈局"
        elif price_now <= hi:
            hint = "位於進場區"
        else:
            hint = "已突破，等拉回"
        entry_str = (f"<span style='color:#ffdd55;'>💡 進場 "
                     f"{lo:.2f}~{hi:.2f}</span> "
                     f"<span style='color:#999;'>({hint})</span>")

    with st.container(border=True):
        # --- 標題列：現價醒目 ---
        st.markdown(
            f"""
            <div style='line-height:1.35;'>
              <div style='font-size:13px; color:#bbb;'>
                <b style='color:#fafafa;'>#{rank} {row['名稱']} ({row['代號']})</b>
                <span style='margin-left:10px;'>🕒 {now_str}</span>
              </div>
              <div style='margin:6px 0 4px 0; display:flex; align-items:baseline; gap:12px;'>
                <span style='font-size:13px; color:#999;'>現價</span>
                <span style='font-size:30px; font-weight:800; color:{chg_color};
                             letter-spacing:-0.5px;'>
                  {row['收盤']:.2f}
                </span>
                <span style='font-size:18px; font-weight:700; color:{chg_color};'>
                  {chg_sign}{row['漲跌%']:.2f}%
                </span>
              </div>
              <div style='font-size:14px; margin-top:2px;'>
                {score_icon} <b>分數 {d.score:+d}</b>
                <span style='color:#666;'>　·　</span>
                {ACTION_ICONS.get(d.action, '')} <b>{d.action}</b>
                <span style='color:#666;'>　·　</span>
                {entry_str}
              </div>
            </div>
            """,
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
            weekly_br = (d.weekly_note.replace("週線", "").strip()
                         if d.weekly_note else "—")
            # 2 欄 × 4 列，所有字體 13px 統一
            info_html = f"""
            <div style='font-size:13px; line-height:1.7;'>
              <div style='display:grid; grid-template-columns:1fr 1fr; gap:4px 10px;'>
                <div><span style='color:#888;'>均線</span>　{d.ma_state}</div>
                <div><span style='color:#888;'>波浪</span>　{d.wave_label}</div>
                <div><span style='color:#888;'>量價</span>　{vol_brief}</div>
                <div><span style='color:#888;'>KD/RSI</span>　{row['KD']} / {row['RSI']}</div>
                <div><span style='color:#888;'>法人</span>　{row['法人(張)']} 張</div>
                <div><span style='color:#888;'>融資/券</span>　{row['融資/券']}</div>
                <div><span style='color:#888;'>Hurst</span>　{hurst_str}</div>
                <div><span style='color:#888;'>費波</span>　{fib_nearest}</div>
              </div>
              <div style='margin-top:6px; color:#888; font-size:12px;'>
                📅 週線　{weekly_br}
              </div>
            </div>
            """
            st.markdown(info_html, unsafe_allow_html=True)

        pa = st.columns([2, 2, 2, 2, 1.5, 1.5])
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
            watched = watchlist.contains(str(row["代號"]))
            if st.button("🌟" if watched else "⭐",
                         key=f"fav_{rank}_{row['代號']}",
                         use_container_width=True,
                         help="移除收藏" if watched else "加入收藏"):
                if watched:
                    watchlist.remove(str(row["代號"]))
                else:
                    watchlist.add(str(row["代號"]))
                st.rerun()
        with pa[5]:
            st.write("")
            if st.button("🔎", key=f"detail_{rank}_{row['代號']}",
                         use_container_width=True, type="primary",
                         help="完整分析"):
                st.session_state._mode_override = "🔎 個股查詢"
                st.session_state.stock_code = str(row["代號"])
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
st.sidebar.markdown(
    "<div style='font-size:18px; font-weight:700; line-height:1.3;'>"
    "🏛️ 中央印製廠<br>"
    "📈 台北股市分析器<br>"
    "<span style='color:#ffd700;'>💰 一起掙大錢</span>"
    "</div>",
    unsafe_allow_html=True,
)

if "app_mode" not in st.session_state:
    st.session_state.app_mode = "🎯 今日選股"
# 處理上一輪 rerun 設定的模式切換意圖（必須在 widget 渲染前）
if "_mode_override" in st.session_state:
    st.session_state.app_mode = st.session_state.pop("_mode_override")

mode = st.sidebar.radio(
    "模式",
    ["🎯 今日選股", "🔎 個股查詢", "⭐ 收藏清單",
     "📈 多股比較", "📊 主動式ETF", "🔥 資金流向"],
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

    st.title("🏛️ 中央印製廠 · 📈 台北股市分析器 · 💰 一起掙大錢")
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
# 📈 多股比較
# ============================================================
elif mode == "📈 多股比較":
    st.title("🏛️ 中央印製廠 · 📈 台北股市分析器 · 💰 一起掙大錢")
    st.caption("📈 多股比較　·　疊加 2~5 檔標的相對走勢與相關性分析")

    st.sidebar.subheader("選取標的")
    ind_df_cmp = industry.snapshot()
    if ind_df_cmp.empty:
        opts_cmp = ["2330 台積電"]
    else:
        opts_cmp = (ind_df_cmp["code"] + " "
                    + ind_df_cmp["short_name"]).tolist()
    default_picks = st.session_state.get("cmp_picks", ["2330 台積電"])
    picked = st.sidebar.multiselect(
        "股票（輸入關鍵字過濾，最多 5 檔）",
        opts_cmp,
        default=[p for p in default_picks if p in opts_cmp],
        max_selections=5,
    )
    st.session_state.cmp_picks = picked
    period_cmp = st.sidebar.selectbox(
        "觀察期間", ["1 個月", "3 個月", "6 個月", "1 年", "2 年"],
        index=2,
    )
    p_map = {"1 個月": "1mo", "3 個月": "3mo", "6 個月": "6mo",
             "1 年": "1y", "2 年": "2y"}
    render_market_sidebar()

    if not picked:
        st.info("👈 於左側選取 2~5 檔股票開始比較")
        st.stop()

    codes_cmp = [p.split()[0] for p in picked]
    names_cmp = {p.split()[0]: " ".join(p.split()[1:]) for p in picked}

    with st.spinner(f"抓取 {len(codes_cmp)} 檔資料中…"):
        raws: dict[str, pd.DataFrame] = {}
        for c in codes_cmp:
            try:
                d = data.fetch(c, period=p_map[period_cmp], interval="1d")
                raws[c] = d
            except Exception as e:
                st.warning(f"{c} 抓取失敗：{e}")

    if not raws:
        st.error("無可用資料")
        st.stop()

    # 對齊索引（取交集日期）
    common_index = None
    for c, d in raws.items():
        common_index = d.index if common_index is None \
            else common_index.intersection(d.index)
    aligned = {c: d.loc[common_index] for c, d in raws.items()}

    # 計算相對漲幅（以起始日為 0%）
    import plotly.graph_objects as _go2
    fig_cmp = _go2.Figure()
    palette = ["#d62728", "#ff7f0e", "#1f77b4", "#9467bd", "#2ca02c"]
    perf_rows = []
    for i, (c, d) in enumerate(aligned.items()):
        if d.empty or len(d) < 2:
            continue
        base = d["close"].iloc[0]
        rel = (d["close"] / base - 1) * 100
        color = palette[i % len(palette)]
        fig_cmp.add_trace(_go2.Scatter(
            x=d.index, y=rel, name=f"{c} {names_cmp.get(c, '')}",
            line=dict(color=color, width=2),
            hovertemplate=(f"<b>{c} {names_cmp.get(c, '')}</b><br>"
                           "%{x|%Y-%m-%d}<br>"
                           "相對漲幅 %{y:.2f}%<extra></extra>"),
        ))
        ret_total = (d["close"].iloc[-1] / base - 1) * 100
        max_up = (d["close"].max() / base - 1) * 100
        max_dn = (d["close"].min() / base - 1) * 100
        daily_ret = d["close"].pct_change().dropna()
        vol_ann = daily_ret.std() * (252 ** 0.5) * 100
        perf_rows.append({
            "代號": c,
            "名稱": names_cmp.get(c, ""),
            "期間報酬 %": round(ret_total, 2),
            "最大漲幅 %": round(max_up, 2),
            "最大回檔 %": round(max_dn, 2),
            "年化波動率 %": round(vol_ann, 1),
            "最新收盤": round(float(d["close"].iloc[-1]), 2),
        })

    fig_cmp.add_hline(y=0, line_dash="dot", line_color="#888", line_width=1)
    fig_cmp.update_layout(
        title=f"相對漲幅 · {period_cmp}起",
        height=520,
        margin=dict(l=10, r=10, t=50, b=10),
        hovermode="x unified",
        xaxis_title="", yaxis_title="相對漲幅 (%)",
        legend=dict(orientation="h", y=1.08, x=0),
        dragmode="pan",
    )
    fig_cmp.update_xaxes(
        rangebreaks=[dict(bounds=["sat", "mon"])],
        showspikes=True, spikemode="across", spikedash="dot",
        spikecolor="#888", spikethickness=1,
    )
    fig_cmp.update_yaxes(
        showspikes=True, spikemode="across", spikedash="dot",
        spikecolor="#888", spikethickness=1,
    )
    st.plotly_chart(fig_cmp, use_container_width=True,
                    config={"scrollZoom": True, "displaylogo": False})

    # 績效表
    st.markdown("#### 📊 績效比較")
    perf_df = pd.DataFrame(perf_rows)

    def _perf_color(v):
        try:
            x = float(v)
        except Exception:
            return ""
        if x > 0:
            return "color:#e55353;"
        if x < 0:
            return "color:#3dbd6e;"
        return ""

    styled_perf = (perf_df.style
                   .map(_perf_color,
                        subset=["期間報酬 %", "最大漲幅 %", "最大回檔 %"])
                   .format({"期間報酬 %": "{:+.2f}",
                            "最大漲幅 %": "{:+.2f}",
                            "最大回檔 %": "{:+.2f}",
                            "年化波動率 %": "{:.1f}",
                            "最新收盤": "{:.2f}"}))
    st.dataframe(styled_perf, use_container_width=True, hide_index=True)

    # 相關性矩陣
    if len(aligned) >= 2:
        st.markdown("#### 🔗 日報酬相關性")
        daily = pd.DataFrame({c: d["close"].pct_change()
                              for c, d in aligned.items()}).dropna()
        if not daily.empty:
            corr = daily.corr()
            # 重新命名
            corr.index = [f"{c} {names_cmp.get(c, '')}" for c in corr.index]
            corr.columns = [f"{c} {names_cmp.get(c, '')}" for c in corr.columns]
            # 用顏色 map 呈現
            def _corr_color(v):
                try:
                    x = float(v)
                except Exception:
                    return ""
                r = int(214 * x) if x > 0 else 0
                g = int(160 * -x) if x < 0 else 0
                return f"background-color: rgba({r},{g},0,{abs(x) * 0.5});"
            st.dataframe(corr.style.map(_corr_color).format("{:.2f}"),
                         use_container_width=True)
            st.caption("🔑 相關係數 +1 完全同向、-1 反向、0 無關。"
                       "同族群通常 > 0.7；避免集中持有高相關股可分散風險。")


# ============================================================
# ⭐ 收藏清單
# ============================================================
elif mode == "⭐ 收藏清單":
    st.title("🏛️ 中央印製廠 · 📈 台北股市分析器 · 💰 一起掙大錢")
    st.caption("⭐ 收藏清單　·　追蹤常看股票、即時進場區警示")

    codes = watchlist.get()

    # 側邊欄：新增股票 + 清單管理
    st.sidebar.subheader("管理收藏")
    add_sel = st.sidebar.selectbox(
        "新增", [""] + _stock_options() if False
        else [""] + (industry.snapshot()["code"] + " "
                     + industry.snapshot()["short_name"]).tolist()
        if not industry.snapshot().empty else [""],
        index=0, key="wl_add",
    )
    if add_sel:
        add_code = add_sel.split()[0]
        if st.sidebar.button(f"➕ 加入 {add_code}", use_container_width=True):
            watchlist.add(add_code)
            st.rerun()

    if codes:
        if st.sidebar.button("🗑️ 清空全部", use_container_width=True):
            watchlist.set_all([])
            st.rerun()
    render_market_sidebar()

    if not codes:
        st.info("📝 清單目前是空的。\n\n"
                "➕ 可於「🔎 個股查詢」頁面按 ⭐ 加入收藏，或使用上方側邊欄新增。\n\n"
                "📌 收藏清單透過 URL 參數同步：複製瀏覽器網址即可分享或書籤保存。")
        st.stop()

    # 取得產業對照 + 即時報價
    ind_df = industry.snapshot()
    with st.spinner(f"抓取 {len(codes)} 檔即時報價 + 計算指標…"):
        quotes = live.quotes(codes)

    # 分類：進場區 / 非進場區
    in_zone: list[dict] = []
    other: list[dict] = []

    progress = st.progress(0.0)
    for idx, code in enumerate(codes):
        progress.progress((idx + 1) / len(codes), text=f"分析 {code}…")
        try:
            raw = data.fetch(code, period="1y", interval="1d")
            raw = indicators.add_all(raw)
            q = quotes.get(code)
            if q:
                raw = live.overlay_today(raw, q)
            d = diagnosis.diagnose(raw, code=code)
            info = ind_df[ind_df["code"] == code]
            name = info.iloc[0]["short_name"] if not info.empty else code
            ind_name = info.iloc[0]["industry"] if not info.empty else "—"
            price_now = float(raw["close"].iloc[-1])
            chg_pct = ((price_now / raw["close"].iloc[-2] - 1) * 100
                       if len(raw) >= 2 else 0.0)

            in_entry = False
            if d.entry_zone:
                lo, hi = d.entry_zone
                if lo <= price_now <= hi:
                    in_entry = True

            bucket = {
                "code": code, "name": name, "industry": ind_name,
                "price": price_now, "chg_pct": chg_pct,
                "score": d.score, "stance": d.stance, "action": d.action,
                "entry_zone": d.entry_zone,
                "target": d.target_price, "stop": d.short_stop,
                "in_zone": in_entry, "diag": d,
            }
            (in_zone if in_entry else other).append(bucket)
        except Exception as e:
            other.append({"code": code, "name": code, "error": str(e)})
    progress.empty()

    # ---- 警示區：觸發進場的股票 ----
    if in_zone:
        st.success(f"🚨 **{len(in_zone)} 檔已達建議進場區間** — 可考慮佈局")
        for b in in_zone:
            lo, hi = b["entry_zone"]
            st.markdown(
                f"""
                <div style='padding:12px 18px; margin:8px 0;
                            border:2px solid #ffdd00;
                            border-radius:10px;
                            background:linear-gradient(90deg,
                                rgba(255,221,0,0.12), rgba(255,221,0,0));
                            box-shadow:0 0 14px rgba(255,221,0,0.28);'>
                  <div style='display:flex; justify-content:space-between;
                              align-items:baseline; flex-wrap:wrap;'>
                    <div>
                      <span style='font-size:18px; font-weight:700;'>
                        💡 {b['name']} ({b['code']})
                      </span>
                      <span style='color:#aaa; margin-left:8px; font-size:13px;'>
                        · {b['industry']}
                      </span>
                    </div>
                    <div>
                      <span style='font-size:24px; font-weight:800;
                              color:{"#e55353" if b["chg_pct"]>=0 else "#3dbd6e"};'>
                        {b['price']:.2f}
                      </span>
                      <span style='margin-left:6px;
                              color:{"#e55353" if b["chg_pct"]>=0 else "#3dbd6e"};'>
                        {'+' if b['chg_pct']>=0 else ''}{b['chg_pct']:.2f}%
                      </span>
                    </div>
                  </div>
                  <div style='margin-top:8px; font-size:13px; color:#ddd;'>
                    🟡 <b>進場區 {lo:.2f} ~ {hi:.2f}</b> 已觸及　·
                    分數 <b>{b['score']:+d}</b>　·　建議 <b>{b['action']}</b>
                    {' · 目標 ' + format(b['target'], '.2f') if b.get('target') else ''}
                    {' · 停損 ' + format(b['stop'], '.2f') if b.get('stop') else ''}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            c_a, c_b = st.columns([5, 1])
            with c_b:
                if st.button("🔎 分析", key=f"wlz_{b['code']}",
                             use_container_width=True):
                    st.session_state._mode_override = "🔎 個股查詢"
                    st.session_state.stock_code = b["code"]
                    st.session_state.auto_analyze = True
                    st.rerun()

    # ---- 其他收藏 ----
    st.markdown("### 📋 全部收藏")
    cols = st.columns(3)
    for i, b in enumerate(other + in_zone):
        with cols[i % 3]:
            with st.container(border=True):
                if "error" in b:
                    st.error(f"{b['code']} 取得失敗：{b['error'][:40]}")
                    if st.button("❌ 移除", key=f"rm_err_{b['code']}",
                                 use_container_width=True):
                        watchlist.remove(b["code"])
                        st.rerun()
                    continue
                chg_color = "#e55353" if b["chg_pct"] >= 0 else "#3dbd6e"
                border = ("border:2px solid #ffdd00; box-shadow:0 0 10px "
                          "rgba(255,221,0,0.4);") if b["in_zone"] else ""
                st.markdown(
                    f"""
                    <div style='padding:4px; {border}'>
                      <div style='font-size:14px; font-weight:700;'>
                        {b['name']} ({b['code']})
                        {"🟡" if b['in_zone'] else ""}
                      </div>
                      <div style='color:#888; font-size:11px;'>
                        {b.get('industry', '—')}
                      </div>
                      <div style='margin:6px 0;'>
                        <span style='font-size:22px; font-weight:800;
                                color:{chg_color};'>
                          {b['price']:.2f}
                        </span>
                        <span style='font-size:13px; color:{chg_color};
                                margin-left:4px;'>
                          {'+' if b['chg_pct']>=0 else ''}{b['chg_pct']:.2f}%
                        </span>
                      </div>
                      <div style='font-size:12px;'>
                        分數 <b>{b['score']:+d}</b> · {b['stance']}<br>
                        建議：<b>{b['action']}</b>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                sub_a, sub_b = st.columns(2)
                with sub_a:
                    if st.button("🔎", key=f"v_{b['code']}",
                                 use_container_width=True,
                                 help="完整分析"):
                        st.session_state._mode_override = "🔎 個股查詢"
                        st.session_state.stock_code = b["code"]
                        st.session_state.auto_analyze = True
                        st.rerun()
                with sub_b:
                    if st.button("❌", key=f"rm_{b['code']}",
                                 use_container_width=True,
                                 help="移除收藏"):
                        watchlist.remove(b["code"])
                        st.rerun()


# ============================================================
# 🔥 資金流向 — 產業族群強弱排行
# ============================================================
elif mode == "🔥 資金流向":
    st.title("🏛️ 中央印製廠 · 📈 台北股市分析器 · 💰 一起掙大錢")
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

    st.title("🏛️ 中央印製廠 · 📈 台北股市分析器 · 💰 一起掙大錢")
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

    # --- B. 自動補齊：以產業表建立下拉 options ---
    @st.cache_data(ttl=86400, show_spinner=False)
    def _stock_options() -> list[str]:
        df = industry.snapshot()
        if df.empty:
            return ["2330 台積電"]
        return (df["code"] + " " + df["short_name"]
                + " · " + df["industry"]).tolist()

    opts = _stock_options()
    # 找到預設選項索引
    current_code = st.session_state.stock_code
    default_idx = 0
    for i, o in enumerate(opts):
        if o.startswith(current_code + " "):
            default_idx = i
            break
    selected = st.sidebar.selectbox(
        "🔍 搜尋股票（輸入代號/名稱/產業）",
        opts, index=default_idx,
        help="輸入任何關鍵字自動過濾",
    )
    code = selected.split()[0] if selected else current_code
    st.session_state.stock_code = code

    # --- A. ⭐ 收藏按鈕 ---
    is_watched = watchlist.contains(code)
    wbtn_label = "🌟 已收藏" if is_watched else "⭐ 加入收藏"
    if st.sidebar.button(wbtn_label, use_container_width=True):
        if is_watched:
            watchlist.remove(code)
        else:
            watchlist.add(code)
        st.rerun()

    interval_label = st.sidebar.selectbox("主要週期", ["日線", "週線", "月線"], index=0)
    period_label = st.sidebar.selectbox(
        "觀察期間",
        ["1 個月", "3 個月", "6 個月", "1 年", "2 年", "5 年"],
        index=1,   # 預設 3 個月
    )
    interval_map = {"日線": "1d", "週線": "1wk", "月線": "1mo"}
    # 實際抓取：短期間也拉 1 年以保留均線 / 指標完整度
    fetch_map = {
        "1 個月": "1y", "3 個月": "1y", "6 個月": "1y",
        "1 年": "1y", "2 年": "2y", "5 年": "5y",
    }
    # 圖表預設顯示交易日數
    display_days_map = {
        "1 個月": 22, "3 個月": 66, "6 個月": 130,
        "1 年": 252, "2 年": 504, "5 年": 1260,
    }
    period_map = fetch_map  # 相容原變數名

    live_on = st.sidebar.checkbox(
        "🔴 盤中即時更新", value=False,
        help="啟用後會抓取 TWSE MIS 即時報價覆蓋今日 K 線；僅在日線模式有效",
    )

    go_btn = st.sidebar.button("🔍 開始分析", use_container_width=True, type="primary")

    render_market_sidebar()

    st.title("🏛️ 中央印製廠 · 📈 台北股市分析器 · 💰 一起掙大錢")
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

    # --- 雙觀點對照（朱家泓 vs 籌碼派） ---
    try:
        chip_diag = diagnosis.diagnose(df, code=code, weekly_df=weekly_df,
                                       school="籌碼派")
    except Exception:
        chip_diag = None

    if chip_diag:
        v1, v2 = st.columns(2)
        with v1:
            st.markdown(
                f"<div style='padding:8px 12px; border-left:3px solid #ff7f0e;'>"
                f"<span style='color:#ff7f0e;'>📈 技術派觀點</span><br>"
                f"<b>{diag.stance} · {diag.action}</b>　分數 {diag.score:+d}"
                f"</div>",
                unsafe_allow_html=True,
            )
        with v2:
            st.markdown(
                f"<div style='padding:8px 12px; border-left:3px solid #9467bd;'>"
                f"<span style='color:#9467bd;'>💼 籌碼派觀點</span><br>"
                f"<b>{chip_diag.stance} · {chip_diag.action}</b>　分數 {chip_diag.score:+d}"
                f"</div>",
                unsafe_allow_html=True,
            )
        # 若兩者觀點分歧，顯示提示
        if (diag.stance in ("多方", "偏多")) != (chip_diag.stance in ("多方", "偏多")):
            st.warning("⚠️ **兩派觀點分歧** — 建議檢視籌碼面與技術面不一致的原因（可能籌碼先行或技術落後）")

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
    (tab_chart, tab_trend, tab_signal, tab_level,
     tab_chip, tab_quant, tab_backtest) = st.tabs(
        ["📉 圖表",
         "📊 趨勢結構",
         "🚨 訊號 & 型態",
         "🎯 關鍵價位",
         "💼 籌碼面",
         "🔬 量化指標",
         "🧪 訊號回測"]
    )

    # ---- 📉 圖表 ----
    with tab_chart:
        from analyzer import candlestick as _cs
        from analyzer import wave as _wave
        w_detail = _wave.detect(df)
        candle_hist = _cs.scan_history(df, lookback=90)

        # ---- 技術指標 Pills（圖表上方） ----
        last_ind = df.iloc[-1]
        def _pill(label, value, color="#888"):
            return (f"<span style='display:inline-block; padding:3px 9px; "
                    f"margin:2px; border-radius:12px; "
                    f"background:rgba(40,44,55,0.7); "
                    f"border:1px solid {color}; font-size:12px;'>"
                    f"<span style='color:{color};'>{label}</span> "
                    f"<b style='color:#fff;'>{value}</b></span>")
        pills = []
        for p, col in [(5, "#ff7f0e"), (10, "#1f77b4"),
                       (20, "#9467bd"), (60, "#8c564b")]:
            k = f"ma{p}"
            if k in df.columns and not pd.isna(last_ind.get(k)):
                pills.append(_pill(f"MA{p}", f"{last_ind[k]:.2f}", col))
        if "k" in df.columns and not pd.isna(last_ind.get("k")):
            k_col = "#d62728" if last_ind["k"] > 80 \
                else "#2ca02c" if last_ind["k"] < 20 else "#1f77b4"
            pills.append(_pill("KD",
                f"{last_ind['k']:.0f}/{last_ind['d']:.0f}", k_col))
        if "rsi" in df.columns and not pd.isna(last_ind.get("rsi")):
            r_col = "#d62728" if last_ind["rsi"] > 70 \
                else "#2ca02c" if last_ind["rsi"] < 30 else "#aaa"
            pills.append(_pill("RSI", f"{last_ind['rsi']:.1f}", r_col))
        if "macd_dif" in df.columns and not pd.isna(last_ind.get("macd_dif")):
            m_col = "#d62728" if last_ind["macd_dif"] > last_ind["macd_dem"] \
                else "#2ca02c"
            pills.append(_pill("MACD", f"{last_ind['macd_dif']:+.2f}", m_col))
        if diag.econ:
            pills.append(_pill("Hurst",
                f"{diag.econ.hurst:.2f}", "#9467bd"))
            pills.append(_pill("波動",
                f"{diag.econ.vol_recent * 100:.0f}% x{diag.econ.vol_ratio:.2f}",
                "#ffa500"))
        st.markdown("".join(pills), unsafe_allow_html=True)
        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        trend_info = {"support": diag.support, "resistance": diag.resistance}
        fig = chart.build(
            df, title=f"{name} ({code}) · {interval_label}",
            patterns=diag.chart_patterns,
            fib=diag.fib, wave_pivots=w_detail.pivots,
            trend=trend_info,
            candle_history=candle_hist,
            econ=diag.econ,
            entry_zone=diag.entry_zone,
            target_price=diag.target_price,
            short_stop=diag.short_stop,
            mid_stop=diag.mid_stop,
            display_days=display_days_map.get(period_label, 130),
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

    # ---- 🧪 訊號回測 ----
    with tab_backtest:
        from analyzer import backtest as _bt
        st.markdown("### 🧪 歷史訊號回測")
        st.caption("掃描近一年所有訊號發生點，統計後續 5 / 10 / 20 / 60 日報酬率與勝率。"
                   "勝率定義：多頭訊號看漲的比例、空頭訊號看跌的比例。")
        with st.spinner("回測中…"):
            events, summary_df = _bt.run(df)

        if summary_df.empty:
            st.info("資料不足以進行回測（需至少 60 日）")
        else:
            # 摘要指標
            tot_bull = len([e for e in events if e.kind == "bull"])
            tot_bear = len([e for e in events if e.kind == "bear"])
            bt_cols = st.columns(3)
            bt_cols[0].metric("多頭訊號總數", tot_bull)
            bt_cols[1].metric("空頭訊號總數", tot_bear)
            bt_cols[2].metric("觀察期間", f"{len(df)} 日")

            # 摘要表
            def _color_win(v):
                try:
                    x = float(v)
                except Exception:
                    return ""
                if x >= 60:
                    return "background-color: rgba(214,39,40,0.35);"
                if x >= 50:
                    return "background-color: rgba(214,39,40,0.15);"
                if x <= 40:
                    return "background-color: rgba(44,160,44,0.25);"
                return ""

            def _color_ret(v):
                try:
                    x = float(v)
                except Exception:
                    return ""
                if x > 0:
                    return "color:#e55353;"
                if x < 0:
                    return "color:#3dbd6e;"
                return ""

            win_cols = [c for c in summary_df.columns if "勝率" in c]
            ret_cols = [c for c in summary_df.columns if "均報酬" in c]

            styled_bt = (summary_df.style
                         .map(_color_win, subset=win_cols)
                         .map(_color_ret, subset=ret_cols)
                         .format({c: "{:.1f}" for c in win_cols}, na_rep="—")
                         .format({c: "{:+.2f}" for c in ret_cols}, na_rep="—"))
            st.dataframe(styled_bt, use_container_width=True, hide_index=True)

            st.caption("💡 **解讀**：勝率 > 60% 底色轉紅表示此訊號對**順向**勝率高；"
                       "T+20 均報酬 > 0 代表多頭訊號後 20 日平均上漲。"
                       "樣本數小於 5 次的訊號僅供參考。")

            # 事件清單（展開）
            with st.expander(f"📋 事件明細（共 {len(events)} 筆）", expanded=False):
                ev_rows = []
                for e in events:
                    r5 = e.returns.get(5)
                    r10 = e.returns.get(10)
                    r20 = e.returns.get(20)
                    ev_rows.append({
                        "日期": str(e.date.date()),
                        "訊號": e.name,
                        "方向": {"bull": "🔴 多", "bear": "🟢 空",
                                "neutral": "⚪ 中"}[e.kind],
                        "價格": round(e.price, 2),
                        "T+5%": round(r5, 2) if r5 is not None else None,
                        "T+10%": round(r10, 2) if r10 is not None else None,
                        "T+20%": round(r20, 2) if r20 is not None else None,
                    })
                ev_df = pd.DataFrame(ev_rows).sort_values(
                    "日期", ascending=False).reset_index(drop=True)
                st.dataframe(ev_df.style.map(
                    _color_ret,
                    subset=[c for c in ["T+5%", "T+10%", "T+20%"]
                            if c in ev_df.columns])
                    .format({"T+5%": "{:+.2f}", "T+10%": "{:+.2f}",
                             "T+20%": "{:+.2f}"}, na_rep="—"),
                    use_container_width=True, hide_index=True)

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
