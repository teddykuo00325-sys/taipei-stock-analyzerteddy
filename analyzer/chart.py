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

    # 計算 overlay 線段繪製範圍：限制在使用者選的 display_days 視窗內，
    # 避免 user 按「全部」rangeselector 時水平線橫跨整個歷史圖（包括沒
    # K 線的空白區）造成視覺擁擠。
    _ovl_x0 = (df.index[max(0, len(df) - display_days)]
               if len(df) else None)
    _ovl_x1 = df.index[-1] if len(df) else None

    def _hline_clipped(y, color, width=1, dash=None,
                       text=None, text_color=None, text_size=10,
                       text_pos="right", row=1):
        """畫水平線，但只限制在 display_days 視窗內（以 add_shape 實作）.

        用 add_shape 而非 add_hline，避免 plotly 擴展線段到所有 x 範圍。
        text_pos: 'left' / 'right' / 'center' — 標註位置在線段的哪端。
        """
        if _ovl_x0 is None:
            return
        line_dict = dict(color=color, width=width)
        if dash:
            line_dict["dash"] = dash
        fig.add_shape(
            type="line", xref=f"x{row if row > 1 else ''}",
            yref=f"y{row if row > 1 else ''}",
            x0=_ovl_x0, x1=_ovl_x1, y0=y, y1=y,
            line=line_dict, layer="below",
        )
        if text:
            xa = _ovl_x1 if text_pos == "right" else \
                 _ovl_x0 if text_pos == "left" else \
                 _ovl_x0 + (_ovl_x1 - _ovl_x0) / 2
            anchor = "right" if text_pos == "right" else \
                     "left" if text_pos == "left" else "center"
            fig.add_annotation(
                xref=f"x{row if row > 1 else ''}",
                yref=f"y{row if row > 1 else ''}",
                x=xa, y=y, text=text, showarrow=False,
                font=dict(size=text_size,
                          color=text_color or color),
                xanchor=anchor, yanchor="bottom",
                bgcolor="rgba(20,24,35,0.7)",
                borderpad=2,
            )
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

    # 型態頸線標示（依多/空著色，更顯眼）— 限制在 display 視窗內
    for pat in patterns:
        if pat.neckline:
            if pat.signal == "bull":
                lcolor = "rgba(214,39,40,0.85)"
                fcolor = "#ff6060"
            elif pat.signal == "bear":
                lcolor = "rgba(44,160,44,0.85)"
                fcolor = "#3dbd6e"
            else:
                lcolor = "rgba(255,215,0,0.75)"
                fcolor = "#ffd700"
            _hline_clipped(
                pat.neckline, color=lcolor, width=1.8, dash="dash",
                text=f"<b>{pat.name}</b> 頸線 {pat.neckline:.2f}",
                text_color=fcolor, text_size=11, text_pos="left",
            )

    # 主要支撐 / 壓力
    if trend:
        sup = trend.get("support")
        res = trend.get("resistance")
        if sup:
            _hline_clipped(
                sup, color="rgba(44,160,44,0.85)", width=2,
                text=f"主支撐 {sup:.2f}",
                text_color="#3dbd6e", text_size=11, text_pos="right",
            )
        if res:
            _hline_clipped(
                res, color="rgba(214,39,40,0.85)", width=2,
                text=f"主壓力 {res:.2f}",
                text_color="#ff6060", text_size=11, text_pos="right",
            )

    # 取現價（用於距離過濾）
    cur_price = float(df["close"].iloc[-1]) if len(df) else 0

    def _within(p: float, pct: float = 15.0) -> bool:
        if cur_price <= 0:
            return True
        return abs(p / cur_price - 1) * 100 <= pct

    # 多級支撐 — 限制視窗、只畫 2 條最接近現價的
    if multi_supports:
        nearby = [p for p in multi_supports if _within(p, 15)][:2]
        for i, p in enumerate(nearby):
            op = 0.55 - i * 0.15
            _hline_clipped(
                p, color=f"rgba(100,180,255,{max(op, 0.25)})",
                width=1, dash="dash",
                text=f"支{i+1} {p:.2f}",
                text_color="#7ab8ff", text_size=9, text_pos="left",
            )
    # 多級壓力 — 同上
    if multi_resistances:
        nearby = [p for p in multi_resistances if _within(p, 15)][:2]
        for i, p in enumerate(nearby):
            op = 0.55 - i * 0.15
            _hline_clipped(
                p, color=f"rgba(255,180,100,{max(op, 0.25)})",
                width=1, dash="dash",
                text=f"壓{i+1} {p:.2f}",
                text_color="#ffb464", text_size=9, text_pos="right",
            )

    # 費波納契關鍵級位 — ±20% 內最多 3 條
    if fib and fib.levels:
        keys_to_draw = {"38.2% 回檔", "50.0% 回檔", "61.8% 回檔",
                        "38.2% 反彈", "50.0% 反彈", "61.8% 反彈"}
        candidates = []
        for lv in fib.levels:
            if lv.name in keys_to_draw or \
               (fib.nearest and lv.name == fib.nearest.name):
                if _within(lv.price, 20):
                    candidates.append(lv)
        candidates.sort(key=lambda x: abs(x.price - cur_price))
        for lv in candidates[:3]:
            _hline_clipped(
                lv.price, color="rgba(148,103,189,0.55)",
                width=1, dash="dot",
                text=f"Fib {lv.name.split()[0]} {lv.price:.2f}",
                text_color="#9a6dd5", text_size=9, text_pos="left",
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
        # Elliott 慣例：最舊為 1，最新為 N（之前版本反向會誤導）
        wave_nums = list(range(1, len(recent) + 1))
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

    # --- 進場區 / 目標 / 停損 水平線（交易計畫）— 限制在 display 視窗 ---
    if entry_zone and _ovl_x0 is not None:
        lo_e, hi_e = entry_zone
        fig.add_shape(
            type="rect", xref="x", yref="y",
            x0=_ovl_x0, x1=_ovl_x1, y0=lo_e, y1=hi_e,
            fillcolor="rgba(255,255,0,0.12)",
            line=dict(width=0), layer="below",
        )
        fig.add_annotation(
            xref="x", yref="y",
            x=_ovl_x1, y=hi_e,
            text=f"💡 進場區 {lo_e:.2f}~{hi_e:.2f}",
            showarrow=False,
            font=dict(size=10, color="#ffdd00"),
            xanchor="right", yanchor="bottom",
            bgcolor="rgba(20,24,35,0.7)", borderpad=2,
        )
    if target_price:
        _hline_clipped(
            target_price, color="rgba(255,165,0,0.85)", width=2,
            text=f"🎯 目標 {target_price:.2f}",
            text_color="#ffa500", text_size=11, text_pos="left",
        )
    if short_stop:
        _hline_clipped(
            short_stop, color="rgba(44,160,44,0.9)",
            width=2, dash="longdashdot",
            text=f"🛑 短線停損 {short_stop:.2f}",
            text_color="#2ca02c", text_size=11, text_pos="left",
        )
    if mid_stop and (not short_stop or abs(mid_stop - short_stop) > 0.5):
        _hline_clipped(
            mid_stop, color="rgba(44,160,44,0.55)",
            width=1.5, dash="dot",
            text=f"中線停損 {mid_stop:.2f}",
            text_color="#2ca02c", text_size=10, text_pos="left",
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
                xref="paper", yref="y4 domain",
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

    # 高度依 subplot 數動態調整（4 副圖 760、5 副圖 920）
    n_subplots = 5 if has_chip else 4
    chart_height = 760 if n_subplots == 4 else 920
    fig.update_layout(
        title=title, height=chart_height, xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=80, b=10),
        legend=dict(orientation="h", y=1.05, x=0, font=dict(size=10)),
        hovermode="x unified",
        dragmode="pan",
        hoverlabel=dict(bgcolor="rgba(20,24,35,0.9)", font_size=12),
    )
    # 時間軸 range selector（所有 subplot 共用）
    # 排除週末 + 資料中實際缺失的日期（台股假日、停牌日）— 避免直線空白段
    missing_dates = []
    if len(df) > 1:
        full_range = pd.date_range(df.index[0], df.index[-1], freq="B")
        present = set(df.index.normalize())
        missing_dates = [d for d in full_range if d not in present]
    rangebreaks = [dict(bounds=["sat", "mon"])]
    if missing_dates:
        rangebreaks.append(dict(values=[d.strftime("%Y-%m-%d")
                                        for d in missing_dates]))
    fig.update_xaxes(
        rangebreaks=rangebreaks,
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikedash="dot", spikecolor="#888", spikethickness=1,
    )
    fig.update_yaxes(
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikedash="dot", spikecolor="#888", spikethickness=1,
    )
    # 在最上方 subplot 加 range selector 與預設縮放
    # 移除「全部」按鈕：點到後 X 軸會擴展到資料極限，水平 overlay 會橫
    # 跨整圖（包括沒有 K 線的空白區）造成嚴重視覺擁擠，且技術分析
    # 用「全部」沒實際意義（重點都在近期）。
    if start_dt and end_dt:
        fig.update_xaxes(
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1M", step="month",
                         stepmode="backward"),
                    dict(count=3, label="3M", step="month",
                         stepmode="backward"),
                    dict(count=6, label="6M", step="month",
                         stepmode="backward"),
                    dict(step="year", stepmode="todate", label="YTD"),
                    dict(count=1, label="1Y", step="year",
                         stepmode="backward"),
                ],
                bgcolor="rgba(40,44,55,0.8)",
                activecolor="#d62728",
                font=dict(color="#fafafa", size=11),
                x=0, y=1.12, xanchor="left",
            ),
            range=[start_dt, end_dt],
            row=1, col=1,
        )
        # 同步所有 subplot 的 X 範圍，避免 K 線 row 跟成交量 / KD row
        # 顯示不同範圍（rangeselector 只控制 row 1 時其他 subplot 會
        # 自動展開到資料極限）
        n_rows = 5 if has_chip else 4
        for r in range(2, n_rows + 1):
            fig.update_xaxes(range=[start_dt, end_dt], row=r, col=1)
    return fig


