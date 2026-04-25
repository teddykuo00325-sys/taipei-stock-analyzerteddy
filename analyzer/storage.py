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
import gzip
import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger("storage")

GITHUB_API = "https://api.github.com"


def is_cloud() -> bool:
    """偵測是否在 Streamlit Cloud 執行（檔案系統會重啟）."""
    # Streamlit Cloud 把程式掛在 /mount/src/... 路徑下
    try:
        here = str(Path(__file__).resolve())
        if "/mount/src" in here or "\\mount\\src" in here:
            return True
    except Exception:
        pass
    # 額外的環境變數判斷
    if os.getenv("STREAMLIT_CLOUD", "").lower() in ("1", "true", "yes"):
        return True
    hostname = os.getenv("HOSTNAME", "").lower()
    if "streamlit" in hostname:
        return True
    return False


def _cfg(db_path: str | None = None) -> dict | None:
    """讀取 Streamlit secrets；未設定則回傳 None.

    db_path: 指定要同步的檔案路徑（相對 repo 根目錄）.
             預設取 secrets 的 db_path，通常是 data/etf.db.
    """
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
            "db_path": db_path or g.get("db_path", "data/etf.db"),
        }
    except Exception:
        return None


def is_configured() -> bool:
    c = _cfg()
    return bool(c and c.get("token") and c.get("owner") and c.get("repo"))


def _cfg_for(repo_path: str) -> dict | None:
    """Get config for a specific file path in the repo."""
    return _cfg(db_path=repo_path)


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


def _download_raw(c: dict) -> tuple[bytes | None, str]:
    """以 Accept: application/vnd.github.raw 取得檔案原始 bytes.

    此 media type 支援 1~100 MB 檔案（普通 JSON 回應在 >1 MB 時 content 被截空）.
    """
    try:
        headers = _headers(c["token"]).copy()
        headers["Accept"] = "application/vnd.github.raw"
        r = requests.get(_content_url(c),
                         headers=headers,
                         params={"ref": c["branch"]},
                         timeout=60)
        if r.status_code == 404:
            return None, "not found"
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text[:120]}"
        return r.content, "ok"
    except Exception as e:
        return None, str(e)[:80]


def download_db(local_path: Path,
                repo_path: str | None = None) -> tuple[bool, str]:
    """從 GitHub 下載 DB 檔至 local_path；自動偵測 .gz 並解壓.

    使用 raw media type 直接取原始 bytes，避開 Contents API 的 1 MB 截斷限制.
    """
    c = _cfg_for(repo_path) if repo_path else _cfg()
    if not is_configured():
        return False, "GitHub 持久化未設定"

    # 先試 .gz 版本，不存在再試原始
    candidates = []
    base = c["db_path"]
    if not base.endswith(".gz"):
        candidates.append(dict(c, db_path=base + ".gz"))
    candidates.append(c)

    last_err = "—"
    for cfg_try in candidates:
        data, err = _download_raw(cfg_try)
        if data is None:
            last_err = err
            continue
        is_gz = cfg_try["db_path"].endswith(".gz")
        try:
            if is_gz:
                data = gzip.decompress(data)
        except Exception as e:
            last_err = f"gzip decode: {e}"
            continue
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(data)
        except Exception as e:
            last_err = f"write: {e}"
            continue
        return True, (f"已下載 {len(data) / 1024:.0f} KB"
                      + (" (解壓後)" if is_gz else ""))

    return False, f"下載失敗：{last_err}"


MAX_API_BYTES = 45 * 1024 * 1024   # ~45 MB 保守上限（API 實際 ~100MB 但 base64 overhead）


def upload_db(local_path: Path,
              message: str = "auto: update etf.db",
              repo_path: str | None = None,
              auto_compress: bool = True) -> tuple[bool, str]:
    """上傳 DB 至 GitHub (覆蓋).

    檔案 > 5 MB 時自動 gzip 壓縮成 .db.gz 上傳.
    """
    c = _cfg_for(repo_path) if repo_path else _cfg()
    if not is_configured():
        return False, "GitHub 持久化未設定"
    if not local_path.exists():
        return False, f"找不到本地檔案 {local_path}"
    try:
        raw = local_path.read_bytes()
        orig_size = len(raw)

        # 大於 5 MB 自動 gzip，否則直接上傳
        if auto_compress and orig_size > 5 * 1024 * 1024:
            data = gzip.compress(raw, compresslevel=6)
            compressed = True
            # 調整上傳路徑 → .db.gz
            if not c["db_path"].endswith(".gz"):
                c = dict(c)
                c["db_path"] = c["db_path"] + ".gz"
        else:
            data = raw
            compressed = False

        if len(data) > MAX_API_BYTES:
            return False, (f"檔案壓縮後仍 {len(data) / 1e6:.1f} MB，"
                           f"超過 GitHub Contents API 限制 ~45 MB；"
                           f"請執行 purge 縮減舊資料")

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
                         timeout=60)
        if r.status_code in (200, 201):
            mode = "gzip" if compressed else "raw"
            return True, (f"已上傳 {len(data) / 1024:.0f} KB ({mode}) · "
                          f"原始 {orig_size / 1024:.0f} KB")
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
