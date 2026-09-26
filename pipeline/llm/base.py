"""LLM provider interface。コアの workflow は特定サービスに依存せず、この型だけを使う。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LLMError(Exception):
    """LLM の呼び出しや出力の読み取りに失敗した。"""


class LLMRefusalError(LLMError):
    """モデルが安全上の理由で応答を断った。"""


class LLMTruncatedError(LLMError):
    """max_tokens に達して出力が途中で切れた。"""


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass(frozen=True)
class LLMResult:
    data: dict
    model: str
    usage: LLMUsage
    request_id: str | None
    stop_reason: str


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_json(self, *, system: str, user: str, schema: dict,
                      max_tokens: int | None = None) -> LLMResult:
        """schema に沿った JSON を1つ生成して返す。"""
        ...
