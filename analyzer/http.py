"""共用 HTTP client — 處理 TWSE 等台灣站台常見 SSL 憑證鏈問題.

Streamlit Cloud (Debian) 的 OpenSSL 對 TWSE 憑證的 Subject Key Identifier
缺失會驗證失敗；本 helper 優先以正常驗證發請求，失敗時退回 verify=False
並自動靜默 urllib3 警告.
"""
from __future__ import annotations

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    ),
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
