from __future__ import annotations

from pipeline.llm.base import LLMProvider


def create_provider(cfg: dict, client=None) -> LLMProvider:
    """config/llm.yaml の llm セクションから provider を作る。"""
    name = cfg.get("provider")
    if name == "claude":
        from pipeline.llm.claude import ClaudeProvider

        c = cfg["claude"]
        return ClaudeProvider(model=c["model"], effort=c["effort"], max_tokens=c["max_tokens"],
                              fallbacks=c.get("fallbacks"), max_retries=c.get("max_retries", 2), client=client)
    raise ValueError(f"unknown LLM provider: {name!r}")
