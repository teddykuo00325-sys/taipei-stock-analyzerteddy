"""共用 HTTP client — 處理 TWSE 等台灣站台常見 SSL 憑證鏈問題.

Streamlit Cloud (Debian) 的 OpenSSL 對 TWSE 憑證的 Subject Key Identifier
缺失會驗證失敗；本 helper 優先以正常驗證發請求，失敗時退回 verify=False
並自動靜默 urllib3 警告.
"""
from __future__ import annotations

import json
import time
from typing import Any

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

_session = requests.Session()
_session.headers.update(DEFAULT_HEADERS)


def get(url: str, *, params=None, headers=None,
        timeout: float = 15, **kwargs) -> requests.Response:
    """GET with automatic SSL-verify fallback."""
    merged = dict(DEFAULT_HEADERS)
    if headers:
        merged.update(headers)
    try:
        return _session.get(url, params=params, headers=merged,
                            timeout=timeout, **kwargs)
    except requests.exceptions.SSLError:
        return _session.get(url, params=params, headers=merged,
                            timeout=timeout, verify=False, **kwargs)


class JSONFetchError(Exception):
    """API 回應非 JSON（HTML 錯誤頁、空 body、被 geo-block 等）."""
    def __init__(self, url: str, status: int, body_preview: str):
        self.url = url
        self.status = status
        self.body_preview = body_preview
        super().__init__(
            f"非 JSON 回應 from {url} "
            f"(HTTP {status}, body[:80]={body_preview!r})"
        )


def get_json(url: str, *, params=None, headers=None,
             timeout: float = 15, retries: int = 2,
             backoff: float = 1.5) -> Any:
    """GET + 解析 JSON，含自動重試與清楚錯誤.

    雲端常見問題：TWSE/TPEX 偶爾對非台灣 IP 回 HTML 錯誤頁或空 body。
    用本函式的呼叫處應 catch JSONFetchError 顯示給使用者，避免
    "Expecting value: line 1 column 1 (char 0)" 這種無解錯誤訊息。
    """
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = get(url, params=params, headers=headers, timeout=timeout)
            r.raise_for_status()
            text = r.text
            if not text or not text.strip():
                raise JSONFetchError(url, r.status_code, "")
            stripped = text.lstrip()
            if stripped.startswith("<"):
                # HTML 錯誤頁 / geo-block 攔截頁
                raise JSONFetchError(url, r.status_code, stripped[:80])
            return json.loads(text)
        except (JSONFetchError, json.JSONDecodeError,
                requests.exceptions.RequestException) as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
                continue
            break
    if isinstance(last_err, JSONFetchError):
        raise last_err
    raise JSONFetchError(url, 0, str(last_err)[:80])
