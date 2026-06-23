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

# ★ 全域 socket timeout — 防止 yfinance 在雲端被 Yahoo 擋時無限 hang
# 沒設 timeout 時，被擋的 socket read 不會 raise，try/except 永遠接不到，
# 整個 build_daily_report 卡死 30 分鐘觸發 workflow 超時。
# 設 30 秒後：所有 socket-level 操作 30 秒沒回應 → raise socket.timeout
# → 既有 try/except 接住 → 該 section 跳過繼續其他 sections.
socket.setdefaulttimeout(30)

# 確保 import path 包含 repo 根目錄
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

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

    # 3) 先預組報告查每段內容（debug 用）
    try:
        from analyzer import daily_report
        text_preview = daily_report.build_daily_report(top_n=5)
        print("=" * 60)
        print("PREVIEW (組合好的報告，會送到 TG):")
        print("=" * 60)
        # 移掉 HTML tags 好讀
        import re as _re
        clean = _re.sub(r"<[^>]+>", "", text_preview)
        print(clean[:3000])
        if len(clean) > 3000:
            print(f"... (還有 {len(clean) - 3000} 字)")
        print("=" * 60)
    except Exception as e:
        print(f"[preview] FAILED: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()

    # 4) 寄報告
    try:
        ok, msg = daily_report.send_daily_report(
            top_n=5, auto_fetch_etf=True)
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
