"""盤中停損 Alert — 每日 13:30 台北時間執行（台股 13:00 收盤後 30 分鐘）.

流程：
  1. 抓所有 open realbacktest sessions
  2. 用 price_cache.get() 強制取最新 K 線
  3. 每檔跑 check_technical_stop（多單跌破 MA10 / 空單突破 MA10）
  4. 觸發者 → 更新 exit_date/exit_price + 私人 TG 推警示
  5. commit realbacktest.db 回 repo

環境變數：
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID_PRIVATE     (優先; 若無用 TELEGRAM_CHAT_ID)
  FORCE_SEND=1                 (跳過週末 / 已無 open session skip)

退出碼：0 成功 / 已無事、1 失敗.
"""
from __future__ import annotations

import gzip
import os
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 強制 line-buffered stdout（GH Actions 即時看到進度）
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

socket.setdefaulttimeout(30)


def _install_yfinance_timeout_patch():
    """Monkey-patch yfinance 加 25s thread-timeout（跟 send_daily_report 同）."""
    try:
        import yfinance as yf
        import pandas as pd
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TO

        _TIMEOUT = 25
        _orig_history = yf.Ticker.history

        def _safe_history(self, *args, **kwargs):
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_orig_history, self, *args, **kwargs)
                try:
                    return fut.result(timeout=_TIMEOUT)
                except _TO:
                    print(f"[yf-timeout] Ticker.history > {_TIMEOUT}s",
                           flush=True)
                    return pd.DataFrame()
                except Exception as e:
                    print(f"[yf-error] Ticker.history: {e}", flush=True)
                    return pd.DataFrame()

        yf.Ticker.history = _safe_history

        _orig_download = yf.download

        def _safe_download(*args, **kwargs):
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_orig_download, *args, **kwargs)
                try:
                    return fut.result(timeout=_TIMEOUT)
                except _TO:
                    print(f"[yf-timeout] yf.download > {_TIMEOUT}s",
                           flush=True)
                    return pd.DataFrame()
                except Exception as e:
                    print(f"[yf-error] yf.download: {e}", flush=True)
                    return pd.DataFrame()

        yf.download = _safe_download
        print("[yf-patch] installed", flush=True)
    except Exception as e:
        print(f"[yf-patch] FAILED: {e}", flush=True)


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
_install_yfinance_timeout_patch()

TPE_TZ = timezone(timedelta(hours=8))


def _restore_ohlcv_from_repo():
    """若 ohlcv.db 不存在但 ohlcv.db.gz 存在，解壓恢復."""
    db = REPO_ROOT / "data" / "ohlcv.db"
    gz = REPO_ROOT / "data" / "ohlcv.db.gz"
    if db.exists() or not gz.exists():
        return
    try:
        with gzip.open(gz, "rb") as fin, open(db, "wb") as fout:
            fout.write(fin.read())
        print(f"[restore] decompressed {gz.name}", flush=True)
    except Exception as e:
        print(f"[restore] FAILED: {e}", file=sys.stderr, flush=True)


