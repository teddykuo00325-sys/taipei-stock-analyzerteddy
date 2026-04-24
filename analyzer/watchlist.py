"""收藏清單 — 使用 URL query params 做跨 session 保存.

分享 URL 即同步收藏；書籤保存。
"""
from __future__ import annotations

from typing import Iterable

import streamlit as st

PARAM_KEY = "watch"


def get() -> list[str]:
    """從 session_state / query params 讀取當前收藏清單."""
    # 優先讀 session
    if "watchlist" in st.session_state:
        return list(st.session_state.watchlist)
    # 從 URL 回寫到 session
    raw = st.query_params.get(PARAM_KEY, "")
    codes = [c.strip() for c in raw.split(",") if c.strip()] if raw else []
    st.session_state.watchlist = codes
    return codes


def _sync_url(codes: list[str]) -> None:
    if codes:
        st.query_params[PARAM_KEY] = ",".join(codes)
    elif PARAM_KEY in st.query_params:
        del st.query_params[PARAM_KEY]


def add(code: str) -> None:
    code = str(code).strip().upper()
    if not code:
        return
    lst = get()
    if code not in lst:
        lst.append(code)
        st.session_state.watchlist = lst
        _sync_url(lst)


def remove(code: str) -> None:
    code = str(code).strip().upper()
    lst = get()
    if code in lst:
        lst.remove(code)
        st.session_state.watchlist = lst
        _sync_url(lst)


def set_all(codes: Iterable[str]) -> None:
    lst = [str(c).strip().upper() for c in codes if str(c).strip()]
    st.session_state.watchlist = lst
    _sync_url(lst)


def contains(code: str) -> bool:
    return str(code).strip().upper() in get()
