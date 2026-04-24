"""持久化儲存 — 透過 GitHub API 將 SQLite DB 檔同步至同 repo.

需求：Streamlit Secrets 設定：
    [github]
    token = "ghp_xxxxxxxxxxxxxxxxxxxx"
    owner = "teddykuo00325-sys"
    repo = "taipei-stock-analyzerteddy"
    branch = "main"
    db_path = "data/etf.db"       # 在 repo 中的路徑

無 secrets 時，降級為純本機檔案（Streamlit Cloud 重啟即失去資料）.
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path

import requests

logger = logging.getLogger("storage")

GITHUB_API = "https://api.github.com"


def _cfg() -> dict | None:
    """讀取 Streamlit secrets；未設定則回傳 None."""
    try:
        import streamlit as st
        if "github" not in st.secrets:
            return None
        g = st.secrets["github"]
        return {
            "token": g.get("token"),
            "owner": g.get("owner"),
            "repo": g.get("repo"),
            "branch": g.get("branch", "main"),
            "db_path": g.get("db_path", "data/etf.db"),
        }
    except Exception:
        return None


def is_configured() -> bool:
    c = _cfg()
    return bool(c and c.get("token") and c.get("owner") and c.get("repo"))


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _content_url(c: dict) -> str:
    return f"{GITHUB_API}/repos/{c['owner']}/{c['repo']}/contents/{c['db_path']}"


def _get_sha(c: dict) -> str | None:
    try:
        r = requests.get(_content_url(c),
                         headers=_headers(c["token"]),
                         params={"ref": c["branch"]},
                         timeout=20)
        if r.status_code == 200:
            return r.json().get("sha")
    except Exception:
        pass
    return None


def download_db(local_path: Path) -> tuple[bool, str]:
    """從 GitHub 下載 DB 檔至 local_path. Return (success, message)."""
    c = _cfg()
    if not is_configured():
        return False, "GitHub 持久化未設定"
    try:
        r = requests.get(_content_url(c),
                         headers=_headers(c["token"]),
                         params={"ref": c["branch"]},
                         timeout=20)
        if r.status_code == 404:
            return False, "GitHub 上尚無 DB 檔（第一次執行）"
        if r.status_code != 200:
            return False, f"下載失敗 HTTP {r.status_code}"
        content_b64 = r.json().get("content", "")
        if not content_b64:
            return False, "下載失敗：空內容"
        data = base64.b64decode(content_b64)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        return True, f"已下載 {len(data)} bytes"
    except Exception as e:
        return False, f"下載例外：{e}"


def upload_db(local_path: Path,
              message: str = "auto: update etf.db") -> tuple[bool, str]:
    """上傳 DB 至 GitHub (覆蓋)."""
    c = _cfg()
    if not is_configured():
        return False, "GitHub 持久化未設定"
    if not local_path.exists():
        return False, f"找不到本地檔案 {local_path}"
    try:
        data = local_path.read_bytes()
        b64 = base64.b64encode(data).decode()
        sha = _get_sha(c)
        payload = {
            "message": message,
            "content": b64,
            "branch": c["branch"],
        }
        if sha:
            payload["sha"] = sha
        r = requests.put(_content_url(c),
                         headers=_headers(c["token"]),
                         json=payload,
                         timeout=30)
        if r.status_code in (200, 201):
            return True, f"已上傳 {len(data) / 1024:.1f} KB"
        return False, f"上傳失敗 HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, f"上傳例外：{e}"


def storage_info() -> dict:
    """回傳當前狀態（供 UI 顯示）."""
    c = _cfg()
    if not c:
        return {"configured": False}
    return {
        "configured": is_configured(),
        "owner": c.get("owner"),
        "repo": c.get("repo"),
        "branch": c.get("branch"),
        "db_path": c.get("db_path"),
    }
