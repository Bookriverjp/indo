"""画像生成の provider interface。コアの workflow は特定サービスに依存せず、この型だけを使う。"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ImageError(Exception):
    """画像の生成に失敗した。"""


class ImageProvider(Protocol):
    name: str
    model: str

    def generate(self, *, prompt: str, size: str, transparent: bool,
                 reference_images: tuple[Path, ...] = ()) -> bytes:
        """PNG のバイト列を1枚返す。"""
        ...
