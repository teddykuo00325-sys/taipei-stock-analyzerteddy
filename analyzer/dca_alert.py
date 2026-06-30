"""長期 DCA 撿便宜警示 — 針對 0050 / 2330 等核心持股.

理念：使用者長期持有 0050 / 2330，但在跌深時加碼比平均成本買法 IRR 更高。
本模組提供 3 層警示（敏感版 2%/5%/10%）：

  🟢 SMALL — 月頻：20 日高點回檔 ≥ 2% AND RSI < 50
  🟡 MEDIUM — 季頻：60 日高點回檔 ≥ 5% AND 跌破 MA60
  🔴 LARGE — 年頻：252 日高點回檔 ≥ 10% AND RSI < 30 AND 跌破 MA200

對外 API:
  evaluate(code) -> AlertResult | None
  evaluate_targets() -> dict[code → AlertResult]  預設掃 ['0050', '2330']
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# 預設追蹤標的（你的核心持股）
DEFAULT_TARGETS = ["0050", "2330", "00981A"]


@dataclass
class AlertResult:
    code: str
    name: str
    level: str            # 'SMALL' / 'MEDIUM' / 'LARGE' / 'NONE'
    emoji: str            # 🟢 / 🟡 / 🔴 / ⚪
    close: float
    pullback_20d: float   # 從 20 日高點回檔 %（負數）
    pullback_60d: float
    pullback_252d: float
    rsi: float | None
    ma60: float | None
    ma200: float | None
    note: str
    suggestion: str       # 中文建議


def _safe_name(code: str) -> str:
    """從 industry / etf / 硬編碼 抓中文名；fallback 用 code."""
    code = str(code).strip()
    # 1. industry (一般上市 / 上櫃)
    try:
        from . import industry as _ind
        df = _ind.snapshot()
        if not df.empty:
            row = df[df["code"].astype(str) == code]
            if not row.empty:
                nm = str(row.iloc[0]["short_name"]).strip()
                if nm and nm != code:
                    return nm
    except Exception:
        pass
    # 2. ETF 從 etf_aum 表抓（主動式 ETF 不在 industry 表中）
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
    # 3. 硬編碼 ETF（GH Actions 上 industry + etf_aum 都失敗時的最後保險）
    try:
        from .daily_report import _HARDCODED_NAMES
        if code in _HARDCODED_NAMES:
            return _HARDCODED_NAMES[code]
    except Exception:
        pass
    return code


def evaluate(code: str) -> AlertResult | None:
    """評估單一標的的撿便宜訊號等級.

    ★ 永遠用 price_cache.get() 而非 _load() — 確保 DCA 3 個核心持股的
    K 線是最新的（雲端 GH Actions skip_yfinance_warm=True 導致 DB 停留
    在過時資料，回檔計算會用錯時間窗口）。get() 內部會增量 fetch；
    yfinance 已 monkey-patch 25 秒 thread-timeout，即使被擋也只浪費 25s.
    """
    from . import indicators, price_cache
    df_raw = None
    try:
        df_raw = price_cache.get(code, period="1y")
    except Exception:
        # get() 失敗 → 退回 _load() 至少用既有資料算（總比沒有強）
        try:
            df_raw = price_cache._load(code)
        except Exception:
            return None
    if df_raw is None or df_raw.empty or len(df_raw) < 60:
        return None

    df = indicators.add_all(df_raw)
    last = df.iloc[-1]
    close = float(last["close"])

    # 高點 / 回檔
    h_20 = float(df["high"].tail(20).max())
    h_60 = float(df["high"].tail(60).max())
    h_252 = float(df["high"].tail(252).max()) if len(df) >= 252 \
        else float(df["high"].max())

    pb_20 = (close / h_20 - 1) * 100
    pb_60 = (close / h_60 - 1) * 100
    pb_252 = (close / h_252 - 1) * 100

    # 技術位置
    rsi = float(last.get("rsi")) if pd.notna(last.get("rsi")) else None
    ma60 = float(last.get("ma60")) if pd.notna(last.get("ma60")) else None
    # MA200 自己算（indicators 沒提供）
    ma200 = (float(df["close"].tail(200).mean())
             if len(df) >= 200 else None)

    name = _safe_name(code)
    level = "NONE"
    emoji = "⚪"
    note = ""
    suggestion = ""

    # === LARGE：年頻（黑天鵝級）===
    if (pb_252 <= -10 and (rsi is None or rsi < 30)
            and ma200 and close < ma200):
        level = "LARGE"
        emoji = "🔴"
        note = (f"<b>{emoji} {name} 大型撿便宜（年頻）</b>\n"
                f"   現價 <b>{close:.2f}</b> ｜ 一年高點回檔 <b>{pb_252:+.1f}%</b>\n"
                f"   RSI {rsi:.0f} ｜ MA200 {ma200:.2f} （跌破年線）")
        suggestion = "建議重押加碼（50%+ 月閒置資金或加重資產配置）"

    # === MEDIUM：季頻 ===
    elif pb_60 <= -5 and ma60 and close < ma60:
        level = "MEDIUM"
        emoji = "🟡"
        note = (f"<b>{emoji} {name} 中型撿便宜（季頻）</b>\n"
                f"   現價 <b>{close:.2f}</b> ｜ 60 日高點回檔 "
                f"<b>{pb_60:+.1f}%</b>\n"
                f"   MA60 {ma60:.2f}（跌破季線）")
        suggestion = "建議中度加碼（20-30% 月閒置資金）"

    # === SMALL：月頻 ===
    # 跌 ≥2% AND (RSI<50 未過熱  OR  跌 ≥4% 已明顯回檔)
    # 第二條件 escape hatch：避免「跌很多但 RSI 還沒掉 < 50」漏觸發
    elif pb_20 <= -2 and (
            (rsi is not None and rsi < 50) or pb_20 <= -4):
        level = "SMALL"
        emoji = "🟢"
        if rsi is not None and rsi < 50:
            rsi_note = f"RSI {rsi:.0f}（未過熱）"
        else:
            rsi_str = f"{rsi:.0f}" if rsi is not None else "—"
            rsi_note = f"回檔已 ≥ 4%（RSI {rsi_str}）"
        note = (f"<b>{emoji} {name} 小型撿便宜（月頻）</b>\n"
                f"   現價 <b>{close:.2f}</b> ｜ 20 日高點回檔 "
                f"<b>{pb_20:+.1f}%</b>\n"
                f"   {rsi_note}")
        suggestion = "建議小額加碼（5-10% 月閒置資金）"

    # 未觸發任何等級：仍回傳 NONE 狀態，讓 UI/TG 可顯示「目前正常」
    if level == "NONE":
        note = (f"<b>⚪ {name}（{code}）</b> 現價 <b>{close:.2f}</b>  "
                f"20d {pb_20:+.1f}% ｜ 60d {pb_60:+.1f}% "
                f"｜ RSI {rsi:.0f}" if rsi else
                f"<b>⚪ {name}（{code}）</b> 現價 <b>{close:.2f}</b>  "
                f"20d {pb_20:+.1f}% ｜ 60d {pb_60:+.1f}%")
        suggestion = "未達加碼條件，續抱觀察"
        return AlertResult(
            code=code, name=name, level="NONE", emoji="⚪",
            close=close, pullback_20d=round(pb_20, 2),
            pullback_60d=round(pb_60, 2), pullback_252d=round(pb_252, 2),
            rsi=round(rsi, 1) if rsi else None,
            ma60=round(ma60, 2) if ma60 else None,
            ma200=round(ma200, 2) if ma200 else None,
            note=note, suggestion=suggestion,
        )

    return AlertResult(
        code=code, name=name, level=level, emoji=emoji,
        close=close, pullback_20d=round(pb_20, 2),
        pullback_60d=round(pb_60, 2), pullback_252d=round(pb_252, 2),
        rsi=round(rsi, 1) if rsi else None,
        ma60=round(ma60, 2) if ma60 else None,
        ma200=round(ma200, 2) if ma200 else None,
        note=note, suggestion=suggestion,
    )


def evaluate_targets(codes: list[str] | None = None
                     ) -> list[AlertResult]:
    """掃預設或指定的標的，回傳所有結果（含未觸發的 NONE 狀態）.

    SMALL / MEDIUM / LARGE 排序在前（依嚴重度），NONE 在後。
    """
    codes = codes or DEFAULT_TARGETS
    out = []
    for c in codes:
        r = evaluate(c)
        if r:
            out.append(r)
    # 依等級嚴重度排序：LARGE > MEDIUM > SMALL > NONE
    order = {"LARGE": 0, "MEDIUM": 1, "SMALL": 2, "NONE": 3}
    out.sort(key=lambda x: order.get(x.level, 9))
    return out
