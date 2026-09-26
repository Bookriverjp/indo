"""リポジトリの JSON Schema を Claude の structured outputs が受け付ける形に変換する。

structured outputs は minLength / pattern / minItems などの制約に対応しないため取り除く。
取り除いた制約は、受け取った後に pipeline.schema_validation で元の schema を使って検証する。
"""
from __future__ import annotations

import copy

_DROP_KEYS = {
    "$schema", "minLength", "maxLength", "pattern", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minItems", "maxItems", "uniqueItems",
}


def _convert(node):
    if isinstance(node, list):
        return [_convert(v) for v in node]
    if not isinstance(node, dict):
        return node

    out = {k: _convert(v) for k, v in node.items() if k not in _DROP_KEYS}

    if isinstance(out.get("type"), list):
        types = out.pop("type")
        out["anyOf"] = [{"type": t} for t in types]

    if "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out["properties"])
    elif out.get("type") == "object":
        out["additionalProperties"] = False
    return out


def to_structured_output_schema(schema: dict) -> dict:
    return _convert(copy.deepcopy(schema))
