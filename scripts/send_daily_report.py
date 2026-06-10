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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

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
    """查 GitHub Actions 今日是否已有此 workflow 成功跑（且推送成功）.

    透過 repo runs API 不需 PAT（public repo）。
    回 True 表示今日已成功跑過，可以跳過。
    """
    try:
        # 從 $GITHUB_REPOSITORY (GH Actions 內建) 取 owner/repo
        repo = os.environ.get("GITHUB_REPOSITORY")
        wf_id = os.environ.get("GITHUB_WORKFLOW_REF", "").split("@")[0]
        wf_name = wf_id.split("/")[-1] if wf_id else "daily-tg-report.yml"
        if not repo:
            return False
        url = (f"https://api.github.com/repos/{repo}/actions/workflows/"
               f"{wf_name}/runs?status=success&per_page=10")
        r = requests.get(url, timeout=10,
                          headers={"Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            return False
        today_tpe = datetime.now(TPE_TZ).date()
        for run in r.json().get("workflow_runs", []):
            # run_started_at 是 UTC ISO timestamp
            ts = run.get("run_started_at", "")
            try:
                dt_utc = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                dt_tpe = dt_utc.astimezone(TPE_TZ)
                if dt_tpe.date() == today_tpe:
                    # 排除「正在跑的自己」這次 run（current run 不算）
                    current_run_id = os.environ.get("GITHUB_RUN_ID")
                    if current_run_id and str(run.get("id")) == current_run_id:
                        continue
                    return True
            except Exception:
                continue
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

    # 1) 去重檢查：今日已發過就跳過（除非 FORCE_SEND=1）
    if os.environ.get("FORCE_SEND") != "1":
        if _already_sent_today():
            today_tpe = datetime.now(TPE_TZ).strftime("%Y-%m-%d %H:%M")
            print(f"✅ 今日 ({today_tpe} TPE) 已發送過，跳過此次 run")
            return 0

    # 2) 還原 K 線
    _restore_ohlcv_from_repo()

    # 3) 寄報告
    try:
        from analyzer import daily_report
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
