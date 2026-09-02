# 台北股市分析器 — 給 Claude 的專案速覽

> 這是給任何 Claude 帳號 / 版本進到此專案時**先讀的檔案**。
> 內容不會自動同步 git — 手動維護，更新時記錄 `## 變更紀錄`。

---

## 1. 一句話

Streamlit + Telegram 台股每日推播系統。GitHub Actions 每天 08:30 台北時間跑選股 + 推 TG，13:30 掃 MA10 停損。

---

## 2. 使用者是誰、期待什麼互動風格

- **郭祐均**（tc8@mjauto.com.tw），InkNote AI 台灣區推廣成員
- **繁體中文回答**、產出要**可上呈** / **可帶走**（不是消耗性的對話而已）
- 慣用 **markdown 表格 + 段落 emoji 分區**表達複雜資訊
- 討論改動前**先分析證據**、**列選項 + trade-off**、**給推薦**，取得同意再改
- **不要**擅自加測試 / 建 md 文件 / 過度重構 — 除非明確要求
- 改完必 commit + push（含詳細 commit message）；rebase 衝突用 fetch+rebase 標準流程

---

## 3. 系統架構

```
使用者 → Streamlit Web (app.py, port 8501)   ← 本機開發 + 手動查詢
        │
        ├─ 讀 8 個 SQLite DB (data/*.db)
        ├─ 呼叫 analyzer/* 各模組
        └─ 顯示選股 / 回測 / 診斷 / Track Record

雲端 GH Actions ─┬─ 08:30 daily-tg-report.yml   → scripts/send_daily_report.py → TG
                └─ 13:30 midday-stop-alert.yml → scripts/midday_stop_alert.py  → TG (私人)

觸發源：cron-job.org 打 GH API workflow_dispatch（非 GH 內建 schedule，因後者延遲 4-6 小時）
```

---

## 4. 資料庫（`data/*.db`）

| DB | 用途 | 更新方式 |
|----|-----|--------|
| `ohlcv.db` (92 MB) | 全台股 K 線快取 | `price_cache.bulk_prepare()`, yfinance |
| `realbacktest.db` | 實盤回測 sessions + holdings（Track Record 主表）| daily 08:30 auto_lock + midday 13:30 stop |
| `etf.db` | 5 檔主動式 ETF holdings（00981A, 00991A, 00982A, 00992A, 00980A）| MoneyDJ 每日抓 |
| `industry.db` | TWSE 產業分類 | 週更 |
| `disposal_history.db` | 處置股歷史（TWSE punish API）| daily snapshot |
| `shareholders.db` | TDCC 籌碼分布（Level 2/3 小散戶）| 週更 |
| `margin_history.db` | 融資融券 | 舊資料 |
| `broker_history.db` | 券商分點（未使用主流程）| 舊資料 |

**持久化**：realbacktest / disposal_history / etf / shareholders / industry 這 5 個 workflow 會 commit 回 repo（`.gitignore` 白名單），其他不進 git。

---

## 5. 核心模組地圖

**入口點**：
- `app.py` — Streamlit UI（今日選股 / 回測 / 診斷 / Track Record 儀表板）
- `scripts/send_daily_report.py` — GH Actions 08:30 daily 入口
- `scripts/midday_stop_alert.py` — GH Actions 13:30 停損入口

**分析核心**（`analyzer/`）：
- `screener.py` — 選股主邏輯（scoring loop, 8-worker 平行）
- `diagnosis.py` — 單檔完整診斷（多維度 score / entry_zone / stop / target / R:R）
- `tiebreaker.py` — 9 維度加分（A-I：爆量突破 / 法人 / 動能 / 不過熱 / 甜蜜起漲 / 融券軋空 / ETF 動向 / 籌碼集中）
- `backtest_filter.py` — 5 層過濾 + regime 偵測（bull / weak_bull / sideways / weak_bear / bear）
- `daily_report.py` — 組 TG 報告（所有 section 拼裝）
- `realbacktest.py` — Track Record + auto_lock + auto_close + MA10 停損

**資料抓取**（`analyzer/`）：
- `price_cache.py` — K 線 yfinance + DB 快取
- `etf.py` / `etf_scraper.py` — 主動式 ETF holdings（MoneyDJ）
- `us_market.py` — 美股指標 + `overnight_gap_risk()`
- `disposal.py` — 處置股（TWSE punish OpenAPI）
- `shareholders.py` — 籌碼分布（TDCC）
- `institutional.py` / `margin.py` — 三大法人 / 融資券

**規則模組**（`analyzer/schools/`）：
- `chu_chia_hung.py` — 朱家泓派（含 `stop_levels` MA10 停損）
- `chip.py` — 籌碼派
- `base.py` — 共用 base class

---

## 6. 重要交易邏輯（近期演進）

### 2026-08-04 起：**Tier1 三層改善**（backtest_filter.py + us_market.py + screener.py）

依 07-04~08-03 近月分析（勝率 30%、累計 -32 萬）診斷出三個結構性問題並修正：

**1C. 弱多頭 / 弱空頭 regime**（原本只有 3 種 regime, 現 5 種）
```
bull:      allow_long=True,  allow_short=False, capital=1.0  (gap>=3 且 close>=ma20)
weak_bull: allow_long=False, allow_short=True,  capital=0.7  (gap>=3 但 close<ma20 - 回檔)
sideways:  allow_long=True,  allow_short=True,  capital=0.5  (|gap|<3)
weak_bear: allow_long=True,  allow_short=False, capital=0.7  (gap<=-3 但 close>ma20 - 反彈)
bear:      allow_long=False, allow_short=True,  capital=1.0  (gap<=-3 且 close<=ma20)
```

