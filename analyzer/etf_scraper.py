"""主動式 ETF 持股擷取 — 透過 MoneyDJ 網站抓取持股明細與中文名稱.

來源頁：https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid={code}.TW
頁面直接內嵌持股表格，可用 regex 解析。
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date

import pandas as pd

from . import etf, http
from .etf import Holding, register_name, save_holdings

MONEYDJ_URL = "https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm"


@dataclass
class FetchResult:
    ok: bool
    etf_code: str
    etf_name: str
    date: str
    holdings: list[Holding]
    error: str = ""


def _parse_moneydj(html: str, etf_code: str) -> FetchResult:
    # ETF 中文名稱 (title tag)
    m = re.search(r"<title>\s*(.+?)-\d+[A-Z]?\.TW-ETF", html)
    etf_name = m.group(1).strip() if m else etf_code

    # 資料日期
    m = re.search(r"資料日期[：:]\s*(\d{4})/(\d{1,2})/(\d{1,2})", html)
    if m:
        y, mo, d = m.groups()
        date_str = f"{y}-{int(mo):02d}-{int(d):02d}"
    else:
        date_str = date.today().isoformat()

    # 持股列 — <a href='...etfid=CODE.TW&back=ETF.TW'>名稱(CODE.TW)</a>
    # </td><td class="col06">權重</td><td class="col07">股數</td>
    pattern = re.compile(
        r"etfid=(\d{4,}[A-Z]?)\.TW&back=\w+\.TW'>"
        r"([^<]+?)\(\1\.TW\)</a></td>"
        r"<td class=\"col06\">([\d.]+)</td>"
        r"<td class=\"col07\">([\d,]+)</td>"
    )
    rows = pattern.findall(html)
    if not rows:
        return FetchResult(False, etf_code, etf_name, date_str, [],
                           "解析不到持股列（頁面格式可能變更）")

    holdings: list[Holding] = []
    for code, name, weight, shares in rows:
        try:
            holdings.append(Holding(
                stock_code=code.strip(),
                stock_name=name.strip(),
                shares=int(shares.replace(",", "")),
                weight=float(weight),
            ))
        except Exception:
            continue
    return FetchResult(True, etf_code, etf_name, date_str, holdings)


def fetch_holdings(etf_code: str, timeout: int = 15) -> FetchResult:
    etf_code = etf_code.strip().upper()
    try:
        r = http.get(MONEYDJ_URL, params={"etfid": f"{etf_code}.TW"},
                     timeout=timeout)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return _parse_moneydj(r.text, etf_code)
    except Exception as e:
        return FetchResult(False, etf_code, etf_code,
                           date.today().isoformat(), [],
                           f"請求失敗：{e}")


def fetch_all(etf_codes: list[str]) -> dict[str, FetchResult]:
    """抓取所有指定 ETF 並存入 DB + 同步註冊中文名."""
    out: dict[str, FetchResult] = {}
    for c in etf_codes:
        r = fetch_holdings(c)
        out[c] = r
        if r.ok:
            register_name(c, r.etf_name)
            if r.holdings:
                save_holdings(c, r.date, r.holdings)
    # 清空 AUM 快取使下次取 top_n 時用新名稱
    etf._aum_cache["list"] = []
    etf._aum_cache["time"] = 0.0
    return out


def fetch_and_save(etf_code: str) -> FetchResult:
    r = fetch_holdings(etf_code)
    if r.ok:
        register_name(etf_code, r.etf_name)
        if r.holdings:
            save_holdings(etf_code, r.date, r.holdings)
        etf._aum_cache["list"] = []
    return r


# =============================================================
# CSV 匯入（備援）
# =============================================================
def import_from_csv(etf_code: str, date_str: str,
                    content: bytes | str) -> tuple[bool, str, int]:
    try:
        if isinstance(content, bytes):
            content = content.decode("utf-8-sig", errors="replace")
        df = pd.read_csv(io.StringIO(content))
    except Exception as e:
        try:
            df = pd.read_csv(io.StringIO(content), encoding="big5")
        except Exception:
            return False, f"無法解析 CSV：{e}", 0

    col_map: dict = {}
    for cand, targets in {
        "stock_code": ["stock_code", "代號", "股票代號", "Code", "code"],
        "stock_name": ["stock_name", "名稱", "股票名稱", "Name", "name"],
        "shares": ["shares", "股數", "持股數", "Shares"],
        "weight": ["weight", "權重", "比重", "佔比", "Weight",
                   "Weight (%)", "weight(%)"],
    }.items():
        for t in targets:
            if t in df.columns:
                col_map[cand] = t
                break
    missing = [k for k in ("stock_code", "stock_name", "shares", "weight")
               if k not in col_map]
    if missing:
        return False, f"缺少欄位：{missing}", 0

    holdings: list[Holding] = []
    for _, r in df.iterrows():
        try:
            code = str(r[col_map["stock_code"]]).strip()
            name = str(r[col_map["stock_name"]]).strip()
            shares = int(float(str(r[col_map["shares"]]).replace(",", "")))
            weight = float(str(r[col_map["weight"]]).replace("%", "").strip())
            if code and name:
                holdings.append(Holding(code, name, shares, weight))
        except Exception:
            continue
    if not holdings:
        return False, "解析到 0 筆有效資料", 0
    save_holdings(etf_code, date_str, holdings)
    return True, f"匯入 {len(holdings)} 檔持股", len(holdings)
