"""ETF 動作訊號 — 系統推薦標的 vs 前 5 大主動式 ETF 動作的加分.

設計：
  - 動作基礎分：NEW +15 / +INC +8 / -DEC -8 / OUT -15
  - ETF 排名權重：0.7^rank (1.0 / 0.7 / 0.5 / 0.35 / 0.25)
  - 總分 = Σ(action_base × etf_weight)
  - 整合：加進 tiebreaker 第 8 維 (regime-aware)

對外 API:
  fetch_etf_signal_map() -> dict[stock_code, dict]  全市場一次計算批次回傳
  format_signal(signal: dict) -> str               for TG / Web 顯示
"""
from __future__ import annotations

from dataclasses import dataclass

from . import etf

# 動作基礎分 — 符合「決策成本越高，分數越大」直覺
ACTION_SCORES = {
    "NEW":  +15,   # 0→有：強信念變化（需通過 ETF 投資委員會）
    "+INC": +8,    # 加碼：信心提升但已部分 priced in
    "-DEC": -8,    # 減碼：信心下降中度負面
    "OUT":  -15,   # 有→0：完全清倉，最強負面
}

# ETF 排名權重：0.7^rank 指數衰減
# 越大 AUM (最大的 981A 第一名) 影響越大
ETF_RANK_WEIGHTS = [
    1.0,   # rank 1 (最大 ETF, e.g. 981A)
    0.7,   # rank 2
    0.5,   # rank 3
    0.35,  # rank 4
    0.25,  # rank 5
]


@dataclass
class EtfAction:
    etf_code: str
    etf_name: str
    etf_rank: int          # 1-based AUM rank
    etf_weight: float      # 0.25 ~ 1.0
    action: str            # NEW / +INC / -DEC / OUT
    base_score: float      # ACTION_SCORES[action]
    contrib: float         # base_score × etf_weight
    shares_diff: int       # ETF 加減的張數


def _short_etf_name(code: str, raw_name: str) -> str:
    """ETF 名稱簡化（去掉 'Active ETF' 後綴 + 截長）."""
    name = (raw_name or "").replace("Active ETF", "").strip()
    if not name or name == code:
        return code
    return name[:12]


def fetch_etf_signal_map(top_etf_n: int = 5) -> dict[str, dict]:
    """掃描前 N 大主動式 ETF 最近一次 diff，回傳 {stock_code: signal_dict}.

    signal_dict 結構：
      {
        "score": float,           # 總分 = Σ(action_base × etf_weight)
        "actions": [EtfAction, ...],  # 該股在各 ETF 的具體動作
        "summary": "981A加碼/991A新進",  # 簡短摘要 for TG
      }
    """
    try:
        metas = etf.top_n(top_etf_n, taiwan_only=True)
    except Exception:
        return {}
    if not metas:
        return {}

    aggregated: dict[str, list[EtfAction]] = {}
    for rank, m in enumerate(metas, start=1):
        weight = (ETF_RANK_WEIGHTS[rank - 1]
                  if rank - 1 < len(ETF_RANK_WEIGHTS) else 0.1)
        try:
            dates = etf.list_holding_dates(m.code)
            if len(dates) < 2:
                continue
            diff = etf.diff_holdings(m.code, dates[0], dates[1])
        except Exception:
            continue
        if diff.empty:
            continue
        for _, row in diff.iterrows():
            action = str(row.get("action", ""))
            if action not in ACTION_SCORES:
                continue
            stock_code = str(row["stock_code"]).strip()
            base = ACTION_SCORES[action]
            contrib = base * weight
            aggregated.setdefault(stock_code, []).append(EtfAction(
                etf_code=m.code,
                etf_name=_short_etf_name(m.code, m.name or ""),
                etf_rank=rank,
                etf_weight=weight,
                action=action,
                base_score=base,
                contrib=contrib,
                shares_diff=int(row.get("shares_diff", 0) or 0),
            ))

    # 組裝最終 signal_dict
    result: dict[str, dict] = {}
    for code, actions in aggregated.items():
        score = sum(a.contrib for a in actions)
        summary_parts = []
        # 依 contrib 絕對值排序顯示，重要的在前
        for a in sorted(actions, key=lambda x: -abs(x.contrib)):
            label_map = {"NEW": "新進", "+INC": "加碼",
                         "-DEC": "減碼", "OUT": "退出"}
            summary_parts.append(f"{a.etf_code} {label_map.get(a.action, a.action)}")
        result[code] = {
            "score": round(score, 2),
            "actions": actions,
            "summary": " / ".join(summary_parts[:3]),  # 最多顯示 3 個
        }
    return result


def format_signal_for_tg(signal: dict | None) -> str:
    """TG 推薦卡片用的簡短標籤.

    範例：'  ✨ETF+14.5 (981A加碼/991A新進)'
    若 signal 為空回 ''
    """
    if not signal or abs(signal.get("score", 0)) < 1:
        return ""
    score = signal["score"]
    icon = "✨" if score > 0 else "⚠️"
    sign = "+" if score > 0 else ""
    return f"  {icon}ETF{sign}{score:.1f} ({signal['summary']})"


def format_signal_for_web(signal: dict | None) -> str:
    """Web 卡片下方的多行明細。Markdown 格式."""
    if not signal or not signal.get("actions"):
        return ""
    lines = []
    score = signal["score"]
    icon = "🟢" if score > 0 else "🔴"
    lines.append(f"{icon} **ETF 動向分數 {score:+.2f}**")
    for a in signal["actions"]:
        label_map = {"NEW": "🆕 新進", "+INC": "📈 加碼",
                     "-DEC": "📉 減碼", "OUT": "❌ 退出"}
        action_str = label_map.get(a.action, a.action)
        shares_str = (f"{a.shares_diff:+,}張"
                      if abs(a.shares_diff) >= 1 else "")
        lines.append(
            f"&nbsp;&nbsp;`{a.etf_code}` {a.etf_name} "
            f"{action_str} {shares_str} (w={a.etf_weight:.2f}, "
            f"+{a.contrib:.1f})"
            if a.action in ("NEW", "+INC")
            else
            f"&nbsp;&nbsp;`{a.etf_code}` {a.etf_name} "
            f"{action_str} {shares_str} (w={a.etf_weight:.2f}, "
            f"{a.contrib:.1f})"
        )
    return "  \n".join(lines)
