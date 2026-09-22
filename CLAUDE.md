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

### 2026-09-03 起：**出場邏輯改造（A）+ score 解飽和（C）**

依 08-05~09-03 重置後 N=35 檢討（毛勝率 37.1%、毛期望 -0.47%/筆、**含成本淨 -7.63%**）。
關鍵診斷：**勝率不是主症狀** —— 37% 對「突破 + 技術停損」是正常值，病在盈虧比與成本。

| 診斷 | 數據 |
|-----|-----|
| 盈虧比 R | 1.354（毛）/ 1.163（淨）｜打平需 1.692 / 1.916 |
| 損益兩平勝率 | 42.5%（毛）/ **46.2%（淨）** vs 實際 34.3% → 缺口 -11.9 pp |
| 交易成本 | **0.62%/筆**，總計 -62,095 = 毛虧損的 **4.4 倍**；年化拖累 ≈ 31% |
| 獲利單撞天花板 | 13 筆中 8 筆（62%）；前 4 大贏家 3 筆是被行事曆殺掉的 |
| score 觸頂 | \|score\|=100 佔 **51%**，期望 -1.07%；85-94 那群 +0.64% |

**A. 出場：MA 移動停利為主，日曆降為安全網**
- `backtest_filter.recommended_hold_days` 語意改為「**最長持有上限**」：3/7/10 → **10/20/30** 交易日
- `backtest_filter.check_technical_stop` 加**獲利分層收緊**（新增 `TRAIL_TIGHTEN_PCT = 10.0`）
  ```
  未實現獲利 <  10% → 跌破/突破 MA10 出場（寬，容忍拉回，讓贏家跑）
  未實現獲利 >= 10% → 改用 MA5（緊，鎖住趨勢末端利潤）
  ```
- `realbacktest._close_if_fully_exited()` 新增：持股全出場即標記 session `closed`
  → **必要**，因 `track_record()` 只算 closed sessions，否則 P&L 卡在 open 不進 KPI
- `auto_close_expired()` 降為「清殭屍部位」，並在迴圈開頭先呼叫 `_close_if_fully_exited`

**C. score 解飽和（僅影響排序，門檻語意不變）**
- `diagnosis.Diagnosis` 新增 `raw_score`（未截斷，可超 ±100）；`score` 仍截斷在 ±100
- `screener` records 加 `原始分數` 欄；4 處排序改 `by=["原始分數","Tiebreak"]`
- **`min_score_long/short` 門檻仍用截斷後的 `分數`** → 85 還是 85，不必重新校準

⚠️ **尚未處理**（檢討時列出但當時決定不動）：
- 交易成本未進入任何決策（**最大單一問題**，A 只間接降低換手）
- 做空淨虧損（long +0.24% vs short -0.55% 單位資金報酬，N=13 太小）
- 集中度：`per_stock = capital / top_n`，當日僅 1 檔時 all-in 100%

### 2026-09-17 起：**鎖單延到 09:08**（盤前試撮價防護）

**問題**：workflow 08:30 觸發時台股尚未開盤（09:00 開），`_live_entry_price()`
拿 MIS `current` 得到的是**盤前試撮參考價** —— 早盤委託未撮合時會被推到
漲跌停上限，並非真實成交價。

實測（08-05~09-03，N=38）：15 筆進出場價落在當日 OHLC 區間外，3 筆恰為
「前一日收盤 × 1.0999」= 漲停價。以當日開盤價修正後，淨績效
**-14.09% → -18.26%**（空單進場價虛高 → 虛增獲利，修正後三筆最大「獲利」
空單全變虧損）。

**修法**：
- `realbacktest.LIVE_PRICE_SAFE_TIME = 09:08`、`live_price_trustworthy()`
- `_live_entry_price()` 在 09:08 前**完全不呼叫** `live.quotes()`，改走
  price_cache / fallback
- `daily_report._wait_until_market_open()`：鎖單前 sleep 到 09:08
  （上限 `_MAX_LOCK_WAIT_MIN = 45` 分，超過則不等但明確警告）
