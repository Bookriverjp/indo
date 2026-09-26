"""Claude (Anthropic API) の provider adapter。"""
from __future__ import annotations

import json

from pipeline.llm.base import LLMError, LLMRefusalError, LLMResult, LLMTruncatedError, LLMUsage
from pipeline.llm.schema_tools import to_structured_output_schema

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeProvider:
    name = "claude"

    def __init__(self, *, model: str, effort: str, max_tokens: int,
                 fallbacks: str | None = None, max_retries: int = 2, client=None):
        if client is None:
            import anthropic  # 実際に呼ぶときだけ読み込む（テストはネットワークなし）

            client = anthropic.Anthropic(max_retries=max_retries)
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.fallbacks = fallbacks

    def generate_json(self, *, system: str, user: str, schema: dict,
                      max_tokens: int | None = None) -> LLMResult:
        params = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": to_structured_output_schema(schema)},
            },
        }
        # 長い出力でもタイムアウトしないようストリーミングで受け取る
        if self.fallbacks:
            stream = self.client.beta.messages.stream(**params, betas=[FALLBACK_BETA], fallbacks=self.fallbacks)
        else:
            stream = self.client.messages.stream(**params)
        with stream as s:
            msg = s.get_final_message()

        if msg.stop_reason == "refusal":
            details = getattr(msg, "stop_details", None)
            raise LLMRefusalError(f"model declined the request: {details}")
        if msg.stop_reason == "max_tokens":
            raise LLMTruncatedError("output hit max_tokens; raise llm.claude.max_tokens")

        # フォールバックが起きた場合は最後の fallback ブロックより後のテキストが最終出力
        blocks = list(msg.content)
        last_fallback = max((i for i, b in enumerate(blocks) if b.type == "fallback"), default=-1)
        text = "".join(b.text for b in blocks[last_fallback + 1:] if b.type == "text")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"model output is not valid JSON: {e}") from None
        if not isinstance(data, dict):
            raise LLMError("model output must be a JSON object")

        u = msg.usage
        usage = LLMUsage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        )
        return LLMResult(data=data, model=msg.model, usage=usage,
                         request_id=getattr(msg, "_request_id", None), stop_reason=msg.stop_reason)
