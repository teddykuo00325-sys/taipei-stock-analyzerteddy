"""Plotly K 線圖 — 朱式四均線、成交量、MACD、KD."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def build(df: pd.DataFrame, title: str = "", patterns=None,
          fib=None, wave_pivots=None, trend=None,
          candle_history=None, econ=None,
          entry_zone=None, target_price=None,
          short_stop=None, mid_stop=None,
          display_days: int = 130,
          show_trend_lines: bool = True) -> go.Figure:
    """建構多面板技術圖表.

    參數：
      patterns: list[Pattern]         — W 底/M 頭等，自動繪頸線
      fib: FibAnalysis                — 費波納契級位
      wave_pivots: list[(idx, H/L, price)] — 波浪轉折點
      trend: dict                      — {support, resistance}
      candle_history: list[(df_idx, [Candle, ...])]
      econ: Econ                       — 計量物理 (供右上角標註)
      entry_zone: (lo, hi)             — 建議進場區間（畫水平帶）
      target_price: float              — 目標價（橘色水平線）
      short_stop: float                — 短線停損（綠色水平線）
      mid_stop: float                  — 中線停損（淡綠水平線）
    """
    patterns = patterns or []
    candle_history = candle_history or []
    # K 線佔 65%，空出更多縱向空間
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.66, 0.12, 0.11, 0.11], vertical_spacing=0.015,
        subplot_titles=("K 線圖", "成交量", "MACD", "KD"),
    )

    # --- K 線 (台股紅漲綠跌) ---
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name="K",
            increasing=dict(line=dict(color="#d62728"), fillcolor="#d62728"),
            decreasing=dict(line=dict(color="#2ca02c"), fillcolor="#2ca02c"),
        ), row=1, col=1,
    )
    colors = {5: "#ff7f0e", 10: "#1f77b4", 20: "#9467bd", 60: "#8c564b"}
    for p, c in colors.items():
        col = f"ma{p}"
        if col in df.columns:
            fig.add_trace(
                go.Scatter(x=df.index, y=df[col], name=f"MA{p}",
                           line=dict(color=c, width=1)),
                row=1, col=1,
            )

    # 型態頸線標示
    for pat in patterns:
        if pat.neckline:
            fig.add_hline(
                y=pat.neckline, line_dash="dash", line_color="#888",
                annotation_text=f"{pat.name} 頸線 {pat.neckline:.2f}",
                annotation_position="top left",
                row=1, col=1,
            )

    # 支撐 / 壓力
    if trend:
        sup = trend.get("support")
        res = trend.get("resistance")
        if sup:
            fig.add_hline(
                y=sup, line_dash="solid", line_color="rgba(44,160,44,0.55)",
                line_width=1.5,
                annotation_text=f"支撐 {sup:.2f}",
                annotation_position="bottom right",
                annotation_font_color="#2ca02c",
                row=1, col=1,
            )
        if res:
            fig.add_hline(
                y=res, line_dash="solid", line_color="rgba(214,39,40,0.55)",
                line_width=1.5,
                annotation_text=f"壓力 {res:.2f}",
                annotation_position="top right",
                annotation_font_color="#d62728",
                row=1, col=1,
            )

    # 費波納契關鍵級位（38.2% / 50% / 61.8% + 最近級位）
    if fib and fib.levels:
        keys_to_draw = {"38.2% 回檔", "50.0% 回檔", "61.8% 回檔",
                        "38.2% 反彈", "50.0% 反彈", "61.8% 反彈"}
        for lv in fib.levels:
            if lv.name in keys_to_draw or \
               (fib.nearest and lv.name == fib.nearest.name):
                color = "rgba(148,103,189,0.55)"  # 紫
                fig.add_hline(
                    y=lv.price, line_dash="dot", line_color=color,
                    line_width=1,
                    annotation_text=f"Fib {lv.name} {lv.price:.2f}",
                    annotation_position="top left",
                    annotation_font_color="#7a4db5",
                    annotation_font_size=9,
                    row=1, col=1,
                )

    # 波浪轉折點標記（簡化：只標最近 4 個，較小字型）
    abs_pivots: list[tuple[int, str, float]] = []
    if wave_pivots:
        lookback = 120 if len(df) >= 120 else len(df)
        tail_start = len(df) - lookback
        for (idx, typ, price) in wave_pivots:
            actual_idx = tail_start + idx
            if 0 <= actual_idx < len(df):
                abs_pivots.append((actual_idx, typ, price))

    if abs_pivots:
        recent = abs_pivots[-4:]
        wave_nums = list(range(len(recent), 0, -1))
        for (actual_idx, typ, price), num in zip(recent, wave_nums):
            date = df.index[actual_idx]
            marker_color = "#d62728" if typ == "H" else "#2ca02c"
            fig.add_trace(
                go.Scatter(
                    x=[date], y=[price], mode="markers+text",
                    marker=dict(size=9, color=marker_color,
                                symbol="triangle-down" if typ == "H"
                                else "triangle-up",
                                line=dict(color="white", width=0.8)),
                    text=[f"{typ}{num}"],
                    textposition="top center" if typ == "H" else "bottom center",
                    textfont=dict(size=8, color=marker_color),
                    showlegend=False, hoverinfo="skip",
                    name="波浪",
                ),
                row=1, col=1,
            )

    # --- 自動繪製近期上升/下降切線 ---
    if show_trend_lines and abs_pivots and len(abs_pivots) >= 3:
        lows = [(i, p) for i, t, p in abs_pivots if t == "L"]
        highs = [(i, p) for i, t, p in abs_pivots if t == "H"]
        # 上升切線：最近兩個低點且第二個 > 第一個
        if len(lows) >= 2:
            i1, p1 = lows[-2]
            i2, p2 = lows[-1]
            if p2 > p1 and i2 > i1:
                # 延伸到最新日期
                slope = (p2 - p1) / (i2 - i1)
                ext_i = len(df) - 1
                ext_p = p2 + slope * (ext_i - i2)
                fig.add_trace(
                    go.Scatter(
                        x=[df.index[i1], df.index[ext_i]],
                        y=[p1, ext_p], mode="lines",
                        line=dict(color="rgba(44,160,44,0.75)",
                                  width=2, dash="dash"),
                        name="上升切線",
                        showlegend=False, hoverinfo="skip",
                    ),
                    row=1, col=1,
                )
        # 下降切線：最近兩個高點且第二個 < 第一個
        if len(highs) >= 2:
            i1, p1 = highs[-2]
            i2, p2 = highs[-1]
            if p2 < p1 and i2 > i1:
                slope = (p2 - p1) / (i2 - i1)
                ext_i = len(df) - 1
                ext_p = p2 + slope * (ext_i - i2)
                fig.add_trace(
                    go.Scatter(
                        x=[df.index[i1], df.index[ext_i]],
                        y=[p1, ext_p], mode="lines",
                        line=dict(color="rgba(214,39,40,0.75)",
                                  width=2, dash="dash"),
                        name="下降切線",
                        showlegend=False, hoverinfo="skip",
                    ),
                    row=1, col=1,
                )

    # --- K 線型態標記（icon only，hover 解說）---
    if candle_history:
        seen_name = set()
        bull_x, bull_y, bull_hover = [], [], []
        bear_x, bear_y, bear_hover = [], [], []
        neutral_x, neutral_y, neutral_hover = [], [], []
        for (cand_idx, candles) in candle_history[-12:]:
            if cand_idx >= len(df):
                continue
            date = df.index[cand_idx]
            for c in candles:
                key = (cand_idx, c.name)
                if key in seen_name:
                    continue
                seen_name.add(key)
                is_bull = c.signal == "bull"
                is_bear = c.signal == "bear"
                tmpl = (f"<b>{c.name}</b><br>"
                        f"日期：{date.date()}<br>"
                        f"含意：{c.note}<br>訊號：")
                if is_bull:
                    y = df["low"].iloc[cand_idx] * 0.985
                    bull_x.append(date); bull_y.append(y)
                    bull_hover.append(tmpl + "🔴 偏多")
                elif is_bear:
                    y = df["high"].iloc[cand_idx] * 1.015
                    bear_x.append(date); bear_y.append(y)
                    bear_hover.append(tmpl + "🟢 偏空")
                else:
                    y = df["high"].iloc[cand_idx] * 1.015
                    neutral_x.append(date); neutral_y.append(y)
                    neutral_hover.append(tmpl + "⚪ 中性")

        if bull_x:
            fig.add_trace(go.Scatter(
                x=bull_x, y=bull_y, mode="markers",
                marker=dict(symbol="triangle-up", size=10, color="#d62728",
                            line=dict(color="white", width=0.8)),
                hovertext=bull_hover, hoverinfo="text",
                name="多頭型態", showlegend=True,
            ), row=1, col=1)
        if bear_x:
            fig.add_trace(go.Scatter(
                x=bear_x, y=bear_y, mode="markers",
                marker=dict(symbol="triangle-down", size=10, color="#2ca02c",
                            line=dict(color="white", width=0.8)),
                hovertext=bear_hover, hoverinfo="text",
                name="空頭型態", showlegend=True,
            ), row=1, col=1)
        if neutral_x:
            fig.add_trace(go.Scatter(
                x=neutral_x, y=neutral_y, mode="markers",
                marker=dict(symbol="diamond", size=8, color="#aaa",
                            line=dict(color="white", width=0.8)),
                hovertext=neutral_hover, hoverinfo="text",
                name="中性型態", showlegend=True,
            ), row=1, col=1)

    # --- 進場區 / 目標 / 停損 水平線（交易計畫）---
    if entry_zone:
        lo_e, hi_e = entry_zone
        fig.add_hrect(
            y0=lo_e, y1=hi_e,
            fillcolor="rgba(255,255,0,0.12)",
            layer="below", line_width=0,
            annotation_text=f"💡 建議進場區 {lo_e:.2f} ~ {hi_e:.2f}",
            annotation_position="top right",
            annotation_font=dict(size=10, color="#ffdd00"),
            row=1, col=1,
        )
    if target_price:
        fig.add_hline(
            y=target_price, line_dash="solid",
            line_color="rgba(255,165,0,0.85)", line_width=2,
            annotation_text=f"🎯 目標 {target_price:.2f}",
            annotation_position="top left",   # 左側避免與壓力衝突
            annotation_font_color="#ffa500",
            annotation_font_size=11,
            row=1, col=1,
        )
    if short_stop:
        fig.add_hline(
            y=short_stop, line_dash="longdashdot",
            line_color="rgba(44,160,44,0.9)", line_width=2,
            annotation_text=f"🛑 短線停損 {short_stop:.2f}",
            annotation_position="bottom left",
            annotation_font_color="#2ca02c",
            annotation_font_size=11,
            row=1, col=1,
        )
    if mid_stop and (not short_stop or abs(mid_stop - short_stop) > 0.5):
        fig.add_hline(
            y=mid_stop, line_dash="dot",
            line_color="rgba(44,160,44,0.55)", line_width=1.5,
            annotation_text=f"中線停損 {mid_stop:.2f}",
            annotation_position="bottom left",
            annotation_font_color="#2ca02c",
            annotation_font_size=10,
            row=1, col=1,
        )

    # 註：技術指標數值改由 app.py 以 pills 顯示在圖表上方，不再占用圖內空間

    # --- 成交量 ---
    vol_color = [
        "#d62728" if c >= o else "#2ca02c"
        for c, o in zip(df["close"], df["open"])
    ]
    fig.add_trace(
        go.Bar(x=df.index, y=df["volume"], name="Vol",
               marker_color=vol_color, showlegend=False),
        row=2, col=1,
    )
    if "vol_ma5" in df.columns:
        fig.add_trace(
            go.Scatter(x=df.index, y=df["vol_ma5"], name="量 MA5",
                       line=dict(color="#ff7f0e", width=1)),
            row=2, col=1,
        )

    # --- MACD ---
    if "macd_dif" in df.columns:
        hist_color = ["#d62728" if v >= 0 else "#2ca02c" for v in df["macd_hist"]]
        fig.add_trace(go.Bar(x=df.index, y=df["macd_hist"], name="Hist",
                             marker_color=hist_color, showlegend=False),
                      row=3, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["macd_dif"], name="DIF",
                                 line=dict(color="#1f77b4", width=1)), row=3, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["macd_dem"], name="DEM",
                                 line=dict(color="#ff7f0e", width=1)), row=3, col=1)

    # --- KD ---
    if "k" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["k"], name="K",
                                 line=dict(color="#1f77b4", width=1)), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["d"], name="D",
                                 line=dict(color="#ff7f0e", width=1)), row=4, col=1)
        fig.add_hline(y=80, line_dash="dot", line_color="#aaa", row=4, col=1)
        fig.add_hline(y=20, line_dash="dot", line_color="#aaa", row=4, col=1)

    # 依使用者選擇的期間決定預設顯示範圍
    if len(df) > 0:
        end_dt = df.index[-1]
        start_dt = df.index[max(0, len(df) - display_days)]
    else:
        start_dt = end_dt = None

    fig.update_layout(
        title=title, height=960, xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=80, b=10),
        legend=dict(orientation="h", y=1.05, x=0, font=dict(size=10)),
        hovermode="x unified",
        dragmode="pan",
        hoverlabel=dict(bgcolor="rgba(20,24,35,0.9)", font_size=12),
    )
    # 時間軸 range selector（在所有 subplot 共用）
    fig.update_xaxes(
        rangebreaks=[dict(bounds=["sat", "mon"])],
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikedash="dot", spikecolor="#888", spikethickness=1,
    )
    fig.update_yaxes(
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikedash="dot", spikecolor="#888", spikethickness=1,
    )
    # 在最上方 subplot 加 range selector 與預設縮放
    if start_dt and end_dt:
        fig.update_xaxes(
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1M", step="month", stepmode="backward"),
                    dict(count=3, label="3M", step="month", stepmode="backward"),
                    dict(count=6, label="6M", step="month", stepmode="backward"),
                    dict(step="year", stepmode="todate", label="YTD"),
                    dict(count=1, label="1Y", step="year", stepmode="backward"),
                    dict(step="all", label="全部"),
                ],
                bgcolor="rgba(40,44,55,0.8)",
                activecolor="#d62728",
                font=dict(color="#fafafa", size=11),
                x=0, y=1.12, xanchor="left",
            ),
            range=[start_dt, end_dt],
            row=1, col=1,
        )
    return fig


def mini(df: pd.DataFrame, height: int = 160,
         patterns_hist=None) -> go.Figure:
    """迷你 K 線圖 — 供卡片式清單使用.

    patterns_hist: [(df_idx, [Candle, ...]), ...]  近期型態發生點
    """
    tail = df.tail(60)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=tail.index, open=tail["open"], high=tail["high"],
        low=tail["low"], close=tail["close"], showlegend=False,
        increasing=dict(line=dict(color="#d62728"), fillcolor="#d62728"),
        decreasing=dict(line=dict(color="#2ca02c"), fillcolor="#2ca02c"),
        hoverinfo="x+y",
    ))
    for p, c in [(5, "#ff7f0e"), (10, "#1f77b4"), (20, "#9467bd")]:
        col = f"ma{p}"
        if col in tail.columns:
            fig.add_trace(go.Scatter(
                x=tail.index, y=tail[col], mode="lines", name=f"MA{p}",
                line=dict(color=c, width=1),
                showlegend=False, hoverinfo="skip",
            ))

    # 最近 2-3 個型態標記（帶 hover）
    if patterns_hist:
        tail_start = len(df) - len(tail)
        markers_x, markers_y, markers_text, markers_hover = [], [], [], []
        markers_color, markers_sym = [], []
        for cand_idx, candles in patterns_hist[-3:]:
            if cand_idx < tail_start or cand_idx >= len(df):
                continue
            date = df.index[cand_idx]
            for c in candles[:1]:  # 只取第一個避免擁擠
                is_bull = c.signal == "bull"
                y = df["low"].iloc[cand_idx] * 0.98 if is_bull \
                    else df["high"].iloc[cand_idx] * 1.02
                markers_x.append(date); markers_y.append(y)
                markers_text.append(c.name)
                markers_hover.append(f"<b>{c.name}</b><br>{c.note}")
                markers_color.append("#d62728" if is_bull
                                     else "#2ca02c" if c.signal == "bear"
                                     else "#aaa")
                markers_sym.append("triangle-up" if is_bull
                                   else "triangle-down" if c.signal == "bear"
                                   else "diamond")
        if markers_x:
            fig.add_trace(go.Scatter(
                x=markers_x, y=markers_y, mode="markers+text",
                marker=dict(size=9, color=markers_color, symbol=markers_sym),
                text=markers_text, textposition="top center",
                textfont=dict(size=8, color="#fff"),
                hovertext=markers_hover, hoverinfo="text",
                showlegend=False,
            ))

    fig.update_layout(
        height=height, margin=dict(l=2, r=2, t=2, b=2),
        xaxis_rangeslider_visible=False,
        xaxis=dict(visible=False, rangebreaks=[dict(bounds=["sat", "mon"])]),
        yaxis=dict(visible=False),
        plot_bgcolor="rgba(0,0,0,0)",
        dragmode="pan",
    )
    return fig