- **報告本身仍 08:30 正常推出**，只有「鎖單」動作往後挪；私人 addendum
  因排在鎖單之後，會在 09:08 後才送達

**連動**：`daily-tg-report.yml` 的 timeout 必須放寬，否則會被誤砍
- job `timeout-minutes` 60 → **90**
- 「Run daily report sender」step 20 → **50**（近 10 次實測平均僅 2.2 分，
  但要容納最多 38 分鐘等待）
- retry step 維持 20（觸發時已過 09:08，不需再等）

### 2026-09-17：**TG 推送前健檢 + 資金曲線方法論修正**

**丁. `telegram_notify.preflight()`** — 唯讀，不發訊息。兩支 script 的
main() 在跑 screener（數分鐘）之前先呼叫，失敗即中止，避免白跑。
驗兩關（缺一不可 —— 09-17 的兩種失敗態各中一關）：
1. `getMe` → token 是否有效（401 = 已被 Telegram 撤銷）
2. `getChatAdministrators` → bot 是否為頻道管理員且 `can_post_messages`
   （token 有效但非管理員時，要到送出才會 403）

網路暫時性錯誤**不阻擋**（回 True + 警告），只有確定的憑證/權限問題才中止。

**乙. `performance.equity_curve()` 改日頻組合淨值**

舊做法用 session 報酬率逐筆 `cumprod()`，等同假設「全額押第 1 個 session
→ 結清 → 全額押第 2 個 → …」。但 session 是**並行**的（08-05~09-17 期間
平均 4.8 個同時在場、最高 10 個），依序複利把虧損放大約 2 倍：

| | 累積淨報酬 | 資金配置基準 |
|---|---:|---:|
| 舊（逐筆複利）| **-66.63%** | 33.4 萬 |
| 新（固定基準 + 逐日已實現損益）| **-28.22%** | **71.8 萬** |

新算法：把帳戶視為固定 `TRACK_RESET_CAPITAL` 的現金帳戶，每筆持股出場時
把該筆淨損益記入 → 真正的組合淨值曲線。

連動修正：`summary_kpis()` 的 `total_return_*` / `max_dd_*`，以及
`daily_report._section_capital_allocation()` 用 `total_return_net_pct`
推算的「當前基準資金」—— 那是每日建議部位大小的分母，先前被系統性低估。

⚠️ **Sharpe / Sortino / Profit Factor 不受此修正影響** —— 那些走
`risk_metrics()`，以逐筆持股報酬計算，不經過 `equity_curve()`。

### 2026-09-22：**R:R 分母改用「操作停損」（丙 的第一步）**

**問題**：`risk_reward` 的分母取 `stop_levels` 算出的**結構支撐**，
但 realbacktest 實際是用 **MA10 移動停利**出場
（`check_technical_stop()`，獲利 >=10% 收緊到 MA5）。兩者是不同的東西 ——
TG 上顯示的 R:R 不描述系統真正會做的事。

2454 實例（2026-09-21，收 5010）：

| 角色 | 價位 |
|---|---:|
| 進場區 | 4644~4648（MA5/MA10）|
| R:R 舊分母（結構支撐）| **3655**，風險 -21.3% |
| 系統實際出場 | MA10 ≈ **4644** |

**連帶效應**：目標價走「機械式 +5%」分支者（40 檔實測佔 **35%**，只在
創新高、上方無壓力時觸發）通過 R:R >= 1.5 的比率僅 **29%**，
而型態頸線分支是 **75%** —— 系統在結構性地丟棄自己最強的突破股。

**實測排除了「只換目標價」這條路**：把機械式那 14 檔改用 3xATR 投射，
通過數只從 4/14 變 5/14。分子調再高也救不回 21% 的分母。

**修法**（`diagnosis.py`）：
- 新增 `RR_ATR_FLOOR_MULT = 1.5`、`_rr_stop()`、欄位 `rr_stop` / `rr_stop_note`
- 操作停損 = `entry_ref -/+ max(MA10 距離, 1.5 x ATR14)`
  （進場區本身常就是 MA5/MA10，距離趨近 0 會讓 R:R 爆成無限大，故設下限）
