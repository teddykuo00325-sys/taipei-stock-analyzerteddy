"""流派共用資料結構與介面說明.

每個流派模組需提供以下屬性與函式：

    NAME: str                # 顯示名稱（中文，用於 UI 下拉）
    FULL_NAME: str           # 完整名稱
    DESCRIPTION: str         # 流派簡介
    REFERENCES: list[str]    # 參考書目/教材

    def ma_alignment(df) -> tuple[state: str, note: str]
    def volume_analysis(df) -> str
    def generate_signals(df) -> list[Signal]
    def stop_levels(df) -> dict
    def score_weights() -> dict   # 各訊號的評分權重（可選）
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Signal:
    kind: str       # "entry" / "exit" / "info"
    name: str
    strength: int   # 1 ~ 3（強度：弱/中/強）
    note: str
