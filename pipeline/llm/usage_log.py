from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.llm.base import LLMUsage


def estimate_cost(model: str, usage: LLMUsage, pricing: dict) -> float | None:
    """料金表（USD / 100万トークン）から費用の目安を出す。表にないモデルは None。"""
    p = pricing.get(model)
    if not p:
        return None
    return (usage.input_tokens * p["input"]
            + usage.output_tokens * p["output"]
            + usage.cache_creation_input_tokens * p["cache_write"]
            + usage.cache_read_input_tokens * p["cache_read"]) / 1_000_000


def append_usage(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), **record}
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