- `risk_reward` 分母改用 `rr_stop`；中立 stance 或無 ATR 時退回結構停損
- `daily_report` 顯示的「停損」同步改用 `rr_stop`

**門檻重新校準**：`MIN_RR` **1.5 → 1.8**（`daily_report.py`，硬過濾與文案
都改吃這個常數）。分母變小後 R:R 中位數由 ~1.56 升到 2.38，沿用 1.5 會讓
通過率衝到 80%、等於沒過濾。40 檔實測：

| 門檻 | 整體 | 機械式分支 | 其他分支 | 分支落差 |
|---:|---:|---:|---:|---:|
| 1.5 | 80% | 86% | 77% | -9pp |
| **1.8** | **62%** | **57%** | **65%** | **8pp** |
| 2.0 | 55% | 36% | 65% | 29pp |
| 舊制 | 55% | 29% | 75% | **46pp** |

選 1.8：選擇性回到跟舊制相當，同時把分支歧視從 46pp 壓到 8pp。

**下一步（丙 的第二步，尚未做）**：目標價算法改 ATR / 前波漲幅投射。
分母修好後才量得出分子換算法的真實效果。

### 2026-09-22：**目標價改前波漲幅投射（丙 的第二步，完成）**

**問題**：目標價在「創新高、上方無壓力」時會退回機械式
「當日高點 x 1.05」—— 40 檔實測佔 **35%**，而且正好是動能最強那批。

**為什麼沒有用純 ATR 倍數投射**（原本考慮的方案之一）：
R:R 的分母已經是 `max(MA10 距離, 1.5 x ATR)`，實測 **65%** 的標的由
ATR 下限決定。若分子也用 `k x ATR`，R:R 會退化成接近固定的 `k/1.5`，
**過濾器變成常數、完全失去鑑別力**。分子必須用與波動度無關的結構量。

**採用量測波幅（measured move）**，也是朱家泓派量波幅的標準作法：
- `_normalize_pivots()` — `wave._find_pivots()` 是高低點各自獨立找再合併，
  會出現連續同型（2454 就有 H4345 → H3875）。先壓成 H/L 交替，
  連續同型取極值。
- `_measured_move()` — 由後往前找最後一組相鄰 (L,H)，波幅 `amp = H - L`；
  若該 H 之後有回檔低點 L2，以 L2 為投射基準，`target = base + amp`。空方對稱。
- 插在「型態頸線」之後、「機械式壓力」之前。
- `TARGET_ATR_MIN_MULT = 2.0` — 目標價最小距離 2xATR（只當下限，很少觸發；
  上限仍由 `diagnose()` 的 ±20% cap 控制）。

**2454 實例**（2026-09-21 收 5010）：

| | 舊 | 新 |
|---|---:|---:|
| 目標價 | 5286.8（= 當日高 5035 x 1.05）| **5490.0** |
| 依據 | 機械式 | 波幅 1060（4760-3700）自回檔低 4430 投射 |
| R:R | 1.98 | **2.62** |

（隔日 09-22 盤中高點 5480，與投射值 5490 幾乎重合。）

**40 檔實測效果**：

| 目標價來源 | 舊 | 新 |
|---|---:|---:|
| 型態頸線 | 20 | 20 |
| **前波幅度投射** | 0 | **6** |
| 機械式 +5%/fallback | **14** | **8** |
| 壓力/支撐價 | 6 | 6 |

`MIN_RR` 維持 **1.8**（2.0 的結果完全相同，無需再動）：

| 階段 | 整體通過 | 機械式分支 | 其他分支 | 分支落差 |
|---|---:|---:|---:|---:|
| 原始（1.5，結構停損）| 55% | 29% | 75% | **-46pp** |
| 乙之後（1.8，操作停損）| 62% | 57% | 65% | -8pp |
| **丙完成（1.8 + 前波投射）** | **70%** | **62%** | **72%** | **-9pp** |

