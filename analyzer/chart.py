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
          show_trend_lines: bool = True,
          multi_supports: list[float] | None = None,
          multi_resistances: list[float] | None = None,
          chip_history: pd.DataFrame | None = None) -> go.Figure:
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
    # 如有籌碼歷史 → 5 subplot; 否則 4 subplot
    has_chip = (chip_history is not None and not chip_history.empty
                and len(chip_history) >= 1)
    if has_chip:
        fig = make_subplots(
            rows=5, cols=1, shared_xaxes=True,
            row_heights=[0.56, 0.11, 0.10, 0.11, 0.12],
            vertical_spacing=0.012,
            subplot_titles=("K 線圖", "成交量", "MACD", "KD",
                            "籌碼 (大戶 / 散戶 %)"),
        )
    else:
        fig = make_subplots(
            rows=4, cols=1, shared_xaxes=True,
            row_heights=[0.66, 0.12, 0.11, 0.11],
            vertical_spacing=0.015,
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

    # 型態頸線標示（依多/空著色，更顯眼）
    for pat in patterns:
        if pat.neckline:
            if pat.signal == "bull":
                lcolor = "rgba(214,39,40,0.85)"   # 紅 bull
                font_color = "#ff6060"
            elif pat.signal == "bear":
                lcolor = "rgba(44,160,44,0.85)"   # 綠 bear
                font_color = "#3dbd6e"
            else:
                lcolor = "rgba(255,215,0,0.75)"   # 黃中性
                font_color = "#ffd700"
            fig.add_hline(
                y=pat.neckline, line_dash="dash",
                line_color=lcolor, line_width=1.8,
                annotation_text=f"<b>{pat.name}</b> 頸線 {pat.neckline:.2f}",
                annotation_position="top left",
                annotation_font_color=font_color,
                annotation_font_size=11,
                annotation_bgcolor="rgba(20,24,35,0.85)",
                annotation_bordercolor=font_color,
                annotation_borderwidth=0.8,
                annotation_borderpad=3,
                row=1, col=1,
            )

    # 主要支撐 / 壓力
    if trend:
        sup = trend.get("support")
        res = trend.get("resistance")
        if sup:
            fig.add_hline(
                y=sup, line_dash="solid", line_color="rgba(44,160,44,0.75)",
                line_width=2,
                annotation_text=f"主支撐 {sup:.2f}",
                annotation_position="bottom right",
                annotation_font_color="#3dbd6e",
                annotation_font_size=11,
                row=1, col=1,
            )
        if res:
            fig.add_hline(
                y=res, line_dash="solid", line_color="rgba(214,39,40,0.75)",
                line_width=2,
                annotation_text=f"主壓力 {res:.2f}",
                annotation_position="top right",
                annotation_font_color="#ff6060",
                annotation_font_size=11,
                row=1, col=1,
            )

    # 多級支撐（藍色虛線，接近現價的更顯眼）
    if multi_supports:
        for i, p in enumerate(multi_supports):
            opacity = 0.6 - i * 0.12
            fig.add_hline(
                y=p, line_dash="dash",
                line_color=f"rgba(100,180,255,{max(opacity, 0.2)})",
                line_width=1,
                annotation_text=f"支 {p:.2f}",
                annotation_position="right",
                annotation_font_color="#7ab8ff",
                annotation_font_size=9,
                row=1, col=1,
            )
    # 多級壓力（橘色虛線）
    if multi_resistances:
        for i, p in enumerate(multi_resistances):
            opacity = 0.6 - i * 0.12
            fig.add_hline(
                y=p, line_dash="dash",
                line_color=f"rgba(255,180,100,{max(opacity, 0.2)})",
                line_width=1,
                annotation_text=f"壓 {p:.2f}",
                annotation_position="right",
                annotation_font_color="#ffb464",
                annotation_font_size=9,
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

    # --- K 線型態標記 ---
    # 分兩層：最近 6 個帶文字標籤、其餘只有 icon（避免擁擠但保留資訊）
    if candle_history:
        seen_name = set()
        # 分別收集：帶字 / 不帶字 兩組
        def _empty():
            return {"x": [], "y": [], "txt": [], "hv": []}
        labeled = {"bull": _empty(), "bear": _empty(), "neutral": _empty()}
        icon_only = {"bull": _empty(), "bear": _empty(), "neutral": _empty()}

        # 取全部，最近 6 個帶字、前面只圖示
        all_events = []
        for (cand_idx, candles) in candle_history[-14:]:
            if cand_idx >= len(df):
                continue
            for c in candles:
                key = (cand_idx, c.name)
                if key in seen_name:
                    continue
                seen_name.add(key)
                all_events.append((cand_idx, c))
        # 按日期排序
        all_events.sort(key=lambda x: x[0])
        n_lbl = 6
        for i, (cand_idx, c) in enumerate(all_events):
            date = df.index[cand_idx]
            is_bull = c.signal == "bull"
            is_bear = c.signal == "bear"
            kind = "bull" if is_bull else "bear" if is_bear else "neutral"
            y = (df["low"].iloc[cand_idx] * 0.98 if is_bull
                 else df["high"].iloc[cand_idx] * 1.02)
            hover = (f"<b>{c.name}</b><br>"
                     f"日期：{date.date()}<br>"
                     f"含意：{c.note}<br>訊號：" +
                     ("🔴 偏多" if is_bull else
                      "🟢 偏空" if is_bear else "⚪ 中性"))
            # 最近 n_lbl 個帶字、其餘只圖示
            target = (labeled[kind] if i >= len(all_events) - n_lbl
                      else icon_only[kind])
            target["x"].append(date)
            target["y"].append(y)
            target["txt"].append(c.name)
            target["hv"].append(hover)

        symbols = {"bull": "triangle-up", "bear": "triangle-down",
                   "neutral": "diamond"}
        colors = {"bull": "#d62728", "bear": "#2ca02c", "neutral": "#aaa"}
        positions = {"bull": "bottom center", "bear": "top center",
                     "neutral": "top center"}
        names = {"bull": "多頭型態", "bear": "空頭型態", "neutral": "中性型態"}

        # 帶文字層（最近 6 個）
        for kind, data in labeled.items():
            if not data["x"]:
                continue
            fig.add_trace(go.Scatter(
                x=data["x"], y=data["y"], mode="markers+text",
                marker=dict(symbol=symbols[kind], size=12, color=colors[kind],
                            line=dict(color="white", width=0.8)),
                text=data["txt"], textposition=positions[kind],
                textfont=dict(size=10, color=colors[kind]),
                hovertext=data["hv"], hoverinfo="text",
                name=names[kind], showlegend=True,
            ), row=1, col=1)
        # 只圖示層（較舊）
        for kind, data in icon_only.items():
            if not data["x"]:
                continue
            fig.add_trace(go.Scatter(
                x=data["x"], y=data["y"], mode="markers",
                marker=dict(symbol=symbols[kind], size=8,
                            color=colors[kind], opacity=0.65,
                            line=dict(color="white", width=0.5)),
                hovertext=data["hv"], hoverinfo="text",
                name=f"{names[kind]} (較舊)", showlegend=False,
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
    if "vol_ma20" in df.columns:
        fig.add_trace(
            go.Scatter(x=df.index, y=df["vol_ma20"], name="量 MA20",
                       line=dict(color="#ffd700", width=1.2, dash="dash")),
            row=2, col=1,
        )
        # 爆量星號：vol > 2x VMA20
        burst_mask = df["volume"] > df["vol_ma20"] * 2
        if burst_mask.any():
            bx = df.index[burst_mask]
            by = df["volume"][burst_mask]
            hover = [f"🌟 爆量 {v / 1000:,.0f} 張<br>"
                     f"= {df.at[d, 'volume'] / df.at[d, 'vol_ma20']:.1f}x VMA20"
                     for d, v in zip(bx, by)]
            fig.add_trace(go.Scatter(
                x=bx, y=by, mode="markers",
                marker=dict(symbol="star", size=11, color="#ffd700",
                            line=dict(color="#fff", width=0.8)),
                hovertext=hover, hoverinfo="text",
                name="爆量", showlegend=False,
            ), row=2, col=1)

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
        # 過熱 / 超賣 區域背景色
        fig.add_hrect(y0=80, y1=100,
                      fillcolor="rgba(214,39,40,0.12)",
                      layer="below", line_width=0,
                      row=4, col=1)
        fig.add_hrect(y0=0, y1=20,
                      fillcolor="rgba(44,160,44,0.12)",
                      layer="below", line_width=0,
                      row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["k"], name="K",
                                 line=dict(color="#1f77b4", width=1.4)),
                      row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["d"], name="D",
                                 line=dict(color="#ff7f0e", width=1.4)),
                      row=4, col=1)
        fig.add_hline(y=80, line_dash="dot", line_color="#888", row=4, col=1)
        fig.add_hline(y=20, line_dash="dot", line_color="#888", row=4, col=1)

        # --- KD 金叉 / 死叉 歷史標記 ---
        gold_x, gold_y, gold_h = [], [], []
        death_x, death_y, death_h = [], [], []
        for i in range(1, len(df)):
            prev_k = df["k"].iloc[i - 1]
            prev_d = df["d"].iloc[i - 1]
            curr_k = df["k"].iloc[i]
            curr_d = df["d"].iloc[i]
            if pd.isna(prev_k) or pd.isna(curr_k):
                continue
            dt = df.index[i]
            if prev_k <= prev_d and curr_k > curr_d:
                gold_x.append(dt)
                gold_y.append(float(curr_k))
                gold_h.append(f"🟡 KD 金叉<br>{dt.date()}<br>"
                              f"K={curr_k:.0f} D={curr_d:.0f}")
            elif prev_k >= prev_d and curr_k < curr_d:
                death_x.append(dt)
                death_y.append(float(curr_k))
                death_h.append(f"🔻 KD 死叉<br>{dt.date()}<br>"
                               f"K={curr_k:.0f} D={curr_d:.0f}")

        if gold_x:
            fig.add_trace(go.Scatter(
                x=gold_x, y=gold_y, mode="markers",
                marker=dict(symbol="circle", size=8, color="#ffd700",
                            line=dict(color="#222", width=0.8)),
                hovertext=gold_h, hoverinfo="text",
                name="KD 金叉", showlegend=False,
            ), row=4, col=1)
        if death_x:
            fig.add_trace(go.Scatter(
                x=death_x, y=death_y, mode="markers",
                marker=dict(symbol="x", size=9, color="#d62728",
                            line=dict(color="#fff", width=1)),
                hovertext=death_h, hoverinfo="text",
                name="KD 死叉", showlegend=False,
            ), row=4, col=1)

        # KD 過熱 / 過冷 標籤（依最新 K 值）
        last_k = df["k"].iloc[-1] if not pd.isna(df["k"].iloc[-1]) else 50
        last_d = df["d"].iloc[-1] if not pd.isna(df["d"].iloc[-1]) else 50
        badge = ""
        badge_color = ""
        if last_k >= 80 and last_d >= 80:
            badge, badge_color = "● 過熱", "#ff6060"
        elif last_k >= 80:
            badge, badge_color = "● 偏熱", "#ffa500"
        elif last_k <= 20 and last_d <= 20:
            badge, badge_color = "● 過冷", "#3dbd6e"
        elif last_k <= 20:
            badge, badge_color = "● 偏冷", "#7ab8ff"
        if badge:
            fig.add_annotation(
                xref="x4 domain" if False else "paper",
                yref="y4 domain",
                x=1.0, y=0.95,
                text=f"<b>{badge}</b>",
                showarrow=False,
                font=dict(size=12, color=badge_color),
                bgcolor="rgba(20,24,35,0.85)",
                bordercolor=badge_color, borderwidth=1,
                borderpad=3,
                xanchor="right", yanchor="top",
                row=4, col=1,
            )

    # --- 籌碼 subplot (row=5): 大戶% / 散戶% 歷史 ---
    if has_chip and chip_history is not None:
        ch = chip_history.copy()
        ch["date"] = pd.to_datetime(ch["date"])
        fig.add_trace(go.Scatter(
            x=ch["date"], y=ch["kilo_pct"],
            mode="lines+markers", name="千張大戶 %",
            line=dict(color="#ffd700", width=2),
            marker=dict(size=6),
            showlegend=False,
        ), row=5, col=1)
        fig.add_trace(go.Scatter(
            x=ch["date"], y=ch["retail_pct"],
            mode="lines+markers", name="散戶 %",
            line=dict(color="#7ab8ff", width=2),
            marker=dict(size=6),
            showlegend=False,
        ), row=5, col=1)

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
