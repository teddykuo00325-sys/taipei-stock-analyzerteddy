"""同分排序機制 — 預測未來 3 天勝率較高的標的.

當主評分系統把多檔股票評為同分（譬如 5+ 檔都是 100 分）時，需要二級
排序機制來挑「短線勝率最高」的進場標的。

權重（v2，已經過 30 天 27,741 觸發點實證調整）：

7 個正向維度（總計 +101）：
  F 短期動能甜蜜點 (+25) ★ 實證勝率 54.6% 最高（昨漲 +1~3%）
  D 不過熱 (+20)            ★ 實證勝率 54.2%、N=13k 最穩定
  B 法人連續買超 (+20)      無歷史回測，依理論保留
  A 爆量突破 (+10) ↓        實證 48.7%（多頭中追熱反失利）
  G 軋空潛力 (+10)          無歷史回測，依理論保留
  C 動能加速 (+8) ↓         實證 48.7%（多頭中過熱反指標）
  E KD/MACD 鮮度 (+8) ↓     實證 51.0% 接近 baseline

5 個反向扣分（殺手警訊，最多 -53）：
  乖離過高 (-15)、單日衝太兇 (-10)、連續紅 K 過久 (-10)
  法人轉賣 (-8)、過熱型態 (-10)

API:
  compute(df, diag) -> TiebreakDetail   給定 K 線 + diagnosis 算 tiebreak
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# === Regime-aware 權重 ===
# 多頭環境：實證顯示「不追熱」型維度勝率高（F, D 強）
# 空頭環境：理論上「爆量突破」「動能加速」反而是真實力道訊號（A, C 強）
# 整理環境：取多空中間值
_WEIGHTS = {
    "bull": {  # 強多頭
        "A_max": 10, "B_max": 20, "C_max": 8,  "D_max": 20,
        "E_max": 8,  "F_max": 25, "G_max": 10,
    },
    "bear": {  # 強空頭（A/C 反轉為強訊號）
        "A_max": 20, "B_max": 20, "C_max": 18, "D_max": 10,
        "E_max": 10, "F_max": 12, "G_max": 15,
    },
    "sideways": {  # 整理（介於兩者）
        "A_max": 15, "B_max": 20, "C_max": 12, "D_max": 15,
        "E_max": 10, "F_max": 18, "G_max": 12,
    },
}


def _get_weights(regime: str | None) -> dict:
    """依 regime 取 7 維度權重；未指定用 sideways."""
    return _WEIGHTS.get(regime or "sideways", _WEIGHTS["sideways"])


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
# A. 爆量突破 (+10) — 實證調降：強多頭中追熱反失利（30 日勝率 48.7%）
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
        notes.append(f"爆量突破 10 日新高 ({vol_ratio:.1f}x 量) +10")
        return 10
    if breakthrough and vol_ratio >= 1.2:
        notes.append(f"突破 10 日新高 ({vol_ratio:.1f}x 量) +6")
        return 6
    if vol_ratio >= 2.0:
        notes.append(f"爆量但未破前高 ({vol_ratio:.1f}x) +4")
        return 4
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
# C. 動能加速 (+8) — 實證調降：多頭中過熱反失利（30 日勝率 48.7%）
# ============================================================
def _score_momentum(df: pd.DataFrame, notes: list[str]) -> int:
    last = df.iloc[-1]
    ma5 = last.get("ma5"); ma10 = last.get("ma10"); ma20 = last.get("ma20")
    if any(pd.isna(x) or x is None or x <= 0 for x in (ma5, ma10, ma20)):
        return 0
    r1 = float(ma5) / float(ma10)
    r2 = float(ma10) / float(ma20)
    if r1 >= 1.02 and r2 >= 1.01:
        notes.append(f"動能加速 (5/10={r1:.3f}, 10/20={r2:.3f}) +8")
        return 8
    if r1 >= 1.01 and r2 >= 1.005:
        notes.append(f"中度動能 (5/10={r1:.3f}) +5")
        return 5
    if r1 >= 1.0 and r2 >= 1.0:
        return 2
    return 0


# ============================================================
# D. 不過熱 (+20) — 實證調升：勝率 54.2%、N=13,173 最穩定預測力
# ============================================================
def _score_not_overheated(df: pd.DataFrame, notes: list[str]) -> int:
    last = df.iloc[-1]
    score = 0
    rsi = last.get("rsi")
    if pd.notna(rsi) and rsi is not None and rsi < 70:
        score += 10
    ma10 = last.get("ma10")
    if pd.notna(ma10) and ma10 is not None and ma10 > 0:
        dev = (float(last["close"]) / float(ma10) - 1) * 100
        if dev < 5:
            score += 10
            notes.append(f"未過熱 (乖離 {dev:+.1f}%, RSI {rsi:.0f}) +{score}")
        elif dev < 8:
            score += 5
    return score


# ============================================================
# E. KD/MACD 鮮度 (+8) — 實證略降：勝率 51.0% 接近 baseline
# ============================================================
def _score_signal_freshness(df: pd.DataFrame, notes: list[str]) -> int:
    if len(df) < 4 or "k" not in df.columns or "d" not in df.columns:
        return 0
    score = 0
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
            add = max(6 - (back - 1) * 2, 2)
            score += add
            notes.append(f"KD 金叉 {back} 日內 +{add}")
            break
    if "macd_hist" in df.columns and len(df) >= 4:
        h = df["macd_hist"].iloc[-3:].values
        if len(h) == 3 and not any(pd.isna(x) for x in h):
            if h[2] > h[1] > h[0] > 0:
                score += 4
                notes.append("MACD hist 連續放大 +4")
            elif h[2] > h[1]:
                score += 2
    return min(score, 8)


# ============================================================
# F. 短期動能甜蜜點 (+25) — 實證調升：勝率 54.6% 最高、N=2,960
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
        notes.append(f"甜蜜起漲 ({pct:+.1f}%) +25  ★ 實證勝率最高")
        return 25
    if 3.0 < pct <= 5.0:
        notes.append(f"穩健起漲 ({pct:+.1f}%) +15")
        return 15
    if 0 < pct < 1.0:
        notes.append(f"小漲 ({pct:+.1f}%) +6")
        return 6
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
def compute(df: pd.DataFrame, diag,
             regime: str | None = None) -> TiebreakDetail:
    """計算 tiebreak 分數.

    df: K 線 (含 indicators — ma5/ma10/ma20/k/d/rsi/macd_hist/volume)
    diag: Diagnosis 物件（用 institutional_info / margin_info / candles）
    regime: 'bull' / 'bear' / 'sideways'，None 自動偵測；用於選權重組
    """
    if df is None or df.empty:
        return TiebreakDetail(total=0)
    notes: list[str] = []

    # 自動偵測 regime（若沒指定）— 使用 backtest_filter
    if regime is None:
        try:
            from . import backtest_filter
            regime = backtest_filter.detect_regime().label  # bull/bear/sideways
        except Exception:
            regime = "sideways"

    w = _get_weights(regime)
    # 算原始分數
    a_raw = _score_breakout(df, notes)
    b_raw = _score_institutional(diag, notes)
    c_raw = _score_momentum(df, notes)
    d_raw = _score_not_overheated(df, notes)
    e_raw = _score_signal_freshness(df, notes)
    f_raw = _score_sweet_spot(df, notes)
    g_raw = _score_short_squeeze(diag, notes)
    # 用 regime 權重 scale（原始最大分 ≈ baseline，依比例調）
    # baseline maxes: A=10, B=20, C=8, D=20, E=8, F=25, G=10
    base = {"A": 10, "B": 20, "C": 8, "D": 20,
            "E": 8, "F": 25, "G": 10}
    a = int(round(a_raw * w["A_max"] / base["A"])) if a_raw else 0
    b = int(round(b_raw * w["B_max"] / base["B"])) if b_raw else 0
    c = int(round(c_raw * w["C_max"] / base["C"])) if c_raw else 0
    d = int(round(d_raw * w["D_max"] / base["D"])) if d_raw else 0
    e = int(round(e_raw * w["E_max"] / base["E"])) if e_raw else 0
    f = int(round(f_raw * w["F_max"] / base["F"])) if f_raw else 0
    g = int(round(g_raw * w["G_max"] / base["G"])) if g_raw else 0
    penalty = _compute_penalty(df, diag, notes)
    total = a + b + c + d + e + f + g + penalty
    if regime != "sideways":
        notes.insert(0, f"[regime={regime} 動態權重]")
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