鑑別力未退化：R:R 標準差 2.36、範圍 0.19~4.64、20 檔全部相異值。

### 2026-09-22：**上櫃股即時報價全壞 + 過期價格防護**

使用者回報「TG 長期持股價格似乎錯誤」查出來的，兩個獨立 bug。

**Bug 1 — `live.quotes()` 批次只查上市**（`live.py`）
```python
ex_ch = "|".join(f"tse_{c}.tw_" for c in chunk)   # 只有 tse_
```
上櫃股永遠拿不到即時價，呼叫端靜默退回 `price_cache` 最後一根 K 線。

**Bug 2 — `live.quote()` 的空殼 row 誤判**（`live.py`）
MIS 對「代號存在但市場錯」會回一個欄位全空的 row
（`tse_4714.tw` → `[{c:'', z:None, ...}]`）。原本判斷 `if rows:`（list 非空）
為真就 return，**永遠不會往下試 `otc_`** —— 所以連單檔查詢也壞了。

**實測損害**：4714 永捷進場日 09-21 @12.10，系統拿 **09-17 的收盤 11.50**
當「現價」→ 報酬算成 -4.96%，實際 +2.48%。
**用比進場日還早 4 天的價格算進場後的損益。**

| 路徑 | 影響 |
|---|---|
| TG「進行中實盤回測」P&L | 受影響 |
| `close_session()` 結算 | **受影響** — 也用 `live.quotes()`，退回 cache 且原本無日期檢查 → 把過期價寫進 `exit_price` |
| `_live_entry_price()` | 部分 — 上櫃股退回 fallback（前一日收盤）|
| **MA10 停損檢查** | **不受影響** — 走 `price_cache.get(force_update=True)`，上櫃抓得到 |

**修法**：
- `_has_data()` 新增，檢查 row 真的有 `c` 欄位；`quote()` 改用它（Bug 2）
- `quotes()` 改兩段式：先整批 `tse_`，沒回資料的再補一輪 `otc_`（Bug 1）。
  比「每 chunk 同送兩種前綴」省一半請求 —— MIS 限 100 key/請求，同送會讓
  chunk 砍半、呼叫次數加倍，而上櫃只佔 7%。
- `_current_price()` 的 cache fallback 加「必須是今日」檢查（獨立第二道防線）
- `close_session()` 同樣加今日檢查，且**拿不到今日價就 skip 該檔並保持
  session `open`**，等下一輪再結 —— 寧可晚一天，不要記錯出場價

**歷史稽核**（重置後上櫃標的 5/71 = 7%，持股 5/77 = 6%）：

| 標的 | 記錄 | 用 `.TWO` 重算 |
|---|---:|---:|
| 6547 高端疫苗 | **-13.24%** | **-2.88%** |
| 4123 晟德（空）| **-5.98%** | **+0.24%** |
| 6907 雅特力-KY | -8.52% | -8.52%（無異常）|
| 3 筆合計 P&L | **-62,254** | **-22,485**（差 +39,770）|

⚠️ 09-03 那次進場價稽核裡「無 K 線無法驗證」的兩檔就是 6547 與 4123 ——
原因是當時只查 `.TW`。而 **高端疫苗 -13.24% 是那次樣本最大單筆虧損，
實際只有 -2.88%**。

**2026-09-22 已回溯校正**（被修的 session 在 `note` 加 `[價格校正 2026-09-22]` 標記）：
- 掃描重置後 77 筆持股，修正 **20 筆 / 22 個價格點**。entry 改當日開盤、
  exit 改當日收盤；偏離 < 1% 的 21 個點保留不動（避免把 yfinance 自身的
  四捨五入差異當成錯誤）。
