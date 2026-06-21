# 台北股市分析器 — 轉移到新電腦的完整指引

從 ZIP 解壓 / GitHub clone 後，依此順序設定即可恢復完整功能。

---

## 📦 套件包含內容

| 路徑 | 內容 |
|------|------|
| `analyzer/` | 41 個分析模組（screener / tiebreaker / performance / ETF signal …） |
| `app.py` | Streamlit 主程式（8 個 mode） |
| `scripts/send_daily_report.py` | TG 推送主腳本（GH Actions / 本機共用） |
| `.github/workflows/daily-tg-report.yml` | GH Actions 每日 08:30 推送 |
| `data/*.db` | 8 個 SQLite — K 線快取、ETF、產業、實盤回測等 |
| `data/ohlcv.db.gz` | 壓縮版 K 線（首次跑會自動解壓）|
| `每日推送TG.bat` | 本機推送 .bat（**含 bot token，預設停用**）|
| `requirements.txt` | Python 套件清單 |
| `選股邏輯說明書.md` | 完整選股理論文件 |

---

## 🚀 新電腦上的安裝步驟

### Step 1 — 安裝 Python 3.11

從 https://www.python.org/downloads/ 下載 **Python 3.11.x**（不要用 3.12+，部分套件相容性問題）。

**重點**：勾選「Add Python to PATH」。

驗證：
```powershell
python --version
# 應顯示 Python 3.11.x
```

### Step 2 — 解壓專案

把 ZIP 解壓到 `D:\台北股市分析器`（或任何路徑都可）。

### Step 3 — 建立虛擬環境 + 安裝套件

```powershell
cd D:\台北股市分析器
python -m venv venv
venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

裝完約 200MB（pandas / numpy / yfinance / plotly / streamlit 等）。

### Step 4 — 解壓 K 線 DB（首次只跑一次）

`data/ohlcv.db.gz` (~14MB) → 自動解壓為 `data/ohlcv.db` (~97MB)。

腳本會自動處理，但你也可手動：
```powershell
python -c "import gzip,shutil; shutil.copyfileobj(gzip.open('data/ohlcv.db.gz','rb'),open('data/ohlcv.db','wb'))"
```

### Step 5 — 跑 Streamlit 確認可用

```powershell
venv\Scripts\activate
streamlit run app.py
```

瀏覽器自動開 `http://localhost:8501`，看到 8 個 mode（🎯今日選股 / 📊系統績效…）即成功。

---

## 🔐 重要 — 設定 Telegram 推送（如果要用 TG）

### 選項 A：純 GH Actions（雲端推送，推薦）

如果有把專案推到自己的 GitHub：

1. 開 https://github.com/{你的帳號}/{repo 名}/settings/secrets/actions
2. 新增三個 secrets（值見舊機器 `每日推送TG.bat`）：
   ```
   TELEGRAM_BOT_TOKEN        = {你的 bot token}
   TELEGRAM_CHAT_ID          = @teddy_stockreport       (公開 channel)
   TELEGRAM_CHAT_ID_PRIVATE  = {你的私人 chat ID}
   ```
3. 設 cron-job.org 每天 08:30 (台北) 用 GitHub API 觸發 workflow_dispatch：
   - URL: `https://api.github.com/repos/{你的帳號}/{repo}/actions/workflows/daily-tg-report.yml/dispatches`
   - Method: POST
   - Body: `{"ref": "main"}`
   - Headers: `Authorization: Bearer {GitHub PAT}` + `Accept: application/vnd.github+json`

### 選項 B：本機 Windows 排程（不推 GH 也可）

1. 編輯 `每日推送TG.bat`，**拿掉 `exit /b 0` 那行**啟用推送
2. 開「工作排程器」→ 建立基本工作：
   - 名稱：台北股市每日 TG 推送
   - 觸發：每天 08:30
   - 動作：執行 `D:\台北股市分析器\每日推送TG.bat`
3. **注意**：如果同時用 GH Actions 跟本機排程，會每天送 2 次。**選一個就好**。

### 選項 C：Streamlit Cloud 部署

如果要部署到 https://share.streamlit.io：

1. 連到 GitHub repo
2. 在 Settings → Secrets 加入：
   ```toml
   [telegram]
   bot_token = "8993139052:AAFltUb8MoxA-tLaU0nRZhdt63FINnnmuMA"
   chat_id = "@teddy_stockreport"
   chat_id_private = "5506547630"

   [github]
   token = "{GitHub PAT — 用於 DB 自動同步}"
   owner = "{你的 GitHub 帳號}"
   repo = "{你的 repo 名稱}"
   branch = "main"
   ```

---

## 🔑 重要憑證清單（**值在本機 .bat 跟 GH Secret 找**，不寫進此檔避免 push 被擋）

| 用途 | 範例格式 | 取得方式 |
|------|---------|---------|
| Telegram Bot Token | `數字:英數混合` | @BotFather → /mybots |
| 公開 channel | `@teddy_stockreport` | 既有 channel |
| 私人 chat ID | `5506547630` | 自己 user ID（getUpdates 查） |
| GitHub repo | `{user}/{repo}` | GitHub URL |
| GitHub PAT | `github_pat_xxx...` | GH Settings → Developer settings → PAT |

⚠️ **這些是私密憑證**，絕對不要 push 到 public repo / 截圖 / 公開分享。
舊機器上完整值在這些位置：
- 本機 `每日推送TG.bat` 第 17-19 行
- GitHub repo 的 Settings → Secrets and variables → Actions
- cron-job.org webhook 設定的 Authorization header

---

## 📅 系統運作機制（轉移後的日常）

### 每日 08:30 自動流程

```
1. cron-job.org @ 08:30 (台北) 觸發 GH Actions workflow_dispatch
2. GH Actions ubuntu runner：
   a. checkout repo（含 realbacktest.db）
   b. install requirements
   c. 跑 scripts/send_daily_report.py:
      - 週末 → skip（market closed）
      - dedupe check（_check_gh_runs_today 防同日重複）
      - auto_close_expired() 結算到期 session
      - build_daily_report() 組報告
      - 公開推 channel @teddy_stockreport
      - 私人推 5506547630（含 Track Record + 資金配置）
      - auto_lock_today_picks() 把推薦鎖進 realbacktest.db
   d. git commit + push realbacktest.db（含 retry）
3. 結束（總時長 5-10 分鐘）
```

### Web 端（Streamlit）

可在本機 / Streamlit Cloud 跑：
```
streamlit run app.py
```

8 個 mode：
1. 🎯 今日選股 — Top 5 long/short + 5 層過濾
2. 🔎 個股查詢 — 單檔完整分析
3. ⭐ 收藏清單 — 自選股追蹤
4. 📈 多股比較 — 走勢疊加
5. 📊 主動式 ETF — 前 5 大持股變動
6. 🔥 資金流向 — 產業強弱
7. 📋 實盤回測 — 鎖定推薦追蹤 P&L
8. 📊 系統績效 — TG_auto 累積績效驗證

---

## 🩹 常見問題排除

### Q1：Streamlit 跑不起來
```
ModuleNotFoundError: No module named 'pandas'
```
→ 沒啟動 venv，先 `venv\Scripts\activate` 再跑

### Q2：Yahoo Finance 抓不到資料
GH Actions IP 被 Yahoo 限流。系統有自動偵測 `GITHUB_ACTIONS=true` 就 skip yfinance bulk_prepare，純用 cache。**本機通常 OK**。

### Q3：TG 推了重複訊息
檢查：
- GH Actions 跑了幾次 → `gh api repos/{user}/{repo}/actions/workflows/daily-tg-report.yml/runs`
- 本機 .bat 是否手動跑了多次
- Streamlit Cloud 是否有 user 在當天開啟 app（這個 bug 已修，移除 auto-push）

### Q4：歷史回測結果看起來怪
歷史回測用**交易日**（business day）計算 hold_days，跟實盤回測一致。如果是舊版（日曆日）的 session，比較會錯位 — 這版（commit f9c5e99 之後）已修正。

---

## 📚 進階：系統文件

- `選股邏輯說明書.md` — 11 維評分 + 7 維 tiebreaker + 5 層過濾 完整理論
- `analyzer/tiebreaker.py` 開頭注釋 — v3 含 ETF 動向第 8 維（H_max regime-aware）
- `analyzer/performance.py` — 風險調整指標公式

---

## ✅ 轉移完成 Checklist

- [ ] Python 3.11 安裝完成
- [ ] venv 建好 + pip install 完成
- [ ] streamlit run app.py 開得起來
- [ ] 8 個 mode 都能切換無錯誤
- [ ] TG 推送來源已重新設定（GH Secret 或本機排程，**擇一**）
- [ ] cron-job.org 觸發點已調整到新 repo 路徑（如有換 repo）
- [ ] 確認週末不會推送（FORCE_SEND 沒誤設）
- [ ] 第一次跑歷史回測測試 OK

完成上面所有項目即轉移成功。
