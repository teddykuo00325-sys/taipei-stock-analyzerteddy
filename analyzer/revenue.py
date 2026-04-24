"""月營收資料 — TWSE OpenAPI t187ap05_L.

每月 10 日後公告上個月營收，內含：
  - 當月營收 (千元)
  - 上月比較增減 (MoM %)
  - 去年同月增減 (YoY %)
  - 累計營收 / 累計增減 (%)
"""
from __future__ import annotations

from dataclasses import dataclass
from time import time

import pandas as pd

from . import http

URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
URL_OTC = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"


@dataclass
class Revenue:
    code: str
    name: str
    year_month: str           # YYYY/MM
    revenue_k: int            # 當月營收（千元）
    mom_pct: float            # MoM %
    yoy_pct: float            # YoY %
    ytd_revenue_k: int        # 累計營收
    ytd_yoy_pct: float        # 累計 YoY %


_cache: dict = {"t": 0.0, "df": None}


def _fetch_raw() -> pd.DataFrame:
    """上市 + 上櫃合併月營收資料."""
    rename = {
        "公司代號": "code", "公司名稱": "name", "資料年月": "ym",
        "營業收入-當月營收": "rev",
        "營業收入-上月比較增減(%)": "mom",
        "營業收入-去年同月增減(%)": "yoy",
        "累計營業收入-當月累計營收": "ytd_rev",
        "累計營業收入-前期比較增減(%)": "ytd_yoy",
    }
    frames: list[pd.DataFrame] = []
    for src_url in (URL, URL_OTC):
        try:
            r = http.get(src_url, timeout=20)
            r.raise_for_status()
            d = pd.DataFrame(r.json())
            for k in rename:
                if k not in d.columns:
                    d[k] = None
            d = d.rename(columns=rename)[list(rename.values())]
            frames.append(d)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame(columns=list(rename.values()))
    df = pd.concat(frames, ignore_index=True)
    df["code"] = df["code"].astype(str).str.strip()
    for c in ("rev", "mom", "yoy", "ytd_rev", "ytd_yoy"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def snapshot(max_age_sec: int = 86400) -> pd.DataFrame:
    now = time()
    if _cache["df"] is not None and now - _cache["t"] < max_age_sec:
        return _cache["df"]
    try:
        df = _fetch_raw()
    except Exception:
        return pd.DataFrame()
    _cache["df"] = df
    _cache["t"] = now
    return df


def for_code(code: str) -> Revenue | None:
    df = snapshot()
    if df.empty:
        return None
    row = df[df["code"] == str(code).strip()]
    if row.empty:
        return None
    r = row.iloc[0]
    ym = str(r["ym"])
    # TWSE 採民國格式 11503 → 2026/03
    if len(ym) == 5:
        yy = int(ym[:3]) + 1911
        mm = int(ym[3:5])
        ym_fmt = f"{yy}/{mm:02d}"
    else:
        ym_fmt = ym
    return Revenue(
        code=r["code"], name=r["name"],
        year_month=ym_fmt,
        revenue_k=int(r["rev"] or 0),
        mom_pct=float(r["mom"] or 0),
        yoy_pct=float(r["yoy"] or 0),
        ytd_revenue_k=int(r["ytd_rev"] or 0),
        ytd_yoy_pct=float(r["ytd_yoy"] or 0),
    )