- ★ **關鍵前置步驟：排除 split 假警報**。yfinance 即使 `auto_adjust=False`
  仍套用 split 調整，而台股的「股票股利」在 yfinance 就是 Stock Splits，
  除權日前的 OHLC 會被除以配股率。首次掃到 27 個「異常」，加上配股還原
  係數後降到 22 個 —— **神達（配股 1.10）、元大金（1.04）的正確價格若
  沒排除就會被改壞**。做這類稽核務必先查 Stock Splits。
- 損益：淨 P&L **-389,743 → -234,015**（+155,728）；
  `total_return_net_pct` **-38.97% → -23.01%**；最差單筆 -20.5% → -13.2%；
  資金配置基準 71.8 萬 → **77.0 萬**。
- 寫入前自動備份至 `data/realbacktest.backup_<timestamp>.db`
  （`.gitignore` 的 `data/*.db` 會排除，白名單只有 `realbacktest.db` 本身）。

### GH Actions Workflow 可靠性
- `daily-tg-report.yml`: send step **50 min timeout**（2026-09-17 由 20 放寬，容納等到 09:08 鎖單）+ retry step 20 min（with `/tmp/tg_sent_ok` marker 防雙推）
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
| 09-17 | bot token 明文寫進 public repo 的 `SETUP.md:109` → Telegram 撤銷 token，08:30 推送全失敗 | 清除明文改 placeholder；換發新 bot 並重設頻道管理員權限 |
| 09-17 | 08:30 鎖單抓到盤前試撮價（漲跌停），15/38 筆進出場價落在當日 OHLC 區間外 | 鎖單延到 09:08 + `live_price_trustworthy()` 守門 |
| 09-17 | `equity_curve()` 對並行 session 逐筆複利 → 累積虧損誇大 2 倍（-28.22% 報成 -66.63%），連帶資金配置基準由 71.8 萬縮成 33.4 萬 | 改固定基準 + 逐日已實現損益 |
| 09-22 | R:R 分母用結構支撐、但實際出場是 MA10 → R:R 不描述系統行為；機械式目標價分支通過率僅 29% vs 其他 75% | 分母改 `_rr_stop()`（MA10 + 1.5xATR 下限），MIN_RR 校準到 1.8 |
| 09-22 | 目標價在創新高時退回「當日高點 x1.05」（佔 35%），無結構依據 | 新增 `_measured_move()` 前波幅度投射，機械式分支 14→8 檔 |
| 09-22 | `live.quotes()` 批次只查 tse_、`live.quote()` 被 MIS 空殼 row 誤導 → 上櫃股全部拿不到即時價，退回過期 cache（4714 用了進場日前 4 天的收盤）| 兩段式 tse_→otc_ 補查、`_has_data()` 判斷、cache fallback 加今日檢查 |

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
- 2026-09-22 修上櫃股即時報價全壞（tse_/otc_ 前綴）＋ 過期價格防護；歷史稽核發現
  高端疫苗 -13.24% 實際只有 -2.88%。
- 2026-09-22 目標價改前波漲幅投射（丙 第二步完成）；機械式分支由 35% 降到 20%。
- 2026-09-22 R:R 分母改用操作停損（MA10 + 1.5xATR），MIN_RR 校準 1.5 → 1.8。
- 2026-09-17 新增 TG 推送前健檢（`telegram_notify.preflight()`）；修正
  `equity_curve()` 對並行 session 逐筆複利的方法論錯誤。
- 2026-09-17 TG 推送中斷事故：bot token 因寫在 public repo 的 SETUP.md 被 Telegram
  撤銷。已清除明文、換發新 bot（id 8638236811 @TeddyKuo_TEST_bot，舊 bot 帳號已刪除）、
  重設頻道管理員權限。同日修正盤前試撮價 bug（鎖單延到 09:08）。
- 2026-09-03 專案轉到 Claude Desktop（Code tab）；`.venv` 為空殼已重建（49 套件，
  pandas 3.0.5 / numpy 2.4.6 / streamlit 1.63.0 / yfinance 1.7.0 — 均為大版本跳躍，
  analyzer 全模組 import 通過）。新增第 6 節「2026-09-03 出場邏輯改造 + score 解飽和」。
