"""台北股市分析器 (Streamlit)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import logging

from analyzer import (chart, data, diagnosis, etf, etf_scraper,
                      indicators, industry, live, marketdata,
                      moneyflow, price_cache, realbacktest, revenue,
                      schools, screener, shareholders, storage, targets,
                      watchlist)

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

st.set_page_config(page_title="Teddy中央印製廠_台北股市分析器 - 掙大錢 !",
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

# ============================================================
# 🇹🇼 頂部指數列 — 加權 / 櫃買 / 台指期日盤 / 夜盤 (5 分鐘快取)
# ============================================================
def render_index_header():
    try:
        idx = marketdata.fetch_indices()
    except Exception:
        idx = {}
    upd = marketdata.idx_last_update()
    # 標題與指數各佔一半，指數列字型放大
    title_col, banner_col = st.columns([1.6, 3])
    with title_col:
        st.markdown(
            f"<h2 style='margin:0; padding:0; line-height:1.25;'>"
            f"Teddy中央印製廠_<br>台北股市分析器 "
            f"<span style='color:#ffd700;'>- 掙大錢 !</span></h2>",
            unsafe_allow_html=True,
        )
    with banner_col:
        if not idx:
            st.markdown(
                "<div style='padding-top:10px; color:#888; text-align:right;'>"
                "（指數資料暫不可用）</div>",
                unsafe_allow_html=True,
            )
            return
        keys = ("twse", "otc", "tx_day", "tx_night")
        parts = []
        for k in keys:
            q = idx.get(k)
            if not q or q.last is None:
                continue
            chg = q.change or 0
            pct = q.change_pct or 0
            color = "#e55353" if chg > 0 else "#3dbd6e" if chg < 0 else "#aaa"
            arrow = "▲" if chg > 0 else "▼" if chg < 0 else "="
            parts.append(
                f"<div style='display:inline-block; margin:0 10px; "
                f"padding:6px 12px; border-left:3px solid {color}; "
                f"vertical-align:top;'>"
                f"<div style='color:#ccc; font-size:13px; font-weight:500;'>"
                f"{q.label}</div>"
                f"<div style='font-size:22px; font-weight:800; color:{color}; "
                f"line-height:1.2; letter-spacing:-0.3px;'>"
                f"{q.last:,.2f}</div>"
                f"<div style='color:{color}; font-size:13px; font-weight:600;'>"
                f"{arrow} {chg:+.2f} ({pct:+.2f}%)</div>"
                f"</div>"
            )
        parts.append(
            f"<div style='display:inline-block; color:#777; "
            f"font-size:12px; margin-left:6px; vertical-align:bottom;'>"
            f"⏱ {upd}</div>"
        )
        st.markdown(
            f"<div style='text-align:right; padding-top:0; "
            f"white-space:nowrap; overflow-x:auto;'>"
            f"{''.join(parts)}</div>",
            unsafe_allow_html=True,
        )


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
# 🚀 全域快取 wrappers — 減少重算，讓 Streamlit rerun 快取即回
# ============================================================
def _today_key() -> str:
    import datetime as _dt
    return _dt.date.today().isoformat()


@st.cache_data(ttl=900, show_spinner=False)
def cached_analyze(code: str, period: str, _day: str,
                   include_weekly: bool = True,
                   school: str | None = None):
    """完整分析：df + indicators + weekly + diagnosis. TTL 15 min.
    參數 _day 當日期 key，自動每日失效."""
    df_raw = data.fetch(code, period=period, interval="1d")
    df_full = indicators.add_all(df_raw)
    wk = None
    if include_weekly:
        try:
            wk_raw = data.fetch(code, period="2y", interval="1wk")
            wk = indicators.add_all(wk_raw)
        except Exception:
            pass
    diag = diagnosis.diagnose(df_full, code=code,
                              weekly_df=wk, school=school)
    return df_full, wk, diag


@st.cache_data(ttl=1800, show_spinner=False)
def cached_targets(code: str, _day: str):
    """多目標價 + 法人共識（含 yfinance info 慢呼叫）. TTL 30 min."""
    df_c, wk_c, diag_c = cached_analyze(code, "1y", _day)
    mo = None
    try:
        mo_raw = data.fetch(code, period="5y", interval="1mo")
        mo = indicators.add_all(mo_raw)
    except Exception:
        pass
    rev = cached_revenue(code, _day)
    return targets.compute_all(df_c, code, fib=diag_c.fib,
                               weekly_df=wk_c, monthly_df=mo,
                               revenue_info=rev)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_revenue(code: str, _day: str):
    try:
        return revenue.for_code(code)
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def cached_shareholders(code: str, _day: str):
    try:
        return shareholders.for_code(code)
    except Exception:
        return None


@st.cache_data(ttl=86400, show_spinner=False)
def cached_industry_info(code: str):
    try:
        return industry.info_for(code)
    except Exception:
        return None


# ============================================================
# 卡片渲染 (今日選股用)
# ============================================================
def render_card(row: pd.Series, rank: int, key_ns: str = "card"):
    d = row["_diag"]
    df = row["_df_tail"]
    code = str(row["代號"])
    score_icon = "🔴" if d.score > 0 else "🟢" if d.score < 0 else "⚪"
    chg_sign = "+" if row["漲跌%"] >= 0 else ""
    chg_color = ("#e55353" if row["漲跌%"] > 0
                 else "#3dbd6e" if row["漲跌%"] < 0 else "#aaa")
    import datetime as _dtk
    now_str = _dtk.datetime.now().strftime("%m-%d %H:%M")

    # --- 續漲/續跌 tag ---
    cont = ""
    if d.continuation_label == "續漲":
        cont = ("<span style='background:rgba(214,39,40,0.25); color:#ff8080;"
                " padding:2px 8px; border-radius:10px; font-size:11px;"
                " font-weight:600; margin-left:6px;'>📈 續漲</span>")
    elif d.continuation_label == "續跌":
        cont = ("<span style='background:rgba(44,160,44,0.25); color:#3dbd6e;"
                " padding:2px 8px; border-radius:10px; font-size:11px;"
                " font-weight:600; margin-left:6px;'>📉 續跌</span>")
    elif d.continuation_label == "震盪":
        cont = ("<span style='background:rgba(255,215,0,0.25); color:#ffd700;"
                " padding:2px 8px; border-radius:10px; font-size:11px;"
                " font-weight:600; margin-left:6px;'>↔️ 震盪</span>")

    # --- 產業 tag ---
    try:
        ind_info = industry.info_for(code)
        ind_name = ind_info["industry"] if ind_info else ""
    except Exception:
        ind_name = ""
    ind_tag = (f"<span style='background:rgba(100,180,255,0.2); color:#7ab8ff;"
               f" padding:1px 7px; border-radius:8px; font-size:11px;"
               f" margin-left:6px;'>{ind_name}</span>" if ind_name else "")

    # --- 月營收 YoY ---
    rev_text = ""
    try:
        rv = revenue.for_code(code)
        if rv and rv.yoy_pct:
            yoy_color = "#e55353" if rv.yoy_pct > 0 else "#3dbd6e"
            rev_text = (f"<span style='color:#888; margin-left:6px;'>"
                        f"月營收 <b style='color:#f5c342;'>"
                        f"{rv.revenue_k / 1e5:.1f}億</b> "
                        f"YoY <b style='color:{yoy_color};'>"
                        f"{rv.yoy_pct:+.1f}%</b></span>")
    except Exception:
        pass

    # --- 主型態 banner ---
    pattern_banner = ""
    primary_pat = next((p for p in d.chart_patterns
                        if p.signal != "neutral"),
                       d.chart_patterns[0] if d.chart_patterns else None)
    if primary_pat:
        pc = ("#d62728" if primary_pat.signal == "bull"
              else "#2ca02c" if primary_pat.signal == "bear"
              else "#ffd700")
        pi = ("📈" if primary_pat.signal == "bull"
              else "📉" if primary_pat.signal == "bear" else "↔️")
        pattern_banner = (
            f"<div style='padding:6px 10px; margin:6px 0; "
            f"border-left:3px solid {pc}; background:rgba(40,44,55,0.45);"
            f" border-radius:3px; font-size:12px;'>"
            f"<b style='color:{pc};'>{pi} {primary_pat.name}</b>"
            f"<span style='color:#bbb; margin-left:8px;'>"
            f"{primary_pat.note}</span></div>"
        )

    # --- 進場資訊 ---
    entry_str = ""
    if d.entry_zone:
        lo, hi = d.entry_zone
        price_now = row["收盤"]
        if price_now < lo:
            hint = "可佈局"
        elif price_now <= hi:
            hint = "✅ 已入進場區"
        else:
            hint = "等拉回"
        entry_str = (f"<span style='color:#ffdd55;'>💡 {lo:.2f}~{hi:.2f}</span>"
                     f" <span style='color:#999; font-size:12px;'>{hint}</span>")

    with st.container(border=True):
        # === 頂部 header (代號 名稱 tag + 現價 漲跌 + 分數建議) ===
        st.markdown(
            f"""
            <div style='line-height:1.35;'>
              <div style='font-size:13px;'>
                <b style='color:#fafafa; font-size:15px;'>
                  #{rank} {row['名稱']} ({code})
                </b>
                {cont}{ind_tag}
                <span style='color:#666; margin-left:8px; font-size:11px;'>
                  🕒 {now_str}</span>
                {rev_text}
              </div>
              <div style='margin:4px 0; display:flex;
                          align-items:baseline; gap:10px;'>
                <span style='font-size:11px; color:#999;'>現價</span>
                <span style='font-size:26px; font-weight:800; color:{chg_color};
                             letter-spacing:-0.5px;'>
                  {row['收盤']:.2f}
                </span>
                <span style='font-size:15px; font-weight:700; color:{chg_color};'>
                  {chg_sign}{row['漲跌%']:.2f}%
                </span>
                <span style='font-size:13px; color:#888; margin-left:8px;'>
                  {score_icon} <b>{d.score:+d}</b> · {d.stance}
                </span>
                <span style='font-size:13px; margin-left:8px;'>
                  {ACTION_ICONS.get(d.action, '')} <b>{d.action}</b>
                </span>
                <span style='margin-left:8px;'>{entry_str}</span>
              </div>
              {pattern_banner}
            </div>
            """,
            unsafe_allow_html=True,
        )

        # === 中型 K-chart（K + Vol + KD 三副圖）===
        # diag 已算好 multi_supports/resistances，直接用
        msup = d.multi_supports if d.multi_supports else []
        mres = d.multi_resistances if d.multi_resistances else []
        p_hist = row.get("_patterns_hist") \
            if "_patterns_hist" in row else d.candle_history
        fig = chart.build_card(
            df, height=400,
            supports=msup, resistances=mres,
            entry_zone=d.entry_zone,
            target_price=d.target_price,
            short_stop=d.short_stop,
            patterns_hist=p_hist,
        )
        st.plotly_chart(fig, use_container_width=True,
                        key=f"{key_ns}_chart_{rank}_{code}",
                        config={"displayModeBar": False})

        # === 指標 + 籌碼 兩列資訊 ===
        vol_brief = (d.volume_note.split("（")[0]
                     if "（" in d.volume_note else d.volume_note)
        # 取股權
        holder_html = ""
        try:
            hd = shareholders.for_code(code)
            if hd:
                holder_html = (
                    f"<span style='color:#ff8080;'>大戶 "
                    f"<b>{hd.big_pct:.1f}%</b></span> · "
                    f"<span style='color:#ffd700;'>中戶 "
                    f"<b>{hd.mid_pct:.1f}%</b></span> · "
                    f"<span style='color:#7ab8ff;'>散戶 "
                    f"<b>{hd.retail_pct:.1f}%</b></span> · "
                    f"<span style='color:#ffa500;'>千張 "
                    f"<b>{hd.kilo_pct:.1f}%</b></span> · "
                    f"<span style='color:#aaa;'>股東 "
                    f"<b style='color:#fafafa;'>{hd.total_holders:,}</b></span>"
                )
        except Exception:
            pass

        st.markdown(
            f"""
            <div style='font-size:12px; line-height:1.6; color:#bbb;
                        margin-top:4px;'>
              <span style='color:#888;'>均線</span> {d.ma_state} ·
              <span style='color:#888;'>波浪</span> {d.wave_label} ·
              <span style='color:#888;'>量</span> {vol_brief} ·
              <span style='color:#888;'>KD</span> {row['KD']} ·
              <span style='color:#888;'>RSI</span> {row['RSI']} ·
              <span style='color:#888;'>法人</span> {row['法人(張)']}張
              {' · ' + holder_html if holder_html else ''}
            </div>
            """,
            unsafe_allow_html=True,
        )

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
            watched = watchlist.contains(code)
            if st.button("🌟" if watched else "⭐",
                         key=f"{key_ns}_fav_{rank}_{code}",
                         use_container_width=True,
                         help="移除收藏" if watched else "加入收藏"):
                if watched:
                    watchlist.remove(code)
                else:
                    watchlist.add(code)
                st.rerun()
        with pa[5]:
            st.write("")
            if st.button("🔎", key=f"{key_ns}_detail_{rank}_{code}",
                         use_container_width=True, type="primary",
                         help="完整分析"):
                st.session_state._mode_override = "🔎 個股查詢"
                st.session_state.stock_code = code
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
    "<div style='font-size:17px; font-weight:700; line-height:1.35;'>"
    "Teddy中央印製廠<br>"
    "台北股市分析器<br>"
    "<span style='color:#ffd700;'>- 掙大錢 !</span>"
    "</div>",
    unsafe_allow_html=True,
)

if "app_mode" not in st.session_state:
    st.session_state.app_mode = "🎯 今日選股"

# === 啟動時自動從 GitHub 還原 K 線快取 + 實盤回測 DB ===
if "_ohlcv_restored" not in st.session_state:
    st.session_state._ohlcv_restored = True
    if storage.is_configured():
        try:
            ok, msg = price_cache.auto_restore()
            if ok:
                st.toast(f"☁️ K 線快取已從 GitHub 還原：{msg}", icon="✅")
        except Exception:
            pass
        try:
            ok, msg = realbacktest.auto_restore()
            if ok:
                st.toast(f"☁️ 實盤回測 DB 已還原：{msg}", icon="✅")
        except Exception:
            pass
# 處理上一輪 rerun 設定的模式切換意圖（必須在 widget 渲染前）
if "_mode_override" in st.session_state:
    st.session_state.app_mode = st.session_state.pop("_mode_override")

mode = st.sidebar.radio(
    "模式",
    ["🎯 今日選股", "🔎 個股查詢", "⭐ 收藏清單",
     "📈 多股比較", "📊 主動式ETF", "🔥 資金流向",
     "📋 實盤回測"],
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

    # 快取狀態 + 手動備份
    _pc_stats = price_cache.stats()
    with st.sidebar.expander(
            f"💾 K 線快取　"
            f"({_pc_stats['codes']} 檔 / {_pc_stats['db_size_kb']:.0f} KB)",
            expanded=False):
        # 容量視覺化：以 60 MB 循環錄影門檻為基準
        size_mb = _pc_stats["db_size_kb"] / 1024
        ratio = min(size_mb / 60.0, 1.0)
        st.progress(ratio,
                    text=f"📦 {size_mb:.1f} / 60 MB （循環錄影門檻）")
        st.caption(
            f"📅 日期範圍：{_pc_stats['date_range'][0] or '—'}"
            f" ~ {_pc_stats['date_range'][1] or '—'}\n\n"
            "🔁 循環錄影：DB 超過 60 MB 時，備份前自動刪除超過 1 年的舊資料。"
            "GitHub 單檔上限 100 MB，目前壓縮後僅占用 ~"
            f"{size_mb * 0.13:.1f} MB。"
        )
        if storage.is_configured():
            if st.button("☁️ 立即備份到 GitHub",
                         key="ohlcv_backup",
                         use_container_width=True,
                         help="超過 60 MB 自動刪 1 年前舊資料（循環錄影模式）"):
                with st.spinner("壓縮 + 上傳中…"):
                    ok, msg = price_cache.backup_with_rotation()
                if ok:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ {msg}")
            if st.button("⬇️ 從 GitHub 還原",
                         key="ohlcv_restore",
                         use_container_width=True):
                with st.spinner("下載 + 解壓中…"):
                    from analyzer.price_cache import DB_PATH as _PDB
                    ok, msg = storage.download_db(_PDB,
                                                   repo_path="data/ohlcv.db")
                if ok:
                    st.success(f"✅ {msg}")
                    st.rerun()
                elif "not found" in msg.lower():
                    st.info(
                        f"ℹ️ GitHub 上尚無 K 線備份。\n\n"
                        f"請先按「☁️ 立即備份到 GitHub」上傳目前 "
                        f"{_pc_stats['db_size_kb'] / 1024:.1f} MB 的資料"
                        f"（壓縮後僅 ~{_pc_stats['db_size_kb'] / 1024 * 0.13:.1f} MB），"
                        f"完成後雲端重開就會自動還原。"
                    )
                else:
                    st.warning(f"⚠️ {msg}")
            # Purge 按鈕：DB 太大時清舊資料
            # GitHub Contents API 上限 100 MB，gzip 後再壓 ~85%，所以 raw 70 MB 才需提醒
            if _pc_stats["db_size_kb"] > 70 * 1024:
                st.warning(
                    f"⚠️ DB {_pc_stats['db_size_kb'] / 1024:.1f} MB "
                    f"建議按「清除 > 1 年舊資料」釋放空間"
                )
            if st.button("🗑️ 清除 > 1 年舊資料",
                         key="ohlcv_purge",
                         use_container_width=True,
                         help="只保留近 1 年 K 線，VACUUM 壓縮 DB"):
                with st.spinner("清理中…"):
                    n = price_cache.purge_older_than(days=365)
                st.success(f"✅ 已刪除 {n} 列舊資料")
                st.rerun()
        elif storage.is_cloud():
            st.caption("⚠️ 雲端未設 secrets，重啟會遺失歷史")
        else:
            st.caption("💻 本機執行：資料已存於 data/ohlcv.db，無需備份")

    st.sidebar.caption("💡 首次掃描約 2~5 分鐘；第二次之後走快取只需 30 秒")

    render_market_sidebar()

    render_index_header()
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
            from analyzer.http import JSONFetchError as _JFE
            if isinstance(e, _JFE) or "Expecting value" in str(e):
                st.error(
                    "🌐 **掃描失敗：台股清單 API (TWSE/TPEX) 回應異常**\n\n"
                    f"`{e}`\n\n"
                    "可能原因：\n"
                    "1. TWSE/TPEX OpenAPI 暫時對 Streamlit Cloud IP 拒絕服務\n"
                    "2. 假日或盤後 API 偶發空值（此情況已自動 retry 2 次）\n"
                    "3. 網路超時\n\n"
                    "建議：稍後（5~10 分鐘）再試一次，或確認 "
                    "https://openapi.twse.com.tw 可達。"
                )
            else:
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
    full_df = result["full"]

    # 計算立即可進場的標的
    if "_in_entry_zone" in full_df.columns:
        imm_bull = full_df[(full_df["分數"] > 0) & full_df["_in_entry_zone"]] \
            .sort_values("分數", ascending=False).reset_index(drop=True)
        imm_bear = full_df[(full_df["分數"] < 0) & full_df["_in_entry_zone"]] \
            .sort_values("分數", ascending=True).reset_index(drop=True)
    else:
        imm_bull = imm_bear = pd.DataFrame()

    tab_imm, tab_long, tab_short, tab_all = st.tabs([
        f"⚡ 立即可進 ({len(imm_bull)} 多 / {len(imm_bear)} 空)",
        f"🔴 做多 Top {top_n}",
        f"🟢 做空 Top {top_n}",
        "📋 全部（表格）",
    ])

    def _render_grid(df_, ns: str = "card"):
        """2 欄網格渲染卡片：1 2 / 3 4 / 5 6..."""
        rows = df_.reset_index(drop=True)
        n = len(rows)
        for i in range(0, n, 2):
            col_l, col_r = st.columns(2, gap="small")
            with col_l:
                render_card(rows.iloc[i], i + 1, key_ns=ns)
            if i + 1 < n:
                with col_r:
                    render_card(rows.iloc[i + 1], i + 2, key_ns=ns)

    with tab_imm:
        st.caption("🎯 **現價位於建議進場區間**的標的 — 不用等拉回或反彈，依朱式戰法立刻可執行")
        sub_b, sub_s = st.tabs([
            f"🔴 立即做多 ({len(imm_bull)} 檔)",
            f"🟢 立即做空 ({len(imm_bear)} 檔)",
        ])
        with sub_b:
            if imm_bull.empty:
                st.info("⚠️ 目前無現價位於進場區的多方標的；考慮等拉回或查看 做多 Top。")
            else:
                _render_grid(imm_bull, ns="imm_b")
        with sub_s:
            if imm_bear.empty:
                st.info("⚠️ 目前無現價位於進場區的空方標的；考慮等反彈或查看 做空 Top。")
            else:
                _render_grid(imm_bear, ns="imm_s")

    with tab_long:
        if long_df.empty:
            st.warning("無符合條件的做多標的")
        else:
            _render_grid(long_df, ns="long")

    with tab_short:
        if short_df.empty:
            st.warning("無符合條件的做空標的")
        else:
            _render_grid(short_df, ns="short")

    with tab_all:
        if result["full"].empty:
            st.info("—")
        else:
            drop_cols = [c for c in ("_df_tail", "_diag",
                                      "_patterns_hist", "_in_entry_zone")
                         if c in result["full"].columns]
            display = result["full"].drop(columns=drop_cols) \
                .sort_values("分數", ascending=False).reset_index(drop=True)
            # 強制數值欄位型別一致，避免 Arrow None/float 混合錯誤
            for col in ("收盤", "漲跌%", "分數", "RSI", "日均量(張)",
                        "目標價", "短線停損", "風報比", "Hurst"):
                if col in display.columns:
                    display[col] = pd.to_numeric(display[col], errors="coerce")
            # 確保字串欄位為 string
            for col in ("代號", "名稱", "評估", "建議", "均線", "量價",
                        "波浪", "KD", "法人(張)", "融資/券", "費波"):
                if col in display.columns:
                    display[col] = display[col].astype(str).fillna("—")

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
    render_index_header()
    st.caption("📈 多股比較　·　疊加 2~5 檔標的相對走勢 + 排行 + 相關性")

    ind_df_cmp = industry.snapshot()
    # ETF 先加入選項
    ETF_OPTS = [
        "0050 元大台灣50", "0052 富邦科技", "0056 元大高股息",
        "006203 元大MSCI台灣", "006208 富邦台50",
        "00679B 元大美債20年", "00692 富邦公司治理",
        "00713 元大台灣高息低波", "00878 國泰永續高股息",
        "00881 國泰台灣5G+", "00891 中信關鍵半導體",
        "00892 富邦台灣半導體", "00893 國泰智能電動車",
        "00895 富邦未來車", "00896 中信綠能及電動車",
        "00900 富邦特選高股息", "00929 復華台灣科技優息",
        "00935 野村臺灣新科技50", "00939 統一台灣高息動能",
        "00940 元大台灣價值高息", "00941 中信上游半導體",
        "00981A 主動統一台股增長", "00982A 主動群益台灣強棒",
        "00991A 主動復華未來50", "00992A 主動群益科技創新",
        "00993A 主動安聯台灣",
    ]
    if ind_df_cmp.empty:
        opts_cmp = ETF_OPTS + ["2330 台積電"]
    else:
        opts_cmp = ETF_OPTS + (ind_df_cmp["code"] + " "
                               + ind_df_cmp["short_name"]).tolist()
    code_to_label = {o.split()[0]: o for o in opts_cmp}

    # ============================================================
    # 側邊欄：快速組合 + 自訂
    # ============================================================
    PRESETS = {
        "⭐ 我的收藏": watchlist.get(),
        "🔥 半導體三雄": ["2330", "2303", "2454"],
        "💻 電子五哥": ["2317", "2324", "2382", "2356", "2353"],
        "🚀 AI 概念": ["2330", "2454", "6446", "3231", "4938"],
        "🏦 金控四雄": ["2882", "2891", "2881", "2886"],
        "📊 大盤 ETF": ["0050", "0056", "006208"],
        "🔧 半導體 ETF": ["00891", "00892", "00941"],
        "💰 高息 ETF": ["0056", "00878", "00929", "00939", "00940"],
        "🚗 綠能車 ETF": ["00893", "00895", "00896"],
        "📊 主動式ETF Top 5": ["00981A", "00982A", "00991A",
                                "00992A", "00993A"],
    }

    st.sidebar.subheader("⚡ 快速組合")
    preset_col1, preset_col2 = st.sidebar.columns(2)
    preset_keys = list(PRESETS.keys())
    for i, k in enumerate(preset_keys):
        target_col = preset_col1 if i % 2 == 0 else preset_col2
        with target_col:
            if st.button(k, key=f"preset_{i}", use_container_width=True):
                st.session_state.cmp_picks = [
                    code_to_label.get(c, f"{c} -")
                    for c in PRESETS[k][:5]
                ]
                st.rerun()

    st.sidebar.subheader("🔍 自訂標的")
    default_picks = st.session_state.get("cmp_picks", ["2330 台積電"])
    picked = st.sidebar.multiselect(
        "股票（最多 5 檔）",
        opts_cmp,
        default=[p for p in default_picks if p in opts_cmp],
        max_selections=5,
        label_visibility="collapsed",
    )
    st.session_state.cmp_picks = picked

    st.sidebar.subheader("📅 期間與顯示")
    period_cmp = st.sidebar.selectbox(
        "觀察期間",
        ["5 日", "1 個月", "3 個月", "6 個月", "1 年", "2 年"],
        index=3,
    )
    p_map = {"5 日": "1mo", "1 個月": "1mo", "3 個月": "3mo",
             "6 個月": "6mo", "1 年": "1y", "2 年": "2y"}
    days_map = {"5 日": 5, "1 個月": 22, "3 個月": 66,
                "6 個月": 130, "1 年": 252, "2 年": 504}

    display_mode = st.sidebar.radio(
        "顯示模式",
        ["📈 相對漲幅 (%)", "💵 標準化價格", "📉 絕對價格"],
        index=0,
    )
    render_market_sidebar()

    if not picked:
        st.info("👈 點左側「快速組合」或自訂選取股票開始比較")
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

    # 截取期間指定的天數
    look = days_map.get(period_cmp, 130)
    aligned = {c: d.tail(look) for c, d in aligned.items()}
    if not aligned or not any(len(d) >= 2 for d in aligned.values()):
        st.error("資料不足以比較")
        st.stop()

    import plotly.graph_objects as _go2
    palette = ["#d62728", "#ff7f0e", "#1f77b4", "#9467bd", "#2ca02c"]

    # ==========================================================
    # 📊 領先/落後排行（主圖上方）
    # ==========================================================
    rank_rows = []
    for i, (c, d) in enumerate(aligned.items()):
        if d.empty or len(d) < 2:
            continue
        base = float(d["close"].iloc[0])
        last_p = float(d["close"].iloc[-1])
        ret_total = (last_p / base - 1) * 100
        rank_rows.append({
            "code": c,
            "label": f"{c} {names_cmp.get(c, '')}",
            "return": ret_total,
            "price": last_p,
            "base": base,
        })
    rank_rows.sort(key=lambda x: x["return"], reverse=True)

    st.markdown("#### 🏆 期間報酬排行")
    rank_fig = _go2.Figure(_go2.Bar(
        x=[r["return"] for r in rank_rows],
        y=[r["label"] for r in rank_rows],
        orientation="h",
        marker_color=["#d62728" if r["return"] >= 0 else "#2ca02c"
                      for r in rank_rows],
        text=[f"{r['return']:+.2f}%  ({r['price']:.2f})"
              for r in rank_rows],
        textposition="outside",
    ))
    rank_fig.update_layout(
        height=max(180, 48 * len(rank_rows) + 60),
        margin=dict(l=10, r=10, t=20, b=10),
        yaxis=dict(autorange="reversed"),
        xaxis_title=f"{period_cmp}報酬 %",
        showlegend=False,
    )
    st.plotly_chart(rank_fig, use_container_width=True,
                    config={"displayModeBar": False})

    # ==========================================================
    # 📈 主走勢圖
    # ==========================================================
    fig_cmp = _go2.Figure()
    perf_rows = []
    for i, (c, d) in enumerate(aligned.items()):
        if d.empty or len(d) < 2:
            continue
        base = float(d["close"].iloc[0])
        color = palette[i % len(palette)]
        name_full = f"{c} {names_cmp.get(c, '')}"

        if display_mode.startswith("📈"):  # 相對漲幅
            y = (d["close"] / base - 1) * 100
            y_title = "相對漲幅 (%)"
            hover = (f"<b>{name_full}</b><br>%{{x|%Y-%m-%d}}<br>"
                     "漲幅 %{y:.2f}%<br>"
                     "價 %{customdata:.2f}<extra></extra>")
        elif display_mode.startswith("💵"):  # 標準化價格
            y = d["close"] / base * 100
            y_title = "標準化價格 (起始=100)"
            hover = (f"<b>{name_full}</b><br>%{{x|%Y-%m-%d}}<br>"
                     "標準化 %{y:.2f}<br>"
                     "實際價 %{customdata:.2f}<extra></extra>")
        else:  # 絕對價格
            y = d["close"]
            y_title = "價格"
            hover = (f"<b>{name_full}</b><br>%{{x|%Y-%m-%d}}<br>"
                     "價格 %{y:.2f}<extra></extra>")

        fig_cmp.add_trace(_go2.Scatter(
            x=d.index, y=y, name=name_full,
            line=dict(color=color, width=2),
            customdata=d["close"],
            hovertemplate=hover,
        ))

        last_p = float(d["close"].iloc[-1])
        ret_total = (last_p / base - 1) * 100
        max_up = (float(d["close"].max()) / base - 1) * 100
        max_dn = (float(d["close"].min()) / base - 1) * 100
        daily_ret = d["close"].pct_change().dropna()
        vol_ann = (float(daily_ret.std()) * (252 ** 0.5) * 100
                   if not daily_ret.empty else 0.0)
        perf_rows.append({
            "代號": c, "名稱": names_cmp.get(c, ""),
            "期間報酬 %": round(ret_total, 2),
            "最大漲幅 %": round(max_up, 2),
            "最大回檔 %": round(max_dn, 2),
            "年化波動率 %": round(vol_ann, 1),
            "最新收盤": round(last_p, 2),
        })

    if display_mode.startswith("📈"):
        fig_cmp.add_hline(y=0, line_dash="dot", line_color="#888",
                          line_width=1)
    elif display_mode.startswith("💵"):
        fig_cmp.add_hline(y=100, line_dash="dot", line_color="#888",
                          line_width=1,
                          annotation_text="起始",
                          annotation_position="right")

    fig_cmp.update_layout(
        title=f"{display_mode.split()[1]}　·　{period_cmp}",
        height=560,
        margin=dict(l=10, r=10, t=60, b=10),
        hovermode="x unified",
        xaxis_title="", yaxis_title=y_title,
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
    st.markdown("#### 📊 績效比較表")
    perf_df = pd.DataFrame(perf_rows).sort_values("期間報酬 %",
                                                  ascending=False).reset_index(drop=True)

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
    render_index_header()
    st.caption("⭐ 收藏清單　·　追蹤常看股票、即時進場區警示")

    codes = watchlist.get()

    # 側邊欄：新增股票 + 清單管理
    st.sidebar.subheader("管理收藏")
    # 單次呼叫 snapshot 並過濾 NaN，避免雲端網路抖動或缺值導致渲染失敗
    try:
        _ind_df = industry.snapshot()
        if _ind_df is not None and not _ind_df.empty:
            _ind_df = _ind_df.dropna(subset=["code", "short_name"])
            wl_options = [""] + (_ind_df["code"].astype(str) + " "
                                 + _ind_df["short_name"].astype(str)).tolist()
        else:
            wl_options = [""]
    except Exception:
        wl_options = [""]
    add_sel = st.sidebar.selectbox(
        "新增", wl_options, index=0, key="wl_add",
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

    # 取得產業對照 + 即時報價（失敗不阻擋整頁，留給每檔 try 各自處理）
    try:
        ind_df = industry.snapshot()
        if ind_df is None:
            ind_df = pd.DataFrame(columns=["code", "short_name"])
    except Exception as e:
        st.warning(f"⚠️ 產業資料取得失敗（不影響分析）：{e}")
        ind_df = pd.DataFrame(columns=["code", "short_name"])

    quotes: dict = {}
    try:
        with st.spinner(f"抓取 {len(codes)} 檔即時報價 + 計算指標…"):
            quotes = live.quotes(codes)
    except Exception as e:
        st.warning(f"⚠️ 即時報價取得失敗，將使用日線收盤：{e}")

    # 逐檔分析 → 建構 render_card 可用的 row dict（多執行緒平行抓取）
    from concurrent.futures import ThreadPoolExecutor, as_completed
    rows_in_zone: list[dict] = []
    rows_other: list[dict] = []
    errors: list[tuple[str, str]] = []

    day_key = _today_key()

    def _analyze_one(code: str) -> tuple[str, dict | None, str | None]:
        try:
            raw, _wk, d = cached_analyze(code, "1y", day_key,
                                         include_weekly=False,
                                         school=DEFAULT_SCHOOL)
            q = quotes.get(code)
            if q and q.current:
                raw = live.overlay_today(raw, q)
                raw = indicators.add_all(raw)
                d = diagnosis.diagnose(raw, code=code,
                                       school=DEFAULT_SCHOOL)
            info_row = ind_df[ind_df["code"] == code]
            nm = (info_row.iloc[0]["short_name"]
                  if not info_row.empty else code)
            last = raw.iloc[-1]
            prev_close = (float(raw["close"].iloc[-2])
                          if len(raw) >= 2 else float(last["close"]))
            chg_pct = ((float(last["close"]) / prev_close - 1) * 100
                       if prev_close else 0.0)
            in_entry = False
            if d.entry_zone:
                lo, hi = d.entry_zone
                if lo <= float(last["close"]) <= hi:
                    in_entry = True
            row = {
                "代號": code,
                "名稱": nm,
                "收盤": round(float(last["close"]), 2),
                "漲跌%": round(chg_pct, 2),
                "分數": d.score,
                "KD": f"{last['k']:.0f}/{last['d']:.0f}",
                "RSI": round(float(last["rsi"]), 1),
                "法人(張)": (f"{d.institutional_info['total_net'] // 1000:+,}"
                             if d.institutional_info else "—"),
                "融資/券": ("融資±" if not d.margin_info else
                           f"資{d.margin_info['margin_change_pct']:+.1f}%"),
                "日均量(張)": int(raw["volume"].tail(20).mean() / 1000),
                "Hurst": round(d.econ.hurst, 2) if d.econ else None,
                "費波": (d.fib.nearest.name if (d.fib and d.fib.nearest
                         and d.fib.nearest_distance_pct <= 2.5) else "—"),
                "_df_tail": raw.tail(90).copy(),
                "_diag": d,
                "_patterns_hist": d.candle_history,
                "_in_entry_zone": in_entry,
            }
            return code, row, None
        except Exception as e:
            return code, None, str(e)[:80]

    progress = st.progress(0.0, text=f"平行分析 {len(codes)} 檔…")
    done = 0
    try:
        with ThreadPoolExecutor(max_workers=min(8, len(codes))) as ex:
            futures = {ex.submit(_analyze_one, c): c for c in codes}
            for fut in as_completed(futures):
                code, row, err = fut.result()
                done += 1
                progress.progress(done / len(codes),
                                  text=f"完成 {done}/{len(codes)}")
                if err:
                    errors.append((code, err))
                elif row:
                    (rows_in_zone if row["_in_entry_zone"]
                     else rows_other).append(row)
    finally:
        progress.empty()

    # 依原始順序排列（ThreadPool 完成順序不定）
    order = {c: i for i, c in enumerate(codes)}
    rows_in_zone.sort(key=lambda r: order.get(r["代號"], 999))
    rows_other.sort(key=lambda r: order.get(r["代號"], 999))

    # ---- 已達進場區警示（突出顯示）----
    if rows_in_zone:
        st.success(f"🚨 **{len(rows_in_zone)} 檔已達建議進場區間** — 可考慮佈局")
        # 金色外框包裝
        st.markdown(
            "<style>.entry-zone-card {border:2px solid #ffdd00 !important; "
            "box-shadow:0 0 14px rgba(255,221,0,0.28);}</style>",
            unsafe_allow_html=True,
        )
        for i, r in enumerate(rows_in_zone):
            render_card(pd.Series(r), i + 1, key_ns="wl_zone")

    # ---- 其他收藏 ----
    if rows_other:
        st.markdown(f"### 📋 其他收藏（{len(rows_other)} 檔）")
        for i, r in enumerate(rows_other):
            render_card(pd.Series(r), i + 1, key_ns="wl_other")

    if errors:
        with st.expander(f"⚠️ {len(errors)} 檔取得失敗"):
            for c, e in errors:
                st.error(f"{c}: {e}")
                if st.button(f"移除 {c}", key=f"wlerr_{c}"):
                    watchlist.remove(c)
                    st.rerun()


# ============================================================
# 🔥 資金流向 — 產業族群強弱排行
# ============================================================
elif mode == "🔥 資金流向":
    render_index_header()
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

    render_index_header()
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
        if storage.is_cloud():
            st.warning(
                "⚠️ **GitHub 持久化未設定** — Streamlit Cloud 重啟會遺失歷史資料。\n\n"
                "設定方式：到 **Streamlit Cloud → Settings → Secrets** 貼上：\n"
                "```toml\n[github]\ntoken = \"ghp_...\"  # 建 PAT 並給 repo 寫入權限\n"
                "owner = \"teddykuo00325-sys\"\nrepo = \"taipei-stock-analyzerteddy\"\n"
                "branch = \"main\"\ndb_path = \"data/etf.db\"\n```"
            )
        else:
            st.caption(
                "💻 本機執行：資料存於 `data/etf.db`，重啟仍保留。"
                "只有部署到 Streamlit Cloud 才需要設定 GitHub 備份。"
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
# 📋 實盤回測 — 鎖定當下推薦、追蹤未來表現
# ============================================================
elif mode == "📋 實盤回測":
    render_index_header()
    st.caption("📋 實盤回測　·　鎖定系統當下推薦、追蹤未來持有期間的真實 P&L")
    render_market_sidebar()

    # --- 側邊欄：建立新 session ---
    with st.sidebar.expander("➕ 新建回測 session", expanded=False):
        new_top_n = st.number_input("Top N（多/空各幾檔）", 1, 20, 5)
        new_capital = st.number_input(
            "資金 (TWD)", 100_000, 10_000_000, 1_000_000, 100_000,
        )
        new_hold_days = st.number_input("持有天數", 1, 60, 5)
        new_note = st.text_input("備註",
                                  value=f"{date.today().isoformat()} 實盤")
        if st.button("🚀 跑當前選股 + 鎖定", use_container_width=True,
                     type="primary"):
            with st.spinner("掃描中（首次約 1-3 分鐘）…"):
                res = screener.screen(
                    min_avg_volume_lots=1000,
                    top_n=int(new_top_n),
                    pre_filter_lots_today=200,
                )
            if res["passed"] == 0:
                st.error("掃描無通過篩選的股票")
            else:
                long_picks = res["long"].head(new_top_n).to_dict("records")
                short_picks = res["short"].head(new_top_n).to_dict("records")
                try:
                    sid_l = realbacktest.lock_session(
                        "long", long_picks, capital=new_capital,
                        hold_days=int(new_hold_days), note=new_note)
                    sid_s = realbacktest.lock_session(
                        "short", short_picks, capital=new_capital,
                        hold_days=int(new_hold_days), note=new_note)
                    st.success(f"✅ 已鎖定 long#{sid_l} + short#{sid_s}")
                    # 自動備份至 GitHub（雲端持久化）
                    if storage.is_configured():
                        try:
                            realbacktest.backup_now(
                                message=f"lock long#{sid_l} short#{sid_s}")
                        except Exception:
                            pass
                    st.rerun()
                except ValueError as e:
                    st.warning(f"⚠️ {e}")

    # --- 主畫面：列出所有 session ---
    sessions = realbacktest.list_sessions()
    if not sessions:
        st.info("尚未鎖定任何回測 session。請從左側「➕ 新建回測 session」開始，"
                "或先去「🎯 今日選股」確認當前推薦。")
        st.stop()

    # 統計卡片
    open_sessions = [s for s in sessions if s.status == "open"]
    closed_sessions = [s for s in sessions if s.status == "closed"]
    c1, c2, c3 = st.columns(3)
    c1.metric("進行中 sessions", len(open_sessions))
    c2.metric("已結算 sessions", len(closed_sessions))
    c3.metric("總投入 (進行中)",
              f"{sum(s.capital for s in open_sessions):,.0f}")

    st.divider()

    for sess in sessions:
        summary = realbacktest.session_summary(sess.id)
        if not summary:
            continue
        df = summary["holdings_df"]
        side_emoji = "🚀" if sess.side == "long" else "🐻"
        side_zh = "做多" if sess.side == "long" else "做空"
        status_emoji = "🟢" if sess.status == "open" else "✅"
        title = (f"{status_emoji} #{sess.id} {side_emoji} {side_zh}　"
                 f"{sess.lock_date} → {sess.target_exit_date}　"
                 f"｜ Top {sess.top_n} ｜ 資金 {sess.capital:,.0f}　"
                 f"｜ P&L {summary['total_pnl']:+,.0f} "
                 f"({summary['total_return_pct']:+.2f}%)")

        with st.expander(title, expanded=(sess.status == "open")):
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("總 P&L", f"{summary['total_pnl']:+,.0f}",
                       f"{summary['total_return_pct']:+.2f}%")
            mc2.metric("結算後資產",
                       f"{summary['final_capital']:,.0f}")
            mc3.metric("勝率",
                       f"{summary['win_rate']:.0f}%",
                       f"贏 {summary['win']} / 輸 {summary['lose']}")
            mc4.metric("無資料", summary["no_data"])

            # 持股明細
            disp = df.copy()
            disp.columns = ["代號", "名稱", "分數",
                            "進場價", "現價", "漲跌%", "P&L"]
            st.dataframe(
                disp.style.format({
                    "進場價": "{:.2f}",
                    "現價": "{:.2f}",
                    "漲跌%": "{:+.2f}%",
                    "P&L": "{:+,.0f}",
                }, na_rep="—").map(
                    lambda v: ("color: #4ade80" if isinstance(v, (int, float))
                               and v > 0 else
                               "color: #f87171" if isinstance(v, (int, float))
                               and v < 0 else ""),
                    subset=["漲跌%", "P&L"],
                ),
                use_container_width=True, hide_index=True,
            )

            # 結算 / 刪除按鈕
            ac1, ac2, ac3 = st.columns([1, 1, 4])
            with ac1:
                if sess.status == "open":
                    if st.button("📌 立即結算",
                                 key=f"close_{sess.id}",
                                 help="以最新收盤鎖定 exit_price"):
                        n, pnl = realbacktest.close_session(sess.id)
                        st.success(f"✅ 結算 {n} 檔，總 P&L {pnl:+,.0f}")
                        if storage.is_configured():
                            try:
                                realbacktest.backup_now(
                                    message=f"close session#{sess.id}")
                            except Exception:
                                pass
                        st.rerun()
            with ac2:
                if st.button("🗑️ 刪除", key=f"del_{sess.id}",
                             help="移除整個 session（不可復原）"):
                    realbacktest.delete_session(sess.id)
                    if storage.is_configured():
                        try:
                            realbacktest.backup_now(
                                message=f"delete session#{sess.id}")
                        except Exception:
                            pass
                    st.rerun()


# ============================================================
# 🔎 個股查詢
# ============================================================
else:
    st.sidebar.subheader("查詢條件")
    if "stock_code" not in st.session_state:
        st.session_state.stock_code = "2330"

    # --- B. 自動補齊：以產業表建立下拉 options + 常見 ETF ---
    ETF_CATALOG = [
        ("0050", "元大台灣50", "大盤 ETF"),
        ("0052", "富邦科技", "科技 ETF"),
        ("0056", "元大高股息", "高股息 ETF"),
        ("006203", "元大MSCI台灣", "大盤 ETF"),
        ("006208", "富邦台50", "大盤 ETF"),
        ("00679B", "元大美債20年", "債券 ETF"),
        ("00692", "富邦公司治理", "ESG ETF"),
        ("00713", "元大台灣高息低波", "高股息 ETF"),
        ("00878", "國泰永續高股息", "ESG ETF"),
        ("00881", "國泰台灣5G+", "5G ETF"),
        ("00891", "中信關鍵半導體", "半導體 ETF"),
        ("00892", "富邦台灣半導體", "半導體 ETF"),
        ("00893", "國泰智能電動車", "電動車 ETF"),
        ("00895", "富邦未來車", "電動車 ETF"),
        ("00896", "中信綠能及電動車", "綠能 ETF"),
        ("00900", "富邦特選高股息", "高股息 ETF"),
        ("00929", "復華台灣科技優息", "科技高息 ETF"),
        ("00935", "野村臺灣新科技50", "科技 ETF"),
        ("00939", "統一台灣高息動能", "高股息 ETF"),
        ("00940", "元大台灣價值高息", "高股息 ETF"),
        ("00941", "中信上游半導體", "半導體 ETF"),
        ("00981A", "主動統一台股增長", "主動式 ETF"),
        ("00982A", "主動群益台灣強棒", "主動式 ETF"),
        ("00991A", "主動復華未來50", "主動式 ETF"),
        ("00992A", "主動群益科技創新", "主動式 ETF"),
        ("00993A", "主動安聯台灣", "主動式 ETF"),
    ]

    @st.cache_data(ttl=86400, show_spinner=False)
    def _stock_options() -> list[str]:
        opts: list[str] = []
        # ETF 放最上面
        for code, name, cat in ETF_CATALOG:
            opts.append(f"{code} {name} · {cat}")
        # 再接個股
        df = industry.snapshot()
        if not df.empty:
            opts += (df["code"] + " " + df["short_name"]
                     + " · " + df["industry"]).tolist()
        if not opts:
            opts = ["2330 台積電"]
        return opts

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
    # 圖表預設顯示交易日數（zoom in 偏短；讓型態文字有空間）
    display_days_map = {
        "1 個月": 22, "3 個月": 45, "6 個月": 80,
        "1 年": 150, "2 年": 300, "5 年": 800,
    }
    period_map = fetch_map  # 相容原變數名

    live_on = st.sidebar.checkbox(
        "🔴 盤中即時更新", value=False,
        help="啟用後會抓取 TWSE MIS 即時報價覆蓋今日 K 線；僅在日線模式有效",
    )

    # --- K 線圖輔助線顯示控制 ---
    with st.sidebar.expander("🎨 圖表 overlay 開關", expanded=False):
        show_patterns = st.checkbox("K 線型態標記", value=True)
        show_waves = st.checkbox("波浪轉折 (H/L)", value=True)
        show_fib = st.checkbox("費波納契級位", value=True)
        show_trend_lines = st.checkbox("上升/下降切線", value=True)
        show_plan = st.checkbox("進場區/目標/停損", value=True)
        show_sr = st.checkbox("支撐/壓力", value=True)

    go_btn = st.sidebar.button("🔍 開始分析", use_container_width=True, type="primary")

    render_market_sidebar()

    render_index_header()
    st.caption("🔎 個股查詢")

    # 從今日選股跳轉時自動觸發
    auto_trigger = st.session_state.pop("auto_analyze", False)

    if not (go_btn or auto_trigger):
        st.info("👈 於左側輸入股票代號後按『開始分析』\n\n"
                "本系統綜合：四均線戰法、K 線型態、量價、KD/MACD/RSI、"
                "型態學、波浪理論、三大法人、融資融券 → 產生個股診斷書。")
        st.stop()

    # === 統一快取路徑：日線直接走 cached_analyze ===
    live_quote = None
    if interval_label == "日線":
        with st.spinner("分析中…（首次約 2-5 秒，之後走快取）"):
            try:
                df, weekly_df, diag = cached_analyze(
                    code, period_map[period_label], _today_key(),
                    include_weekly=True, school=DEFAULT_SCHOOL,
                )
            except ValueError as e:
                st.error(str(e))
                st.stop()
            except Exception as e:
                st.error(f"分析失敗：{e}")
                st.stop()
            # 盤中即時覆蓋
            if live_on:
                live_quote = live.quote(code)
                if live_quote:
                    df_raw = live.overlay_today(df, live_quote)
                    df = indicators.add_all(df_raw)
                    diag = diagnosis.diagnose(df, code=code,
                                              weekly_df=weekly_df,
                                              school=DEFAULT_SCHOOL)
            name = data.get_name(code)
    else:
        # 週線 / 月線：直接呼叫（頻率低）
        with st.spinner("抓取資料中…"):
            try:
                df_raw = data.fetch(code, period=period_map[period_label],
                                    interval=interval_map[interval_label])
            except ValueError as e:
                st.error(str(e))
                st.stop()
            df = indicators.add_all(df_raw)
            weekly_df = None
            diag = diagnosis.diagnose(df, code=code,
                                      weekly_df=None,
                                      school=DEFAULT_SCHOOL)
            name = data.get_name(code)

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

    info = cached_industry_info(code)
    ind_name = info["industry"] if info else "—"
    full_name = info["full_name"] if info else name
    rev_info = cached_revenue(code, _today_key())

    # ============================================================
    # 📌 頂部：大標題列（名稱/代號 + 現價超大）
    # ============================================================
    import datetime as _dt_ind
    now_str = _dt_ind.datetime.now().strftime("%Y-%m-%d %H:%M")
    # 續漲/續跌標籤
    cont_tag = ""
    if diag.continuation_label == "續漲":
        cont_tag = ("<span style='background:rgba(214,39,40,0.3); "
                    "color:#ff8080; padding:4px 10px; border-radius:12px; "
                    "font-size:15px; font-weight:700; margin-left:10px;'>"
                    "📈 續漲</span>")
    elif diag.continuation_label == "續跌":
        cont_tag = ("<span style='background:rgba(44,160,44,0.3); "
                    "color:#3dbd6e; padding:4px 10px; border-radius:12px; "
                    "font-size:15px; font-weight:700; margin-left:10px;'>"
                    "📉 續跌</span>")
    elif diag.continuation_label == "震盪":
        cont_tag = ("<span style='background:rgba(255,215,0,0.3); "
                    "color:#ffd700; padding:4px 10px; border-radius:12px; "
                    "font-size:15px; font-weight:700; margin-left:10px;'>"
                    "↔️ 震盪</span>")
    # 產業標籤
    ind_tag = (f"<span style='background:rgba(100,180,255,0.25); "
               f"color:#7ab8ff; padding:3px 10px; border-radius:10px; "
               f"font-size:14px; font-weight:600; margin-left:8px;'>"
               f"{ind_name}</span>" if ind_name and ind_name != "—" else "")
    chg_color = "#e55353" if chg > 0 else "#3dbd6e" if chg < 0 else "#aaa"
    chg_sign = "+" if chg >= 0 else ""
    arrow = "▲" if chg > 0 else "▼" if chg < 0 else "="

    # 大標題：股票名稱 + 代號 + 標籤 | 現價超大
    rev_line = ""
    if rev_info and rev_info.yoy_pct:
        yoy_c = "#e55353" if rev_info.yoy_pct > 0 else "#3dbd6e"
        rev_line = (f"<span style='font-size:13px; color:#bbb; "
                    f"margin-left:12px;'>"
                    f"📊 {rev_info.year_month} 營收 "
                    f"<b style='color:#f5c342;'>"
                    f"{rev_info.revenue_k / 1e5:.1f}億</b> "
                    f"YoY <b style='color:{yoy_c};'>"
                    f"{rev_info.yoy_pct:+.1f}%</b></span>")

    st.markdown(
        f"""
        <div style='display:flex; justify-content:space-between;
                    align-items:center; flex-wrap:wrap; gap:10px;
                    padding:10px 4px; border-bottom:2px solid #333;
                    margin-bottom:12px;'>
          <div style='flex:1; min-width:250px;'>
            <div style='font-size:28px; font-weight:800; color:#fafafa;
                        line-height:1.2;'>
              {name}
              <span style='color:#bbb; font-size:22px; font-weight:700;
                           margin-left:8px;'>({code})</span>
              {cont_tag}{ind_tag}
            </div>
            <div style='font-size:12px; color:#888; margin-top:4px;'>
              🏭 {full_name[:30]} · 🕒 {now_str}{rev_line}
            </div>
          </div>
          <div style='text-align:right;'>
            <div style='font-size:11px; color:#999;'>現價</div>
            <div style='font-size:46px; font-weight:800; color:{chg_color};
                        letter-spacing:-1px; line-height:1;'>
              {price:,.2f}
            </div>
            <div style='font-size:17px; font-weight:700; color:{chg_color};
                        margin-top:2px;'>
              {arrow} {chg_sign}{chg:.2f} ({chg_sign}{chg_pct:.2f}%)
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 下面 4 欄小資訊
    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("成交量", f"{int(last['volume']):,}",
               f"{(last['volume'] / last['vol_ma5'] - 1) * 100:+.1f}% vs 5MA")
    sc2.metric("多空評分", f"{diag.score:+d}", diag.stance)
    sc3.metric(f"{ACTION_ICONS.get(diag.action, '')} 建議", diag.action)
    if diag.risk_reward is not None:
        rr_label = ("🟢 優" if diag.risk_reward >= 2
                    else "🟡 可" if diag.risk_reward >= 1 else "🔴 差")
        sc4.metric("風險報酬比", f"{diag.risk_reward:.2f} : 1", rr_label)
    else:
        sc4.metric("風險報酬比", "—")

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
    col_p, col_t, col_e, col_s = st.columns(4)
    with col_p:
        # 現價
        st.metric("📍 現價", f"{price:,.2f}",
                  f"{chg_sign}{chg:.2f} ({chg_sign}{chg_pct:.2f}%)")
        st.caption(f"{arrow} 當前成交價")
    with col_t:
        if diag.target_price:
            pct = (diag.target_price / price - 1) * 100
            st.metric("🎯 目標價", f"{diag.target_price:,.2f}", f"{pct:+.2f}%")
            st.caption(f"依據：{diag.target_note}")
        else:
            st.metric("🎯 目標價", "—")
    with col_e:
        if diag.entry_zone:
            lo, hi = diag.entry_zone
            st.metric("💡 建議進場區", f"{lo:,.2f} ~ {hi:,.2f}")
            if price < lo:
                st.caption("✅ 現價低於進場區，可分批佈局")
            elif price <= hi:
                st.caption("✅ 現價位於進場區內")
            else:
                st.caption("⚠️ 現價高於進場區，等待拉回")
        else:
            st.metric("💡 建議進場區", "—")
    with col_s:
        if diag.short_stop:
            pct = (diag.short_stop / price - 1) * 100
            st.metric("🛑 短線停損 (MA10)",
                      f"{diag.short_stop:,.2f}", f"{pct:+.2f}%")
        if diag.mid_stop:
            pct = (diag.mid_stop / price - 1) * 100
            st.caption(f"中線停損 (MA20)：**{diag.mid_stop:,.2f}**（{pct:+.2f}%）")
        st.caption(f"絕對停損：**{diag.abs_stop:,.2f}**")

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
        # 直接用 diag 內已計算好的，省去重複運算
        candle_hist = diag.candle_history
        multi_sup = diag.multi_supports
        multi_res = diag.multi_resistances
        # wave_pivots 需 list[(idx, H/L, price)] 格式，diag 已提供
        class _W:
            pass
        w_detail = _W()
        w_detail.pivots = diag.wave_pivots

        # ---- 型態銘牌（主 bull/bear 型態）----
        primary_pat = None
        for p in diag.chart_patterns:
            if p.signal != "neutral":
                primary_pat = p
                break
        if not primary_pat and diag.chart_patterns:
            primary_pat = diag.chart_patterns[0]
        if primary_pat:
            badge_color = ("#d62728" if primary_pat.signal == "bull"
                           else "#2ca02c" if primary_pat.signal == "bear"
                           else "#ffd700")
            badge_icon = ("📈" if primary_pat.signal == "bull"
                          else "📉" if primary_pat.signal == "bear" else "↔️")
            st.markdown(
                f"<div style='padding:10px 16px; margin-bottom:6px; "
                f"border-left:4px solid {badge_color}; "
                f"background:rgba(40,44,55,0.55); border-radius:4px;'>"
                f"<div style='font-size:16px; font-weight:700;'>"
                f"{badge_icon} {primary_pat.name}</div>"
                f"<div style='font-size:13px; color:#ccc; margin-top:3px;'>"
                f"{primary_pat.note}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        # ---- 技術指標 Pills（圖表上方） ----

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
        trend_info = {"support": diag.support,
                      "resistance": diag.resistance} if show_sr else None
        # 取股權歷史供籌碼 subplot 使用
        try:
            chip_hist = shareholders.history(code)
        except Exception:
            chip_hist = None
        fig = chart.build(
            df, title=f"{name} ({code}) · {interval_label}",
            patterns=diag.chart_patterns if show_patterns else [],
            fib=diag.fib if show_fib else None,
            wave_pivots=w_detail.pivots if show_waves else None,
            trend=trend_info,
            candle_history=candle_hist if show_patterns else [],
            econ=diag.econ,
            entry_zone=diag.entry_zone if show_plan else None,
            target_price=diag.target_price if show_plan else None,
            short_stop=diag.short_stop if show_plan else None,
            mid_stop=diag.mid_stop if show_plan else None,
            display_days=display_days_map.get(period_label, 130),
            show_trend_lines=show_trend_lines,
            multi_supports=multi_sup if show_sr else None,
            multi_resistances=multi_res if show_sr else None,
            chip_history=chip_hist,
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
            "📖 **圖例**：🟥 紅實線=主壓力　·　🟩 綠實線=主支撐　·　"
            "🟦 藍虛線=多級支撐　·　🟧 橘虛線=多級壓力　·　"
            "🟪 紫虛線=費波納契　·　▲▼(編號)=波浪 · "
            "三角形=K 線型態（hover 看含意）"
        )

        # ---- 底部：籌碼 summary bar + 成本區 ----
        try:
            holder_sum = cached_shareholders(code, _today_key())
        except Exception:
            holder_sum = None
        # 成本區（近 30 日均價 ± σ）
        cz_lo = cz_hi = cz_avg = None
        if len(df) >= 30:
            tail30 = df["close"].tail(30)
            cz_avg = float(tail30.mean())
            cz_std = float(tail30.std())
            cz_lo = round(cz_avg - cz_std, 2)
            cz_hi = round(cz_avg + cz_std, 2)

        st.markdown("---")
        sb1, sb2 = st.columns([3, 2])
        with sb1:
            if holder_sum:
                st.markdown(
                    f"""
                    <div style='display:flex; gap:16px; flex-wrap:wrap;
                                font-size:14px;'>
                      <div><span style='color:#e55353; font-size:18px;'>●</span>
                        <b style='margin-left:4px;'>大戶</b>
                        <span style='color:#ff8080; font-weight:700;
                                     font-size:16px; margin-left:3px;'>
                          {holder_sum.big_pct:.1f}%</span></div>
                      <div><span style='color:#ffd700; font-size:18px;'>●</span>
                        <b style='margin-left:4px;'>中戶</b>
                        <span style='font-weight:700; font-size:16px;
                                     margin-left:3px;'>
                          {holder_sum.mid_pct:.1f}%</span></div>
                      <div><span style='color:#7ab8ff; font-size:18px;'>●</span>
                        <b style='margin-left:4px;'>散戶</b>
                        <span style='color:#7ab8ff; font-weight:700;
                                     font-size:16px; margin-left:3px;'>
                          {holder_sum.retail_pct:.1f}%</span></div>
                      <div><span style='color:#ffa500; font-size:18px;'>●</span>
                        <b style='margin-left:4px;'>千張</b>
                        <span style='color:#ffa500; font-weight:700;
                                     font-size:16px; margin-left:3px;'>
                          {holder_sum.kilo_pct:.1f}%</span></div>
                      <div style='color:#888;'>股東
                        <b style='color:#fafafa; margin-left:4px;'>
                          {holder_sum.total_holders:,}</b> 人</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.caption("籌碼資料尚不可用")
        with sb2:
            if cz_lo and cz_hi:
                pct = ((price - cz_avg) / cz_avg * 100) if cz_avg else 0
                warn_icon = ("⚠️" if abs(pct) > 20
                             else "✅" if abs(pct) < 5 else "")
                color = ("#ff6060" if pct > 15
                         else "#3dbd6e" if pct < -15 else "#ffd700")
                st.markdown(
                    f"""
                    <div style='text-align:right; font-size:14px;'>
                      <span style='color:#aaa;'>📍 成本區 (30日均±σ)：</span>
                      <b style='color:#f5c342;'>{cz_lo:.2f} ~ {cz_hi:.2f}</b>
                      <span style='color:{color}; margin-left:6px;'>
                        {pct:+.1f}%</span> {warn_icon}
                    </div>
                    """,
                    unsafe_allow_html=True,
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

    # ---- 🎯 關鍵價位（多目標 + 費波 + 支撐壓力） ----
    with tab_level:
        # ========== 多目標價區 ==========
        st.markdown("#### 🎯 多層級目標價")
        # 走快取（15-30 min TTL，yfinance info 慢呼叫只跑一次）
        target_data = cached_targets(code, _today_key())
        t_list = target_data["targets"]
        if t_list:
            # 法人共識卡
            analyst = target_data["analyst"]
            if analyst:
                rec_color = {
                    "strong_buy": "#d62728", "buy": "#e67e22",
                    "hold": "#f5c342", "sell": "#3dbd6e",
                    "strong_sell": "#2ca02c", "none": "#888",
                }.get(analyst["recommend"], "#888")
                rec_label = {
                    "strong_buy": "強烈買進", "buy": "買進",
                    "hold": "持有", "sell": "賣出",
                    "strong_sell": "強烈賣出", "none": "—",
                }.get(analyst["recommend"], analyst["recommend"])
                st.markdown(
                    f"""
                    <div style='padding:12px 18px;
                                background:linear-gradient(90deg,
                                    rgba(148,103,189,0.18), rgba(148,103,189,0));
                                border-left:4px solid #9467bd;
                                border-radius:6px; margin-bottom:10px;'>
                      <div style='display:flex;
                                  justify-content:space-between;
                                  flex-wrap:wrap; align-items:baseline;'>
                        <div>
                          <span style='font-size:16px; font-weight:700;'>
                            🏦 法人共識目標</span>
                          <span style='color:#aaa; margin-left:8px;
                                       font-size:12px;'>
                            {analyst['n']} 位分析師
                          </span>
                          <span style='background:{rec_color};
                                       color:#fff; padding:2px 8px;
                                       border-radius:8px; font-size:12px;
                                       font-weight:700; margin-left:10px;'>
                            {rec_label}
                          </span>
                        </div>
                        <div>
                          <span style='font-size:26px; font-weight:800;
                                       color:#9467bd;'>
                            {analyst['mean']:.2f}
                          </span>
                          <span style='color:#9467bd; margin-left:6px;
                                       font-size:14px;'>
                            ({(analyst['mean'] / price - 1) * 100:+.1f}%)
                          </span>
                        </div>
                      </div>
                      <div style='font-size:12px; color:#bbb;
                                  margin-top:6px;'>
                        區間 <b style='color:#3dbd6e;'>
                          {analyst['low']:.2f}</b> (最低) ~
                        <b style='color:#e55353;'>
                          {analyst['high']:.2f}</b> (最高)
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            # 各目標表格
            t_rows = [{
                "目標類型": f"{t.icon} {t.label}",
                "價格": f"{t.price:,.2f}",
                "距現價": f"{t.pct:+.2f}%",
                "信心": t.confidence,
                "依據": t.note,
            } for t in t_list]
            def _col_pct(v):
                try:
                    x = float(str(v).replace("%", "").replace("+", ""))
                except Exception:
                    return ""
                if x > 0:
                    return "color:#e55353; font-weight:600;"
                if x < 0:
                    return "color:#3dbd6e; font-weight:600;"
                return ""
            styled = (pd.DataFrame(t_rows).style
                      .map(_col_pct, subset=["距現價"]))
            st.dataframe(styled, use_container_width=True, hide_index=True)

            # 基本面 PE 卡
            fund = target_data["fundamental"]
            if fund:
                fc = st.columns(3)
                fc[0].metric("forwardEPS",
                             f"{fund['forward_eps']:.2f}")
                fc[1].metric("trailingPE",
                             f"{fund['trailing_pe']:.1f}")
                fc[2].metric("forwardPE",
                             f"{fund['forward_pe']:.1f}"
                             if fund['forward_pe'] else "—")
        else:
            st.info("目前無可用目標價")

        st.markdown("---")
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

        st.markdown("#### 📦 股權分布 (集保 TDCC · 每週更新)")
        try:
            holder = cached_shareholders(code, _today_key())
        except Exception:
            holder = None
        if not holder:
            st.info("無股權分散資料")
        else:
            hc = st.columns(5)
            hc[0].metric("🌟 千張大戶",
                         f"{holder.kilo_pct:.2f}%",
                         "> 100萬 股")
            hc[1].metric("🏦 大戶",
                         f"{holder.big_pct:.2f}%",
                         "10~100 萬股")
            hc[2].metric("🧑‍💼 中戶",
                         f"{holder.mid_pct:.2f}%",
                         "1萬~5萬股")
            hc[3].metric("👥 散戶",
                         f"{holder.retail_pct:.2f}%",
                         "< 1萬股")
            hc[4].metric("總股東",
                         f"{holder.total_holders:,}",
                         f"@ {holder.date}")
            # 歷史趨勢圖（若有 2 筆以上）
            hist = shareholders.history(code)
            if len(hist) >= 2:
                import plotly.graph_objects as _go_h
                fig_h = _go_h.Figure()
                hist["date"] = pd.to_datetime(hist["date"])
                fig_h.add_trace(_go_h.Scatter(
                    x=hist["date"], y=hist["kilo_pct"],
                    mode="lines+markers", name="千張大戶 %",
                    line=dict(color="#ffd700", width=2)))
                fig_h.add_trace(_go_h.Scatter(
                    x=hist["date"], y=hist["retail_pct"],
                    mode="lines+markers", name="散戶 %",
                    line=dict(color="#1f77b4", width=2)))
                fig_h.update_layout(
                    height=260, margin=dict(l=10, r=10, t=30, b=10),
                    title="股權分散歷史趨勢",
                    yaxis_title="佔比 %",
                    legend=dict(orientation="h", y=1.1),
                )
                st.plotly_chart(fig_h, use_container_width=True,
                                config={"displayModeBar": False})
            else:
                st.caption("💡 每次查詢會累積一筆快照，多查幾次後自動呈現歷史趨勢。")

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
