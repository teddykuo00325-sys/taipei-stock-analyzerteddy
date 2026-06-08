"""Telegram 通知 — 每日報告 + 即時警示.

Streamlit Secrets 設定:
  [telegram]
  bot_token = "123456:ABC-DEF..."
  chat_id   = "-1001234567890"   # 群組 ID 或私人對話 ID

  # 建 Bot:
  #   1. Telegram 找 @BotFather → /newbot → 取 Bot Token
  #   2. 把 Bot 加入你的群組（或先跟 Bot 私訊一次啟動對話）
  #   3. 找 chat_id: 對 Bot 傳一句話，然後打開瀏覽器：
  #      https://api.telegram.org/bot<TOKEN>/getUpdates
  #      → "chat":{"id": ... } 那串數字
"""
from __future__ import annotations

import requests


def _cfg() -> dict | None:
    """讀取 Streamlit secrets；未設定回 None."""
    try:
        import streamlit as st
        if "telegram" not in st.secrets:
            return None
        g = st.secrets["telegram"]
        token = g.get("bot_token")
        chat = g.get("chat_id")
        if not token or not chat:
            return None
        return {"token": token, "chat_id": str(chat)}
    except Exception:
        return None


def is_configured() -> bool:
    return _cfg() is not None


def send(text: str,
         parse_mode: str = "HTML",
         disable_preview: bool = True,
         silent: bool = False) -> tuple[bool, str]:
    """發送訊息到 Telegram. 回傳 (ok, message)."""
    c = _cfg()
    if not c:
        return False, "未設定 Telegram secrets"
    # Telegram 訊息上限 4096 chars，過長要切片
    if len(text) > 4000:
        # 先發第一段
        first = text[:3950] + "\n\n…（內容過長，已截斷）"
        text = first
    url = f"https://api.telegram.org/bot{c['token']}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": c["chat_id"],
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_preview,
            "disable_notification": silent,
        }, timeout=15)
        if r.status_code == 200:
            return True, "已發送"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, f"例外：{e}"


def send_long(text: str, chunk_size: int = 3800,
              parse_mode: str = "HTML") -> tuple[bool, str]:
    """長訊息自動分段發送（每段 < 4000 chars）.

    分段以 \\n\\n 為界，避免切斷句子。
    """
    if len(text) <= chunk_size:
        return send(text, parse_mode=parse_mode)
    chunks: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        if len(buf) + len(para) + 2 > chunk_size:
            if buf:
                chunks.append(buf)
            buf = para
        else:
            buf = (buf + "\n\n" + para) if buf else para
    if buf:
        chunks.append(buf)
    n_ok = 0
    last_err = ""
    for i, ch in enumerate(chunks):
        prefix = f"<i>(第 {i+1}/{len(chunks)} 段)</i>\n" if len(chunks) > 1 else ""
        ok, msg = send(prefix + ch, parse_mode=parse_mode)
        if ok:
            n_ok += 1
        else:
            last_err = msg
            break
    if n_ok == len(chunks):
        return True, f"已分段發送 {n_ok}/{len(chunks)} 段"
    return False, f"發送失敗（第 {n_ok+1} 段）：{last_err}"
