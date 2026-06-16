"""同分排序機制 — 預測未來 3 天勝率較高的標的.

當主評分系統把多檔股票評為同分（譬如 5+ 檔都是 100 分）時，需要二級
排序機制來挑「短線勝率最高」的進場標的。

7 個正向維度（總計 +110）：
  A 爆量突破 (+25)       — 主力進場最強訊號
  B 法人連續買超 (+20)   — 短線最持續買盤
  C 動能加速 (+20)       — 多頭排列「拉開距離」
  D 不過熱 (+15)         — RSI < 70 + 乖離 < 5%
  E KD/MACD 鮮度 (+10)   — 訊號剛發動續航強
  F 短期動能甜蜜點 (+10) — 昨漲 +1~+5%
  G 軋空潛力 (+10)       — 券資比 > 15%

5 個反向扣分（殺手警訊，最多 -53）：
  乖離過高 (-15)、單日衝太兇 (-10)、連續紅 K 過久 (-10)
  法人轉賣 (-8)、過熱型態 (-10)

API:
  compute(df, diag) -> TiebreakDetail   給定 K 線 + diagnosis 算 tiebreak
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class TiebreakDetail:
    total: int                              # 總分 (-53 ~ +110)
    a_breakout: int = 0                     # 爆量突破
    b_institutional: int = 0                # 法人連續買超
    c_momentum: int = 0                     # 動能加速
    d_not_overheated: int = 0               # 不過熱
    e_signal_fresh: int = 0                 # KD/MACD 鮮度
    f_sweet_spot: int = 0                   # 短期動能甜蜜點
    g_short_squeeze: int = 0                # 軋空潛力
    penalty: int = 0                        # 反向扣分總和（負數）
    notes: list[str] = field(default_factory=list)


# ============================================================
# A. 爆量突破 (+25)
# ============================================================
def _score_breakout(df: pd.DataFrame, notes: list[str]) -> int:
    if len(df) < 21:
        return 0
    last = df.iloc[-1]
    vol_recent = df["volume"].iloc[-21:-1]
    if vol_recent.empty:
        return 0
    vol_ma20 = float(vol_recent.mean())
    if vol_ma20 <= 0:
        return 0
    vol_ratio = float(last["volume"]) / vol_ma20
    high_10 = float(df["high"].iloc[-11:-1].max())
    breakthrough = float(last["close"]) > high_10
    if breakthrough and vol_ratio >= 1.5:
        notes.append(f"爆量突破 10 日新高 ({vol_ratio:.1f}x 量) +25")
        return 25
    if breakthrough and vol_ratio >= 1.2:
        notes.append(f"突破 10 日新高 ({vol_ratio:.1f}x 量) +15")
        return 15
    if vol_ratio >= 2.0:
        notes.append(f"爆量但未破前高 ({vol_ratio:.1f}x) +10")
        return 10
    return 0


# ============================================================
# B. 法人連續買超 (+20)
# ============================================================
def _score_institutional(diag, notes: list[str]) -> int:
    inst = getattr(diag, "institutional_info", None)
    if not inst:
        return 0
    total_net_lots = int(inst.get("total_net", 0)) // 1000
    if total_net_lots >= 5000:
        notes.append(f"法人大買 +{total_net_lots:,}張 +20")
        return 20
    if total_net_lots >= 2000:
        notes.append(f"法人買超 +{total_net_lots:,}張 +15")
        return 15
    if total_net_lots >= 500:
        notes.append(f"法人小買 +{total_net_lots:,}張 +10")
        return 10
    if total_net_lots >= 0:
        return 5
    return 0


# ============================================================
# C. 動能加速 (+20)
# ============================================================
def _score_momentum(df: pd.DataFrame, notes: list[str]) -> int:
    last = df.iloc[-1]
    ma5 = last.get("ma5"); ma10 = last.get("ma10"); ma20 = last.get("ma20")
    if any(pd.isna(x) or x is None or x <= 0 for x in (ma5, ma10, ma20)):
        return 0
    r1 = float(ma5) / float(ma10)
    r2 = float(ma10) / float(ma20)
    if r1 >= 1.02 and r2 >= 1.01:
        notes.append(f"動能加速 (5/10={r1:.3f}, 10/20={r2:.3f}) +20")
        return 20
    if r1 >= 1.01 and r2 >= 1.005:
        notes.append(f"中度動能 (5/10={r1:.3f}) +12")
        return 12
    if r1 >= 1.0 and r2 >= 1.0:
        return 5
    return 0


# ============================================================
# D. 不過熱 (+15)
# ============================================================
def _score_not_overheated(df: pd.DataFrame, notes: list[str]) -> int:
    last = df.iloc[-1]
    score = 0
    rsi = last.get("rsi")
    if pd.notna(rsi) and rsi is not None and rsi < 70:
        score += 7
    ma10 = last.get("ma10")
    if pd.notna(ma10) and ma10 is not None and ma10 > 0:
        dev = (float(last["close"]) / float(ma10) - 1) * 100
        if dev < 5:
            score += 8
            notes.append(f"未過熱 (乖離 {dev:+.1f}%, RSI {rsi:.0f}) +{score}")
        elif dev < 8:
            score += 4
    return score


# ============================================================
# E. KD/MACD 鮮度 (+10)
# ============================================================
def _score_signal_freshness(df: pd.DataFrame, notes: list[str]) -> int:
    if len(df) < 4 or "k" not in df.columns or "d" not in df.columns:
        return 0
    score = 0
    # KD 近 3 日內金叉
    for back in range(1, 4):
        if back + 1 > len(df):
            break
        prev_k = df["k"].iloc[-back - 1]
        prev_d = df["d"].iloc[-back - 1]
        cur_k = df["k"].iloc[-back]
        cur_d = df["d"].iloc[-back]
        if pd.isna(prev_k) or pd.isna(cur_k):
            continue
        if prev_k <= prev_d and cur_k > cur_d:
            add = max(8 - (back - 1) * 2, 2)
            score += add
            notes.append(f"KD 金叉 {back} 日內 +{add}")
            break
    # MACD histogram 連續放大
    if "macd_hist" in df.columns and len(df) >= 4:
        h = df["macd_hist"].iloc[-3:].values
        if len(h) == 3 and not any(pd.isna(x) for x in h):
            if h[2] > h[1] > h[0] > 0:
                score += 5
                notes.append("MACD hist 連續放大 +5")
            elif h[2] > h[1]:
                score += 2
    return min(score, 10)


# ============================================================
# F. 短期動能甜蜜點 (+10)
# ============================================================
def _score_sweet_spot(df: pd.DataFrame, notes: list[str]) -> int:
    if len(df) < 2:
        return 0
    last = df.iloc[-1]
    prev = df.iloc[-2]
    if float(prev["close"]) <= 0:
        return 0
    pct = (float(last["close"]) / float(prev["close"]) - 1) * 100
    if 1.0 <= pct <= 3.0:
        notes.append(f"甜蜜起漲 ({pct:+.1f}%) +10")
        return 10
    if 3.0 < pct <= 5.0:
        notes.append(f"穩健起漲 ({pct:+.1f}%) +7")
        return 7
    if 0 < pct < 1.0:
        return 3
    return 0


# ============================================================
# G. 軋空潛力 (+10)
# ============================================================
def _score_short_squeeze(diag, notes: list[str]) -> int:
    marg = getattr(diag, "margin_info", None)
    if not marg or not marg.get("margin_today"):
        return 0
    ratio = float(marg.get("short_today", 0)) / float(marg["margin_today"])
    if ratio > 0.30:
        notes.append(f"高軋空 (券資比 {ratio*100:.1f}%) +10")
        return 10
    if ratio > 0.15:
        notes.append(f"中軋空 (券資比 {ratio*100:.1f}%) +6")
        return 6
    if ratio > 0.05:
        return 2
    return 0


# ============================================================
# 殺手扣分
# ============================================================
def _compute_penalty(df: pd.DataFrame, diag, notes: list[str]) -> int:
    if len(df) < 6:
        return 0
    penalty = 0
    last = df.iloc[-1]
    prev = df.iloc[-2]
    # 乖離過高
    ma10 = last.get("ma10")
    if pd.notna(ma10) and ma10 is not None and ma10 > 0:
        dev = (float(last["close"]) / float(ma10) - 1) * 100
        if dev > 8:
            penalty -= 15
            notes.append(f"⚠️ 乖離 {dev:+.1f}% 過熱 -15")
    # 單日衝太兇
    if float(prev["close"]) > 0:
        pct = (float(last["close"]) / float(prev["close"]) - 1) * 100
        if pct > 7:
            penalty -= 10
            notes.append(f"⚠️ 昨漲 {pct:+.1f}% 追高 -10")
    # 連續 5 日紅 K
    consecutive_red = 0
    for i in range(1, min(6, len(df) + 1)):
        if (float(df["close"].iloc[-i]) > float(df["open"].iloc[-i])):
            consecutive_red += 1
        else:
            break
    if consecutive_red >= 5:
        penalty -= 10
        notes.append(f"⚠️ 連續 {consecutive_red} 日紅 K -10")
    # K 棒過熱型態（吊人 / 流星 / 長黑）— 從 diag.candles 拿
    candles = getattr(diag, "candles", []) or []
    for c in candles:
        name = getattr(c, "name", "")
        if any(s in name for s in ("吊人", "流星", "長黑", "黃昏星")):
            penalty -= 10
            notes.append(f"⚠️ {name} 反轉訊號 -10")
            break
    return penalty


# ============================================================
# 主入口
# ============================================================
def compute(df: pd.DataFrame, diag) -> TiebreakDetail:
    """計算 tiebreak 分數.

    df: K 線 (含 indicators — ma5/ma10/ma20/k/d/rsi/macd_hist/volume)
    diag: Diagnosis 物件（用 institutional_info / margin_info / candles）
    """
    if df is None or df.empty:
        return TiebreakDetail(total=0)
    notes: list[str] = []
    a = _score_breakout(df, notes)
    b = _score_institutional(diag, notes)
    c = _score_momentum(df, notes)
    d = _score_not_overheated(df, notes)
    e = _score_signal_freshness(df, notes)
    f = _score_sweet_spot(df, notes)
    g = _score_short_squeeze(diag, notes)
    penalty = _compute_penalty(df, diag, notes)
    total = a + b + c + d + e + f + g + penalty
    return TiebreakDetail(
        total=total, a_breakout=a, b_institutional=b, c_momentum=c,
        d_not_overheated=d, e_signal_fresh=e, f_sweet_spot=f,
        g_short_squeeze=g, penalty=penalty, notes=notes,
    )


def compute_short_side(df: pd.DataFrame, diag) -> TiebreakDetail:
    """做空版 tiebreak（方向相反）.

    對做空候選，理想是「跌破 + 量縮反彈 + 短期已過熱 + 法人賣超」。
    簡化：把多空鏡像處理 — 取多單 tiebreak 的負數，並加做空特有 bonus。

    這版直接用多方 compute 並取負，方便共用邏輯；未來可獨立。
    """
    long_score = compute(df, diag)
    # 簡單反向：多單高分 → 不適合做空（分數低）；多單低分 → 適合做空
    # 但 G 軋空 對做空是 risk，要扣
    flipped = TiebreakDetail(
        total=-long_score.total - long_score.g_short_squeeze,
        a_breakout=-long_score.a_breakout,
        b_institutional=-long_score.b_institutional,
        c_momentum=-long_score.c_momentum,
        d_not_overheated=long_score.d_not_overheated,  # 不過熱對空也好
        e_signal_fresh=-long_score.e_signal_fresh,
        f_sweet_spot=-long_score.f_sweet_spot,
        g_short_squeeze=-long_score.g_short_squeeze * 2,
        penalty=long_score.penalty,
        notes=[f"做空版反向計算（基於多方分數 {long_score.total}）"],
    )
    return flipped
