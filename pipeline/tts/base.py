"""音声合成の provider interface。コアの workflow は特定エンジンに依存せず、この型だけを使う。"""
from __future__ import annotations

from typing import Protocol


class TTSError(Exception):
    """音声合成に失敗した（エンジンに接続できない等）。"""


class TTSProvider(Protocol):
    name: str

    def synthesize(self, text: str, *, style_id: int, speed: float, intonation: float,
                   phrase_end_rise: float, post_phoneme: float) -> bytes:
        """WAV のバイト列を返す。"""
        ...
