"""GitHub Actions / cron 用 — 不經 Streamlit 直接組 + 發報告.

讀取環境變數：
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
  FORCE_SEND (optional)           # ="1" 時跳過「今日已發送」去重

執行流程：
  1. 嘗試解壓 data/ohlcv.db.gz → data/ohlcv.db（若 K 線 cache 為空）
  2. 檢查 Telegram channel 最新訊息：若今日已有報告 → 跳過
     （讓 cron 設多個時點，搶到第一次成功的）
  3. 觸發 daily_report.send_daily_report()
  4. 印 ok/msg 到 stdout（GH Actions log 可看）

退出碼：0 成功 / 已跳過、1 失敗。
"""
from __future__ import annotations

import gzip
import os
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ★ 強制 line-buffered stdout — 確保每個 print 立即 flush，否則 GH Actions
# 看不到中間日誌，hang 時無法定位卡在哪
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# ★ 全域 socket timeout（純 Python socket 防護，對 curl_cffi 無效但仍保留）
socket.setdefaulttimeout(30)

# ★ Monkey-patch yfinance — yfinance 用 curl_cffi 忽略 socket.setdefaulttimeout
# 全局為 yf.Ticker.history 與 yf.download 加 thread-timeout，凡是雲端被
# Yahoo 擋的呼叫 25 秒內無回應 → 視為失敗回空 DataFrame，主流程不卡死.
def _install_yfinance_timeout_patch():
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
                    print(f"[yf-timeout] Ticker.history > {_TIMEOUT}s, "
                           f"return empty", flush=True)
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
                    print(f"[yf-timeout] yf.download > {_TIMEOUT}s, "
                           f"return empty", flush=True)
                    return pd.DataFrame()
                except Exception as e:
                    print(f"[yf-error] yf.download: {e}", flush=True)
                    return pd.DataFrame()

        yf.download = _safe_download
        print("[yf-patch] installed: history/download → 25s thread-timeout",
              flush=True)
    except Exception as e:
        print(f"[yf-patch] FAILED: {e}", flush=True)


# 確保 import path 包含 repo 根目錄
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# patch 必須在 analyzer 模組被 import 之前執行
_install_yfinance_timeout_patch()

TPE_TZ = timezone(timedelta(hours=8))


