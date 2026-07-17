"""主動式 ETF 追蹤 —
1. 依 AUM（資產規模）自動抓取前 5 大
2. 每日持股快照儲存 (SQLite)
3. 持股變化 (今日 vs 上一交易日) 計算
4. 提供個股被哪些 ETF 持有的反查
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Lock
from time import time
from typing import Iterable

import pandas as pd
import yfinance as yf


# 已知主動式 ETF 候選清單（依 TWSE 009XXA 號段 + 使用者提供）
# 未來新增標的只需加入此清單即可被自動 AUM 排名
CANDIDATE_CODES: list[str] = [
    "00980A", "00981A", "00982A", "00983A", "00984A", "00985A",
    "00986A", "00987A", "00988A", "00989A",
    "00990A", "00991A", "00992A", "00993A", "00994A", "00995A",
    "00996A", "00997A",
]

# 已知中文名稱（若 MoneyDJ 爬取成功會自動覆蓋/新增）
NAME_MAP: dict[str, str] = {
    "00981A": "主動統一台股增長",
    "00982A": "主動群益台灣強棒",
    "00990A": "主動元大全球 AI 新經濟",
    "00991A": "主動復華未來 50",
    "00992A": "主動群益科技創新",
    "00993A": "主動安聯台灣",
}


def register_name(code: str, name: str) -> None:
    """外部模組（例如 etf_scraper）可呼叫此函式註冊中文名稱."""
    if code and name:
        NAME_MAP[code.strip().upper()] = name.strip()

DB_PATH = Path(__file__).parent.parent / "data" / "etf.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_db_lock = Lock()


# =============================================================
# 資料模型
# =============================================================
@dataclass
class EtfMeta:
    code: str
    name: str        # 中文名稱（顯示用；優先取自 NAME_MAP）
    nav: float
    aum: float       # 資產規模 (NTD)
    family: str
    updated: str     # ISO date
    name_en: str = ""   # yfinance longName（英文，用於過濾台股/全球）


@dataclass
class Holding:
    stock_code: str
    stock_name: str
    shares: int
    weight: float    # 0~100 (%)


# =============================================================
# SQLite
# =============================================================
def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.execute("""
        CREATE TABLE IF NOT EXISTS etf_aum (
            date TEXT, code TEXT, name TEXT, family TEXT,
            nav REAL, aum REAL,
            PRIMARY KEY (date, code)
        )""")
    c.execute("""
        CREATE TABLE IF NOT EXISTS etf_holdings (
            date TEXT, etf_code TEXT, stock_code TEXT, stock_name TEXT,
            shares INTEGER, weight REAL,
            PRIMARY KEY (date, etf_code, stock_code)
        )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hold_stock ON etf_holdings(stock_code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hold_etf_date ON etf_holdings(etf_code, date)")
    return c


def save_aum(snapshot: list[EtfMeta]) -> None:
    with _db_lock, _conn() as c:
        c.executemany(
            "INSERT OR REPLACE INTO etf_aum VALUES (?,?,?,?,?,?)",
            [(m.updated, m.code, m.name, m.family, m.nav, m.aum) for m in snapshot],
        )


def save_holdings(etf_code: str, date_str: str, holdings: list[Holding]) -> None:
    with _db_lock, _conn() as c:
        c.execute("DELETE FROM etf_holdings WHERE etf_code=? AND date=?",
                  (etf_code, date_str))
        c.executemany(
            "INSERT OR REPLACE INTO etf_holdings VALUES (?,?,?,?,?,?)",
            [(date_str, etf_code, h.stock_code, h.stock_name, h.shares, h.weight)
             for h in holdings],
        )


def purge_old(days: int = 90) -> int:
    """刪除超過 N 天的持股 / AUM 資料 (預設保留 90 日). 回傳刪除筆數."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with _db_lock:
        with _conn() as c:
            n1 = c.execute("DELETE FROM etf_holdings WHERE date < ?",
                           (cutoff,)).rowcount
            n2 = c.execute("DELETE FROM etf_aum WHERE date < ?",
                           (cutoff,)).rowcount
        # VACUUM 須在 transaction 外，獨立連線執行
        try:
            vac = sqlite3.connect(DB_PATH, isolation_level=None)
            vac.execute("VACUUM")
            vac.close()
        except Exception:
            pass
    return (n1 or 0) + (n2 or 0)


def db_size_kb() -> float:
    if not DB_PATH.exists():
        return 0.0
    return DB_PATH.stat().st_size / 1024


def list_holding_dates(etf_code: str) -> list[str]:
    with _db_lock, _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT date FROM etf_holdings WHERE etf_code=? "
            "ORDER BY date DESC", (etf_code,),
        ).fetchall()
    return [r[0] for r in rows]


def load_holdings(etf_code: str, date_str: str) -> pd.DataFrame:
    with _db_lock, _conn() as c:
        df = pd.read_sql_query(
            "SELECT stock_code, stock_name, shares, weight FROM etf_holdings "
            "WHERE etf_code=? AND date=? ORDER BY weight DESC",
            c, params=(etf_code, date_str),
        )
    return df


def diff_holdings(etf_code: str,
                  newer: str, older: str) -> pd.DataFrame:
    """計算 newer vs older 日的持股變化.
    輸出欄位：stock_code, stock_name, shares_new, shares_old, shares_diff,
             weight_new, weight_old, weight_diff, action
    action = NEW / OUT / +INC / -DEC

    ★ merge on stock_code only（不含 stock_name）— 舊版用兩者 merge，
    若同一 code 兩次 name 因亂碼/更名不同，會被拆成兩筆假的
    「新進 + 退出」訊號. 名稱優先取 newer；若 newer 缺（=OUT）用 older.
    """
    new_df = load_holdings(etf_code, newer)
    old_df = load_holdings(etf_code, older)
    if new_df.empty and old_df.empty:
        return pd.DataFrame()
    new_df = new_df.rename(columns={
        "shares": "shares_new", "weight": "weight_new",
        "stock_name": "stock_name_new"})
    old_df = old_df.rename(columns={
        "shares": "shares_old", "weight": "weight_old",
        "stock_name": "stock_name_old"})
    merged = pd.merge(new_df, old_df, on="stock_code",
                      how="outer").fillna(0)
    # 名稱優先用 newer 那次；若 newer 缺（新進為 0=OUT）退回 older
    merged["stock_name"] = merged["stock_name_new"].where(
        merged["stock_name_new"] != 0,
        merged["stock_name_old"])
    merged = merged.drop(columns=["stock_name_new", "stock_name_old"])
    merged["shares_diff"] = merged["shares_new"] - merged["shares_old"]
    merged["weight_diff"] = merged["weight_new"] - merged["weight_old"]

    def _act(r):
        if r["shares_old"] == 0 and r["shares_new"] > 0:
            return "NEW"
        if r["shares_new"] == 0 and r["shares_old"] > 0:
            return "OUT"
        if r["shares_diff"] > 0:
            return "+INC"
        if r["shares_diff"] < 0:
            return "-DEC"
        return "="

    merged["action"] = merged.apply(_act, axis=1)
    merged = merged.sort_values(
        by=["action", "shares_diff"], key=lambda s: s.map(
            {"NEW": 0, "+INC": 1, "-DEC": 2, "OUT": 3, "=": 4}
        ) if s.name == "action" else s.abs(),
        ascending=[True, False],
    ).reset_index(drop=True)
    return merged


# 反查：某股票被哪些 ETF 持有（最新一筆）
def holders_of(stock_code: str) -> pd.DataFrame:
    stock_code = str(stock_code).strip()
    with _db_lock, _conn() as c:
        df = pd.read_sql_query("""
            SELECT h.etf_code, h.date, h.shares, h.weight
            FROM etf_holdings h
            INNER JOIN (
                SELECT etf_code, MAX(date) AS latest
                FROM etf_holdings WHERE stock_code=?
                GROUP BY etf_code
            ) t ON h.etf_code = t.etf_code AND h.date = t.latest
            WHERE h.stock_code=?
            ORDER BY h.weight DESC
        """, c, params=(stock_code, stock_code))
    if df.empty:
        return df
    # 加上 ETF 名稱
    with _db_lock, _conn() as c:
        aum = pd.read_sql_query(
            "SELECT code, name FROM etf_aum GROUP BY code", c,
        )
    df = df.merge(aum.rename(columns={"code": "etf_code", "name": "etf_name"}),
                  on="etf_code", how="left")
    return df


# =============================================================
# AUM 排名（依 yfinance totalAssets）
# =============================================================
_aum_cache = {"time": 0.0, "list": []}


def _fetch_meta(code: str) -> EtfMeta | None:
    try:
        info = yf.Ticker(f"{code}.TW").info or {}
        aum = info.get("totalAssets")
        if aum is None or aum <= 0:
            return None
        name_en = info.get("longName") or info.get("shortName") or ""
        name = NAME_MAP.get(code) or name_en or code
        return EtfMeta(
            code=code, name=name,
            nav=float(info.get("navPrice") or 0),
            aum=float(aum),
            family=info.get("fundFamily") or "",
            updated=date.today().isoformat(),
            name_en=name_en,
        )
    except Exception:
        return None


def is_taiwan_focused(m: EtfMeta) -> bool:
    """是否為台股專注主動 ETF.

    改用「排除海外」邏輯（whitelist by exclusion）— 舊版要求名稱含
    「台/台灣/Taiwan」才通過，但很多台股主動 ETF 名稱沒此字（如
    「主動復華未來 50」實際投資台灣 50 大卻被誤 filter）.

    只要沒明確標「全球/US/日本/中國」等海外關鍵字，預設視為台股.
    """
    name_zh = m.name or ""
    name_en = (m.name_en or "").lower()
    family = (m.family or "").lower()
    combined_lower = (name_zh + " " + name_en + " " + family).lower()

    # 明確排除海外/區域型
    OVERSEAS_KEYWORDS = [
        "global", "world", "全球", "世界",
        "us growth", "us tech", "u.s.", "美國", "美股",
        "japan", "日本",
        "china ", "中國",  # 加空格避免 "china..." 誤傷
        "asia", "亞洲",
        "korea", "韓國",
        "vietnam", "越南",
        "innovation active",  # UPAMC Global Innovation
        "ark innovation",     # ARK Innovation
    ]
    for kw in OVERSEAS_KEYWORDS:
        if kw in combined_lower:
            return False
    return True


def _load_aum_from_db() -> list[EtfMeta]:
    """從 etf_aum 表還原 metas（給 yfinance 抓不到時 fallback 用）.

    etf_aum PK = (date, code)，同一 code 可能有多筆歷史快照；
    取每個 code 的最新一筆。
    """
    try:
        with _db_lock, _conn() as c:
            rows = c.execute("""
                SELECT date, code, name, family, nav, aum
                FROM etf_aum
                WHERE (code, date) IN (
                    SELECT code, MAX(date) FROM etf_aum GROUP BY code
                )
                ORDER BY aum DESC
            """).fetchall()
        return [EtfMeta(code=r[1], name=r[2], nav=float(r[4] or 0),
                         aum=float(r[5] or 0), family=r[3] or "",
                         updated=r[0] or "", name_en="")
                for r in rows if r[5] and float(r[5]) > 0]
    except Exception:
        return []


def refresh_aum(candidates: Iterable[str] | None = None,
                max_age_sec: int = 86400) -> list[EtfMeta]:
    """從候選清單抓 AUM、排序、存 DB.

    雲端 (GITHUB_ACTIONS=true)：直接讀 DB 跳過 yfinance — 避免逐個
    ETF yf.Ticker.info 在被擋 IP 上卡 30+ 秒 × 20 檔 → 工作流超時.

    yfinance 抓不到時，自動 fallback 到 DB 已存的 AUM 快照。
    """
    import os as _os
    if _os.environ.get("GITHUB_ACTIONS") == "true":
        metas = _load_aum_from_db()
        _aum_cache["list"] = metas
        _aum_cache["time"] = time()
        return metas

    now = time()
    if _aum_cache["list"] and now - _aum_cache["time"] < max_age_sec:
        return _aum_cache["list"]
    codes = list(candidates or CANDIDATE_CODES)
    metas: list[EtfMeta] = []
    for c in codes:
        m = _fetch_meta(c)
        if m:
            metas.append(m)
    # Fallback：若 yfinance 全失敗，從 DB 還原（保留前次 AUM 排序）
    if not metas:
        metas = _load_aum_from_db()
    metas.sort(key=lambda x: x.aum, reverse=True)
    _aum_cache["list"] = metas
    _aum_cache["time"] = now
    if metas:
        save_aum(metas)
    return metas


def top_n(n: int = 5, candidates: Iterable[str] | None = None,
          taiwan_only: bool = True) -> list[EtfMeta]:
    metas = refresh_aum(candidates)
    if taiwan_only:
        metas = [m for m in metas if is_taiwan_focused(m)]
    return metas[:n]