def _format_tg_message(triggered: dict, sessions_map: dict) -> str:
    """組合 TG 訊息 HTML.

    ★ 以「標的」為主呈現而非以 session — 使用者關心「我要出哪些股」
    而非「哪個 session 觸發」. 同一 code 出現在多 session 只印一次，
    但列出跨幾個 session（提醒集中風險）.
    """
    now = datetime.now(TPE_TZ).strftime("%Y-%m-%d %H:%M")
    total = sum(len(v) for v in triggered.values())

    # 用 code 聚合跨 session 觸發
    by_code = {}  # {code: {name, side, sessions: [(sid, exit_p, reason)]}}
    for sid, items in triggered.items():
        for code, name, side, reason, exit_p in items:
            key = code
            if key not in by_code:
                by_code[key] = {
                    "name": name, "side": side, "sessions": []
                }
            by_code[key]["sessions"].append((sid, exit_p, reason))

    unique_n = len(by_code)
    lines = [
        f"⚠️ <b>{now} 盤中停損 Alert</b>",
        "━━━━━━━━━━━━━━━━━━━",
        f"🛑 觸發 <b>{unique_n}</b> 檔標的觸及 MA10 停損"
        + (f"（共 {total} 筆跨 session）" if total > unique_n else ""),
        "",
    ]

    # 依「跨幾 session」降序（重複次數多的優先看，因為集中風險大）
    sorted_codes = sorted(
        by_code.items(),
        key=lambda kv: -len(kv[1]["sessions"])
    )

    for code, data in sorted_codes:
        name = data["name"]
        side = data["side"]
        sess_list = data["sessions"]
        emoji = "🛑" if side == "long" else "↩️"
        side_zh = "做多" if side == "long" else "做空"

        # 集中風險警示
        concentration = ""
        if len(sess_list) >= 2:
            concentration = (f"  ⚠️ <b>跨 {len(sess_list)} 個 session</b> "
                             f"= 集中部位風險")

        # 取代表性 exit（各 session 應該接近，用第一筆）
        rep_sid, rep_exit, rep_reason = sess_list[0]
        session_ids = ", ".join(f"#{s[0]}" for s in sess_list)

        lines.append(
            f"{emoji} <b>{code} {name}</b> ({side_zh}) "
            f"@ {rep_exit:.2f}{concentration}"
        )
        lines.append(f"   <i>{rep_reason}</i>")
        lines.append(f"   Session: {session_ids}")
        lines.append("")

    lines.append("<i>系統已自動標記 exit — 請儘快實盤出場</i>")
    return "\n".join(lines)


def main() -> int:
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        print("❌ TELEGRAM_BOT_TOKEN 未設定", file=sys.stderr)
        return 1

    # 週末跳過（台股休市，無盤中）
    today_tpe = datetime.now(TPE_TZ)
    weekday = today_tpe.weekday()
    if weekday >= 5 and os.environ.get("FORCE_SEND") != "1":
        weekday_zh = "六日"[weekday - 5]
        print(f"✅ 星期{weekday_zh} 市場休市，跳過")
        return 0

    _restore_ohlcv_from_repo()

    try:
        from analyzer import realbacktest, telegram_notify
    except Exception as e:
        print(f"❌ import failed: {e}", file=sys.stderr)
        return 1

    # 先查是否有 open session
    open_sessions = realbacktest.list_sessions(status="open")
    if not open_sessions:
        print("✅ 無進行中 session，跳過停損檢查")
        return 0

    print(f"[scan] {len(open_sessions)} open sessions 掃描 MA10 停損 …",
          flush=True)

    # 執行停損檢查（強制 fetch 最新 K 線）
    try:
        triggered = realbacktest.check_stop_loss_open_sessions(
            force_update=True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ check_stop_loss 例外: {e}", file=sys.stderr)
        return 1

    if not triggered:
        print("✅ 無標的觸發 MA10 停損 — 靜默不推 TG")
        return 0

    total = sum(len(v) for v in triggered.values())
    print(f"⚠️ {total} 檔觸發停損，跨 {len(triggered)} sessions", flush=True)

    # 組 TG 訊息（用 open_sessions map 補 lock_date 資訊）
    sessions_map = {s.id: s for s in open_sessions}
    tg_text = _format_tg_message(triggered, sessions_map)

    # 推送 — 私人優先，沒設就 fallback 公開
    private_chat = os.environ.get("TELEGRAM_CHAT_ID_PRIVATE", "").strip()
    if private_chat:
        ok, msg = telegram_notify.send_long_to(
            tg_text, private_chat, parse_mode="HTML")
    else:
        ok, msg = telegram_notify.send_long(tg_text, parse_mode="HTML")

    if ok:
        print(f"✅ {msg}")
        return 0
    print(f"❌ {msg}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