def _already_sent_today() -> bool:
    """查 Telegram channel 最新幾則訊息，若有今日（台北日期）的報告就跳過."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    today_tpe = datetime.now(TPE_TZ).date()
    # 用 getUpdates 不行（會 race），改用 getChat + 抓 latest_message_id 確認
    # 簡化：抓近 24 小時內是否有 bot 自己發過「台北股市分析器每日報告」字樣
    try:
        # forwardMessage 不行；用 sendChatAction 也不行。
        # 最穩做法：呼叫 getUpdates 並掃我 bot 自己發到此 chat 的訊息。
        # 但 channel 推送的訊息 getUpdates 拿不到。
        # 改用「dry-run + getMe」確認 bot 活著，然後依 GH Actions 自身的
        # idempotency：在 repo 留個 sentinel file 或用 GH artifact。
        # 最簡單：用 GitHub API 看今天的 workflow runs 是否已有 success。
        return _check_gh_runs_today()
    except Exception:
        return False


def _check_gh_runs_today() -> bool:
    """查 GitHub Actions 今日是否已有此 workflow run（任何狀態，含 in_progress）.

    回 True → 跳過此次 run，避免重複推送。
    抓所有狀態（success / in_progress / queued / failure），因為：
      - 兩個 cron 同時被 release 時都是 in_progress，要彼此看得到對方
      - 已 success 的 run 也要當作「今天已推過」
      - failure 的也算（避免失敗後又一直 retry）
    """
    try:
        repo = os.environ.get("GITHUB_REPOSITORY")
        wf_id = os.environ.get("GITHUB_WORKFLOW_REF", "").split("@")[0]
        wf_name = wf_id.split("/")[-1] if wf_id else "daily-tg-report.yml"
        current_run_id = os.environ.get("GITHUB_RUN_ID")
        if not repo:
            return False
        # ★ 不再加 ?status=success — 抓所有狀態
        url = (f"https://api.github.com/repos/{repo}/actions/workflows/"
               f"{wf_name}/runs?per_page=20")
        r = requests.get(url, timeout=10,
                          headers={"Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            return False
        today_tpe = datetime.now(TPE_TZ).date()
        for run in r.json().get("workflow_runs", []):
            run_id = str(run.get("id"))
            # 排除自己
            if current_run_id and run_id == current_run_id:
                continue
            ts = run.get("run_started_at", "")
            try:
                dt_utc = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                dt_tpe = dt_utc.astimezone(TPE_TZ)
            except Exception:
                continue
            if dt_tpe.date() != today_tpe:
                continue
            status = run.get("status", "")
            concl = run.get("conclusion", "")
            # success / in_progress / queued 一律 skip
            # failure / cancelled 不算（讓重試有機會）
            if status in ("completed",):
                if concl == "success":
                    return True
                # failure / cancelled / timed_out → 不擋
            elif status in ("in_progress", "queued", "waiting", "pending"):
                # 已有別人在跑，跳過
                return True
        return False
    except Exception:
        return False


def _restore_ohlcv_from_repo():
    """若 ohlcv.db 不存在但 ohlcv.db.gz 存在，解壓恢復."""
    db = REPO_ROOT / "data" / "ohlcv.db"
    gz = REPO_ROOT / "data" / "ohlcv.db.gz"
    if db.exists() or not gz.exists():
        return
    try:
        with gzip.open(gz, "rb") as fin, open(db, "wb") as fout:
            fout.write(fin.read())
        print(f"[restore] decompressed {gz.name} → ohlcv.db "
              f"({db.stat().st_size / 1e6:.1f} MB)")
    except Exception as e:
        print(f"[restore] FAILED: {e}", file=sys.stderr)


def main() -> int:
    # 0) 驗證 credentials 在
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        print("❌ TELEGRAM_BOT_TOKEN 未設定", file=sys.stderr)
        return 1
    if not os.environ.get("TELEGRAM_CHAT_ID"):
        print("❌ TELEGRAM_CHAT_ID 未設定", file=sys.stderr)
        return 1

    # 0.5) 週末跳過推送 — 市場休市，報告內容跟週五一樣（除非 FORCE_SEND）
    today_tpe = datetime.now(TPE_TZ)
    weekday = today_tpe.weekday()  # Monday=0, Sunday=6
    if weekday >= 5 and os.environ.get("FORCE_SEND") != "1":
        weekday_zh = "六日"[weekday - 5]
        print(f"✅ 今天是星期{weekday_zh}（市場休市），跳過推送 "
              f"({today_tpe.strftime('%Y-%m-%d %H:%M')} TPE)")
        return 0

    # 1) 去重檢查：今日已發過就跳過（除非 FORCE_SEND=1）
    if os.environ.get("FORCE_SEND") != "1":
        if _already_sent_today():
            today_tpe = datetime.now(TPE_TZ).strftime("%Y-%m-%d %H:%M")
            print(f"✅ 今日 ({today_tpe} TPE) 已發送過，跳過此次 run")
            return 0

    # 2) 還原 K 線
    _restore_ohlcv_from_repo()

    # 3) 組報告 (build 一次，preview + send 共用避免重複跑 screener)
    text = None
    try:
        from analyzer import daily_report, etf, etf_scraper
        # ★ ETF 抓取移到 build 之前 — 舊版在 send_daily_report 內部
        # auto_fetch_etf 位置導致 build 用舊資料建 ETF section，
        # 之後 fetch 也來不及影響本次推送.
        try:
            metas = etf.top_n(5, taiwan_only=True)
            if metas:
                fetch_r = etf_scraper.fetch_all([m.code for m in metas])
                # 逐個 log — 若雲端 IP 被 MoneyDJ 擋這裡會看到 error
                for code, res in (fetch_r or {}).items():
                    status = "✅" if res.ok else "❌"
                    detail = (f"date={res.date} n={len(res.holdings)}"
                              if res.ok else f"err={res.error[:60]}")
                    print(f"[etf-scraper] {status} {code} {detail}",
                          flush=True)
        except Exception as _e:
            print(f"[etf-scraper] FAILED: {_e}", flush=True)

        text = daily_report.build_daily_report(top_n=5)
        # Preview log — 印出 HTML 移除後的純文字
        print("=" * 60)
        print("PREVIEW (組合好的報告，會送到 TG):")
        print("=" * 60)
        import re as _re
        clean = _re.sub(r"<[^>]+>", "", text)
        print(clean[:3000])
        if len(clean) > 3000:
            print(f"... (還有 {len(clean) - 3000} 字)")
        print("=" * 60)
    except Exception as e:
        print(f"[build] FAILED: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()
        return 1

    # 4) 寄報告 — 傳入 prebuilt_text 避免重複 build（雲端省 ~25 分鐘）
    try:
        ok, msg = daily_report.send_daily_report(
            top_n=5, auto_fetch_etf=True, prebuilt_text=text)
        if ok:
            print(f"✅ {msg}")
            return 0
        print(f"❌ {msg}", file=sys.stderr)
        return 1
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ 例外：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
