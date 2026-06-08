"""GitHub Actions / cron 用 — 不經 Streamlit 直接組 + 發報告.

讀取環境變數：
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
  GH_PAT (optional)               # 若要還原 ohlcv.db 從 GitHub
  GH_REPO (optional)              # "owner/repo"，預設用本機 git origin

執行流程：
  1. 嘗試解壓 data/ohlcv.db.gz → data/ohlcv.db（若 K 線 cache 為空）
  2. 觸發 daily_report.send_daily_report()
  3. 印 ok/msg 到 stdout（GH Actions log 可看）

退出碼：0 成功、1 失敗。
"""
from __future__ import annotations

import gzip
import os
import sys
from pathlib import Path

# 確保 import path 包含 repo 根目錄
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


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

    # 1) 還原 K 線
    _restore_ohlcv_from_repo()

    # 2) 寄報告
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
