"""台股產業別分類 — 透過 TWSE OpenAPI t187ap03_L 取得.

各上市公司的「產業別」以代碼呈現，需對照中文名稱.
"""
from __future__ import annotations

from time import time

import pandas as pd
import requests

TWSE_COMPANY_API = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"

# TWSE 產業別代碼 → 中文
CODE_MAP: dict[str, str] = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維",
    "05": "電機機械", "06": "電器電纜", "07": "化學工業", "08": "玻璃陶瓷",
    "09": "造紙工業", "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業",
    "13": "電子工業", "14": "建材營造", "15": "航運業", "16": "觀光餐旅",
    "17": "金融保險業", "18": "貿易百貨業", "19": "綜合", "20": "其他",
    "21": "化學工業", "22": "生技醫療業", "23": "油電燃氣業",
    "24": "半導體業", "25": "電腦及週邊設備業", "26": "光電業",
    "27": "通信網路業", "28": "電子零組件業", "29": "電子通路業",
    "30": "資訊服務業", "31": "其他電子業", "32": "文化創意業",
    "33": "農業科技", "34": "電子商務", "35": "綠能環保",
    "36": "數位雲端", "37": "運動休閒", "38": "居家生活",
    "80": "管理股票", "91": "存託憑證", "99": "受益證券",
}


def code_to_name(code: str) -> str:
    return CODE_MAP.get(str(code).zfill(2), f"其他({code})")


_cache: dict = {"time": 0.0, "df": None}


def _fetch_raw() -> pd.DataFrame:
    r = requests.get(TWSE_COMPANY_API,
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.raise_for_status()
    data = r.json()
    df = pd.DataFrame(data)
    # 標準化欄位
    keep = {
        "公司代號": "code",
        "公司簡稱": "short_name",
        "公司名稱": "full_name",
        "產業別": "ind_code",
        "英文簡稱": "name_en",
    }
    for k in keep:
        if k not in df.columns:
            df[k] = ""
    df = df.rename(columns=keep)[list(keep.values())]
    df["code"] = df["code"].astype(str).str.strip()
    df["ind_code"] = df["ind_code"].astype(str).str.zfill(2)
    df["industry"] = df["ind_code"].map(lambda c: CODE_MAP.get(c, f"其他({c})"))
    return df


def snapshot(max_age_sec: int = 86400) -> pd.DataFrame:
    now = time()
    if _cache["df"] is not None and now - _cache["time"] < max_age_sec:
        return _cache["df"]
    try:
        df = _fetch_raw()
    except Exception:
        return pd.DataFrame(columns=["code", "short_name", "full_name",
                                      "ind_code", "name_en", "industry"])
    _cache["df"] = df
    _cache["time"] = now
    return df


def info_for(code: str) -> dict | None:
    df = snapshot()
    if df.empty:
        return None
    row = df[df["code"] == str(code).strip()]
    if row.empty:
        return None
    r = row.iloc[0]
    return {
        "code": r["code"],
        "short_name": r["short_name"],
        "full_name": r["full_name"],
        "ind_code": r["ind_code"],
        "industry": r["industry"],
        "name_en": r["name_en"],
    }


def industry_of(code: str) -> str:
    info = info_for(code)
    return info["industry"] if info else "未分類"
