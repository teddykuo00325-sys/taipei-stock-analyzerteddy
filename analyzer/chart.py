"""Plotly K 線圖 — 朱式四均線、成交量、MACD、KD."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def build(df: pd.DataFrame, title: str = "", patterns=None,
          fib=None, wave_pivots=None, trend=None,
          candle_history=None, econ=None) -> go.Figure:
    """建構多面板技術圖表.

    參數：
      patterns: list[Pattern]         — W 底/M 頭等，自動繪頸線
      fib: FibAnalysis                — 費波納契級位
      wave_pivots: list[(idx, H/L, price)] — 波浪轉折點
      trend: dict                      — {support, resistance}
      candle_history: list[(df_idx, [Candle, ...])] — 歷史 K 線型態
      econ: Econ                       — 計量物理結果（供右上角標註）
    """
    patterns = patterns or []
    candle_history = candle_history or []
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.52, 0.15, 0.17, 0.16], vertical_spacing=0.02,
        subplot_titles=("K 線 + 四均線 + 支撐壓力 + 費波納契", "成交量", "MACD", "KD"),
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

    # 波浪轉折點標記（含編號 1~5 或 H/L）
    abs_pivots: list[tuple[int, str, float]] = []
    if wave_pivots:
        lookback = 120 if len(df) >= 120 else len(df)
        tail_start = len(df) - lookback
        for (idx, typ, price) in wave_pivots:
            actual_idx = tail_start + idx
            if 0 <= actual_idx < len(df):
                abs_pivots.append((actual_idx, typ, price))

    # 近 6 個轉折加上編號標籤（5-4-3-2-1 倒序代表波浪次序）
    if abs_pivots:
        recent = abs_pivots[-6:]
        wave_nums = list(range(len(recent), 0, -1))  # 6,5,4,3,2,1
        for (actual_idx, typ, price), num in zip(recent, wave_nums):
            date = df.index[actual_idx]
            marker_color = "#d62728" if typ == "H" else "#2ca02c"
            label = f"{typ}{num}"
            fig.add_trace(
                go.Scatter(
                    x=[date], y=[price], mode="markers+text",
                    marker=dict(size=11, color=marker_color,
                                symbol="triangle-down" if typ == "H"
                                else "triangle-up",
                                line=dict(color="white", width=1)),
                    text=[label],
                    textposition="top center" if typ == "H" else "bottom center",
                    textfont=dict(size=10, color=marker_color,
                                  family="sans-serif"),
                    showlegend=False, hoverinfo="skip",
                ),
                row=1, col=1,
            )

    # --- 自動繪製近期上升/下降切線 ---
    if abs_pivots and len(abs_pivots) >= 3:
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

    # --- K 線型態歷史標記（近 60 日發生者）---
    if candle_history:
        seen_name = set()
        for (cand_idx, candles) in candle_history[-10:]:  # 最近 10 個型態點
            if cand_idx >= len(df):
                continue
            date = df.index[cand_idx]
            for c in candles:
                # 同名型態同位置只標一次
                key = (cand_idx, c.name)
                if key in seen_name:
                    continue
                seen_name.add(key)
                is_bull = c.signal == "bull"
                y_at = df["low"].iloc[cand_idx] * 0.985 if is_bull \
                    else df["high"].iloc[cand_idx] * 1.015
                arrow_color = "#d62728" if is_bull else "#2ca02c"
                fig.add_annotation(
                    x=date, y=y_at,
                    text=f"<b>{c.name}</b>",
                    showarrow=True, arrowhead=2, arrowsize=1,
                    arrowwidth=1.2, arrowcolor=arrow_color,
                    ax=0, ay=25 if is_bull else -25,
                    font=dict(size=10, color=arrow_color,
                              family="sans-serif"),
                    bgcolor="rgba(14,17,23,0.85)",
                    bordercolor=arrow_color, borderwidth=0.8,
                    borderpad=2,
                    row=1, col=1,
                )

    # --- Hurst / 計量物理角落標註 ---
    if econ is not None:
        fig.add_annotation(
            xref="paper", yref="paper", x=0.01, y=0.99,
            text=(f"🔬 Hurst={econ.hurst:.2f} · "
                  f"波動 {econ.vol_recent * 100:.0f}%（x{econ.vol_ratio:.2f}）"),
            showarrow=False,
            font=dict(size=11, color="#ccc"),
            bgcolor="rgba(20,24,35,0.8)",
            bordercolor="rgba(148,103,189,0.4)", borderwidth=0.8,
            borderpad=4, xanchor="left", yanchor="top",
        )

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

    fig.update_layout(
        title=title, height=820, xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=1.04, x=0),
        hovermode="x unified",
    )
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    return fig


def mini(df: pd.DataFrame, height: int = 160) -> go.Figure:
    """迷你 K 線圖 — 供卡片式清單使用."""
    tail = df.tail(60)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=tail.index, open=tail["open"], high=tail["high"],
        low=tail["low"], close=tail["close"], showlegend=False,
        increasing=dict(line=dict(color="#d62728"), fillcolor="#d62728"),
        decreasing=dict(line=dict(color="#2ca02c"), fillcolor="#2ca02c"),
    ))
    for p, c in [(5, "#ff7f0e"), (20, "#9467bd")]:
        col = f"ma{p}"
        if col in tail.columns:
            fig.add_trace(go.Scatter(
                x=tail.index, y=tail[col], mode="lines",
                line=dict(color=c, width=1),
                showlegend=False, hoverinfo="skip",
            ))
    fig.update_layout(
        height=height, margin=dict(l=2, r=2, t=2, b=2),
        xaxis_rangeslider_visible=False,
        xaxis=dict(visible=False, rangebreaks=[dict(bounds=["sat", "mon"])]),
        yaxis=dict(visible=False),
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig
