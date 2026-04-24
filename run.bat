@echo off
REM 台北股市分析器 - 啟動腳本
cd /d "%~dp0"

REM 檢查依賴是否齊全（缺少即安裝）
python -c "import streamlit, yfinance, plotly, pandas, scipy" 2>nul
if errorlevel 1 (
    echo 安裝相依套件...
    python -m pip install -r requirements.txt
)

echo 啟動台北股市分析器（瀏覽器將自動開啟 http://localhost:8501）
python -m streamlit run app.py
pause