**2B. US overnight gap-down 風險** (`us_market.overnight_gap_risk()`)
- SOX ≤ -2% 或 SPX ≤ -2% 或 VIX ≥ 30 → **high** → 完全 skip 做多
- SOX ≤ -1% 或 SPX ≤ -1% 或 VIX ≥ 25 → **medium** → 做多資金 × 0.5

**3. min_score 門檻**（screener.screen）
- `min_score_long=85` / `min_score_short=-85`
- top_n 從 5 → 4（品質優於數量）

### 2026-08-05 起：**Track Record 重置**（realbacktest.py）
- `TRACK_RESET_DATE = "2026-08-05"`
- `TRACK_RESET_CAPITAL = 1_000_000`
- 所有 KPI / 資金配置只算 `lock_date >= TRACK_RESET_DATE` 的 sessions
- 之前的 sessions 保留 DB 但不進計算（見 `performance.py` 各函式的 `since` 參數）

### 2026-08-27：**平行化 scoring loop**（screener.py）
- `ThreadPoolExecutor(max_workers=8)`
- 每檔 `fut.result(timeout=60)` hard timeout
- 300 檔從 3 分 → ~30 秒

### GH Actions Workflow 可靠性
- `daily-tg-report.yml`: send step **20 min timeout** + retry step（with `/tmp/tg_sent_ok` marker 防雙推）
- 兩支 workflow 都有 dedup（`_check_gh_runs_today` 用 run_number tiebreaker 避免並行 dispatch 死鎖）

---

## 7. 修過的重要 bug（歷史）

| 日期 | Bug | 修法 |
|-----|-----|-----|
| 07-16 | HTML `<` 未 escape → TG 400 整封推不出 | 各處 `<` → `&lt;`, `str(e)` → `html.escape()` |
| 07-16 | ETF holdings DB 沒 commit 回 repo → 22 天沒更新 | `.gitignore` 白名單 + workflow commit 5 個 DB |
| 07-16 | `is_taiwan_focused` filter 過嚴 → 只抓 3/5 檔 | 改成 exclusion-based（排除 global/us/japan 等）|
| 07-21 | Sideways note 寫死「在 ±3% 內」但 gap +5% 矛盾 | note 動態化 |
| 07-21 | 停損距離 <1% → R:R 灌水 13-18 | `MIN_STOP_PCT = 2%` sanity check |
| 07-21 | Short target -21.68% 超過 20% cap | cap 基準改用 entry midpoint |
| 08-03 | screener `str(e)` 進 TG 未 escape | `html.escape()` |
| 08-03 | `telegram_notify` 硬切在 `<b>` 中間 | `_safe_truncate()` 補閉合 tag |
| 08-03 | `disposal.py` 6-char ETF 誤過濾 | 加 `not code.startswith("00")` |
| 08-03 | `auto_close_expired` 早關 1 天（用昨日收盤結算）| `today > target_dt` |
| 08-03 | Alpha vs TWII 對比 buy-and-hold 不公平 | 新增 `twii_matched_return()` 用 session 期間複利 |
| 08-03 | dedup 死鎖：並行 dispatch 互看 in_progress 都 skip | 用 `run_number` tiebreaker |
| 08-04 | `_section_capital_allocation` else 落入「強空頭」文案 | 改 dict lookup, 5 個 label 都有對應 |
| 08-27 | Scoring loop sequential，單檔卡住 hang 全部 | 8-worker 平行 + 60s per-task timeout |

---

## 8. 環境 / secrets

- **Python 3.11.x** + `requirements.txt`
- **`.venv/`** 本機 venv（Windows binary）
- **`.streamlit/secrets.toml`** — 含 Telegram bot token（`chat_id` 公開 channel + `chat_id_private` 私人 Track Record）
- **`每日推送TG.bat`** — 本機備援推送用（含 token, 不進 git）
- **GH Actions Secrets** — 已在 GitHub 設定：`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `TELEGRAM_CHAT_ID_PRIVATE`
- **cron-job.org** — 兩個 webhook 已設好（08:30 daily-tg + 13:30 midday-stop）

---

## 9. 常用開發指令

```bash
# 本機開 Web
streamlit run app.py

# 手動 force 觸發 daily 推送（跳過 dedup）
curl -X POST -H "Authorization: Bearer <PAT>" \
  https://api.github.com/repos/teddykuo00325-sys/taipei-stock-analyzerteddy/actions/workflows/daily-tg-report.yml/dispatches \
  -d '{"ref":"main","inputs":{"force":"true"}}'

# 看今天 GH Actions 狀態
gh run list --workflow=daily-tg-report.yml --limit 5

# 查 Track Record（本機 python）
python -c "from analyzer import realbacktest; print(realbacktest.track_record(since='2026-08-05'))"
```

---

## 10. 待處理 / 觀察中

- Tier1 效果驗證：需 N=30 樣本（約 4-6 週）才能統計顯著
- 若 08-05 後推播數過少（>50% 天數「無標的」）→ 考慮 min_score 從 85 降到 80
- 若仍有「1 日內停損」發生 → 考慮 US risk threshold 從 -2% 降到 -1.5%
- 週一進場勝率 10%（N=10 尚小）→ 等累積驗證是否加 filter

---

## 變更紀錄

- 2026-09-02 建立此檔（Claude 帳號轉換用）
