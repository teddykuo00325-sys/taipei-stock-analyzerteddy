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
    """讀取 Telegram credentials.

    優先順序：
      1. 環境變數 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
      2. Streamlit secrets [telegram] block

    chat_id 支援多種格式：
      - 單一字串："5506547630"
      - 多個逗號分隔："5506547630,-1001234567890,@my_channel"
      - Streamlit secrets 也可用 list: chat_id = ["123", "456"]
    """
    import os
    env_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    env_chat = os.environ.get("TELEGRAM_CHAT_ID")
    if env_token and env_chat:
        return {"token": env_token, "chat_id": str(env_chat)}
    try:
        import streamlit as st
        if "telegram" not in st.secrets:
            return None
        g = st.secrets["telegram"]
        token = g.get("bot_token")
        chat = g.get("chat_id")
        if not token or not chat:
            return None
        # secrets 若是 list，join 成逗號分隔字串
        if isinstance(chat, list):
            chat = ",".join(str(x) for x in chat)
        return {"token": token, "chat_id": str(chat)}
    except Exception:
        return None


def _parse_chats(chat_id_raw: str) -> list[str]:
    """把 chat_id 字串拆成 list（支援逗號分隔多個）."""
    return [c.strip() for c in chat_id_raw.split(",") if c.strip()]


def is_configured() -> bool:
    return _cfg() is not None


def send(text: str,
         parse_mode: str = "HTML",
         disable_preview: bool = True,
         silent: bool = False) -> tuple[bool, str]:
    """發送訊息到 Telegram（支援多個 chat_id）. 回傳 (ok, message)."""
    c = _cfg()
    if not c:
        return False, "未設定 Telegram secrets"
    if len(text) > 4000:
        text = text[:3950] + "\n\n…（內容過長，已截斷）"
    chats = _parse_chats(c["chat_id"])
    if not chats:
        return False, "chat_id 為空"
    url = f"https://api.telegram.org/bot{c['token']}/sendMessage"
    n_ok = 0
    last_err = ""
    for chat_id in chats:
        try:
            r = requests.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_preview,
                "disable_notification": silent,
            }, timeout=15)
            if r.status_code == 200:
                n_ok += 1
            else:
                last_err = f"{chat_id}: HTTP {r.status_code} {r.text[:100]}"
        except Exception as e:
            last_err = f"{chat_id}: {e}"
    if n_ok == len(chats):
        return True, f"已發送（{n_ok} 個收件人）"
    if n_ok > 0:
        return True, f"部分成功：{n_ok}/{len(chats)} ｜ 最後錯誤：{last_err}"
    return False, last_err or "全部失敗"


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