def build_card(df: pd.DataFrame, height: int = 480,
               supports: list[float] | None = None,
               resistances: list[float] | None = None,
               entry_zone: tuple[float, float] | None = None,
               target_price: float | None = None,
               short_stop: float | None = None,
               patterns_hist=None,
               title: str = "") -> go.Figure:
    """中型卡片圖：K + Vol + KD 三副圖，供今日選股 / 收藏清單使用."""
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.62, 0.15, 0.23], vertical_spacing=0.02,
    )

    # --- K + MA ---
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], showlegend=False,
        increasing=dict(line=dict(color="#d62728"), fillcolor="#d62728"),
        decreasing=dict(line=dict(color="#2ca02c"), fillcolor="#2ca02c"),
    ), row=1, col=1)
    for p, c in [(5, "#ff7f0e"), (10, "#1f77b4"), (20, "#9467bd")]:
        col = f"ma{p}"
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[col], mode="lines", name=f"MA{p}",
                line=dict(color=c, width=1),
                showlegend=False, hoverinfo="skip",
            ), row=1, col=1)

    # 多級支撐
    for p in (supports or [])[:3]:
        fig.add_hline(
            y=p, line_dash="dash",
            line_color="rgba(100,180,255,0.55)", line_width=0.9,
            annotation_text=f"支 {p:.2f}",
            annotation_position="right",
            annotation_font_color="#7ab8ff",
            annotation_font_size=8,
            row=1, col=1,
        )
    # 多級壓力
    for p in (resistances or [])[:3]:
        fig.add_hline(
            y=p, line_dash="dash",
            line_color="rgba(255,180,100,0.55)", line_width=0.9,
            annotation_text=f"壓 {p:.2f}",
            annotation_position="right",
            annotation_font_color="#ffb464",
            annotation_font_size=8,
            row=1, col=1,
        )
    # 進場區
    if entry_zone:
        lo_e, hi_e = entry_zone
        fig.add_hrect(
            y0=lo_e, y1=hi_e,
            fillcolor="rgba(255,255,0,0.12)",
            layer="below", line_width=0,
            row=1, col=1,
        )
    # 目標 / 停損
    if target_price:
        fig.add_hline(
            y=target_price, line_dash="solid",
            line_color="rgba(255,165,0,0.85)", line_width=1.5,
            annotation_text=f"🎯 {target_price:.2f}",
            annotation_position="top left",
            annotation_font_color="#ffa500",
            annotation_font_size=10,
            row=1, col=1,
        )
    if short_stop:
        fig.add_hline(
            y=short_stop, line_dash="longdashdot",
            line_color="rgba(44,160,44,0.9)", line_width=1.5,
            annotation_text=f"🛑 {short_stop:.2f}",
            annotation_position="bottom left",
            annotation_font_color="#2ca02c",
            annotation_font_size=10,
            row=1, col=1,
        )

    # K 線型態標記（最近 3 個有字）
    if patterns_hist:
        tail_idx = max(len(df) - 60, 0)
        for cand_idx, candles in patterns_hist[-3:]:
            if cand_idx < tail_idx or cand_idx >= len(df):
                continue
            dt = df.index[cand_idx]
            for c in candles[:1]:
                is_bull = c.signal == "bull"
                y = (df["low"].iloc[cand_idx] * 0.98 if is_bull
                     else df["high"].iloc[cand_idx] * 1.02)
                color = ("#d62728" if is_bull
                         else "#2ca02c" if c.signal == "bear" else "#aaa")
                sym = ("triangle-up" if is_bull
                       else "triangle-down" if c.signal == "bear"
                       else "diamond")
                fig.add_trace(go.Scatter(
                    x=[dt], y=[y], mode="markers+text",
                    marker=dict(size=10, color=color, symbol=sym),
                    text=[c.name], textposition="bottom center"
                    if is_bull else "top center",
                    textfont=dict(size=9, color=color),
                    hovertext=f"<b>{c.name}</b><br>{c.note}",
                    hoverinfo="text", showlegend=False,
                ), row=1, col=1)

    # --- Volume + VMA20 ---
    vol_color = ["#d62728" if c >= o else "#2ca02c"
                 for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df.index, y=df["volume"], marker_color=vol_color,
        showlegend=False, name="Vol",
    ), row=2, col=1)
    if "vol_ma20" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["vol_ma20"], mode="lines",
            line=dict(color="#ffd700", width=1, dash="dash"),
            showlegend=False, hoverinfo="skip", name="VMA20",
        ), row=2, col=1)
        # 爆量標記
        burst = df["volume"] > df["vol_ma20"] * 2
        if burst.any():
            fig.add_trace(go.Scatter(
                x=df.index[burst], y=df["volume"][burst],
                mode="markers", marker=dict(
                    symbol="star", size=8, color="#ffd700",
                    line=dict(color="#fff", width=0.6)),
                showlegend=False, hoverinfo="skip", name="爆量",
            ), row=2, col=1)

    # --- KD + 背景 + 交叉 ---
    if "k" in df.columns:
        fig.add_hrect(y0=80, y1=100,
                      fillcolor="rgba(214,39,40,0.12)",
                      layer="below", line_width=0, row=3, col=1)
        fig.add_hrect(y0=0, y1=20,
                      fillcolor="rgba(44,160,44,0.12)",
                      layer="below", line_width=0, row=3, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["k"], mode="lines",
            line=dict(color="#1f77b4", width=1.2),
            showlegend=False, name="K",
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["d"], mode="lines",
            line=dict(color="#ff7f0e", width=1.2),
            showlegend=False, name="D",
        ), row=3, col=1)
        fig.add_hline(y=80, line_dash="dot", line_color="#666",
                      row=3, col=1)
        fig.add_hline(y=20, line_dash="dot", line_color="#666",
                      row=3, col=1)

        # 金叉死叉
        gx, gy, dx_, dy = [], [], [], []
        for i in range(1, len(df)):
            pk, pd_ = df["k"].iloc[i - 1], df["d"].iloc[i - 1]
            ck, cd_ = df["k"].iloc[i], df["d"].iloc[i]
            if pd.isna(pk) or pd.isna(ck):
                continue
            if pk <= pd_ and ck > cd_:
                gx.append(df.index[i]); gy.append(float(ck))
            elif pk >= pd_ and ck < cd_:
                dx_.append(df.index[i]); dy.append(float(ck))
        if gx:
            fig.add_trace(go.Scatter(
                x=gx, y=gy, mode="markers",
                marker=dict(symbol="circle", size=6, color="#ffd700",
                            line=dict(color="#222", width=0.6)),
                showlegend=False, hoverinfo="skip",
            ), row=3, col=1)
        if dx_:
            fig.add_trace(go.Scatter(
                x=dx_, y=dy, mode="markers",
                marker=dict(symbol="x", size=7, color="#d62728",
                            line=dict(color="#fff", width=0.6)),
                showlegend=False, hoverinfo="skip",
            ), row=3, col=1)

    # Layout
    fig.update_layout(
        title=dict(text=title, font=dict(size=11)) if title else None,
        height=height,
        margin=dict(l=6, r=50, t=10 if title else 4, b=4),
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        dragmode="pan",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(
        rangebreaks=[dict(bounds=["sat", "mon"])],
        showticklabels=False,
    )
    # 只在最底部 subplot 顯示日期
    fig.update_xaxes(showticklabels=True, row=3, col=1,
                     tickfont=dict(size=9))
    fig.update_yaxes(tickfont=dict(size=9))
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
