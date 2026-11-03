# -*- coding: utf-8 -*-
"""Track Record 進出場價稽核 — 找出「當天不可能成交」的價格並可選擇修正。

為什麼需要這支：
    realbacktest 的進出場價來自 MIS 即時報價 / price_cache fallback，
    歷史上出過三類錯誤，都會讓 Track Record 失真：
      1. 盤前試撮價（08:30 鎖單時台股未開盤，MIS 回漲跌停參考價）
         → 2026-09-17 已修（鎖單延到 09:08）
      2. 上櫃股拿不到即時價，退回數日前的 cache
         → 2026-09-22 已修（quotes() 補 otc_ 前綴 + cache 加今日檢查）
      3. 非交易日鎖單（颱風假用前一交易日收盤當進場價）
         → 2026-11-03 已修（鎖單前用 MIS 報價日期判斷是否開盤）
    修掉來源不代表歷史乾淨，這支負責定期體檢與回溯校正。

★ 最重要的一件事：先還原 split
    yfinance 即使 auto_adjust=False 仍會套用 split 調整，而台股的
    「股票股利」在 yfinance 就是 Stock Splits。除權日之前的 OHLC 會被
    除以配股率，跟 DB 記的「當時實際成交價」不在同一個基準上。
    2026-09-22 首次掃描抓出 27 個「異常」，加上配股還原後只剩 22 個 ——
    神達（配股 1.10）、元大金（1.04）的**正確**價格差點被改壞。

用法：
    python scripts/audit_prices.py                  # 稽核，只報告不寫入
    python scripts/audit_prices.py --apply          # 實際修正（先自動備份）
    python scripts/audit_prices.py --since 2026-08-05
    python scripts/audit_prices.py --threshold 0.02 # 偏離門檻（預設 1%）
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import warnings
from datetime import date, datetime

warnings.filterwarnings("ignore")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd      # noqa: E402
import yfinance as yf    # noqa: E402

from analyzer import realbacktest as rb  # noqa: E402

DB = os.path.join(_ROOT, "data", "realbacktest.db")


# ------------------------------------------------------------------
def fetch_ohlc(codes: list[str], start: str, end: str) -> dict:
    """抓每檔的 OHLC。先試 .TW（上市），再試 .TWO（上櫃）。"""
    data: dict[str, tuple[str, pd.DataFrame]] = {}
    for code in codes:
        for sym in (f"{code}.TW", f"{code}.TWO"):
            try:
                h = yf.Ticker(sym).history(start=start, end=end,
                                           auto_adjust=False)
            except Exception:
                continue
            if h is None or h.empty:
                continue
            h.index = pd.to_datetime(h.index).tz_localize(None).normalize()
            data[code] = (sym, h)
            break
    return data


def split_factor(data: dict, code: str, d: str) -> float:
    """d 之後發生的 split（含股票股利）累積係數。"""
    if code not in data:
        return 1.0
    _, dd = data[code]
    if "Stock Splits" not in dd.columns:
        return 1.0
    ts = pd.Timestamp(d).normalize()
    f = 1.0
    for v in dd[(dd.index > ts) & (dd["Stock Splits"] > 0)]["Stock Splits"]:
        f *= float(v)
    return f


def bar(data: dict, code: str, d: str):
    """回傳還原 split 後的 (Low, High, Open, Close)，與 DB 同基準。"""
    if code not in data or not d:
        return None
    _, dd = data[code]
    ts = pd.Timestamp(d).normalize()
    if ts not in dd.index:
        return None
    f = split_factor(data, code, d)
    return (float(dd.loc[ts, "Low"]) * f, float(dd.loc[ts, "High"]) * f,
            float(dd.loc[ts, "Open"]) * f, float(dd.loc[ts, "Close"]) * f)


def _d(s: str) -> date:
    y, m, dd = s.split("-")
    return date(int(y), int(m), int(dd))


def _m(v: float) -> str:
    return format(round(v), "+,")


# ------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="實際寫入（預設只報告）")
    ap.add_argument("--since", default=rb.TRACK_RESET_DATE,
                    help="只稽核 lock_date >= 此日期")
    ap.add_argument("--threshold", type=float, default=0.01,
                    help="偏離多少才算錯誤（預設 0.01 = 1%%）")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """select s.id as sid, s.lock_date, s.side,
                  h.code, h.name, h.entry_date, h.entry_price,
                  h.exit_date, h.exit_price, h.position_size
           from realbt_session s
           join realbt_holding h on h.session_id = s.id
           where s.lock_date >= ?
           order by h.entry_date, h.code""", (args.since,)).fetchall()
    if not rows:
        print("無資料可稽核")
        return 0

    codes = sorted({r["code"] for r in rows})
    print(f"稽核範圍 {args.since} 起 ｜ 持股 {len(rows)} 筆 / 標的 "
          f"{len(codes)} 檔 ｜ 門檻 {args.threshold * 100:.1f}%")
    print("抓取 OHLC（先 .TW 再 .TWO）…")
    data = fetch_ohlc(codes, "2026-07-01",
                      (date.today().isoformat()))
    missing = [c for c in codes if c not in data]
    print(f"  取得 {len(data)} / {len(codes)} 檔")
    if missing:
        print(f"  無資料（跳過不動）：{', '.join(missing)}")
    otc = [c for c, (s, _) in data.items() if s.endswith(".TWO")]
    if otc:
        print(f"  其中上櫃(.TWO) {len(otc)} 檔：{', '.join(otc)}")
    print()

    fixes, borderline = [], []
    for r in rows:
        for kind, d, px in (("entry", r["entry_date"], r["entry_price"]),
                            ("exit", r["exit_date"], r["exit_price"])):
            if px is None or not d:
                continue
            b = bar(data, r["code"], d)
            if b is None:
                continue
            lo, hi, op, cl = b
            if lo <= px <= hi:
                continue
            dev = (px / hi - 1) if px > hi else (px / lo - 1)
            if abs(dev) < args.threshold:
                borderline.append((r, kind, px, lo, hi, dev))
                continue
            fixes.append((r, kind, px, op if kind == "entry" else cl,
                          dev, lo, hi, d))

    print("=" * 108)
    print(f"落在當日 OHLC 區間外且偏離 >= {args.threshold * 100:.1f}%："
          f"{len(fixes)} 個價格點")
    print("=" * 108)
    if fixes:
        print("%-5s %-5s %-9s %-5s %-11s %10s %10s %-17s %8s %s" % (
            "sid", "code", "name", "side", "date", "原價", "改為",
            "當日區間", "偏離", "備註"))
        for r, kind, px, new, dev, lo, hi, d in fixes:
            sf = split_factor(data, r["code"], d)
            print("%-5s %-5s %-9s %-5s %-11s %10.2f %10.2f %-17s %+7.1f%% %s"
                  % (r["sid"], r["code"], (r["name"] or "")[:9], r["side"],
                     d, px, new, f"{lo:.2f}-{hi:.2f}", dev * 100,
                     f"split x{sf:.4f}" if abs(sf - 1) > 1e-9 else ""))
    if borderline:
        print()
        print(f"--- 偏離 < {args.threshold * 100:.1f}%，保留不動"
              f"（{len(borderline)} 個）---")

    # ---------- 損益影響 ----------
    fix_map: dict = {}
    for r, kind, px, new, dev, lo, hi, d in fixes:
        fix_map.setdefault((r["sid"], r["code"]), {})[kind] = new

    og = ng = oc = nc = 0.0
    n_closed = 0
    for r in rows:
        if r["exit_price"] is None:
            continue
        n_closed += 1
        f = fix_map.get((r["sid"], r["code"]), {})
        e = f.get("entry", r["entry_price"])
        x = f.get("exit", r["exit_price"])
        sgn = 1 if r["side"] == "long" else -1
        hold = (_d(r["exit_date"]) - _d(r["entry_date"])).days
        og += sgn * (r["exit_price"] / r["entry_price"] - 1) * r["position_size"]
        ng += sgn * (x / e - 1) * r["position_size"]
        oc += rb.estimate_costs(r["side"], r["entry_price"], r["exit_price"],
                                r["position_size"], hold)["total"]
        nc += rb.estimate_costs(r["side"], e, x,
                                r["position_size"], hold)["total"]

    print()
    print("=" * 108)
    print(f"損益影響（已出場 {n_closed} 筆）")
    print("=" * 108)
    print(f"  毛 P&L   {_m(og)} → {_m(ng)}   （差 {_m(ng - og)}）")
    print(f"  淨 P&L   {_m(og - oc)} → {_m(ng - nc)}   "
          f"（差 {_m((ng - nc) - (og - oc))}）")
    print(f"  對 {rb.TRACK_RESET_CAPITAL:,} 基準："
          f"{(og - oc) / rb.TRACK_RESET_CAPITAL * 100:.2f}% → "
          f"{(ng - nc) / rb.TRACK_RESET_CAPITAL * 100:.2f}%")

    if not fixes:
        print()
        print("沒有需要修正的價格點。")
        return 0
    if not args.apply:
        print()
        print("*** 稽核模式，未寫入。加 --apply 才會實際修改 ***")
        return 0

    # ---------- 寫入 ----------
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = DB.replace(".db", f".backup_{stamp}.db")
    shutil.copy2(DB, bak)
    print()
    print(f"已備份 → {bak}")

    n_upd, sids = 0, set()
    with sqlite3.connect(DB) as w:
        for (sid, code), f in fix_map.items():
            sets, vals = [], []
            if "entry" in f:
                sets.append("entry_price=?")
                vals.append(f["entry"])
            if "exit" in f:
                sets.append("exit_price=?")
                vals.append(f["exit"])
            vals += [sid, code]
            w.execute("UPDATE realbt_holding SET %s "
                      "WHERE session_id=? AND code=?" % ", ".join(sets), vals)
            n_upd += 1
            sids.add(sid)
        tag = f"[價格校正 {date.today().isoformat()}]"
        for sid in sids:
            cur = w.execute("SELECT note FROM realbt_session WHERE id=?",
                            (sid,)).fetchone()[0] or ""
            if tag not in cur:
                w.execute("UPDATE realbt_session SET note=? WHERE id=?",
                          ((cur + " " + tag).strip(), sid))
    print(f"已更新 {n_upd} 筆持股、標記 {len(sids)} 個 session")
    return 0


if __name__ == "__main__":
    sys.exit(main())
