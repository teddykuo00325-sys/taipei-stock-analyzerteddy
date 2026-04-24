"""技術分析流派註冊表.

加入新流派步驟：
1. 在本目錄新增 `<school>.py`，實作 base.SchoolInterface 的函式
2. 在 REGISTRY 註冊（顯示名稱 -> 模組）
"""
from __future__ import annotations

from types import ModuleType

from . import chu_chia_hung

REGISTRY: dict[str, ModuleType] = {
    chu_chia_hung.NAME: chu_chia_hung,
}

DEFAULT = chu_chia_hung.NAME


def names() -> list[str]:
    return list(REGISTRY.keys())


def get(name: str | None = None) -> ModuleType:
    return REGISTRY.get(name or DEFAULT, chu_chia_hung)
